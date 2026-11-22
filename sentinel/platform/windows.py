"""Windows platform adapter.

All writes are user-scoped (HKCU) except the explicitly confirmed system
time-zone change and the kill-switch outbound firewall rules.  No service,
driver, hosts-file or kernel change is made.
"""

from __future__ import annotations

import ctypes
import glob
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from sentinel.models import ClaudeClientInfo, EnvValue, ProcessEntry, SystemTimezone, TunInfo
from sentinel.platform.base import OperationResult, PlatformAdapter, system_utc_offset_seconds
from sentinel.tzmap import iana_for_windows_id, windows_id_for_iana
from sentinel.util import proc
from sentinel.util.proc import CommandResult, file_version, run

try:  # Windows-only module
    import winreg  # type: ignore
except ImportError:  # pragma: no cover - imported only on Windows
    winreg = None  # type: ignore

ENV_KEY = r"Environment"
WM_SETTINGCHANGE = 0x001A
HWND_BROADCAST = 0xFFFF
SMTO_ABORTIFHUNG = 0x0002


def _reg_kind_name(kind: int | None) -> str | None:
    if winreg is None or kind is None:
        return None
    return {
        winreg.REG_SZ: "REG_SZ",
        winreg.REG_EXPAND_SZ: "REG_EXPAND_SZ",
        winreg.REG_MULTI_SZ: "REG_MULTI_SZ",
    }.get(kind, str(kind))


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _windows_current_offset_seconds() -> int | None:
    """Read the *current* Windows zone offset via Win32.

    Python's ``time.timezone`` can be cached at process start; after an
    in-process ``tzutil /s`` change it may remain stale.  GetTimeZoneInformation
    returns the live OS setting.
    """
    try:
        from ctypes import wintypes

        class SYSTEMTIME(ctypes.Structure):
            _fields_ = [
                ("wYear", wintypes.WORD),
                ("wMonth", wintypes.WORD),
                ("wDayOfWeek", wintypes.WORD),
                ("wDay", wintypes.WORD),
                ("wHour", wintypes.WORD),
                ("wMinute", wintypes.WORD),
                ("wSecond", wintypes.WORD),
                ("wMilliseconds", wintypes.WORD),
            ]

        class TIME_ZONE_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("Bias", wintypes.LONG),
                ("StandardName", wintypes.WCHAR * 32),
                ("StandardDate", SYSTEMTIME),
                ("StandardBias", wintypes.LONG),
                ("DaylightName", wintypes.WCHAR * 32),
                ("DaylightDate", SYSTEMTIME),
                ("DaylightBias", wintypes.LONG),
            ]

        info = TIME_ZONE_INFORMATION()
        state = ctypes.windll.kernel32.GetTimeZoneInformation(ctypes.byref(info))
        bias = int(info.Bias)
        if state == 2:  # TIME_ZONE_ID_DAYLIGHT
            bias += int(info.DaylightBias)
        else:
            bias += int(info.StandardBias)
        return -bias * 60
    except (AttributeError, OSError, ValueError):
        return system_utc_offset_seconds()


