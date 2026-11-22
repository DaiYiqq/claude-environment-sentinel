"""Platform abstraction used by audit, alignment and safety services."""

from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel.config import atomic_write_text
from sentinel.models import (
    BrowserInfo,
    ClaudeClientInfo,
    EnvValue,
    ProcessEntry,
    SystemTimezone,
    TunInfo,
)
from sentinel.tzmap import iana_for_windows_id, windows_id_for_iana
from sentinel.util.proc import CommandResult, list_processes, run


@dataclass
class OperationResult:
    ok: bool
    detail: str
    command: list[str] = field(default_factory=list)
    error: str | None = None
    output: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "command": list(self.command),
            "error": self.error,
            "output": self.output,
        }


def system_utc_offset_seconds() -> int | None:
    try:
        import time

        if time.daylight and time.localtime().tm_isdst > 0:
            return -int(time.altzone)
        return -int(time.timezone)
    except (OSError, ValueError):
        return None


class PlatformAdapter:
    """Default implementations plus optional capability flags."""

    name = "unknown"
    display_name = "Unknown"
    supports_system_timezone = False
    supports_process_firewall = False

    # --- environment -----------------------------------------------------
    def effective_env(self) -> dict[str, str]:
        return {str(k): str(v) for k, v in os.environ.items() if v is not None}

    def get_user_env(self, name: str) -> EnvValue:
        value = os.environ.get(name)
        return EnvValue(exists=value is not None, value=value, source="process")

    def get_persistent_env(self, name: str) -> EnvValue:
        """User-level persistent value, excluding a parent shell's process env.

        Snapshots must use this so a TZ that exists only in the terminal that
        launched Sentinel is not turned into a persistent registry value during
        restore.
        """
        return self.get_user_env(name)

    def get_user_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_user_env(name) for name in names}

    def get_persistent_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_persistent_env(name) for name in names}

    def set_user_env(self, name: str, value: str) -> OperationResult:
        os.environ[name] = value
        return OperationResult(True, f"仅当前进程设置 {name}")

    def delete_user_env(self, name: str) -> OperationResult:
        os.environ.pop(name, None)
        return OperationResult(True, f"仅当前进程删除 {name}")

    def broadcast_env_change(self) -> None:
        return None

    def get_user_language(self) -> str | None:
        for key in ("LC_ALL", "LANG", "LANGUAGE"):
            value = os.environ.get(key)
            if value:
                return value
        return None

    def capture_env_file(self) -> dict[str, Any]:
        return {
            "path": None,
            "existed": False,
            "content": None,
            "sha256": None,
            "sha256_note": "此平台没有 Sentinel 管理的用户级环境文件。",
        }

    def restore_env_file(self, snapshot: dict[str, Any]) -> OperationResult:
        return OperationResult(True, "无需恢复环境文件")

    # --- timezone --------------------------------------------------------
    def get_system_timezone(self) -> SystemTimezone:
        return SystemTimezone(
            native_id=None,
            iana=None,
            utc_offset_seconds=system_utc_offset_seconds(),
            source="platform",
            error="该平台尚未实现系统时区读取",
        )

    def set_system_timezone(self, iana: str, *, confirm: bool = False) -> OperationResult:
        return OperationResult(False, f"{self.display_name} 未实现系统时区修改")

    def set_system_timezone_native(self, native_id: str, *, confirm: bool = False) -> OperationResult:
        """Restore an exact native time-zone id when the platform has one.

        The default delegates to the IANA path; Windows overrides this so a
        snapshot restore writes the original Windows id rather than relying on
        a many-to-one IANA mapping.
        """
        return self.set_system_timezone(native_id, confirm=confirm)

    # --- process / network ----------------------------------------------
    def list_processes(self) -> list[ProcessEntry]:
        return list_processes()

    def get_tun_info(self) -> TunInfo:
        return TunInfo(active=False, source="platform", error="该平台尚未实现 TUN 探测")

    def local_addresses(self) -> list[dict[str, Any]]:
        from sentinel.util.net import local_ipv4_addresses

        return [{"ip": ip, "interface": "unknown"} for ip in local_ipv4_addresses()]

    # --- discovery -------------------------------------------------------
    def browser_paths(self) -> dict[str, str | None]:
        return {}

    def claude_paths(self) -> dict[str, str | None]:
        return {"cli": shutil.which("claude"), "desktop": None}

    def detect_claude(self) -> ClaudeClientInfo:
        paths = self.claude_paths()
        info = ClaudeClientInfo(cli_path=paths.get("cli"), desktop_path=paths.get("desktop"))
        if info.cli_path:
            info.client_types.append("CLI")
        if info.desktop_path:
            info.client_types.append("Desktop")
        return info

    def font_dirs(self) -> list[Path]:
        return []

    def running_process_names(self) -> set[str]:
        return {p.name.lower() for p in self.list_processes() if p.name}

    # --- kill switch -----------------------------------------------------
    def is_admin(self) -> bool:
        return False

    def killswitch_capability(self) -> tuple[bool, str]:
        return False, f"{self.display_name} 没有检测到可用的进程级断网后端"

    def firewall_add(self, rule_name: str, program_path: str) -> OperationResult:
        return OperationResult(False, "未实现防火墙规则")

    def firewall_delete(self, rule_name: str) -> OperationResult:
        return OperationResult(False, "未实现防火墙规则")

    def firewall_rule_exists(self, rule_name: str) -> bool:
        return False

    def hotkey_available(self) -> bool:
        return False

    def hotkey_unavailable_reason(self) -> str:
        return "该平台没有内置全局热键后端"

    def browser_running(self, browser_key: str) -> bool:
        names = self.running_process_names()
        return browser_key in names or f"{browser_key}.exe" in names


