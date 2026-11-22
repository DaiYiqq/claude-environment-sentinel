"""Chrome/Edge policy read/write.

Only *user-level policy keys* are written.  Sentinel never edits browser
binaries, extensions or cookie/login databases.  On Windows Chrome policies
live under HKCU\\Software\\Policies\\Google\\Chrome and Edge under
HKCU\\Software\\Policies\\Microsoft\\Edge.  A machine policy (HKLM) may still
override the user policy; that is detected and reported instead of hidden.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel.config import atomic_write_json
from sentinel.models import BrowserInfo, RestoreFailure
from sentinel.platform.base import OperationResult, PlatformAdapter

try:
    import winreg  # type: ignore
except ImportError:  # pragma: no cover
    winreg = None  # type: ignore


CHROME_POLICY_PATH = r"Software\Policies\Google\Chrome"
EDGE_POLICY_PATH = r"Software\Policies\Microsoft\Edge"
CHROME_ACCEPT_NAMES = ("IntlAcceptLanguages", "AcceptLanguages", "AcceptLanguage")
EDGE_ACCEPT_NAMES = ("DefinePreferredLanguages", "AcceptLanguages", "AcceptLanguage")
WEBRTC_NAMES = ("WebRtcIPHandling", "WebRtcIPHandlingPolicy")


@dataclass(frozen=True)
class BrowserDefinition:
    key: str
    name: str
    policy_path: str
    accept_names: tuple[str, ...]
    mac_domain: str
    linux_managed_path: Path


BROWSERS: tuple[BrowserDefinition, ...] = (
    BrowserDefinition(
        key="chrome",
        name="Google Chrome",
        policy_path=CHROME_POLICY_PATH,
        accept_names=CHROME_ACCEPT_NAMES,
        mac_domain="com.google.Chrome",
        linux_managed_path=Path.home() / ".config" / "google-chrome" / "policies" / "managed" / "claude-sentinel.json",
    ),
    BrowserDefinition(
        key="edge",
        name="Microsoft Edge",
        policy_path=EDGE_POLICY_PATH,
        accept_names=EDGE_ACCEPT_NAMES,
        mac_domain="com.microsoft.Edge",
        linux_managed_path=Path.home() / ".config" / "microsoft-edge" / "policies" / "managed" / "claude-sentinel.json",
    ),
)

BROWSER_BY_KEY = {b.key: b for b in BROWSERS}


def _win_kind_name(kind: int | None) -> str | None:
    if winreg is None or kind is None:
        return None
    return {
        winreg.REG_SZ: "REG_SZ",
        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
    }.get(kind, str(kind))


def _read_reg_value(hive: Any, path: str, name: str) -> dict[str, Any]:
    if winreg is None:
        return {"exists": False, "value": None, "kind": None, "error": "winreg unavailable"}
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ) as key:
            value, kind = winreg.QueryValueEx(key, name)
            return {"exists": True, "value": str(value), "kind": _win_kind_name(kind), "error": None}
    except FileNotFoundError:
        return {"exists": False, "value": None, "kind": None, "error": None}
    except OSError as exc:
        return {"exists": False, "value": None, "kind": None, "error": str(exc)}


def _write_reg_value(path: str, name: str, value: str) -> None:
    if winreg is None:
        raise OSError("winreg unavailable")
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))


def _delete_reg_value(path: str, name: str) -> None:
    if winreg is None:
        raise OSError("winreg unavailable")
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            winreg.DeleteValue(key, name)
    except FileNotFoundError:
        pass


def _key_exists(hive: Any, path: str) -> bool:
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ):
            return True
    except OSError:
        return False


def _delete_key_if_empty(hive: Any, path: str) -> None:
    if winreg is None:
        return
    try:
        with winreg.OpenKey(hive, path, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
            subkeys, values, _mtime = winreg.QueryInfoKey(key)
            if subkeys or values:
                return
        winreg.DeleteKey(hive, path)
    except OSError:
        pass


class BrowserPolicyStore:
    def __init__(self, platform: PlatformAdapter) -> None:
        self.platform = platform

    # --- discovery and audit --------------------------------------------
    def installed(self) -> dict[str, str | None]:
        return self.platform.browser_paths()

    def audit_browsers(self) -> list[BrowserInfo]:
        installed = self.installed()
        result: list[BrowserInfo] = []
        for definition in BROWSERS:
            exe = installed.get(definition.key)
            running = self.platform.browser_running(definition.key)
            info = BrowserInfo(
                key=definition.key,
                name=definition.name,
                installed=bool(exe) or running,
                exe_path=exe,
                running=running,
            )
            if not info.installed:
                result.append(info)
                continue
            info.policy = self.read_effective_policy(definition)
            prefs = self.read_preferences_accept_language(definition)
            info.preferences = {"accept_languages": prefs.get("value")} if prefs else {}
            if prefs.get("error"):
                info.errors.append(str(prefs["error"]))
            result.append(info)
        return result

    def read_effective_policy(self, definition: BrowserDefinition) -> dict[str, Any]:
        if winreg is not None:
            values: dict[str, Any] = {}
            for names in (definition.accept_names, WEBRTC_NAMES):
                for name in names:
                    user = _read_reg_value(winreg.HKEY_CURRENT_USER, definition.policy_path, name)
                    machine = _read_reg_value(winreg.HKEY_LOCAL_MACHINE, definition.policy_path, name)
                    if user["exists"] or machine["exists"]:
                        values[name] = {
                            "user": user,
                            "machine": machine,
                            "effective": machine if machine["exists"] else user,
                            "effective_hive": "HKLM" if machine["exists"] else "HKCU",
                        }
            return {
                "kind": "registry",
                "key_path": definition.policy_path,
                "key_existed": _key_exists(winreg.HKEY_CURRENT_USER, definition.policy_path),
                "values": values,
            }
        if self.platform.name == "macos":
            return self._read_mac_policy(definition)
        return self._read_linux_policy(definition)

    def policy_value(self, policy: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any] | None:
        values = policy.get("values", {}) if isinstance(policy, dict) else {}
        for name in names:
            entry = values.get(name)
            if entry:
                effective = entry.get("effective") if "effective" in entry else entry
                if isinstance(effective, dict) and effective.get("exists"):
                    return {"name": name, **effective}
        return None

    def read_preferences_accept_language(self, definition: BrowserDefinition) -> dict[str, Any]:
        if winreg is not None:
            local = Path(os.environ.get("LOCALAPPDATA", ""))
            base = local / ("Google/Chrome" if definition.key == "chrome" else "Microsoft/Edge") / "User Data" / "Default"
            path = base / "Preferences"
        elif self.platform.name == "macos":
            path = (
                Path.home()
                / "Library"
                / "Application Support"
                / ("Google/Chrome" if definition.key == "chrome" else "Microsoft Edge")
                / "Default"
                / "Preferences"
            )
        else:
            path = (
                Path.home()
                / ".config"
                / ("google-chrome" if definition.key == "chrome" else "microsoft-edge")
                / "Default"
                / "Preferences"
            )
        if not path.is_file():
            return {"value": None, "error": None, "path": str(path)}
        try:
            with path.open("r", encoding="utf-8-sig") as handle:
                data = json.load(handle)
            intl = data.get("intl") if isinstance(data, dict) else None
            value = intl.get("accept_languages") if isinstance(intl, dict) else None
            return {"value": str(value) if value else None, "error": None, "path": str(path)}
        except (OSError, json.JSONDecodeError) as exc:
            return {"value": None, "error": f"无法读取浏览器语言偏好: {exc}", "path": str(path)}

    # --- snapshot / restore ---------------------------------------------
    def capture_policy_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {}
        for definition in BROWSERS:
            if not self._browser_installed(definition):
                state[definition.key] = {
                    "key": definition.key,
                    "name": definition.name,
                    "installed": False,
                    "kind": "none",
                    "key_existed": False,
                    "values": {},
                }
                continue
            if winreg is not None:
                values: dict[str, Any] = {}
                for name in (*definition.accept_names, *WEBRTC_NAMES):
                    values[name] = _read_reg_value(winreg.HKEY_CURRENT_USER, definition.policy_path, name)
                state[definition.key] = {
                    "key": definition.key,
                    "name": definition.name,
                    "installed": True,
                    "kind": "registry",
                    "hive": "HKCU",
                    "key_path": definition.policy_path,
                    "key_existed": _key_exists(winreg.HKEY_CURRENT_USER, definition.policy_path),
                    "values": values,
                }
            elif self.platform.name == "macos":
                path = self._mac_plist_path(definition)
                existed = path.is_file()
                keys: dict[str, Any] = {}
                data: dict[str, Any] = {}
                if existed:
                    try:
                        with path.open("rb") as handle:
                            loaded = plistlib.load(handle)
                        data = loaded if isinstance(loaded, dict) else {}
                    except (OSError, plistlib.InvalidFileException):
                        data = {}
                for name in (*definition.accept_names, *WEBRTC_NAMES):
                    keys[name] = {
                        "exists": name in data,
                        "value": str(data[name]) if name in data and not isinstance(data[name], (dict, list)) else None,
                        "kind": "plist",
                    }
                state[definition.key] = {
                    "key": definition.key,
                    "name": definition.name,
                    "installed": True,
                    "kind": "plist",
                    "path": str(path),
                    "key_existed": existed,
                    "values": keys,
                }
            else:
                path = definition.linux_managed_path
                existed = path.is_file()
                content = path.read_text(encoding="utf-8") if existed else None
                state[definition.key] = {
                    "key": definition.key,
                    "name": definition.name,
                    "installed": True,
                    "kind": "managed-json",
                    "path": str(path),
                    "key_existed": existed,
                    "content": content,
                    "values": {},
                }
        return state

    def restore_policy_state(self, state: dict[str, Any]) -> list[RestoreFailure]:
        failures: list[RestoreFailure] = []
        for definition in BROWSERS:
            record = state.get(definition.key)
            if not isinstance(record, dict) or not record.get("installed"):
                continue
            kind = record.get("kind")
            try:
                if kind == "registry" and winreg is not None:
                    path = str(record.get("key_path") or definition.policy_path)
                    for name, original in (record.get("values") or {}).items():
                        if not isinstance(original, dict):
                            continue
                        if original.get("exists"):
                            _write_reg_value(path, name, str(original.get("value") or ""))
                        else:
                            _delete_reg_value(path, name)
                    if not record.get("key_existed"):
                        _delete_key_if_empty(winreg.HKEY_CURRENT_USER, path)
                elif kind == "plist":
                    path = Path(str(record.get("path") or self._mac_plist_path(definition)))
                    data: dict[str, Any] = {}
                    if path.is_file():
                        with path.open("rb") as handle:
                            loaded = plistlib.load(handle)
                        data = loaded if isinstance(loaded, dict) else {}
                    for name, original in (record.get("values") or {}).items():
                        if original.get("exists"):
                            data[name] = str(original.get("value") or "")
                        else:
                            data.pop(name, None)
                    self._write_plist(path, data)
                elif kind == "managed-json":
                    path = Path(str(record.get("path") or definition.linux_managed_path))
                    if record.get("key_existed"):
                        content = record.get("content")
                        if content is None:
                            raise OSError("快照中的策略文件内容缺失")
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_text(str(content), encoding="utf-8")
                    elif path.exists():
                        path.unlink()
            except (OSError, ValueError) as exc:
                failures.append(
                    RestoreFailure(
                        item=f"浏览器策略 {definition.name}",
                        detail=str(exc),
                        manual_command=self.manual_restore_command(definition, record),
                    )
                )
        return failures

    # --- alignment -------------------------------------------------------
    def apply_policy(
        self,
        accept_language: str,
        *,
        webrtc_policy: str = "disable_non_proxied_udp",
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for definition in BROWSERS:
            if not self._browser_installed(definition):
                continue
            # Edge's DefinePreferredLanguages expects a language tag, while
            # Chrome's IntlAcceptLanguages accepts an ordered header-style
            # list.  Keep both valid rather than writing an ambiguous value.
            policy_accept = accept_language if definition.key == "chrome" else accept_language.split(",", 1)[0]
            if winreg is not None:
                try:
                    _write_reg_value(definition.policy_path, definition.accept_names[0], policy_accept)
                    _write_reg_value(definition.policy_path, WEBRTC_NAMES[0], webrtc_policy)
                    results.append(
                        {
                            "browser": definition.key,
                            "ok": True,
                            "detail": f"已写入 HKCU 策略：{definition.accept_names[0]}={policy_accept}, "
                            f"{WEBRTC_NAMES[0]}={webrtc_policy}",
                        }
                    )
                except OSError as exc:
                    results.append({"browser": definition.key, "ok": False, "detail": str(exc)})
            elif self.platform.name == "macos":
                path = self._mac_plist_path(definition)
                try:
                    data: dict[str, Any] = {}
                    if path.is_file():
                        with path.open("rb") as handle:
                            loaded = plistlib.load(handle)
                        data = loaded if isinstance(loaded, dict) else {}
                    data[definition.accept_names[0]] = policy_accept
                    data[WEBRTC_NAMES[0]] = webrtc_policy
                    self._write_plist(path, data)
                    results.append(
                        {
                            "browser": definition.key,
                            "ok": True,
                            "detail": f"已写入用户 plist：{definition.accept_names[0]} / {WEBRTC_NAMES[0]}",
                        }
                    )
                except (OSError, ValueError) as exc:
                    results.append({"browser": definition.key, "ok": False, "detail": str(exc)})
            else:
                path = definition.linux_managed_path
                try:
                    data = {}
                    if path.is_file():
                        loaded = json.loads(path.read_text(encoding="utf-8"))
                        data = loaded if isinstance(loaded, dict) else {}
                    data[definition.accept_names[0]] = policy_accept
                    data[WEBRTC_NAMES[0]] = webrtc_policy
                    atomic_write_json(path, data, mode=0o600)
                    results.append(
                        {
                            "browser": definition.key,
                            "ok": True,
                            "detail": f"已写入用户级 managed policy：{path}",
                        }
                    )
                except (OSError, ValueError) as exc:
                    results.append({"browser": definition.key, "ok": False, "detail": str(exc)})
        return results

    def _browser_installed(self, definition: BrowserDefinition) -> bool:
        exe = self.installed().get(definition.key)
        return bool(exe) or self.platform.browser_running(definition.key)

    def _mac_plist_path(self, definition: BrowserDefinition) -> Path:
        return Path.home() / "Library" / "Preferences" / f"{definition.mac_domain}.plist"

    def _read_mac_policy(self, definition: BrowserDefinition) -> dict[str, Any]:
        path = self._mac_plist_path(definition)
        data: dict[str, Any] = {}
        if path.is_file():
            try:
                with path.open("rb") as handle:
                    loaded = plistlib.load(handle)
                data = loaded if isinstance(loaded, dict) else {}
            except (OSError, plistlib.InvalidFileException):
                data = {}
        values: dict[str, Any] = {}
        for name in (*definition.accept_names, *WEBRTC_NAMES):
            if name in data:
                values[name] = {
                    "user": {"exists": True, "value": str(data[name]), "kind": "plist"},
                    "machine": {"exists": False, "value": None, "kind": None},
                    "effective": {"exists": True, "value": str(data[name])},
                    "effective_hive": "user-plist",
                }
        return {"kind": "plist", "path": str(path), "key_existed": path.is_file(), "values": values}

    def _read_linux_policy(self, definition: BrowserDefinition) -> dict[str, Any]:
        path = definition.linux_managed_path
        values: dict[str, Any] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
            if isinstance(data, dict):
                for name in (*definition.accept_names, *WEBRTC_NAMES):
                    if name in data:
                        values[name] = {
                            "user": {"exists": True, "value": str(data[name]), "kind": "managed-json"},
                            "machine": {"exists": False, "value": None, "kind": None},
                            "effective": {"exists": True, "value": str(data[name])},
                            "effective_hive": "user-managed-json",
                        }
        return {"kind": "managed-json", "path": str(path), "key_existed": path.is_file(), "values": values}

    def _write_plist(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                plistlib.dump(data, handle, fmt=plistlib.FMT_BINARY)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass

    def manual_restore_command(self, definition: BrowserDefinition, record: dict[str, Any]) -> str:
        if winreg is not None:
            path = record.get("key_path") or definition.policy_path
            return f'reg delete "HKCU\\{path}" /v "{definition.accept_names[0]}" /f'
        if self.platform.name == "macos":
            return f'defaults delete {definition.mac_domain} {definition.accept_names[0]}'
        return f"del / remove {record.get('path') or definition.linux_managed_path}"
