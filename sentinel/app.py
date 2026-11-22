"""Application service wiring for GUI and CLI."""

from __future__ import annotations

import json
import platform as py_platform
import shutil
import sys
from pathlib import Path
from typing import Any

from sentinel.align.browsers import BrowserPolicyStore
from sentinel.align.engine import AlignmentEngine, AlignmentRequest, AlignmentResult
from sentinel.audit.engine import AuditEngine
from sentinel.config import AppPaths, Settings, atomic_write_json
from sentinel.killswitch import KillSwitch
from sentinel.launcher import SafeLauncher, SafeStartResult
from sentinel.models import AuditReport, RestoreResult
from sentinel.platform.base import PlatformAdapter
from sentinel.platform.factory import get_platform
from sentinel.profiles import ProfileService
from sentinel.snapshots import SnapshotError, SnapshotStore
from sentinel.util.net import NetworkProbe


class SentinelApp:
    def __init__(
        self,
        *,
        paths: AppPaths | None = None,
        settings: Settings | None = None,
        platform: PlatformAdapter | None = None,
        on_killswitch_event: Any | None = None,
    ) -> None:
        self.paths = paths or AppPaths.discover()
        self.paths.ensure()
        self.settings = settings or Settings.load(self.paths.config_file)
        self.platform = platform or get_platform()
        self.network = NetworkProbe(
            timeout=self.settings.http_timeout_seconds,
            enabled=self.settings.network_enabled,
        )
        self.browser_store = BrowserPolicyStore(self.platform)
        self.snapshot_store = SnapshotStore(self.paths, self.platform, self.browser_store)
        self.audit_engine = AuditEngine(
            self.paths,
            self.settings,
            self.platform,
            network=self.network,
            browser_store=self.browser_store,
        )
        self.killswitch = KillSwitch(
            self.paths,
            self.platform,
            self.settings,
            network=self.network,
            on_event=on_killswitch_event,
        )
        self.alignment_engine = AlignmentEngine(
            self.paths,
            self.platform,
            self.settings,
            network=self.network,
            browser_store=self.browser_store,
            snapshot_store=self.snapshot_store,
            audit_runner=self.verify_audit,
        )
        self.profile_service = ProfileService(
            self.paths,
            self.platform,
            self.settings,
            browser_store=self.browser_store,
            snapshot_store=self.snapshot_store,
            alignment_engine=self.alignment_engine,
        )
        self.launcher = SafeLauncher(
            self.paths,
            self.settings,
            self.platform,
            self.killswitch,
            self.audit_engine,
        )
        self.last_report: AuditReport | None = None
        self.last_verification_report: AuditReport | None = None

    def audit(self, *, save_baseline: bool = True, export: bool | None = None) -> AuditReport:
        report = self.audit_engine.run(save_baseline=save_baseline, export=export)
        self.last_report = report
        return report

    def verify_audit(self) -> AuditReport:
        # Alignment/profile-switch verification is an intentional change, so
        # the new state becomes the drift baseline.  Safe-start still performs
        # its own fresh audit without mutating the baseline.
        report = self.audit_engine.run(save_baseline=True, export=False)
        self.last_verification_report = report
        self.last_report = report
        return report

    def align(self, request: AlignmentRequest, *, egress: Any | None = None) -> AlignmentResult:
        target_egress = egress or (self.last_report.egress if self.last_report else None)
        result = self.alignment_engine.apply(request, target_egress)
        if self.last_verification_report is not None:
            self.last_report = self.last_verification_report
        return result

    def safe_start(self) -> SafeStartResult:
        result = self.launcher.start()
        if result.audit is not None:
            self.last_report = result.audit
        return result

    def stop(self) -> dict[str, Any]:
        return self.launcher.stop()

    def export_report(self, report: AuditReport, path: Path) -> Path:
        return self.audit_engine.export_json(report, path)

    def restore(self, snapshot_id: str) -> RestoreResult:
        result = self.snapshot_store.restore(snapshot_id)
        # C3 asks for a complete audit after restore; keep the verification
        # report available to the caller without overwriting the baseline.
        try:
            self.verify_audit()
        except Exception:
            pass
        return result

    def save_settings(self) -> None:
        self.settings.save(self.paths.config_file)
        # Rebuild the network/timing-sensitive pieces without losing a latched
        # kill-switch state.
        self.network.timeout = max(1.0, float(self.settings.http_timeout_seconds))
        self.network.enabled = bool(self.settings.network_enabled)
        self.audit_engine.settings = self.settings
        self.alignment_engine.settings = self.settings
        self.killswitch.settings = self.settings
        self.launcher.settings = self.settings
        self.profile_service.settings = self.settings

    def doctor(self) -> dict[str, Any]:
        tkinter_ok = True
        tkinter_error = None
        try:
            import tkinter  # noqa: F401

            tkinter_version = str(tkinter.TkVersion)
        except Exception as exc:
            tkinter_ok = False
            tkinter_error = str(exc)
            tkinter_version = None
        try:
            killswitch_ok, killswitch_reason = self.platform.killswitch_capability()
        except Exception as exc:
            killswitch_ok, killswitch_reason = False, str(exc)
        try:
            hotkey_ok, hotkey_reason = self._hotkey_capability()
        except Exception as exc:
            hotkey_ok, hotkey_reason = False, str(exc)
        browsers = self.browser_store.audit_browsers()
        return {
            "app": "Claude Environment Sentinel",
            "platform": self.platform.name,
            "os": py_platform.platform(),
            "python": sys.version.split()[0],
            "tkinter": {"ok": tkinter_ok, "version": tkinter_version, "error": tkinter_error},
            "node": shutil.which("node"),
            "admin": self.platform.is_admin(),
            "killswitch": {"ok": killswitch_ok, "reason": killswitch_reason, "latched": self.killswitch.latched},
            "hotkey": {"ok": hotkey_ok, "reason": hotkey_reason, "combination": self.settings.hotkey},
            "browsers": [b.to_dict() for b in browsers],
            "claude": self.platform.detect_claude().to_dict(),
            "paths": {
                "root": str(self.paths.root),
                "backups": str(self.paths.backups),
                "logs": str(self.paths.logs),
                "state": str(self.paths.state),
                "profiles": str(self.paths.profiles),
            },
            "snapshots": len(self.snapshot_store.list()),
            "settings_file": str(self.paths.config_file),
        }

    def _hotkey_capability(self) -> tuple[bool, str]:
        from sentinel.gui.hotkey import GlobalHotkey

        helper = GlobalHotkey(self.settings.hotkey, lambda: None)
        return helper.available()

    def close(self) -> None:
        """Normal application close.  A latched firewall state is preserved."""
        try:
            if self.launcher.running and not self.killswitch.latched:
                self.launcher.stop()
        except Exception:
            pass