class PosixPlatformAdapter(PlatformAdapter):
    """Shared POSIX user-env and timezone behavior.

    Persistent user environment is written to a dedicated environment.d file
    (and, on macOS, applied to launchd).  This is intentionally explicit and
    snapshot-backed; Sentinel never edits shell profiles or system-wide files.
    """

    name = "posix"
    display_name = "POSIX"
    env_file = Path.home() / ".config" / "environment.d" / "90-claude-sentinel.conf"

    def _read_env_file(self) -> tuple[bool, str]:
        try:
            return True, self.env_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            return False, ""
        except OSError:
            return False, ""

    def _file_values(self) -> dict[str, str]:
        existed, content = self._read_env_file()
        values: dict[str, str] = {}
        if not existed:
            return values
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            if key in {"TZ", "LANG", "LC_ALL"}:
                values[key] = value
        return values

    def get_user_env(self, name: str) -> EnvValue:
        if name in os.environ and os.environ[name] is not None:
            return EnvValue(True, os.environ[name], source="process")
        return self.get_persistent_env(name)

    def get_persistent_env(self, name: str) -> EnvValue:
        values = self._file_values()
        if name in values:
            return EnvValue(True, values[name], source=str(self.env_file))
        return EnvValue(False, source="未设置")

    def _write_file_values(self, values: dict[str, str]) -> OperationResult:
        lines = [
            "# Managed by Claude Environment Sentinel.  Remove this file to",
            "# drop its session-level TZ/LANG/LC_ALL overrides.",
        ]
        for key in ("TZ", "LANG", "LC_ALL"):
            if key in values:
                lines.append(f"{key}={values[key]}")
        try:
            self.env_file.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self.env_file, "\n".join(lines) + "\n", mode=0o600)
            return OperationResult(True, f"已写入 {self.env_file}")
        except OSError as exc:
            return OperationResult(False, f"写入环境文件失败: {exc}", error=str(exc))

    def set_user_env(self, name: str, value: str) -> OperationResult:
        os.environ[name] = value
        values = self._file_values()
        values[name] = value
        result = self._write_file_values(values)
        if self.name == "macos":
            run(["launchctl", "setenv", name, value], timeout=5)
        return result

    def delete_user_env(self, name: str) -> OperationResult:
        os.environ.pop(name, None)
        values = self._file_values()
        values.pop(name, None)
        result = self._write_file_values(values)
        if self.name == "macos":
            run(["launchctl", "unsetenv", name], timeout=5)
        return result

    def effective_env(self) -> dict[str, str]:
        env = super().effective_env()
        for name, value in self._file_values().items():
            env.setdefault(name, value)
        return env

    def get_user_language(self) -> str | None:
        for key in ("LC_ALL", "LANG", "LANGUAGE"):
            value = self.effective_env().get(key)
            if value:
                return value
        return None

    def capture_env_file(self) -> dict[str, Any]:
        existed, content = self._read_env_file()
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest() if existed else None
        return {
            "path": str(self.env_file),
            "existed": existed,
            "content": content if existed else None,
            "sha256": digest,
        }

    def restore_env_file(self, snapshot: dict[str, Any]) -> OperationResult:
        path = Path(str(snapshot.get("path") or self.env_file))
        existed = bool(snapshot.get("existed"))
        content = snapshot.get("content")
        try:
            if existed:
                if content is None or not isinstance(content, str):
                    return OperationResult(False, "快照中的环境文件内容缺失")
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, content, mode=0o600)
                restored_values: dict[str, str] = {}
                for line in content.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        key, value = line.split("=", 1)
                        if key in {"TZ", "LANG", "LC_ALL"}:
                            restored_values[key] = value
                            os.environ[key] = value
                if self.name == "macos":
                    for key in ("TZ", "LANG", "LC_ALL"):
                        run(["launchctl", "unsetenv", key], timeout=5)
                    for key, value in restored_values.items():
                        run(["launchctl", "setenv", key, value], timeout=5)
                return OperationResult(True, f"已恢复 {path}")
            if path.exists():
                path.unlink()
            for key in ("TZ", "LANG", "LC_ALL"):
                os.environ.pop(key, None)
                if self.name == "macos":
                    run(["launchctl", "unsetenv", key], timeout=5)
            return OperationResult(True, f"已删除 {path}（原状态为不存在）")
        except OSError as exc:
            return OperationResult(False, f"恢复环境文件失败: {exc}", error=str(exc))

    def get_system_timezone(self) -> SystemTimezone:
        if self.name == "macos":
            result = run(["systemsetup", "-gettimezone"], timeout=8)
            native = None
            if result.ok and ":" in result.stdout:
                native = result.stdout.split(":", 1)[1].strip()
            iana = native
            source = "systemsetup -gettimezone"
        else:
            result = run(["timedatectl", "show", "-p", "Timezone", "--value"], timeout=8)
            native = result.stdout.strip() if result.ok else None
            iana = native
            source = "timedatectl"
        if not iana:
            try:
                target = Path("/etc/localtime").resolve()
                marker = "zoneinfo/"
                text = str(target)
                if marker in text:
                    iana = text.split(marker, 1)[1]
            except OSError:
                pass
        from sentinel.tzmap import offset_for_zone

        return SystemTimezone(
            native_id=native,
            iana=iana,
            utc_offset_seconds=offset_for_zone(iana) if iana else system_utc_offset_seconds(),
            source=source,
            raw={"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode},
            error=None if iana else (result.error or "无法读取系统时区"),
        )

    def set_system_timezone(self, iana: str, *, confirm: bool = False) -> OperationResult:
        if not confirm:
            return OperationResult(False, "修改系统时区需要用户显式确认")
        if self.name == "macos":
            escaped = iana.replace("'", "'\\''")
            script = f'do shell script "systemsetup -settimezone {escaped}" with administrator privileges'
            result = run(["osascript", "-e", script], timeout=120)
        else:
            result = run(["timedatectl", "set-timezone", iana], timeout=15)
        detail = (result.stdout + result.stderr).strip()
        return OperationResult(
            result.ok,
            detail or ("系统时区已修改" if result.ok else "系统时区修改失败"),
            command=list(result.argv),
            error=result.error,
            output=result.stdout,
        )

    def get_tun_info(self) -> TunInfo:
        adapters: list[dict[str, Any]] = []
        if self.name == "macos":
            result = run(["ifconfig"], timeout=8)
            current = None
            for line in result.stdout.splitlines():
                if line and not line[0].isspace():
                    current = line.split(":", 1)[0]
                if current and current.startswith("utun") and "inet " in line:
                    adapters.append({"name": current, "detail": line.strip(), "status": "up"})
            return TunInfo(active=bool(adapters), adapters=adapters, source="ifconfig", error=result.error)
        result = run(["ip", "-brief", "link", "show"], timeout=8)
        for line in result.stdout.splitlines():
            parts = line.split()
            if not parts:
                continue
            name = parts[0].rstrip(":")
            if any(token in name.lower() for token in ("tun", "tap", "wg", "utun")):
                adapters.append({"name": name, "detail": line.strip(), "status": "up" if "UP" in line else "down"})
        return TunInfo(active=bool(adapters), adapters=adapters, source="ip link", error=result.error)

    def local_addresses(self) -> list[dict[str, Any]]:
        from sentinel.util.net import local_ipv4_addresses

        return [{"ip": ip, "interface": "unknown"} for ip in local_ipv4_addresses()]

    def font_dirs(self) -> list[Path]:
        if self.name == "macos":
            return [Path("/System/Library/Fonts"), Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
        return [Path("/usr/share/fonts"), Path("/usr/local/share/fonts"), Path.home() / ".local" / "share" / "fonts"]
