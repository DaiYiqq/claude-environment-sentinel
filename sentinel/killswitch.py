"""Kill-Switch: monitor Claude, terminate its tree and block reconnection.

The monitor is an in-process daemon thread, not a persistent service.  It only
runs while Sentinel is managing a Claude process.  Trigger state is latched and
persisted; only an explicit user action removes the firewall rules and clears
the latch.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from sentinel.audit.probes import PROXY_NAME_RE
from sentinel.config import AppPaths, Settings, atomic_write_json
from sentinel.models import ProcessEntry
from sentinel.platform.base import PlatformAdapter
from sentinel.util.log import JsonlLogger
from sentinel.util.net import NetworkProbe, read_proxy_env
from sentinel.util.proc import port_open, process_tree, run, terminate_process_tree
from sentinel.util.redact import redact_mapping


@dataclass
class KillSwitchSnapshot:
    checked_at: str
    egress: dict[str, Any]
    country: str | None
    ip: str | None
    proxy_core_alive: bool
    tun_active: bool
    proxy_processes: list[str] = field(default_factory=list)


class KillSwitch:
    def __init__(
        self,
        paths: AppPaths,
        platform: PlatformAdapter,
        settings: Settings,
        *,
        network: NetworkProbe | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.paths = paths
        self.platform = platform
        self.settings = settings
        self.network = network or NetworkProbe(
            timeout=settings.http_timeout_seconds,
            enabled=settings.network_enabled,
        )
        self.on_event = on_event
        self.log = JsonlLogger(paths.logs / "killswitch.jsonl")
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None
        self._latched = False
        self._armed = False
        self._session_id: str | None = None
        self._pid: int | None = None
        self._started_at: str | None = None
        self._expected_country: str | None = None
        self._expected_ip: str | None = None
        self._expected_proxy_core = False
        self._expected_tun = False
        self._rules: list[str] = []
        self._last_trigger: dict[str, Any] | None = None
        self._last_samples: dict[str, Any] | None = None
        self._load_persisted()

    # --- public state ----------------------------------------------------
    @property
    def latched(self) -> bool:
        return self._latched

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def pid(self) -> int | None:
        return self._pid

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "latched": self._latched,
                "armed": self._armed,
                "session_id": self._session_id,
                "pid": self._pid,
                "started_at": self._started_at,
                "expected_country": self._expected_country,
                "expected_ip": self._expected_ip,
                "expected_proxy_core": self._expected_proxy_core,
                "expected_tun": self._expected_tun,
                "rules": list(self._rules),
                "last_trigger": self._last_trigger,
                "last_samples": self._last_samples,
                "poll_seconds": self.settings.poll_seconds,
            }

    # --- persistence -----------------------------------------------------
    def _load_persisted(self) -> None:
        path = self.paths.killswitch_state_file
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        self._latched = bool(data.get("latched"))
        # A persisted "armed" flag from a previous process cannot be trusted:
        # there is no monitor thread after restart.  Keep only the latched
        # state, which is deliberately sticky and requires manual release.
        self._armed = False
        self._session_id = str(data.get("session_id") or "") or None
        self._pid = int(data["pid"]) if isinstance(data.get("pid"), int) else None
        self._expected_country = str(data.get("expected_country") or "") or None
        self._expected_ip = str(data.get("expected_ip") or "") or None
        self._rules = [str(r) for r in data.get("rules") or []]
        self._last_trigger = data.get("last_trigger") if isinstance(data.get("last_trigger"), dict) else None
        self._last_samples = data.get("last_samples") if isinstance(data.get("last_samples"), dict) else None
        self._started_at = str(data.get("started_at") or "") or None
        # A persisted latch is deliberate; don't auto-remove rules or start.

    def _persist(self) -> None:
        data = {
            "schema_version": 1,
            "latched": self._latched,
            "armed": self._armed,
            "session_id": self._session_id,
            "pid": self._pid,
            "started_at": self._started_at,
            "expected_country": self._expected_country,
            "expected_ip": self._expected_ip,
            "expected_proxy_core": self._expected_proxy_core,
            "expected_tun": self._expected_tun,
            "rules": list(self._rules),
            "last_trigger": self._last_trigger,
            "last_samples": self._last_samples,
            "updated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        try:
            atomic_write_json(self.paths.killswitch_state_file, data, mode=0o600)
        except OSError:
            pass

    # --- arming ----------------------------------------------------------
    def arm(
        self,
        *,
        pid: int,
        expected_country: str | None,
        expected_ip: str | None,
        expected_proxy_core: bool,
        expected_tun: bool,
        samples: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._latched:
                return {"ok": False, "detail": "Kill-Switch 处于锁定状态，必须先手动解除。"}
            self._armed = True
            self._pid = int(pid)
            self._session_id = uuid.uuid4().hex[:12]
            self._started_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self._expected_country = (expected_country or "").upper() or None
            self._expected_ip = expected_ip or None
            self._expected_proxy_core = bool(expected_proxy_core)
            self._expected_tun = bool(expected_tun)
            self._last_samples = redact_mapping(samples or {})
            self._stop.clear()
            self._persist()
            self._monitor = threading.Thread(
                target=self._monitor_loop,
                name="sentinel-killswitch",
                daemon=True,
            )
            self._monitor.start()
            self.log.write(
                "killswitch_armed",
                pid=pid,
                expected_country=self._expected_country,
                expected_ip=self._expected_ip,
                expected_proxy_core=self._expected_proxy_core,
                expected_tun=self._expected_tun,
            )
            self._emit("armed", self.status())
            return {"ok": True, "detail": "Kill-Switch 已布防。"}

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event, payload)
            except Exception:
                pass

    # --- monitor ---------------------------------------------------------
    def _monitor_loop(self) -> None:
        while not self._stop.wait(max(2.0, float(self.settings.poll_seconds))):
            if not self._armed or self._latched:
                break
            try:
                sample = self.sample()
            except Exception as exc:
                self.trigger(
                    source="monitor",
                    check_id="monitor_error",
                    reason=f"Kill-Switch 采样异常: {exc}",
                    samples={"error": str(exc)},
                )
                break
            problems = self.evaluate(sample)
            if problems:
                self.trigger(
                    source="monitor",
                    check_id=problems[0][0],
                    reason="; ".join(reason for _cid, reason in problems),
                    samples=sample.__dict__,
                )
                break
        with self._lock:
            if self._armed and not self._latched:
                # Thread ended unexpectedly; make the loss of protection visible.
                self._armed = False
                self._persist()
                self._emit("monitor_stopped", self.status())

    def sample(self, *, force: bool = True) -> KillSwitchSnapshot:
        egress = self.network.egress(force=force)
        try:
            procs = self.platform.list_processes()
        except Exception:
            procs = []
        proxy_env = read_proxy_env(self.platform.effective_env())
        names = [p.name for p in procs if p.name and PROXY_NAME_RE.search(p.name)]
        # A lightweight liveness check for the common local proxy ports.  The
        # full audit does the more expensive port sweep; a 5s monitor should
        # not itself become a source of load.
        alive = bool(names)
        if not alive:
            ports = {7890, 7891, 1080, 10808, 2080}
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                value = proxy_env.get(name)
                if not value:
                    continue
                candidate = value if "://" in value else "http://" + value
                try:
                    from urllib.parse import urlsplit

                    port = urlsplit(candidate).port
                    if port:
                        ports.add(int(port))
                except (ValueError, TypeError):
                    pass
            alive = any(port_open(port, timeout=0.2) for port in sorted(ports))
        tun = self.platform.get_tun_info()
        return KillSwitchSnapshot(
            checked_at=datetime.now().astimezone().isoformat(timespec="seconds"),
            egress=egress.to_dict(),
            country=egress.country_code,
            ip=egress.ip,
            proxy_core_alive=alive,
            tun_active=bool(tun.active),
            proxy_processes=names,
        )

    def evaluate(self, sample: KillSwitchSnapshot) -> list[tuple[str, str]]:
        problems: list[tuple[str, str]] = []
        if not sample.egress.get("ok"):
            problems.append(("A5", "出口 IP 探测失败，无法确认网络是否仍符合安全启动基线"))
        elif self._expected_country and not sample.country:
            problems.append(("A5", "出口国家在本轮采样中缺失，无法确认是否仍符合基线"))
        elif self._expected_country and sample.country and sample.country.upper() != self._expected_country:
            problems.append(("A5", f"出口国家变化：{self._expected_country} -> {sample.country}"))
        if self._expected_ip and sample.ip and sample.ip != self._expected_ip:
            problems.append(("A5/IP", f"出口 IP 变化：{self._expected_ip} -> {sample.ip}"))
        if self._expected_proxy_core and not sample.proxy_core_alive:
            problems.append(("A11", "代理内核已不存活"))
        if (self._expected_tun or self.settings.require_tun) and not sample.tun_active:
            problems.append(("A12", "TUN 已不处于活动状态"))
        return problems

    # --- trigger ---------------------------------------------------------
    def trigger(
        self,
        *,
        source: str,
        check_id: str,
        reason: str,
        samples: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._latched:
                return {"ok": True, "already_latched": True, "detail": "Kill-Switch 已处于锁定状态。"}
            self._latched = True
            self._armed = False
            self._stop.set()
            pid = self._pid
            session = self._session_id or uuid.uuid4().hex[:12]
            sample_data = redact_mapping(samples or {})
            proc_paths = self._collect_paths(pid)
            termination = terminate_process_tree(pid) if pid else None
            rules: list[tuple[str, str, bool, str]] = []
            for index, path in enumerate(proc_paths):
                rule_name = f"ClaudeSentinel-Block-{session}-{index + 1}"
                result = self.platform.firewall_add(rule_name, path)
                rules.append((rule_name, path, result.ok, result.detail))
                if result.ok:
                    self._rules.append(rule_name)
            firewall_ok = bool(proc_paths) and all(ok for _name, _path, ok, _detail in rules)
            trigger = {
                "source": source,
                "check_id": check_id,
                "reason": reason,
                "triggered_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "triggered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "pid": pid,
                "session_id": session,
                "samples": sample_data,
                "termination": termination.to_dict() if termination else None,
                "firewall_rules": [
                    {"name": name, "program": path, "ok": ok, "detail": detail}
                    for name, path, ok, detail in rules
                ],
                "firewall_ok": firewall_ok,
                "paths": proc_paths,
            }
            self._last_trigger = trigger
            self._last_samples = sample_data
            self._persist()
            self.log.write("killswitch_triggered", **trigger)
            self._emit("triggered", trigger)
            return {"ok": True, "trigger": trigger}

    def _collect_paths(self, pid: int | None) -> list[str]:
        if not pid:
            return []
        try:
            procs = self.platform.list_processes()
            tree = process_tree(pid, procs)
        except Exception:
            tree = []
        paths: list[str] = []
        for entry in tree:
            path = entry.exe_path
            if not path or not Path(path).is_file():
                continue
            lowered = f"{entry.name} {path}".lower()
            if any(name in lowered for name in ("cmd.exe", "powershell.exe", "conhost.exe", "windowsterminal.exe")):
                continue
            if path not in paths:
                paths.append(path)
        if not paths:
            # Last resort: block the configured executable path, if it exists.
            configured = self.settings.claude_command.strip().strip('"')
            if configured and Path(configured).is_file():
                paths.append(str(Path(configured)))
        # Prefer Claude-named binaries; if only node.exe is available, include it
        # but the trigger log records that broadness explicitly.
        claude_paths = [p for p in paths if "claude" in p.lower()]
        if claude_paths:
            return claude_paths
        return paths

    def emergency_stop(self, source: str = "hotkey") -> dict[str, Any]:
        if not self._armed and not self._latched:
            message = "当前没有由 Sentinel 托管的 Claude 会话；未误杀其他进程。"
            self.log.write("killswitch_noop", source=source, detail=message)
            self._emit("noop", {"detail": message})
            return {"ok": False, "detail": message}
        if self._latched:
            return {"ok": True, "already_latched": True, "detail": "Kill-Switch 已处于锁定状态。"}
        samples: dict[str, Any] = {}
        if self._armed:
            try:
                samples = self.sample().__dict__
            except Exception as exc:
                samples = {"error": f"急停时采样失败: {exc}"}
        return self.trigger(
            source=source,
            check_id="manual",
            reason="用户触发全局急停/手动 Kill-Switch",
            samples=samples,
        )

    # --- release ---------------------------------------------------------
    def release(self) -> dict[str, Any]:
        with self._lock:
            failures: list[str] = []
            for rule_name in list(self._rules):
                result = self.platform.firewall_delete(rule_name)
                if result.ok:
                    self._rules.remove(rule_name)
                else:
                    failures.append(f"{rule_name}: {result.detail}")
            self._latched = False
            self._armed = False
            self._pid = None
            self._session_id = None
            self._expected_country = None
            self._expected_ip = None
            self._expected_proxy_core = False
            self._expected_tun = False
            self._stop.set()
            self._persist()
            self.log.write("killswitch_released", failures=failures, rules_remaining=self._rules)
            self._emit("released", {"failures": failures, "rules_remaining": list(self._rules)})
            return {"ok": not failures, "failures": failures, "rules_remaining": list(self._rules)}

    def stop_managed(self, *, remove_rules: bool = True) -> dict[str, Any]:
        """Normal user-requested stop, not a security trigger."""
        with self._lock:
            pid = self._pid
            failures: list[str] = []
            termination = None
            if pid:
                try:
                    termination = terminate_process_tree(pid)
                except Exception as exc:
                    failures.append(f"终止进程失败: {exc}")
            if remove_rules:
                for rule_name in list(self._rules):
                    result = self.platform.firewall_delete(rule_name)
                    if result.ok:
                        self._rules.remove(rule_name)
                    else:
                        failures.append(f"{rule_name}: {result.detail}")
            self._armed = False
            self._pid = None
            self._session_id = None
            self._expected_country = None
            self._expected_ip = None
            self._expected_proxy_core = False
            self._expected_tun = False
            self._stop.set()
            self._persist()
            self.log.write("killswitch_normal_stop", pid=pid, failures=failures, termination=termination.to_dict() if termination else None)
            return {"ok": not failures, "failures": failures, "pid": pid}

    def list_rules(self) -> list[str]:
        return list(self._rules)
