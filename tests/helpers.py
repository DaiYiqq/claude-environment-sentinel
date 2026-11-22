"""Shared fakes for Sentinel tests.  No test touches real system settings."""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any

from sentinel.audit.probes import AuditSample
from sentinel.config import AppPaths
from sentinel.models import (
    AuditReport,
    BrowserInfo,
    CheckResult,
    ClaudeClientInfo,
    EgressInfo,
    EnvValue,
    GateResult,
    ProcessEntry,
    ProxyProbeInfo,
    Status,
    SystemTimezone,
    TunInfo,
)
from sentinel.platform.base import OperationResult


class FakePlatform:
    name = "windows"
    display_name = "Fake Windows"
    supports_system_timezone = True
    supports_process_firewall = True

    def __init__(self) -> None:
        self.env: dict[str, EnvValue] = {
            "TZ": EnvValue(True, "America/Los_Angeles", "REG_SZ", "fake-registry"),
            "LANG": EnvValue(True, "en-US", "REG_SZ", "fake-registry"),
            "LC_ALL": EnvValue(True, "en-US", "REG_SZ", "fake-registry"),
        }
        self.system_tz = SystemTimezone("Pacific Standard Time", "America/Los_Angeles", -28800, "fake")
        self.events: list[tuple[str, Any]] = []
        self.fail_system_tz = False
        self.firewall_rules: list[tuple[str, str]] = []
        self.deleted_firewall_rules: list[str] = []
        self.processes: list[ProcessEntry] = []
        self.browser_running = False
        self.claude = ClaudeClientInfo(
            cli_path=r"C:\Fake\claude.exe",
            version="1.2.3",
            client_types=["CLI"],
        )

    def get_system_timezone(self) -> SystemTimezone:
        return self.system_tz

    def set_system_timezone(self, iana: str, *, confirm: bool = False) -> OperationResult:
        self.events.append(("set_system_timezone", (iana, confirm)))
        if not confirm or self.fail_system_tz:
            return OperationResult(False, "fake system tz failure")
        from sentinel.tzmap import offset_for_zone, windows_id_for_iana

        native = windows_id_for_iana(iana) or ("Fake " + iana)
        self.system_tz = SystemTimezone(native, iana, offset_for_zone(iana), "fake")
        return OperationResult(True, "fake system tz set")

    def get_user_env(self, name: str) -> EnvValue:
        value = self.env.get(name, EnvValue(False, source="absent"))
        return EnvValue(value.exists, value.value, value.kind, value.source)

    def get_user_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_user_env(name) for name in names}

    def get_persistent_env(self, name: str) -> EnvValue:
        return self.get_user_env(name)

    def get_persistent_env_snapshot(self, names: list[str]) -> dict[str, EnvValue]:
        return {name: self.get_persistent_env(name) for name in names}

    def set_system_timezone_native(self, native_id: str, *, confirm: bool = False) -> OperationResult:
        self.events.append(("set_system_timezone_native", (native_id, confirm)))
        if not confirm or self.fail_system_tz:
            return OperationResult(False, "fake native system tz failure")
        self.system_tz = SystemTimezone(native_id, self.system_tz.iana, self.system_tz.utc_offset_seconds, "fake")
        return OperationResult(True, "fake native system tz set")

    def set_user_env(self, name: str, value: str) -> OperationResult:
        self.events.append(("set_user_env", (name, value)))
        self.env[name] = EnvValue(True, value, "REG_SZ", "fake-registry")
        return OperationResult(True, f"set {name}")

    def delete_user_env(self, name: str) -> OperationResult:
        self.events.append(("delete_user_env", name))
        self.env[name] = EnvValue(False, None, None, "fake-registry")
        return OperationResult(True, f"deleted {name}")

    def effective_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update({name: value.value for name, value in self.env.items() if value.exists and value.value is not None})
        return env

    def broadcast_env_change(self) -> None:
        self.events.append(("broadcast_env_change", None))

    def get_user_language(self) -> str | None:
        return "en-US"

    def capture_env_file(self) -> dict[str, Any]:
        return {"path": None, "existed": False, "content": None, "sha256": None}

    def restore_env_file(self, snapshot: dict[str, Any]) -> OperationResult:
        self.events.append(("restore_env_file", snapshot))
        return OperationResult(True, "no env file")

    def list_processes(self) -> list[ProcessEntry]:
        return list(self.processes)

    def get_tun_info(self) -> TunInfo:
        return TunInfo(active=True, adapters=[{"name": "FakeTUN", "status": "Up"}], source="fake")

    def local_addresses(self) -> list[dict[str, Any]]:
        return [{"ip": "192.168.1.5", "interface": "Wi-Fi"}]

    def browser_paths(self) -> dict[str, str | None]:
        return {"chrome": r"C:\Fake\chrome.exe", "edge": None}

    def browser_running(self, browser_key: str) -> bool:
        return self.browser_running

    def claude_paths(self) -> dict[str, str | None]:
        return {"cli": r"C:\Fake\claude.exe", "desktop": None}

    def detect_claude(self) -> ClaudeClientInfo:
        return self.claude

    def font_dirs(self) -> list[Path]:
        return []

    def is_admin(self) -> bool:
        return True

    def killswitch_capability(self) -> tuple[bool, str]:
        return True, "fake firewall ready"

    def firewall_add(self, rule_name: str, program_path: str) -> OperationResult:
        self.events.append(("firewall_add", (rule_name, program_path)))
        self.firewall_rules.append((rule_name, program_path))
        return OperationResult(True, "fake rule added")

    def firewall_delete(self, rule_name: str) -> OperationResult:
        self.events.append(("firewall_delete", rule_name))
        self.deleted_firewall_rules.append(rule_name)
        self.firewall_rules = [(n, p) for n, p in self.firewall_rules if n != rule_name]
        return OperationResult(True, "fake rule deleted")

    def firewall_rule_exists(self, rule_name: str) -> bool:
        return any(name == rule_name for name, _ in self.firewall_rules)

    def hotkey_available(self) -> bool:
        return True

    def hotkey_unavailable_reason(self) -> str:
        return ""


