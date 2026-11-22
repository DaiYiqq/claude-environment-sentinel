"""Core data models shared by the audit, alignment, GUI and CLI layers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    ERROR = "error"

    @property
    def label_zh(self) -> str:
        return {
            "pass": "通过",
            "warn": "警告",
            "fail": "失败",
            "error": "采样异常",
        }[self.value]

    @property
    def is_blocking_status(self) -> bool:
        return self in (Status.FAIL, Status.ERROR)


@dataclass
class EnvValue:
    exists: bool
    value: str | None = None
    kind: str | None = None
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SystemTimezone:
    native_id: str | None
    iana: str | None
    utc_offset_seconds: int | None
    source: str
    raw: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EgressInfo:
    ok: bool = False
    ip: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    region: str | None = None
    city: str | None = None
    timezone: str | None = None
    org: str | None = None
    asn: str | None = None
    ip_type: str = "unknown"  # residential | mobile | datacenter | proxy | unknown
    privacy_flags: list[str] = field(default_factory=list)
    source: str = "none"
    fetched_at: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessEntry:
    pid: int
    ppid: int
    name: str
    exe_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ProxyProbeInfo:
    configured: bool = False
    env: dict[str, str] = field(default_factory=dict)
    valid: bool = False
    malformed: list[str] = field(default_factory=list)
    core_processes: list[ProcessEntry] = field(default_factory=list)
    listening_ports: dict[int, bool] = field(default_factory=dict)
    core_running: bool = False
    socks_or_http_reachable: bool = False
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TunInfo:
    active: bool = False
    adapters: list[dict[str, Any]] = field(default_factory=list)
    source: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BrowserInfo:
    key: str
    name: str
    installed: bool
    exe_path: str | None = None
    policy: dict[str, dict[str, Any]] = field(default_factory=dict)
    preferences: dict[str, Any] = field(default_factory=dict)
    running: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ClaudeClientInfo:
    cli_path: str | None = None
    desktop_path: str | None = None
    version: str | None = None
    client_types: list[str] = field(default_factory=list)
    process_entries: list[ProcessEntry] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    identity_inspected: bool = False

    @property
    def detected(self) -> bool:
        return bool(self.cli_path or self.desktop_path or self.process_entries)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["process_entries"] = [p.to_dict() for p in self.process_entries]
        return data


@dataclass
class CheckResult:
    id: str
    title: str
    status: Status
    summary: str
    evidence: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    weight: int = 1
    blocking: bool = False
    fixable: bool = False
    fix_action: str | None = None
    explanation: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["status_label"] = self.status.label_zh
        return data


@dataclass
class GateResult:
    allowed: bool = False
    reasons: list[str] = field(default_factory=list)
    risk_score: int = 0
    blocking_ids: list[str] = field(default_factory=list)
    launch_configured: bool = False
    killswitch_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    report_id: str
    started_at: str
    finished_at: str
    checks: list[CheckResult]
    risk_score: int
    gate: GateResult
    egress: EgressInfo | None = None
    baseline_id: str | None = None
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    runtime: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    @property
    def status_counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for check in self.checks:
            counts[check.status.value] += 1
        return counts

    @property
    def blocking_failures(self) -> list[CheckResult]:
        return [c for c in self.checks if c.blocking and c.status.is_blocking_status]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.status is Status.WARN]

    def to_dict(self) -> dict[str, Any]:
        from sentinel import APP_NAME, __version__

        return {
            "schema_version": self.schema_version,
            "app": APP_NAME,
            "app_version": __version__,
            "report_id": self.report_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "risk_score": self.risk_score,
            "status_counts": self.status_counts,
            "gate": self.gate.to_dict(),
            "egress": self.egress.to_dict() if self.egress else None,
            "baseline_id": self.baseline_id,
            "runtime": self.runtime,
            "checks": [c.to_dict() for c in self.checks],
            "errors": list(self.errors),
            "notes": list(self.notes),
            "disclaimer": (
                "Sentinel 只降低本地环境画像与账号地区不一致带来的风险，"
                "不承诺任何账号结果，也不是服务端风控的绕过工具。"
            ),
        }


@dataclass
class SnapshotMeta:
    snapshot_id: str
    path: str
    created_at: str
    label: str
    reason: str
    modified_items: list[str]
    checksum: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RestoreFailure:
    item: str
    detail: str
    manual_command: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RestoreResult:
    snapshot_id: str
    restored_items: list[str] = field(default_factory=list)
    failures: list[RestoreFailure] = field(default_factory=list)
    verified: bool = False
    verification: list[dict[str, Any]] = field(default_factory=list)
    completed_at: str = field(default_factory=lambda: datetime.now().astimezone().isoformat(timespec="seconds"))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["failures"] = [f.to_dict() for f in self.failures]
        return data


@dataclass
class AlignmentItemResult:
    key: str
    label: str
    status: str  # applied | verified | failed | partial | skipped
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AlignmentResult:
    ok: bool
    snapshot_id: str | None
    items: list[AlignmentItemResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    partial: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "snapshot_id": self.snapshot_id,
            "items": [i.to_dict() for i in self.items],
            "failures": list(self.failures),
            "verification": self.verification,
            "partial": self.partial,
        }
