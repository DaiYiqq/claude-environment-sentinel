"""Audit orchestration, baseline persistence and JSON export."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel.audit.probes import AuditSample, gather_sample
from sentinel.audit.risk import BLOCKING, WEIGHTS, build_gate, compute_risk_score
from sentinel.config import AppPaths, Settings, atomic_write_json
from sentinel.models import AuditReport, CheckResult, Status
from sentinel.platform.base import PlatformAdapter
from sentinel.util.log import JsonlLogger
from sentinel.util.net import NetworkProbe


class AuditEngine:
    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        platform: PlatformAdapter,
        *,
        network: NetworkProbe | None = None,
        browser_store: Any | None = None,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.platform = platform
        self.network = network or NetworkProbe(
            timeout=settings.http_timeout_seconds,
            enabled=settings.network_enabled,
        )
        if browser_store is None:
            from sentinel.align.browsers import BrowserPolicyStore

            browser_store = BrowserPolicyStore(platform)
        self.browser_store = browser_store
        self.history_log = JsonlLogger(self.paths.state / "audit_history.jsonl")

    def run(self, *, save_baseline: bool = True, export: bool | None = None) -> AuditReport:
        started = datetime.now().astimezone()
        report_id = started.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        previous = self._load_previous()
        sample = gather_sample(
            platform=self.platform,
            network=self.network,
            browser_store=self.browser_store,
            settings=self.settings,
            previous=previous,
        )
        checks: list[CheckResult] = []
        errors = list(sample.errors)
        for index, func in enumerate(run_checks_functions(), start=1):
            check_id = f"A{index}"
            try:
                checks.append(func(sample))
            except Exception as exc:  # one broken probe must not hide the rest
                checks.append(
                    CheckResult(
                        id=check_id,
                        title="检查执行异常",
                        status=Status.ERROR,
                        summary=f"{check_id} 执行异常: {exc}",
                        evidence=[f"{type(exc).__name__}: {exc}"],
                        raw={"error": str(exc)},
                        weight=WEIGHTS.get(check_id, 1),
                        blocking=BLOCKING.get(check_id, False),
                        explanation="该检查执行时发生异常，结果不可信；请查看日志。",
                    )
                )
                errors.append(f"{check_id} 执行异常: {exc}")
        risk = compute_risk_score(checks)
        launch_configured = bool(
            self.settings.claude_command.strip()
            or sample.claude.cli_path
            or sample.claude.desktop_path
        )
        try:
            killswitch_ready, killswitch_reason = self.platform.killswitch_capability()
        except Exception as exc:
            killswitch_ready, killswitch_reason = False, f"Kill-Switch 能力检测失败: {exc}"
        lock_reasons: list[str] = []
        if self.settings.country_lock:
            expected = (self.settings.expected_country or "").strip().upper()
            actual = (sample.egress.country_code or "").upper() if sample.egress else ""
            if not expected:
                lock_reasons.append("已开启国家锁定，但设置中没有填写目标国家代码。")
            elif not sample.egress.ok or not actual:
                lock_reasons.append(f"国家锁定为 {expected}，但本轮无法确认出口国家。")
            elif actual != expected:
                lock_reasons.append(f"国家锁定为 {expected}，但当前出口为 {actual}。")
        gate = build_gate(
            checks,
            risk,
            launch_configured=launch_configured,
            killswitch_ready=killswitch_ready,
            killswitch_reason=killswitch_reason,
            extra_reasons=lock_reasons,
        )
        notes = [
            "本报告只描述本地环境一致性，不代表 Anthropic 的账号风控结果。",
            "证据中的代理凭据已脱敏；Sentinel 不读取 Claude 登录态、Cookie、Token 或会话文件。",
        ]
        if not sample.claude.detected:
            notes.append("未检测到 Claude 客户端；安全启动需在专家模式配置命令。")
        finished = datetime.now().astimezone()
        report = AuditReport(
            report_id=report_id,
            started_at=started.isoformat(timespec="seconds"),
            finished_at=finished.isoformat(timespec="seconds"),
            checks=checks,
            risk_score=risk,
            gate=gate,
            egress=sample.egress,
            baseline_id=str(previous.get("audit_id")) if previous and previous.get("audit_id") else None,
            errors=errors,
            notes=notes,
            runtime={
                "proxy_configured": sample.proxy.configured,
                "proxy_core_alive": sample.proxy.core_running,
                "tun_active": bool(sample.tun.active),
                "proxy_processes": [p.name for p in sample.proxy.core_processes],
                "require_tun": bool(sample.require_tun),
            },
        )
        if save_baseline and sample.egress.ok:
            self._save_baseline(report, sample)
            self._append_history(report, sample)
        if export is None:
            export = bool(self.settings.auto_export_audit)
        if export:
            try:
                self.export_json(report, self.paths.audits_dir / f"audit-{report.report_id}.json")
            except OSError:
                pass
        return report

    def export_json(self, report: AuditReport, path: Path) -> Path:
        atomic_write_json(path, report.to_dict(), mode=0o600)
        return path

    def _load_previous(self) -> dict[str, Any] | None:
        path = self.paths.last_audit_file
        try:
            if not path.is_file() or path.stat().st_size > 2_000_000:
                return None
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data, dict) and data.get("schema_version") == 1:
                return data
        except (OSError, json.JSONDecodeError):
            return None
        return None

    def _save_baseline(self, report: AuditReport, sample: AuditSample) -> None:
        browsers: dict[str, Any] = {}
        from sentinel.align.browsers import BROWSER_BY_KEY, WEBRTC_NAMES
        from sentinel.audit.checks import _first_policy_value, _proxy_hosts

        for browser in sample.browsers:
            if not browser.installed:
                continue
            definition = BROWSER_BY_KEY[browser.key]
            accept = _first_policy_value(browser.policy or {}, definition.accept_names)
            webrtc = _first_policy_value(browser.policy or {}, WEBRTC_NAMES)
            browsers[browser.key] = {
                "accept_language": (accept or {}).get("value"),
                "webrtc": (webrtc or {}).get("value"),
            }
        baseline = {
            "schema_version": 1,
            "audit_id": report.report_id,
            "created_at": report.finished_at,
            "risk_score": report.risk_score,
            "gate_allowed": report.gate.allowed,
            "system_timezone": sample.system_timezone.to_dict(),
            "user_env": {name: value.to_dict() for name, value in sample.user_env.items()},
            "egress": {
                "ip": sample.egress.ip,
                "country_code": sample.egress.country_code,
                "timezone": sample.egress.timezone,
                "asn": sample.egress.asn,
                "org": sample.egress.org,
                "source": sample.egress.source,
            },
            "proxy": {
                "hosts": sorted(_proxy_hosts(sample.proxy.env)),
                "configured": sample.proxy.configured,
            },
            "browsers": browsers,
            "node": sample.node.get("raw"),
            "checks": {check.id: check.status.value for check in report.checks},
        }
        try:
            atomic_write_json(self.paths.last_audit_file, baseline, mode=0o600)
        except OSError:
            pass

    def _append_history(self, report: AuditReport, sample: AuditSample) -> None:
        try:
            self.history_log.write(
                "audit",
                audit_id=report.report_id,
                risk_score=report.risk_score,
                gate_allowed=report.gate.allowed,
                counts=report.status_counts,
                country=sample.egress.country_code,
                ip=sample.egress.ip,
                timezone=sample.egress.timezone,
                system_timezone=sample.system_timezone.iana or sample.system_timezone.native_id,
                failures=[c.id for c in report.checks if c.status in (Status.FAIL, Status.ERROR)],
                warnings=[c.id for c in report.checks if c.status is Status.WARN],
                check_statuses={c.id: c.status.value for c in report.checks},
            )
        except OSError:
            pass


def run_checks_functions():
    """Indirection keeps monkeypatching/tests simple."""
    from sentinel.audit.checks import CHECKS

    return CHECKS
