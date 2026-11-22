"""Linux adapter (audit + user-level alignment; no process-level firewall)."""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path

from sentinel.models import ClaudeClientInfo
from sentinel.platform.base import PosixPlatformAdapter
from sentinel.util.proc import file_version, run


class LinuxPlatform(PosixPlatformAdapter):
    name = "linux"
    display_name = "Linux"
    supports_system_timezone = True
    supports_process_firewall = False

    def browser_paths(self) -> dict[str, str | None]:
        return {
            "chrome": shutil.which("google-chrome") or shutil.which("google-chrome-stable") or shutil.which("chromium"),
            "edge": shutil.which("microsoft-edge") or shutil.which("microsoft-edge-stable"),
        }

    def claude_paths(self) -> dict[str, str | None]:
        cli = shutil.which("claude") or shutil.which("claude-code")
        desktop_candidates = [
            Path("/opt/Claude/claude-desktop"),
            Path("/usr/bin/claude-desktop"),
            Path.home() / "Applications" / "Claude.AppImage",
        ]
        desktop = next((str(p) for p in desktop_candidates if p.is_file()), None)
        return {"cli": cli, "desktop": desktop}

    def detect_claude(self) -> ClaudeClientInfo:
        paths = self.claude_paths()
        info = ClaudeClientInfo(cli_path=paths.get("cli"), desktop_path=paths.get("desktop"))
        if info.cli_path:
            info.client_types.append("CLI")
        if info.desktop_path:
            info.client_types.append("Desktop")
        try:
            info.process_entries = [
                p for p in self.list_processes() if (p.name or "").lower() in {"claude", "claude-code"}
            ]
        except Exception:
            pass
        if info.process_entries:
            info.client_types.append("正在运行的 Claude 进程")
        if not info.client_types and (self.browser_paths().get("chrome") or self.browser_paths().get("edge")):
            info.client_types.append("Browser（已安装浏览器，登录状态未验证）")
        if info.cli_path:
            result = run([info.cli_path, "--version"], timeout=6)
            if result.ok and result.stdout.strip():
                info.version = result.stdout.strip().splitlines()[0][:200]
            else:
                info.version = file_version(info.cli_path)
        elif info.desktop_path:
            # Do not launch the desktop GUI just to read a version; report it
            # as unknown instead of causing a side effect during an audit.
            info.version = None
        if (info.cli_path or info.desktop_path) and not info.version:
            info.errors.append("客户端版本采样失败")
        info.identity_inspected = False
        return info

    def running_process_names(self) -> set[str]:
        try:
            return {p.name.lower() for p in self.list_processes() if p.name}
        except Exception:
            return set()

    def browser_running(self, browser_key: str) -> bool:
        names = self.running_process_names()
        if browser_key == "chrome":
            return bool(names & {"chrome", "google-chrome", "chromium"})
        if browser_key == "edge":
            return bool(names & {"msedge", "microsoft-edge"})
        return False

    def killswitch_capability(self) -> tuple[bool, str]:
        return (
            False,
            "Linux 版尚未提供可验证的进程级出站隔离后端；为避免虚假安全感，安全启动被禁用。"
            "审计、对齐和快照仍可使用。",
        )

    def hotkey_available(self) -> bool:
        return importlib.util.find_spec("pynput") is not None

    def hotkey_unavailable_reason(self) -> str:
        return "Linux 全局热键需要可选依赖 pynput；未安装时不可用。"