class FakeBrowserStore:
    def __init__(self, *, installed: bool = True, policy_values: dict[str, str] | None = None) -> None:
        values = policy_values if policy_values is not None else {
            "IntlAcceptLanguages": "en-US,en",
            "WebRtcIPHandling": "disable_non_proxied_udp",
        }
        self.policy_values = dict(values)
        self.installed = installed
        self.events: list[str] = []
        self.capture_state = {
            "chrome": {
                "key": "chrome",
                "name": "Google Chrome",
                "installed": installed,
                "kind": "registry",
                "hive": "HKCU",
                "key_path": "Software\\Policies\\Google\\Chrome",
                "key_existed": bool(values),
                "values": {
                    name: {"exists": True, "value": value, "kind": "REG_SZ"}
                    for name, value in values.items()
                },
            }
        }

    def audit_browsers(self) -> list[BrowserInfo]:
        if not self.installed:
            return []
        policy_values = {}
        for name, value in self.policy_values.items():
            policy_values[name] = {
                "user": {"exists": True, "value": value, "kind": "REG_SZ"},
                "machine": {"exists": False, "value": None, "kind": None},
                "effective": {"exists": True, "value": value},
                "effective_hive": "HKCU",
            }
        return [
            BrowserInfo(
                key="chrome",
                name="Google Chrome",
                installed=True,
                exe_path=r"C:\Fake\chrome.exe",
                policy={"kind": "registry", "key_path": "Software\\Policies\\Google\\Chrome", "values": policy_values},
                preferences={"accept_languages": "en-US"},
                running=False,
            )
        ]

    def capture_policy_state(self) -> dict[str, Any]:
        return self.capture_state

    def restore_policy_state(self, state: dict[str, Any]) -> list[Any]:
        self.events.append("restore_policy_state")
        return []

    def apply_policy(self, accept_language: str, *, webrtc_policy: str = "disable_non_proxied_udp") -> list[dict[str, Any]]:
        self.events.append("apply_policy")
        if not self.installed:
            return []
        self.policy_values["IntlAcceptLanguages"] = accept_language
        self.policy_values["WebRtcIPHandling"] = webrtc_policy
        return [{"browser": "chrome", "ok": True, "detail": "fake policy applied"}]


