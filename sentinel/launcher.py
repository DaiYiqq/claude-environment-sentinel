"""Safe-start orchestration.

The gate is deliberately re-evaluated here, not trusted from the GUI's last
report.  If the fresh audit fails, ``Popen`` is never reached.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel.audit.engine import AuditEngine
from sentinel.config import AppPaths, Settings
from sentinel.killswitch import KillSwitch
from sentinel.models import AuditReport
from sentinel.platform.base import PlatformAdapter
from sentinel.util.log import JsonlLogger
from sentinel.util.proc import CREATE_NO_WINDOW, IS_WINDOWS


class SafeStartBlocked(RuntimeError):
    pass


@dataclass
class LaunchCommand:
    argv: list[str]
    program: str
    label: str
    is_batch: bool = False
    is_cli: bool = False

    def to_dict(self) -> dict[str, Any]:
        # Do not retain a full argument vector: it can contain user prompts.
        return {"program": self.program, "label": self.label, "is_batch": self.is_batch, "is_cli": self.is_cli}


@dataclass
class SafeStartResult:
    ok: bool
    detail: str
    audit: AuditReport | None = None
    pid: int | None = None
    command: LaunchCommand | None = None
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "pid": self.pid,
            "command": self.command.to_dict() if self.command else None,
            "failures": list(self.failures),
            "audit_id": self.audit.report_id if self.audit else None,
            "risk_score": self.audit.risk_score if self.audit else None,
        }


class SafeLauncher:
    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        platform: PlatformAdapter,
        killswitch: KillSwitch,
        audit_engine: AuditEngine,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.platform = platform
        self.killswitch = killswitch
        self.audit_engine = audit_engine
        self.log = JsonlLogger(paths.logs / "sentinel.jsonl")
        self._process: subprocess.Popen[Any] | None = None
        self._last_audit: AuditReport | None = None
        self._launch_command: LaunchCommand | None = None

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def resolve_command(self) -> LaunchCommand | None:
        raw = self.settings.claude_command.strip()
        argv: list[str] = []
        program = ""
        if raw:
            try:
                parts = [part.strip('"') for part in shlex.split(raw, posix=False)]
            except ValueError as exc:
                self.log.write("safe_start_bad_command", error=str(exc))
                return None
            if not parts:
                return None
            program = parts[0]
            argv = parts
        else:
            detected = self.platform.claude_paths()
            if detected.get("cli"):
                program = str(detected["cli"])
                argv = [program]
            elif detected.get("desktop"):
                program = str(detected["desktop"])
                argv = [program]
            else:
                return None
        if not program:
            return None
        argv.extend(self.settings.claude_arguments)
        is_batch = program.lower().endswith((".cmd", ".bat"))
        lowered = program.lower()
        is_desktop = any(token in lowered for token in ("anthropicclaude", "claude.app", "programs\\claude", "programs/claude"))
        is_cli = is_batch or not is_desktop
        if is_batch and IS_WINDOWS:
            # CreateProcess cannot reliably start a .cmd directly.  The wrapper
            # is part of the process tree, and the kill-switch collects its
            # Claude descendants.
            batch_line = subprocess.list2cmdline(argv)
            argv = ["cmd.exe", "/d", "/s", "/c", batch_line]
        return LaunchCommand(
            argv=argv,
            program=program,
            label=Path(program).name or program,
            is_batch=is_batch,
            is_cli=is_cli,
        )

    def start(self) -> SafeStartResult:
        if self.killswitch.latched:
            return SafeStartResult(
                ok=False,
                detail="Kill-Switch 处于锁定状态；请先在专家模式中手动解除。",
                failures=["killswitch_latched"],
            )
        fresh = self.audit_engine.run(save_baseline=False, export=False)
        self._last_audit = fresh
        if not fresh.gate.allowed:
            reasons = "; ".join(fresh.gate.reasons) or "审计未通过"
            self.log.write("safe_start_blocked", audit_id=fresh.report_id, risk=fresh.risk_score, reasons=fresh.gate.reasons)
            return SafeStartResult(
                ok=False,
                detail=f"审计未通过，已阻止启动 Claude：{reasons}",
                audit=fresh,
                failures=list(fresh.gate.reasons),
            )
        command = self.resolve_command()
        if command is None:
            return SafeStartResult(
                ok=False,
                detail="未找到 Claude 启动命令；请在专家模式指定 CLI 或桌面客户端路径。",
                audit=fresh,
                failures=["launch_command_missing"],
            )
        ready, reason = self.platform.killswitch_capability()
        if not ready:
            return SafeStartResult(ok=False, detail=reason, audit=fresh, failures=[reason])
        env = self.platform.effective_env()
        env.pop("SENTINEL_INTERNAL", None)
        creationflags = 0
        stdout = None
        stderr = None
        stdin = None
        if IS_WINDOWS and command.is_cli:
            creationflags = subprocess.CREATE_NEW_CONSOLE  # type: ignore[attr-defined]
        elif IS_WINDOWS:
            creationflags = CREATE_NO_WINDOW
            stdout = subprocess.DEVNULL
            stderr = subprocess.DEVNULL
            stdin = subprocess.DEVNULL
        try:
            self._process = subprocess.Popen(
                command.argv,
                env=env,
                cwd=None,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                creationflags=creationflags,
                start_new_session=not IS_WINDOWS,
            )
        except (OSError, ValueError) as exc:
            self.log.write("safe_start_spawn_failed", error=str(exc), command=command.to_dict())
            return SafeStartResult(
                ok=False,
                detail=f"拉起 Claude 失败：{exc}",
                audit=fresh,
                command=command,
                failures=[str(exc)],
            )
        runtime = fresh.runtime or {}
        arm = self.killswitch.arm(
            pid=self._process.pid,
            expected_country=fresh.egress.country_code if fresh.egress else None,
            expected_ip=fresh.egress.ip if fresh.egress else None,
            expected_proxy_core=bool(runtime.get("proxy_core_alive")),
            expected_tun=bool(runtime.get("tun_active")),
            samples={
                "audit_id": fresh.report_id,
                "egress": fresh.egress.to_dict() if fresh.egress else None,
                "runtime": runtime,
                "command": command.to_dict(),
            },
        )
        if not arm.get("ok"):
            try:
                self._process.terminate()
            except OSError:
                pass
            self.log.write("safe_start_arm_failed", detail=arm.get("detail"))
            return SafeStartResult(
                ok=False,
                detail=f"Claude 已拉起但 Kill-Switch 布防失败，已回退终止：{arm.get('detail')}",
                audit=fresh,
                command=command,
                failures=[str(arm.get("detail"))],
            )
        self._launch_command = command
        self.log.write(
            "safe_start",
            audit_id=fresh.report_id,
            risk_score=fresh.risk_score,
            pid=self._process.pid,
            command=command.to_dict(),
        )
        return SafeStartResult(
            ok=True,
            detail=f"审计通过，已安全启动 {command.label}（PID {self._process.pid}），Kill-Switch 已布防。",
            audit=fresh,
            pid=self._process.pid,
            command=command,
        )

    def stop(self) -> dict[str, Any]:
        result = self.killswitch.stop_managed()
        if self._process is not None:
            try:
                if self._process.poll() is None:
                    self._process.terminate()
                    try:
                        self._process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        self._process.kill()
            except OSError:
                pass
        self._process = None
        self.log.write("safe_stop", **result)
        return result

    def poll(self) -> int | None:
        return self._process.poll() if self._process is not None else None
