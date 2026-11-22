"""Subprocess, PowerShell, process-tree and privilege helpers.

No shell is used for Sentinel's own commands.  Command lines are intentionally
not retained in reports: Claude session arguments can contain sensitive data.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from sentinel.models import ProcessEntry

IS_WINDOWS = os.name == "nt"
CREATE_NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


@dataclass
class CommandResult:
    argv: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {
            "argv": list(self.argv),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
            "error": self.error,
        }


def run(
    argv: Iterable[str],
    *,
    timeout: float = 8.0,
    env: dict[str, str] | None = None,
    cwd: str | None = None,
    input_text: str | None = None,
) -> CommandResult:
    args = [str(a) for a in argv]
    try:
        proc = subprocess.run(
            args,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(0.5, float(timeout)),
            env=env,
            cwd=cwd,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return CommandResult(args, proc.returncode, proc.stdout or "", proc.stderr or "")
    except subprocess.TimeoutExpired as exc:
        return CommandResult(
            args,
            None,
            (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or ""),
            (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""),
            timed_out=True,
            error=f"命令超时（{timeout}s）",
        )
    except (OSError, ValueError) as exc:
        return CommandResult(args, None, error=str(exc))


def run_powershell(script: str, *, timeout: float = 10.0) -> CommandResult:
    if not IS_WINDOWS:
        return CommandResult(["powershell"], None, error="PowerShell 仅在 Windows 可用")
    wrapped = (
        "$ProgressPreference='SilentlyContinue';"
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
        "$OutputEncoding=[System.Text.Encoding]::UTF8;"
        + script
    )
    return run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            wrapped,
        ],
        timeout=timeout,
    )


def powershell_json(script: str, *, timeout: float = 10.0) -> Any:
    result = run_powershell(script + " | ConvertTo-Json -Depth 6 -Compress", timeout=timeout)
    if not result.ok:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def which(name: str) -> str | None:
    return shutil.which(name)


def is_admin() -> bool:
    if IS_WINDOWS:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (AttributeError, OSError):
            return False
    try:
        return os.geteuid() == 0  # type: ignore[attr-defined]
    except AttributeError:
        return False


def list_processes(*, timeout: float = 8.0) -> list[ProcessEntry]:
    if IS_WINDOWS:
        data = powershell_json(
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name,ExecutablePath",
            timeout=timeout,
        )
        if data is None:
            return []
        if isinstance(data, dict):
            data = [data]
        entries: list[ProcessEntry] = []
        for row in data:
            try:
                entries.append(
                    ProcessEntry(
                        pid=int(row.get("ProcessId") or 0),
                        ppid=int(row.get("ParentProcessId") or 0),
                        name=str(row.get("Name") or ""),
                        exe_path=str(row["ExecutablePath"]) if row.get("ExecutablePath") else None,
                    )
                )
            except (TypeError, ValueError):
                continue
        return entries
    result = run(["ps", "-axo", "pid=,ppid=,comm="], timeout=timeout)
    entries = []
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        try:
            entries.append(ProcessEntry(pid=int(parts[0]), ppid=int(parts[1]), name=parts[2].strip()))
        except ValueError:
            continue
    return entries


def descendants(root_pid: int, processes: list[ProcessEntry] | None = None) -> list[ProcessEntry]:
    procs = processes if processes is not None else list_processes()
    by_parent: dict[int, list[ProcessEntry]] = {}
    for proc in procs:
        by_parent.setdefault(proc.ppid, []).append(proc)
    found: list[ProcessEntry] = []
    queue = [root_pid]
    seen = {root_pid}
    while queue:
        parent = queue.pop(0)
        for child in by_parent.get(parent, []):
            if child.pid in seen:
                continue
            seen.add(child.pid)
            found.append(child)
            queue.append(child.pid)
    return found


def process_tree(root_pid: int, processes: list[ProcessEntry] | None = None) -> list[ProcessEntry]:
    procs = processes if processes is not None else list_processes()
    root = next((p for p in procs if p.pid == root_pid), None)
    return ([root] if root else []) + descendants(root_pid, procs)


def terminate_process_tree(pid: int, *, timeout: float = 8.0) -> CommandResult:
    if pid <= 0:
        return CommandResult(["taskkill"], None, error="无效 PID")
    if IS_WINDOWS:
        return run(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=timeout)
    # POSIX: terminate descendants first, then the root.  Claude launched by
    # Sentinel uses its own process group, so killpg is preferred when safe.
    procs = list_processes()
    targets = [p.pid for p in descendants(pid, procs)] + [pid]
    errors: list[str] = []
    for target in targets:
        try:
            os.kill(target, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except OSError as exc:
            errors.append(f"pid {target}: {exc}")
    return CommandResult(["kill", *map(str, targets)], 0 if not errors else 1, stderr="; ".join(errors))


def port_open(port: int, host: str = "127.0.0.1", timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def listening_ports(ports: Iterable[int]) -> dict[int, bool]:
    return {int(port): port_open(int(port)) for port in ports}


def file_version(path: str) -> str | None:
    if not path:
        return None
    if IS_WINDOWS:
        data = powershell_json(
            f"(Get-Item -LiteralPath {json.dumps(path)}).VersionInfo | "
            "Select-Object FileVersion,ProductVersion",
            timeout=6,
        )
        if isinstance(data, dict):
            return str(data.get("FileVersion") or data.get("ProductVersion") or "") or None
        return None
    result = run([path, "--version"], timeout=4)
    if result.ok:
        return result.stdout.strip().splitlines()[0][:200] if result.stdout.strip() else None
    return None


def hostname() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "unknown"


def safe_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Copy of the current environment with non-string values removed."""
    source = os.environ if base is None else base
    return {str(k): str(v) for k, v in source.items() if v is not None}