class WindowsPlatform(PlatformAdapter):
    name = "windows"
    display_name = "Windows"
    supports_system_timezone = True
    supports_process_firewall = True

    # --- registry-backed user environment --------------------------------
    def _open_env_key(self, write: bool = False):
        if winreg is None:
            raise OSError("winreg 不可用")
        access = winreg.KEY_READ
        if write:
            access = winreg.KEY_READ | winreg.KEY_WRITE
        return winreg.OpenKey(winreg.HKEY_CURRENT_USER, ENV_KEY, 0, access)

    def get_user_env(self, name: str) -> EnvValue:
        if winreg is None:
            value = os.environ.get(name)
            return EnvValue(value is not None, value, source="process")
        try:
            with self._open_env_key(False) as key:
                value, kind = winreg.QueryValueEx(key, name)
                if isinstance(value, (list, tuple)):
                    value = "\x00".join(str(v) for v in value)
                return EnvValue(True, str(value), _reg_kind_name(kind), f"HKCU\\{ENV_KEY}")
        except FileNotFoundError:
            process_value = os.environ.get(name)
            if process_value is not None:
                return EnvValue(True, process_value, source="process (用户级未设置)")
            return EnvValue(False, source="HKCU\\Environment 中不存在")
        except OSError as exc:
            return EnvValue(False, source=f"读取失败: {exc}")

    def get_persistent_env(self, name: str) -> EnvValue:
        if winreg is None:
            return EnvValue(False, source="winreg 不可用")
        try:
            with self._open_env_key(False) as key:
                value, kind = winreg.QueryValueEx(key, name)
                if isinstance(value, (list, tuple)):
                    value = "\x00".join(str(v) for v in value)
                return EnvValue(True, str(value), _reg_kind_name(kind), f"HKCU\\{ENV_KEY}")
        except FileNotFoundError:
            return EnvValue(False, source="HKCU\\Environment 中不存在")
        except OSError as exc:
            return EnvValue(False, source=f"读取失败: {exc}")

    def get_user_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_user_env(name) for name in names}

    def get_persistent_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_persistent_env(name) for name in names}

    def effective_env(self) -> dict[str, str]:
        env = super().effective_env()
        for name in ("TZ", "LANG", "LC_ALL", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
            value = self.get_user_env(name)
            if value.exists and value.value is not None:
                env[name] = value.value
        return env

    def set_user_env(self, name: str, value: str) -> OperationResult:
        if winreg is None:
            return OperationResult(False, "winreg 不可用，无法写用户环境变量")
        try:
            with self._open_env_key(True) as key:
                winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
        except OSError as exc:
            return OperationResult(False, f"写入 HKCU\\Environment\\{name} 失败: {exc}", error=str(exc))
        os.environ[name] = str(value)
        self.broadcast_env_change()
        return OperationResult(True, f"已写入用户环境变量 {name}（新进程生效）")

    def delete_user_env(self, name: str) -> OperationResult:
        if winreg is None:
            return OperationResult(False, "winreg 不可用，无法删除用户环境变量")
        try:
            with self._open_env_key(True) as key:
                try:
                    winreg.DeleteValue(key, name)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            return OperationResult(False, f"删除 HKCU\\Environment\\{name} 失败: {exc}", error=str(exc))
        os.environ.pop(name, None)
        self.broadcast_env_change()
        return OperationResult(True, f"已删除用户环境变量 {name}（新进程生效）")

    def broadcast_env_change(self) -> None:
        try:
            result = ctypes.c_ulong()
            ctypes.windll.user32.SendMessageTimeoutW(
                HWND_BROADCAST,
                WM_SETTINGCHANGE,
                0,
                ctypes.c_wchar_p("Environment"),
                SMTO_ABORTIFHUNG,
                3000,
                ctypes.byref(result),
            )
        except (AttributeError, OSError):
            pass

    def get_user_language(self) -> str | None:
        if winreg is not None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
                    value, kind = winreg.QueryValueEx(key, "PreferredUILanguages")
                    if kind == winreg.REG_MULTI_SZ:
                        items = [str(v) for v in value if str(v).strip()]
                    else:
                        items = [part for part in str(value).replace("\x00", "\n").splitlines() if part.strip()]
                    if items:
                        return items[0].strip()
            except (FileNotFoundError, OSError):
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\International") as key:
                    value, _kind = winreg.QueryValueEx(key, "LocaleName")
                    if value:
                        return str(value).strip()
            except (FileNotFoundError, OSError):
                pass
        data = proc.powershell_json("Get-Culture | Select-Object Name", timeout=6)
        if isinstance(data, dict) and data.get("Name"):
            return str(data["Name"])
        return os.environ.get("LANG") or os.environ.get("LC_ALL")

    # --- timezone --------------------------------------------------------
    def get_system_timezone(self) -> SystemTimezone:
        result = run(["tzutil", "/g"], timeout=6)
        native = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else None
        if not native:
            data = proc.powershell_json("Get-TimeZone | Select-Object Id,BaseUtcOffset", timeout=8)
            if isinstance(data, dict):
                native = str(data.get("Id") or "") or None
        iana = iana_for_windows_id(native)
        return SystemTimezone(
            native_id=native,
            iana=iana,
            utc_offset_seconds=_windows_current_offset_seconds(),
            source="tzutil /g",
            raw=result.to_dict(),
            error=result.error if not native else None,
        )

    def set_system_timezone(self, iana: str, *, confirm: bool = False) -> OperationResult:
        if not confirm:
            return OperationResult(False, "修改系统时区需要用户在界面中显式确认")
        native = windows_id_for_iana(iana)
        if not native:
            return OperationResult(
                False,
                f"Sentinel 的映射表没有 {iana} 对应的 Windows 时区 ID；为避免猜测，本次不修改系统时区。",
            )
        return self.set_system_timezone_native(native, confirm=True)

    def set_system_timezone_native(self, native_id: str, *, confirm: bool = False) -> OperationResult:
        if not confirm:
            return OperationResult(False, "修改系统时区需要用户在界面中显式确认")
        if not native_id:
            return OperationResult(False, "目标 Windows 时区 ID 为空")
        result = run(["tzutil", "/s", native_id], timeout=15)
        verified = run(["tzutil", "/g"], timeout=6)
        current = verified.stdout.strip()
        ok = result.ok and current == native_id
        detail = (result.stdout + result.stderr).strip() or (
            f"系统时区已设为 {native_id}" if ok else "tzutil 修改失败"
        )
        return OperationResult(
            ok,
            detail,
            command=list(result.argv),
            error=result.error,
            output=result.stdout + result.stderr,
        )

    # --- process / network ----------------------------------------------
    def list_processes(self) -> list[ProcessEntry]:
        return proc.list_processes()

    def get_tun_info(self) -> TunInfo:
        data = proc.powershell_json(
            "Get-NetAdapter -IncludeHidden | Select-Object Name,InterfaceDescription,Status,InterfaceType",
            timeout=12,
        )
        if data is None:
            return TunInfo(active=False, source="Get-NetAdapter", error="无法读取网络适配器列表")
        if isinstance(data, dict):
            data = [data]
        adapters: list[dict[str, Any]] = []
        for row in data:
            name = str(row.get("Name") or "")
            description = str(row.get("InterfaceDescription") or "")
            combined = f"{name} {description}".lower()
            is_tun = any(
                token in combined
                for token in ("wintun", "wireguard", "sing-box", "singbox", "mihomo", "clash", "v2ray", "xray", "tun", "tap", "utun")
            )
            if is_tun:
                adapters.append(
                    {
                        "name": name,
                        "description": description,
                        "status": str(row.get("Status") or ""),
                        "type": str(row.get("InterfaceType") or ""),
                    }
                )
        active = any(str(a.get("status", "")).lower() == "up" for a in adapters)
        return TunInfo(active=active, adapters=adapters, source="Get-NetAdapter")

    def local_addresses(self) -> list[dict[str, Any]]:
        data = proc.powershell_json(
            "Get-NetIPAddress -AddressFamily IPv4 | Select-Object IPAddress,InterfaceAlias",
            timeout=10,
        )
        if data is None:
            return super().local_addresses()
        if isinstance(data, dict):
            data = [data]
        addresses: list[dict[str, Any]] = []
        for row in data:
            ip = str(row.get("IPAddress") or "")
            if ip:
                addresses.append({"ip": ip, "interface": str(row.get("InterfaceAlias") or "")})
        return addresses

    # --- discovery -------------------------------------------------------
    def browser_paths(self) -> dict[str, str | None]:
        candidates: dict[str, list[Path]] = {"chrome": [], "edge": []}
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        pf = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files"))
        pf86 = Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"))
        candidates["chrome"].extend(
            [
                local / "Google" / "Chrome" / "Application" / "chrome.exe",
                pf / "Google" / "Chrome" / "Application" / "chrome.exe",
                pf86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            ]
        )
        candidates["edge"].extend(
            [
                pf86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                pf / "Microsoft" / "Edge" / "Application" / "msedge.exe",
                local / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            ]
        )
        result: dict[str, str | None] = {}
        for key, paths in candidates.items():
            found = next((str(p) for p in paths if p.is_file()), None)
            if found is None:
                exe = "chrome.exe" if key == "chrome" else "msedge.exe"
                found = shutil.which(exe)
            result[key] = found
        return result

    def claude_paths(self) -> dict[str, str | None]:
        local = Path(os.environ.get("LOCALAPPDATA", ""))
        appdata = Path(os.environ.get("APPDATA", ""))
        candidates = [
            local / "AnthropicClaude" / "Claude.exe",
            local / "AnthropicClaude" / "claude.exe",
            local / "Programs" / "Claude" / "Claude.exe",
            local / "Claude" / "Claude.exe",
        ]
        try:
            candidates.extend(Path(p) for p in glob.glob(str(local / "AnthropicClaude" / "app-*" / "Claude.exe")))
        except OSError:
            pass
        desktop = next((str(p) for p in candidates if p.is_file()), None)
        cli = shutil.which("claude") or shutil.which("claude.cmd")
        npm_cli = appdata / "npm" / "claude.cmd"
        if cli is None and npm_cli.is_file():
            cli = str(npm_cli)
        return {"cli": cli, "desktop": desktop}

    def detect_claude(self) -> ClaudeClientInfo:
        paths = self.claude_paths()
        info = ClaudeClientInfo(cli_path=paths.get("cli"), desktop_path=paths.get("desktop"))
        try:
            processes = self.list_processes()
        except Exception:
            processes = []
        info.process_entries = [
            p for p in processes if (p.name or "").lower() in {"claude.exe", "claude", "claude-code.exe"}
        ]
        if info.cli_path:
            info.client_types.append("CLI")
        if info.desktop_path:
            info.client_types.append("Desktop")
        if info.process_entries:
            info.client_types.append("正在运行的 Claude 进程")
        if not info.client_types:
            if self.browser_paths().get("chrome") or self.browser_paths().get("edge"):
                info.client_types.append("Browser（已安装浏览器，登录状态未验证）")
            else:
                info.errors.append("未发现 Claude CLI、桌面客户端或浏览器")
        # Never execute the desktop GUI just to read its version: launching it
        # would be an unexpected side effect of an audit.  File metadata is
        # enough for the desktop client; only the CLI is invoked with
        # --version.
        if info.cli_path:
            version_source = info.cli_path
            if version_source.lower().endswith((".cmd", ".bat")):
                result = run(["cmd.exe", "/d", "/c", version_source, "--version"], timeout=6)
            else:
                result = run([version_source, "--version"], timeout=6)
            if result.ok and result.stdout.strip():
                info.version = result.stdout.strip().splitlines()[0][:200]
            else:
                info.version = file_version(version_source)
        elif info.desktop_path:
            info.version = file_version(info.desktop_path)
        if (info.cli_path or info.desktop_path) and not info.version:
            info.errors.append("客户端版本采样失败（文件可能存在，但版本不可读）")
        info.identity_inspected = False
        return info

    def font_dirs(self) -> list[Path]:
        dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
        local_fonts = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts"
        if local_fonts.is_dir():
            dirs.append(local_fonts)
        return dirs

    def running_process_names(self) -> set[str]:
        try:
            return {p.name.lower() for p in self.list_processes() if p.name}
        except Exception:
            return set()

    def browser_running(self, browser_key: str) -> bool:
        names = self.running_process_names()
        mapping = {"chrome": {"chrome.exe", "chrome"}, "edge": {"msedge.exe", "msedge"}}
        return bool(names & mapping.get(browser_key, {browser_key.lower(), browser_key.lower() + ".exe"}))

    # --- kill switch / firewall -----------------------------------------
    def is_admin(self) -> bool:
        return proc.is_admin()

    def killswitch_capability(self) -> tuple[bool, str]:
        if not self.is_admin():
            return False, "Kill-Switch 需要管理员权限创建 Windows 出站防火墙规则；请以管理员身份运行 Sentinel。"
        if not shutil.which("powershell.exe"):
            return False, "找不到 powershell.exe，无法管理防火墙规则。"
        return True, "Windows 用户环境具备防火墙规则能力（管理员已确认）。"

    def firewall_add(self, rule_name: str, program_path: str) -> OperationResult:
        if not self.is_admin():
            return OperationResult(False, "创建防火墙规则需要管理员权限")
        if not program_path or not Path(program_path).is_file():
            return OperationResult(False, f"程序路径不存在，无法建立规则: {program_path}")
        script = (
            f"New-NetFirewallRule -DisplayName {_ps_quote(rule_name)} "
            f"-Direction Outbound -Program {_ps_quote(program_path)} "
            "-Action Block -Profile Any -Enabled True -ErrorAction Stop | Out-Null;"
            f"if (Get-NetFirewallRule -DisplayName {_ps_quote(rule_name)} -ErrorAction SilentlyContinue) "
            "{ 'SENTINEL_OK' } else { 'SENTINEL_MISSING' }"
        )
        result = proc.run_powershell(script, timeout=30)
        ok = result.ok and "SENTINEL_OK" in result.stdout
        return OperationResult(
            ok,
            f"已添加出站阻断规则 {rule_name}" if ok else (result.stderr.strip() or "防火墙规则创建失败"),
            command=list(result.argv),
            error=result.error,
            output=result.stdout + result.stderr,
        )

    def firewall_delete(self, rule_name: str) -> OperationResult:
        if not self.is_admin():
            return OperationResult(False, "删除防火墙规则需要管理员权限")
        script = (
            f"Remove-NetFirewallRule -DisplayName {_ps_quote(rule_name)} -ErrorAction SilentlyContinue;"
            f"if (Get-NetFirewallRule -DisplayName {_ps_quote(rule_name)} -ErrorAction SilentlyContinue) "
            "{ 'SENTINEL_STILL_PRESENT' } else { 'SENTINEL_GONE' }"
        )
        result = proc.run_powershell(script, timeout=30)
        ok = result.ok and "SENTINEL_GONE" in result.stdout
        return OperationResult(
            ok,
            f"已删除防火墙规则 {rule_name}" if ok else (result.stderr.strip() or "防火墙规则删除失败"),
            command=list(result.argv),
            error=result.error,
            output=result.stdout + result.stderr,
        )

    def firewall_rule_exists(self, rule_name: str) -> bool:
        if not self.is_admin():
            return False
        script = (
            f"if (Get-NetFirewallRule -DisplayName {_ps_quote(rule_name)} -ErrorAction SilentlyContinue) "
            "{ 'YES' } else { 'NO' }"
        )
        result = proc.run_powershell(script, timeout=15)
        return "YES" in result.stdout

    def hotkey_available(self) -> bool:
        return True

    def hotkey_unavailable_reason(self) -> str:
        return ""
