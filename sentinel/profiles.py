"""Multi-account *environment* profiles.

Profiles contain time zone, locale, browser policy and a proxy label/endpoint.
They intentionally contain no cookies, tokens, session files, account IDs or
credentials.  A recursive schema check rejects sensitive key names.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, TYPE_CHECKING

from sentinel.align.browsers import BrowserPolicyStore
from sentinel.config import AppPaths, Settings, atomic_write_json
from sentinel.models import AuditReport, EgressInfo
from sentinel.platform.base import PlatformAdapter
from sentinel.snapshots import SnapshotError, SnapshotStore
from sentinel.util.log import JsonlLogger
from sentinel.util.redact import assert_no_credentials, redact_proxy_url
from sentinel.util.net import read_proxy_env

if TYPE_CHECKING:
    from sentinel.align.engine import AlignmentEngine

SAFE_PROFILE_ID = re.compile(r"^[a-f0-9-]{32,36}$")


class ProfileError(RuntimeError):
    pass


class ProfileService:
    def __init__(
        self,
        paths: AppPaths,
        platform: PlatformAdapter,
        settings: Settings,
        *,
        browser_store: BrowserPolicyStore | None = None,
        snapshot_store: SnapshotStore | None = None,
        alignment_engine: "AlignmentEngine | None" = None,
    ) -> None:
        self.paths = paths
        self.platform = platform
        self.settings = settings
        self.browser_store = browser_store or BrowserPolicyStore(platform)
        self.snapshot_store = snapshot_store or SnapshotStore(paths, platform, self.browser_store)
        self.alignment_engine = alignment_engine
        self.paths.ensure()
        self.state_file = self.paths.state / "profile_state.json"
        self.log = JsonlLogger(self.paths.logs / "profiles.jsonl")
        self._current_profile_id = self._load_current_profile_id()

    # --- current pointer -------------------------------------------------
    def _load_current_profile_id(self) -> str | None:
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8-sig"))
            value = data.get("current_profile_id") if isinstance(data, dict) else None
            return str(value) if value else None
        except (OSError, json.JSONDecodeError):
            return None

    @property
    def current_profile_id(self) -> str | None:
        return self._current_profile_id

    def _set_current_profile_id(self, profile_id: str | None) -> None:
        self._current_profile_id = profile_id
        try:
            atomic_write_json(self.state_file, {"current_profile_id": profile_id}, mode=0o600)
        except OSError:
            pass

    # --- persistence -----------------------------------------------------
    def list(self) -> list[dict[str, Any]]:
        profiles: list[dict[str, Any]] = []
        for path in self.paths.profiles.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict) and data.get("schema_version") == 1:
                    data["_path"] = str(path)
                    profiles.append(data)
            except (OSError, json.JSONDecodeError):
                continue
        profiles.sort(key=lambda p: str(p.get("updated_at") or ""), reverse=True)
        return profiles

    def load(self, profile_id: str) -> dict[str, Any]:
        if not SAFE_PROFILE_ID.match(profile_id):
            raise ProfileError("非法配置包 ID")
        for profile in self.list():
            if profile.get("profile_id") == profile_id:
                return profile
        raise ProfileError(f"找不到环境配置包 {profile_id}")

    def _path_for(self, profile_id: str) -> Path:
        if not SAFE_PROFILE_ID.match(profile_id):
            raise ProfileError("非法配置包 ID")
        return self.paths.profiles / f"profile-{profile_id}.json"

    def save(self, profile: dict[str, Any]) -> dict[str, Any]:
        assert_no_credentials(profile, label="环境配置包")
        profile = dict(profile)
        profile.pop("_path", None)
        profile["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        data = json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True)
        assert_no_credentials(json.loads(data), label="环境配置包")
        path = self._path_for(str(profile["profile_id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        try:
            tmp.write_text(data + "\n", encoding="utf-8")
            tmp.replace(path)
        except OSError as exc:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise ProfileError(f"保存配置包失败: {exc}") from exc
        self.log.write("profile_saved", profile_id=profile["profile_id"], name=profile.get("name"))
        return profile

    def export_profile(self, profile_id: str, path: Path) -> Path:
        profile = self.load(profile_id)
        profile = dict(profile)
        profile.pop("_path", None)
        assert_no_credentials(profile, label="环境配置包")
        path = Path(path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, profile, mode=0o600)
        self.log.write("profile_exported", profile_id=profile_id, path=str(path))
        return path

    def import_profile(self, path: Path) -> dict[str, Any]:
        path = Path(path).expanduser()
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"无法读取配置包: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ProfileError("不支持的配置包格式")
        assert_no_credentials(data, label="导入的环境配置包")
        existing = {str(p.get("profile_id")) for p in self.list()}
        profile = dict(data)
        profile.pop("_path", None)
        if not SAFE_PROFILE_ID.match(str(profile.get("profile_id") or "")) or str(profile.get("profile_id")) in existing:
            profile["profile_id"] = str(uuid.uuid4())
            profile["name"] = f"{profile.get('name') or '导入的配置包'}（导入副本）"
        profile.setdefault("created_at", datetime.now().astimezone().isoformat(timespec="seconds"))
        profile["note"] = "只包含环境配置；不包含任何登录凭证、Cookie、Token 或会话文件。"
        return self.save(profile)

    def delete(self, profile_id: str) -> None:
        profile = self.load(profile_id)
        path = self._path_for(profile_id)
        try:
            path.unlink()
        except OSError as exc:
            raise ProfileError(f"删除配置包失败: {exc}") from exc
        if self._current_profile_id == profile_id:
            self._set_current_profile_id(None)
        self.log.write("profile_deleted", profile_id=profile_id, name=profile.get("name"))

    # --- capture ---------------------------------------------------------
    def capture_current_environment(self, *, expected_country: str | None = None, proxy_label: str = "") -> dict[str, Any]:
        env = self.platform.get_persistent_env_snapshot(["TZ", "LANG", "LC_ALL"])
        system_tz = self.platform.get_system_timezone()
        proxy_env = read_proxy_env(self.platform.effective_env())
        endpoint = ""
        for name in ("ALL_PROXY", "HTTPS_PROXY", "HTTP_PROXY"):
            value = proxy_env.get(name)
            if value:
                endpoint = redact_proxy_url(value)
                break
        environment = {
            "system_timezone": system_tz.to_dict(),
            "user_env": {name: value.to_dict() for name, value in env.items()},
            "browser_policies": self.browser_store.capture_policy_state(),
            "proxy_label": str(proxy_label or "")[:120],
            "proxy_endpoint": endpoint[:300],
            "expected_exit_country": (expected_country or "").upper()[:8],
        }
        assert_no_credentials(environment, label="环境配置包")
        return environment

    def create_from_current(
        self,
        name: str,
        *,
        expected_country: str | None = None,
        proxy_label: str = "",
    ) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ProfileError("配置包名称不能为空")
        if len(clean_name) > 80:
            raise ProfileError("配置包名称过长")
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        profile = {
            "schema_version": 1,
            "profile_id": str(uuid.uuid4()),
            "name": clean_name,
            "created_at": now,
            "updated_at": now,
            "note": "只包含环境配置；不包含任何登录凭证、Cookie、Token 或会话文件。",
            "environment": self.capture_current_environment(
                expected_country=expected_country,
                proxy_label=proxy_label,
            ),
        }
        saved = self.save(profile)
        self.log.write("profile_created", profile_id=saved["profile_id"], name=clean_name)
        return saved

    def update_from_current(self, profile_id: str) -> dict[str, Any]:
        profile = self.load(profile_id)
        profile["environment"] = self.capture_current_environment(
            expected_country=profile.get("environment", {}).get("expected_exit_country"),
            proxy_label=profile.get("environment", {}).get("proxy_label", ""),
        )
        return self.save(profile)

    # --- activation ------------------------------------------------------
    def activate(
        self,
        profile_id: str,
        *,
        confirm_system_timezone: bool,
        audit_runner: Callable[[], AuditReport] | None = None,
        current_egress: EgressInfo | None = None,
    ) -> dict[str, Any]:
        profile = self.load(profile_id)
        environment = profile.get("environment") or {}
        assert_no_credentials(environment, label="环境配置包")
        failures: list[str] = []
        partial = False
        try:
            snapshot = self.snapshot_store.capture(
                reason=f"profile-switch:{profile.get('name')}",
                label=f"切换环境配置包：{profile.get('name')}",
                modified_items=["A1", "A2", "A3", "A4", "A8", "A9", "A16", "A17"],
            )
        except (SnapshotError, OSError, Exception) as exc:
            return {
                "ok": False,
                "profile_id": profile_id,
                "snapshot_id": None,
                "failures": [f"切换前快照失败，已中止：{exc}"],
                "partial": False,
            }

        # Archive the environment we are leaving into its profile, if known.
        if self._current_profile_id and self._current_profile_id != profile_id:
            try:
                self.update_from_current(self._current_profile_id)
            except (ProfileError, OSError) as exc:
                failures.append(f"归档当前配置包失败: {exc}")

        target_tz = (environment.get("system_timezone") or {})
        target_iana = str(target_tz.get("iana") or "")
        current_tz = self.platform.get_system_timezone()
        if target_iana and (current_tz.iana != target_iana):
            if confirm_system_timezone:
                op = self.platform.set_system_timezone(target_iana, confirm=True)
                if not op.ok:
                    failures.append(f"系统时区未能切换: {op.detail}")
            else:
                partial = True
        for name, record in (environment.get("user_env") or {}).items():
            if not isinstance(record, dict) or name not in {"TZ", "LANG", "LC_ALL"}:
                continue
            if record.get("exists"):
                op = self.platform.set_user_env(name, str(record.get("value") or ""))
            else:
                op = self.platform.delete_user_env(name)
            if not op.ok:
                failures.append(f"环境变量 {name} 未能切换: {op.detail}")
        policy_failures = self.browser_store.restore_policy_state(environment.get("browser_policies") or {})
        for failure in policy_failures:
            failures.append(f"{failure.item}: {failure.detail}")
        if policy_failures:
            partial = True

        audit: AuditReport | None = None
        if audit_runner is not None:
            try:
                audit = audit_runner()
            except Exception as exc:
                failures.append(f"切换后审计失败: {exc}")
        expected_country = str(environment.get("expected_exit_country") or "").upper()
        if audit is not None and audit.egress and expected_country:
            actual = (audit.egress.country_code or "").upper()
            if actual and actual != expected_country:
                failures.append(
                    f"出口国家与配置包期望不一致：实际 {actual}，期望 {expected_country}；"
                    "请先确认代理是否已切到目标线路。"
                )
        if audit is not None and not audit.gate.allowed:
            partial = True
        ok = not failures
        if ok:
            self._set_current_profile_id(profile_id)
        self.log.write(
            "profile_activated",
            profile_id=profile_id,
            name=profile.get("name"),
            snapshot_id=snapshot.snapshot_id,
            failures=failures,
            ok=ok,
            partial=partial,
        )
        return {
            "ok": ok,
            "profile_id": profile_id,
            "profile_name": profile.get("name"),
            "snapshot_id": snapshot.snapshot_id,
            "failures": failures,
            "partial": partial,
            "audit": audit,
            "expected_country": expected_country,
        }
