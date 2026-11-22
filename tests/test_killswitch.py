from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeNetwork, FakePlatform, make_paths  # noqa: E402

from sentinel.config import Settings  # noqa: E402
from sentinel.killswitch import KillSwitch, KillSwitchSnapshot  # noqa: E402
from sentinel.models import ProcessEntry  # noqa: E402
from sentinel.util.proc import CommandResult  # noqa: E402


class KillSwitchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-kill-"))
        self.paths = make_paths(self.root)
        self.platform = FakePlatform()
        self.exe = self.root / "Claude.exe"
        self.exe.write_bytes(b"fake")
        self.platform.processes = [
            ProcessEntry(pid=4321, ppid=1, name="Claude.exe", exe_path=str(self.exe))
        ]
        self.ks = KillSwitch(self.paths, self.platform, Settings(poll_seconds=60), network=FakeNetwork())
        self.termination = CommandResult(["taskkill"], 0, "terminated")

    def tearDown(self) -> None:
        self.ks._stop.set()

    def test_trigger_terminates_blocks_and_latches(self) -> None:
        with patch("sentinel.killswitch.terminate_process_tree", return_value=self.termination):
            self.ks.arm(
                pid=4321,
                expected_country="US",
                expected_ip="203.0.113.10",
                expected_proxy_core=False,
                expected_tun=True,
            )
            result = self.ks.trigger(
                source="test",
                check_id="A5",
                reason="country changed",
                samples={"country": "CN"},
            )
        self.assertTrue(result["ok"])
        self.assertTrue(self.ks.latched)
        self.assertFalse(self.ks.armed)
        self.assertTrue(self.platform.firewall_rules)
        self.assertTrue(self.paths.killswitch_state_file.exists())
        state = json.loads(self.paths.killswitch_state_file.read_text(encoding="utf-8"))
        self.assertTrue(state["latched"])
        self.assertEqual(state["last_trigger"]["check_id"], "A5")
        log = self.paths.logs / "killswitch.jsonl"
        self.assertTrue(log.exists())
        self.assertIn("killswitch_triggered", log.read_text(encoding="utf-8"))

    def test_release_removes_rules_and_clears_latch(self) -> None:
        with patch("sentinel.killswitch.terminate_process_tree", return_value=self.termination):
            self.ks.arm(
                pid=4321,
                expected_country="US",
                expected_ip="203.0.113.10",
                expected_proxy_core=False,
                expected_tun=True,
            )
            self.ks.trigger(source="test", check_id="A11", reason="proxy dead", samples={})
        rules = list(self.ks.list_rules())
        self.assertTrue(rules)
        result = self.ks.release()
        self.assertTrue(result["ok"])
        self.assertFalse(self.ks.latched)
        self.assertEqual(self.ks.list_rules(), [])
        self.assertTrue(set(rules).issubset(set(self.platform.deleted_firewall_rules)))

    def test_emergency_stop_without_session_does_not_kill_anything(self) -> None:
        result = self.ks.emergency_stop("hotkey")
        self.assertFalse(result["ok"])
        self.assertFalse(self.platform.firewall_rules)

    def test_evaluate_detects_country_ip_proxy_and_tun_changes(self) -> None:
        self.ks._expected_country = "US"
        self.ks._expected_ip = "203.0.113.10"
        self.ks._expected_proxy_core = True
        self.ks._expected_tun = True
        sample = KillSwitchSnapshot(
            checked_at="now",
            egress={"ok": True},
            country="CN",
            ip="198.51.100.1",
            proxy_core_alive=False,
            tun_active=False,
        )
        problems = self.ks.evaluate(sample)
        ids = {check_id for check_id, _reason in problems}
        self.assertIn("A5", ids)
        self.assertIn("A5/IP", ids)
        self.assertIn("A11", ids)
        self.assertIn("A12", ids)

    def test_persisted_latch_is_not_auto_released(self) -> None:
        self.paths.killswitch_state_file.write_text(
            json.dumps({"schema_version": 1, "latched": True, "rules": ["ClaudeSentinel-Block-x-1"]}),
            encoding="utf-8",
        )
        second = KillSwitch(self.paths, self.platform, Settings(poll_seconds=60), network=FakeNetwork())
        self.assertTrue(second.latched)
        self.assertEqual(second.list_rules(), ["ClaudeSentinel-Block-x-1"])


if __name__ == "__main__":
    unittest.main()
