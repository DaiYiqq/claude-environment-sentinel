"""Immutable, checksummed environment snapshots and restore verification.

Snapshot files are written with O_CREAT|O_EXCL and are never replaced.  A
restore verifies the checksum first, then writes back the recorded originals
item by item.  A value that did not exist before is *deleted*, never set to an
empty string.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel.config import AppPaths
from sentinel.models import EnvValue, RestoreFailure, RestoreResult
from sentinel.platform.base import PlatformAdapter
from sentinel.util.log import JsonlLogger

SNAPSHOT_PREFIX = "sentinel-snapshot-"
ENV_NAMES = ("TZ", "LANG", "LC_ALL")
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


class SnapshotError(RuntimeError):
    pass


@dataclass
class Snapshot:
    data: dict[str, Any]
    path: Path

    @property
    def snapshot_id(self) -> str:
        return str(self.data.get("snapshot_id") or "")

    @property
    def created_at(self) -> str:
        return str(self.data.get("created_at") or "")

    @property
    def label(self) -> str:
        return str(self.data.get("label") or "")

    @property
    def reason(self) -> str:
        return str(self.data.get("reason") or "")

    @property
    def modified_items(self) -> list[str]:
        items = self.data.get("modified_items")
        return [str(x) for x in items] if isinstance(items, list) else []

    def to_dict(self) -> dict[str, Any]:
        return self.data


def canonical_checksum(data: dict[str, Any]) -> str:
    payload = {k: v for k, v in data.items() if k != "checksum"}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class SnapshotStore:
    def __init__(self, paths: AppPaths, platform: PlatformAdapter, browser_store: Any) -> None:
        self.paths = paths
        self.platform = platform
        self.browser_store = browser_store
        self.paths.ensure()
        self.restore_log = JsonlLogger(self.paths.logs / "restore.jsonl")

    def capture(self, *, reason: str, label: str, modified_items: list[str]) -> Snapshot:
        now = datetime.now().astimezone()
        snapshot_id = now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        data: dict[str, Any] = {
            "schema_version": 1,
            "snapshot_id": snapshot_id,
            "created_at": now.isoformat(timespec="seconds"),
            "label": label[:300],
            "reason": reason[:100],
            "modified_items": list(dict.fromkeys(modified_items)),
            "system_timezone": self.platform.get_system_timezone().to_dict(),
            "user_env": {
                name: self.platform.get_persistent_env(name).to_dict() for name in ENV_NAMES
            },
            "browser_policies": self.browser_store.capture_policy_state(),
            "posix_env_file": self.platform.capture_env_file(),
        }
        data["checksum"] = canonical_checksum(data)
        path = self.paths.backups / f"{SNAPSHOT_PREFIX}{snapshot_id}.json"
        encoded = (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        try:
            fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise SnapshotError(f"快照文件已存在，拒绝覆盖: {path}") from exc
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            raise SnapshotError(f"写入快照失败: {exc}") from exc
        return Snapshot(data=data, path=path)

    def list(self) -> list[Snapshot]:
        result: list[Snapshot] = []
        for path in self.paths.backups.glob(f"{SNAPSHOT_PREFIX}*.json"):
            try:
                snapshot = self._load_path(path, verify=False)
            except SnapshotError:
                continue
            result.append(snapshot)
        result.sort(key=lambda s: (s.created_at, s.snapshot_id), reverse=True)
        return result

    def latest(self) -> Snapshot | None:
        items = self.list()
        return items[0] if items else None

    def load(self, snapshot_id: str) -> Snapshot:
        if not _SAFE_ID.match(snapshot_id):
            raise SnapshotError("非法快照 ID")
        path = self.paths.backups / f"{SNAPSHOT_PREFIX}{snapshot_id}.json"
        if not path.is_file():
            raise SnapshotError(f"快照不存在: {snapshot_id}")
        return self._load_path(path, verify=True)

    def delete(self, snapshot_id: str) -> None:
        if not _SAFE_ID.match(snapshot_id):
            raise SnapshotError("非法快照 ID")
        path = self.paths.backups / f"{SNAPSHOT_PREFIX}{snapshot_id}.json"
        if not path.is_file():
            raise SnapshotError(f"快照不存在: {snapshot_id}")
        path.unlink()

    def _load_path(self, path: Path, *, verify: bool) -> Snapshot:
        try:
            if path.stat().st_size > 5_000_000:
                raise SnapshotError("快照文件过大，拒绝加载")
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SnapshotError(f"无法读取快照: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise SnapshotError("不支持的快照格式")
        snapshot_id = str(data.get("snapshot_id") or "")
        if not _SAFE_ID.match(snapshot_id) or path.name != f"{SNAPSHOT_PREFIX}{snapshot_id}.json":
            raise SnapshotError("快照 ID 与文件名不一致")
        if verify:
            checksum = str(data.get("checksum") or "")
            actual = canonical_checksum(data)
            if not checksum or checksum != actual:
                raise SnapshotError("快照校验和不匹配，文件可能已损坏或被修改")
        return Snapshot(data=data, path=path)

    # --- restore ---------------------------------------------------------
    def restore(self, snapshot_id: str, *, verify_after: bool = True) -> RestoreResult:
        snapshot = self.load(snapshot_id)
        result = RestoreResult(snapshot_id=snapshot_id)
        failures: list[RestoreFailure] = []
        restored: list[str] = []

        env_file = snapshot.data.get("posix_env_file")
        env_file_ok = False
        if isinstance(env_file, dict) and env_file.get("path"):
            op = self.platform.restore_env_file(env_file)
            if op.ok:
                env_file_ok = True
                restored.append("用户级环境文件")
            else:
                failures.append(
                    RestoreFailure(
                        item="用户级环境文件",
                        detail=op.detail,
                        manual_command=f"检查并手工恢复 {env_file.get('path')}",
                    )
                )

        env_records = snapshot.data.get("user_env") or {}
        if not (self.platform.name in {"macos", "linux"} and env_file_ok):
            for name in ENV_NAMES:
                record = env_records.get(name)
                if not isinstance(record, dict):
                    continue
                exists = bool(record.get("exists"))
                value = record.get("value")
                if exists:
                    op = self.platform.set_user_env(name, str(value if value is not None else ""))
                else:
                    op = self.platform.delete_user_env(name)
                if op.ok:
                    restored.append(name)
                else:
                    failures.append(
                        RestoreFailure(
                            item=f"用户环境变量 {name}",
                            detail=op.detail,
                            manual_command=self.manual_env_command(name, exists=exists, value=value),
                        )
                    )
        else:
            restored.append("TZ/LANG/LC_ALL（由环境文件恢复）")

        policy_failures = self.browser_store.restore_policy_state(
            snapshot.data.get("browser_policies") or {}
        )
        failures.extend(policy_failures)
        if not policy_failures:
            restored.append("浏览器策略")

        tz_record = snapshot.data.get("system_timezone") or {}
        if isinstance(tz_record, dict) and (tz_record.get("iana") or tz_record.get("native_id")):
            iana = str(tz_record.get("iana") or "")
            native = str(tz_record.get("native_id") or "")
            # Restore the exact native id when available; IANA -> native
            # mapping is many-to-one.  Fall back to IANA only if no native id
            # was recorded.
            if native:
                op = self.platform.set_system_timezone_native(native, confirm=True)
            else:
                op = self.platform.set_system_timezone(iana, confirm=True)
            if op.ok:
                restored.append("系统时区")
            else:
                failures.append(
                    RestoreFailure(
                        item="系统时区",
                        detail=op.detail,
                        manual_command=self.manual_timezone_command(iana, native),
                    )
                )

        result.restored_items = list(dict.fromkeys(restored))
        result.failures = failures
        if verify_after:
            verification = self.verify_restored(snapshot)
            result.verification = verification
            result.verified = not failures and all(item.get("matches") for item in verification)
        self.restore_log.write(
            "snapshot_restore",
            snapshot_id=snapshot_id,
            restored=result.restored_items,
            failures=[f.to_dict() for f in failures],
            verified=result.verified,
        )
        return result

    def verify_restored(self, snapshot: Snapshot) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        env_records = snapshot.data.get("user_env") or {}
        for name in ENV_NAMES:
            record = env_records.get(name)
            if not isinstance(record, dict):
                continue
            current = self.platform.get_persistent_env(name)
            expected_exists = bool(record.get("exists"))
            expected_value = record.get("value")
            matches = (current.exists == expected_exists) and (
                not expected_exists or current.value == expected_value
            )
            checks.append(
                {
                    "item": f"环境变量 {name}",
                    "expected": {"exists": expected_exists, "value": expected_value},
                    "actual": {"exists": current.exists, "value": current.value},
                    "matches": matches,
                }
            )
        tz_record = snapshot.data.get("system_timezone") or {}
        if isinstance(tz_record, dict) and (tz_record.get("native_id") or tz_record.get("iana")):
            current_tz = self.platform.get_system_timezone()
            expected_native = tz_record.get("native_id")
            expected_iana = tz_record.get("iana")
            matches = bool(
                (expected_native and current_tz.native_id == expected_native)
                or (not expected_native and expected_iana and current_tz.iana == expected_iana)
            )
            checks.append(
                {
                    "item": "系统时区",
                    "expected": {"native_id": expected_native, "iana": expected_iana},
                    "actual": {"native_id": current_tz.native_id, "iana": current_tz.iana},
                    "matches": matches,
                }
            )
        current_browser = self.browser_store.capture_policy_state()
        expected_browser = snapshot.data.get("browser_policies") or {}
        for browser_key, expected in expected_browser.items():
            if not isinstance(expected, dict) or not expected.get("installed"):
                continue
            actual = current_browser.get(browser_key) or {}
            mismatches: list[str] = []
            expected_values = expected.get("values") or {}
            actual_values = actual.get("values") or {}
            for name, expected_value in expected_values.items():
                if not isinstance(expected_value, dict):
                    continue
                got = actual_values.get(name) or {}
                if bool(expected_value.get("exists")) != bool(got.get("exists")):
                    mismatches.append(name)
                elif expected_value.get("exists") and str(expected_value.get("value")) != str(got.get("value")):
                    mismatches.append(name)
            checks.append(
                {
                    "item": f"浏览器策略 {expected.get('name')}",
                    "expected": expected_values,
                    "actual": actual_values,
                    "matches": not mismatches,
                    "mismatched_values": mismatches,
                }
            )
        return checks

    # --- manual recovery strings ----------------------------------------
    def manual_timezone_command(self, iana: str, native: str) -> str:
        if self.platform.name == "windows":
            return f'tzutil /s "{native or iana}"'
        if self.platform.name == "macos":
            return f"sudo systemsetup -settimezone {iana}"
        return f"sudo timedatectl set-timezone {iana}"

    def manual_env_command(self, name: str, *, exists: bool, value: Any) -> str:
        if self.platform.name == "windows":
            if exists:
                escaped = str(value or "").replace('"', '\\"')
                return f'setx {name} "{escaped}"'
            return f'reg delete "HKCU\\Environment" /v {name} /f'
        if exists:
            escaped = str(value or "").replace("'", "'\\''")
            return f"export {name}='{escaped}'  # 写入你的 shell 启动文件以持久化"
        return f"unset {name}  # 并删除 shell 启动文件中的对应行"
