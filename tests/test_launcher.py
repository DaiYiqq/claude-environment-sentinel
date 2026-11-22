from __future__ import annotations

import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakePlatform, make_paths, make_report, make_sample  # noqa: E402

from sentinel.config import Settings  # noqa: E402
from sentinel.launcher import SafeLauncher  # noqa: E402


class FakeAuditEngine:
    def __init__(self, report):
        self.report = report
        self.calls = 0

    def run(self, **_kwargs):
        self.calls += 1
        return self.report


class FakeKillSwitch:
    def __init__(self):
        self.latched = False
        self.armed = False
        self.armed_with = None
        self.stopped = False

    def arm(self, **kwargs):
        self.armed = True
        self.armed_with = kwargs
        return {"ok": True, "detail": "armed"}

    def stop_managed(self, **_kwargs):
        self.stopped = True
        return {"ok": True, "failures": []}


class LauncherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-launcher-"))
        self.paths = make_paths(self.root)
        self.exe = self.root / "claude.exe"
        self.exe.write_bytes(b"fake")
        self.platform = FakePlatform()
        self.killswitch = FakeKillSwitch()
        self.settings = Settings(claude_command=str(self.exe), poll_seconds=5)
        self.report = make_report(make_sample(), gate_allowed=True)
        self.engine = FakeAuditEngine(self.report)
        self.launcher = SafeLauncher(self.paths, self.settings, self.platform, self.killswitch, self.engine)

    def test_blocked_audit_never_calls_popen(self) -> None:
        self.engine.report = make_report(make_sample(), gate_allowed=False)
        with patch("sentinel.launcher.subprocess.Popen") as popen:
            result = self.launcher.start()
        self.assertFalse(result.ok)
        popen.assert_not_called()
        self.assertEqual(self.engine.calls, 1)

    def test_successful_start_arms_killswitch(self) -> None:
        fake_process = MagicMock()
        fake_process.pid = 4242
        fake_process.poll.return_value = None
        with patch("sentinel.launcher.subprocess.Popen", return_value=fake_process) as popen:
            result = self.launcher.start()
        self.assertTrue(result.ok, result.to_dict())
        popen.assert_called_once()
        self.assertTrue(self.killswitch.armed)
        self.assertEqual(self.killswitch.armed_with["pid"], 4242)
        self.assertEqual(self.killswitch.armed_with["expected_country"], "US")

    def test_missing_command_blocks(self) -> None:
        self.settings.claude_command = ""
        self.platform.claude_paths = lambda: {"cli": None, "desktop": None}  # type: ignore[method-assign]
        with patch("sentinel.launcher.subprocess.Popen") as popen:
            result = self.launcher.start()
        self.assertFalse(result.ok)
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