class FakeNetwork:
    enabled = True

    def __init__(self, egress: EgressInfo | None = None) -> None:
        self._egress = egress or EgressInfo(
            ok=True,
            ip="203.0.113.10",
            country_code="US",
            country_name="United States",
            region="California",
            city="Los Angeles",
            timezone="America/Los_Angeles",
            org="AS64500 Example Residential",
            asn="AS64500",
            ip_type="residential",
            source="fake",
            fetched_at="2026-01-01T00:00:00+00:00",
        )
        self.clock = {
            "source": "fake",
            "server_epoch": 1000000000.0,
            "local_epoch": 1000000002.0,
            "skew_seconds": 2.0,
            "error": None,
        }

    def egress(self, *, force: bool = False) -> EgressInfo:
        return self._egress

    def dns_egress(self) -> list[dict[str, Any]]:
        return [
            {"resolver": "cloudflare", "ips": ["203.0.113.1"], "asn": "AS64500", "org": "Example", "error": None},
            {"resolver": "google", "ips": ["203.0.113.2"], "asn": "AS64500", "org": "Example", "error": None},
        ]

    def clock_sample(self) -> dict[str, Any]:
        return self.clock

    def stun_binding(self, server: str = "stun.l.google.com", port: int = 19302) -> dict[str, Any]:
        return {"ok": True, "mapped_ip": "203.0.113.10", "mapped_port": 5000, "server": server, "error": None}


def make_paths(root: Path | None = None) -> AppPaths:
    root = root or Path(tempfile.mkdtemp(prefix="sentinel-test-"))
    paths = AppPaths(
        root=root,
        backups=root / "backups",
        logs=root / "logs",
        state=root / "state",
        profiles=root / "profiles",
        tutorials=root / "tutorials",
        docs=root / "docs",
    )
    paths.ensure()
    return paths


def make_sample(**overrides: Any) -> AuditSample:
    base = AuditSample(
        system_timezone=SystemTimezone("Pacific Standard Time", "America/Los_Angeles", -28800, "fake"),
        user_env={
            "TZ": EnvValue(True, "America/Los_Angeles", "REG_SZ", "fake"),
            "LANG": EnvValue(True, "en-US", "REG_SZ", "fake"),
            "LC_ALL": EnvValue(True, "en-US", "REG_SZ", "fake"),
        },
        process_env={"TZ": None, "LANG": None, "LC_ALL": None},
        effective_env={"TZ": "America/Los_Angeles", "LANG": "en-US", "LC_ALL": "en-US"},
        user_language="en-US",
        node={"available": True, "error": None, "raw": {"locale": "en-US", "timeZone": "America/Los_Angeles"}},
        egress=FakeNetwork().egress(),
        proxy=ProxyProbeInfo(configured=False, env={}, valid=True, core_running=False, socks_or_http_reachable=False),
        tun=TunInfo(active=True, adapters=[{"name": "FakeTUN", "status": "Up"}], source="fake"),
        dns=FakeNetwork().dns_egress(),
        webrtc={
            "verdict": "pass",
            "reasons": ["no public leak"],
            "local_addresses": [{"ip": "192.168.1.5", "interface": "Wi-Fi"}],
            "stun": {"ok": True, "mapped_ip": "203.0.113.10"},
            "aiortc": {"available": False, "candidates": []},
        },
        fonts={"matches": [], "count": 0, "scanned": 10, "directories": [], "errors": []},
        browsers=FakeBrowserStore().audit_browsers(),
        claude=ClaudeClientInfo(cli_path=r"C:\Fake\claude.exe", version="1.2.3", client_types=["CLI"]),
        clock={"source": "fake", "server_epoch": 1.0, "local_epoch": 2.0, "skew_seconds": 1.0, "error": None},
        previous=None,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def make_report(sample: AuditSample | None = None, *, gate_allowed: bool | None = None) -> AuditReport:
    from sentinel.audit.checks import run_checks
    from sentinel.audit.risk import build_gate, compute_risk_score

    sample = sample or make_sample()
    checks = run_checks(sample)
    risk = compute_risk_score(checks)
    gate = build_gate(checks, risk, launch_configured=True, killswitch_ready=True)
    if gate_allowed is not None:
        gate = replace(gate, allowed=gate_allowed)
    return AuditReport(
        report_id="test-report",
        started_at="2026-01-01T00:00:00+00:00",
        finished_at="2026-01-01T00:00:01+00:00",
        checks=checks,
        risk_score=risk,
        gate=gate,
        egress=sample.egress,
        runtime={"proxy_core_alive": True, "tun_active": True, "proxy_configured": False},
    )


def all_pass_checks() -> list[CheckResult]:
    from sentinel.audit.risk import BLOCKING, WEIGHTS

    return [
        CheckResult(
            id=f"A{i}",
            title=f"item {i}",
            status=Status.PASS,
            summary="ok",
            evidence=["ok"],
            raw={},
            weight=WEIGHTS[f"A{i}"],
            blocking=BLOCKING[f"A{i}"],
        )
        for i in range(1, 21)
    ]
