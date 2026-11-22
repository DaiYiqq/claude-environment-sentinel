"""Reversible alignment of user-level settings.

Safety invariant: the snapshot is created before the first write.  If snapshot
creation fails, no setting is changed.  The engine never deletes fonts and
never edits browser binaries or Claude files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sentinel.align.browsers import BrowserPolicyStore
from sentinel.config import AppPaths, Settings
from sentinel.models import AlignmentItemResult, AlignmentResult, AuditReport, EgressInfo, Status
from sentinel.platform.base import PlatformAdapter
from sentinel.snapshots import SnapshotError, SnapshotStore
from sentinel.tzmap import (
    IANA_TO_WINDOWS,
    accept_language_value,
    language_for_country,
    locale_for_country,
    windows_id_for_iana,
)
from sentinel.util.net import NetworkProbe
from sentinel.util.proc import run


@dataclass
class AlignmentRequest:
    timezone: bool = False
    language: bool = False
    browser_policies: bool = False
    confirm_system_timezone: bool = False
    expected_country: str | None = None
    expected_timezone: str | None = None
    expected_locale: str | None = None
    reason: str = "align"

    @property
    def any_action(self) -> bool:
        return self.timezone or self.language or self.browser_policies

    def modified_items(self) -> list[str]:
        items: list[str] = []
        if self.timezone:
            items.extend(["A1", "A2", "A8"])
        if self.language:
            items.extend(["A3", "A4", "A9"])
        if self.browser_policies:
            items.extend(["A16", "A17"])
        return list(dict.fromkeys(items))


@dataclass
class ResolvedTarget:
    country: str
    timezone: str
    locale: str
    accept_language: str
    windows_timezone_id: str | None
    fallback_used: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


class AlignmentError(RuntimeError):
    pass


def locale_for_env(locale: str, platform_name: str) -> str:
    tag = locale.replace("-", "_")
    if platform_name == "windows":
        return locale
    if "." not in tag:
        tag += ".UTF-8"
    return tag


class AlignmentEngine:
    def __init__(
        self,
        paths: AppPaths,
        platform: PlatformAdapter,
        settings: Settings,
        *,
        network: NetworkProbe | None = None,
        browser_store: BrowserPolicyStore | None = None,
        snapshot_store: SnapshotStore | None = None,
        audit_runner: Callable[[], AuditReport] | None = None,
    ) -> None:
        self.paths = paths
        self.platform = platform
        self.settings = settings
        self.network = network or NetworkProbe(
            timeout=settings.http_timeout_seconds,
            enabled=settings.network_enabled,
        )
        self.browser_store = browser_store or BrowserPolicyStore(platform)
        self.snapshot_store = snapshot_store or SnapshotStore(paths, platform, self.browser_store)
        self.audit_runner = audit_runner

    def resolve_target(
        self,
        egress: EgressInfo | None,
        request: AlignmentRequest,
    ) -> ResolvedTarget:
        country = (request.expected_country or (egress.country_code if egress else None) or "").upper()
        timezone = request.expected_timezone or (egress.timezone if egress else None) or ""
        if not timezone:
            # We deliberately do not invent a time zone for large multi-zone
            # countries.  A wrong "representative" zone is worse than refusing.
            raise AlignmentError(
                "出口服务没有返回 IANA 时区，无法安全对齐系统时区；"
                "请稍后重试网络探测，或在专家模式手动指定目标时区。"
            )
        # Validate the target against our fallback table/zoneinfo.
        from sentinel.tzmap import offset_for_zone

        if offset_for_zone(timezone) is None:
            raise AlignmentError(f"无法识别目标时区 {timezone!r}，已中止对齐。")
        locale = request.expected_locale or locale_for_country(country, language_for_country(country))
        accept = accept_language_value(locale)
        windows_id = windows_id_for_iana(timezone) or IANA_TO_WINDOWS.get(timezone)
        return ResolvedTarget(
            country=country,
            timezone=timezone,
            locale=locale,
            accept_language=accept,
            windows_timezone_id=windows_id,
            evidence={
                "country": country,
                "timezone": timezone,
                "locale": locale,
                "accept_language": accept,
                "windows_timezone_id": windows_id,
                "source": "request" if (request.expected_timezone or request.expected_country) else (egress.source if egress else "none"),
            },
        )

    def apply(self, request: AlignmentRequest, egress: EgressInfo | None = None) -> AlignmentResult:
        if not request.any_action:
            return AlignmentResult(ok=False, snapshot_id=None, failures=["没有选择任何对齐项。"])
        try:
            target = self.resolve_target(egress, request)
        except AlignmentError as exc:
            return AlignmentResult(ok=False, snapshot_id=None, failures=[str(exc)])
        if request.timezone and request.confirm_system_timezone and not target.windows_timezone_id and self.platform.name == "windows":
            return AlignmentResult(
                ok=False,
                snapshot_id=None,
                failures=[
                    f"目标时区 {target.timezone} 没有对应的 Windows 时区 ID；"
                    "为避免猜测，本次没有修改任何设置。"
                ],
            )
        label_parts = []
        if request.timezone:
            label_parts.append("时区")
        if request.language:
            label_parts.append("语言")
        if request.browser_policies:
            label_parts.append("浏览器策略")
        label = "一键对齐：" + "/".join(label_parts) + f" → {target.country or '?'} / {target.locale}"
        try:
            snapshot = self.snapshot_store.capture(
                reason=request.reason,
                label=label,
                modified_items=request.modified_items(),
            )
        except Exception as exc:
            return AlignmentResult(
                ok=False,
                snapshot_id=None,
                failures=[f"快照创建失败，已中止所有写入（未修改任何设置）：{exc}"],
            )

        items: list[AlignmentItemResult] = []
        failures: list[str] = []
        partial = False

        if request.timezone:
            op = self.platform.set_user_env("TZ", target.timezone)
            items.append(
                AlignmentItemResult(
                    key="B1_TZ",
                    label="用户级 TZ",
                    status="applied" if op.ok else "failed",
                    detail=op.detail,
                    evidence={"target": target.timezone},
                )
            )
            if not op.ok:
                failures.append(op.detail)
            if request.confirm_system_timezone:
                tz_op = self.platform.set_system_timezone(target.timezone, confirm=True)
                items.append(
                    AlignmentItemResult(
                        key="B1_SYSTEM_TZ",
                        label="系统时区",
                        status="applied" if tz_op.ok else "failed",
                        detail=tz_op.detail,
                        evidence={"target": target.timezone, "windows_id": target.windows_timezone_id},
                    )
                )
                if not tz_op.ok:
                    failures.append(tz_op.detail)
            else:
                partial = True
                items.append(
                    AlignmentItemResult(
                        key="B1_SYSTEM_TZ",
                        label="系统时区",
                        status="partial",
                        detail="用户未确认修改系统时区，仅写入了用户级 TZ；A1/A8 可能仍失败。",
                        evidence={"target": target.timezone},
                    )
                )

        if request.language:
            env_locale = locale_for_env(target.locale, self.platform.name)
            for name in ("LANG", "LC_ALL"):
                op = self.platform.set_user_env(name, env_locale)
                items.append(
                    AlignmentItemResult(
                        key=f"B2_{name}",
                        label=f"用户级 {name}",
                        status="applied" if op.ok else "failed",
                        detail=op.detail,
                        evidence={"value": env_locale},
                    )
                )
                if not op.ok:
                    failures.append(op.detail)
            if self.platform.name == "windows":
                items.append(
                    AlignmentItemResult(
                        key="B2_NODE_NOTE",
                        label="Node/Electron locale 说明",
                        status="partial",
                        detail=(
                            "Windows 上 Node 的 ICU 默认 locale 由系统决定，LANG/LC_ALL 不一定会改变 "
                            "Intl.DateTimeFormat().resolvedOptions().locale；Sentinel 不会为此修改"
                            "系统显示语言，重新采样后如未跟随会明确标记为部分完成。"
                        ),
                        evidence={"platform": "windows"},
                    )
                )
                partial = True

        if request.browser_policies:
            results = self.browser_store.apply_policy(target.accept_language)
            if not results:
                partial = True
                items.append(
                    AlignmentItemResult(
                        key="B3_BROWSER",
                        label="浏览器策略",
                        status="skipped",
                        detail="未检测到 Chrome/Edge，未写入浏览器策略。",
                    )
                )
            for result in results:
                ok = bool(result.get("ok"))
                items.append(
                    AlignmentItemResult(
                        key=f"B3_{result.get('browser')}",
                        label=f"浏览器策略 {result.get('browser')}",
                        status="applied" if ok else "failed",
                        detail=str(result.get("detail") or ""),
                        evidence={"accept_language": target.accept_language, "webrtc": "disable_non_proxied_udp"},
                    )
                )
                if not ok:
                    failures.append(str(result.get("detail") or "浏览器策略写入失败"))
            try:
                if any(browser.installed and browser.running for browser in self.browser_store.audit_browsers()):
                    partial = True
                    items.append(
                        AlignmentItemResult(
                            key="B3_RESTART_NOTE",
                            label="浏览器重启提示",
                            status="partial",
                            detail="浏览器正在运行；策略通常需要重启浏览器后才能完全生效。",
                        )
                    )
            except Exception:
                pass

        verification: dict[str, Any] = {}
        verification_ok = True
        if self.audit_runner is not None:
            try:
                report = self.audit_runner()
                relevant = self._relevant_check_ids(request)
                states = {
                    check.id: {"status": check.status.value, "summary": check.summary}
                    for check in report.checks
                    if check.id in relevant
                }
                verification = {
                    "audit_id": report.report_id,
                    "risk_score": report.risk_score,
                    "gate": report.gate.to_dict(),
                    "checks": states,
                }
                # The acceptance contract is "all requested items must be
                # verified after alignment".  A warning is not silently
                # promoted to success; it is reported as an unfinished item.
                unfinished = [
                    cid for cid, value in states.items() if value["status"] != "pass"
                ]
                if unfinished:
                    verification_ok = False
                    partial = True
                    failures.append("对齐后复检未全部通过：" + ", ".join(sorted(unfinished)))
                for cid, value in states.items():
                    items.append(
                        AlignmentItemResult(
                            key=f"VERIFY_{cid}",
                            label=f"复检 {cid}",
                            status="verified" if value["status"] == "pass" else "partial",
                            detail=str(value.get("summary") or ""),
                            evidence={"status": value.get("status")},
                        )
                    )
            except Exception as exc:
                verification_ok = False
                failures.append(f"对齐后复检无法完成: {exc}")

        if request.timezone and not request.confirm_system_timezone:
            verification_ok = False
        ok = not failures and verification_ok
        return AlignmentResult(
            ok=ok,
            snapshot_id=snapshot.snapshot_id,
            items=items,
            failures=failures,
            verification=verification,
            partial=partial,
        )

    def _relevant_check_ids(self, request: AlignmentRequest) -> set[str]:
        ids: set[str] = set()
        if request.timezone:
            # The acceptance contract for B1 is A1–A4, not just the clock
            # value.  A3/A4 may require B2; if they remain unresolved this
            # verification reports a failure/partial instead of claiming B1
            # is complete.
            ids.update({"A1", "A2", "A3", "A4", "A8"})
        if request.language:
            ids.update({"A3", "A4", "A9"})
        if request.browser_policies:
            ids.update({"A16", "A17"})
        return ids

    def font_advice(self, report: AuditReport | None = None) -> str:
        return (
            "字体项只做标记，不自动删除。删除 SimSun/微软雅黑/文泉驿/方正等字体会影响其他软件，"
            "不属于 Sentinel 的职责。是否处理由你自行决定。"
        )
