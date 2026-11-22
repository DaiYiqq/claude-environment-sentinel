from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, FakeNetwork, FakePlatform, make_paths, make_sample  # noqa: E402

from sentinel.audit.engine import AuditEngine  # noqa: E402
from sentinel.config import Settings  # noqa: E402


class AuditEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-engine-"))
        self.paths = make_paths(self.root)
        self.platform = FakePlatform()
        self.sample = make_sample()
        self.engine = AuditEngine(
            self.paths,
            Settings(auto_export_audit=False),
            self.platform,
            network=FakeNetwork(self.sample.egress),
            browser_store=FakeBrowserStore(),
        )

    def test_twenty_checks_and_baseline(self) -> None:
        with patch("sentinel.audit.engine.gather_sample", return_value=self.sample):
            report = self.engine.run(save_baseline=True, export=False)
        self.assertEqual([check.id for check in report.checks], [f"A{i}" for i in range(1, 21)])
        self.assertTrue(self.paths.last_audit_file.exists())
        baseline = json.loads(self.paths.last_audit_file.read_text(encoding="utf-8"))
        self.assertEqual(baseline["egress"]["country_code"], "US")
        self.assertEqual(baseline["audit_id"], report.report_id)
        self.assertIn("A20", [check.id for check in report.checks])

    def test_previous_baseline_is_passed_to_next_sample(self) -> None:
        seen: list[object] = []

        def gather(**kwargs):
            seen.append(kwargs.get("previous"))
            return self.sample

        with patch("sentinel.audit.engine.gather_sample", side_effect=gather):
            self.engine.run(save_baseline=True, export=False)
            self.engine.run(save_baseline=True, export=False)
        self.assertIsNone(seen[0])
        self.assertIsNotNone(seen[1])

    def test_export_json(self) -> None:
        with patch("sentinel.audit.engine.gather_sample", return_value=self.sample):
            report = self.engine.run(save_baseline=False, export=False)
        target = self.root / "audit.json"
        self.engine.export_json(report, target)
        data = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(len(data["checks"]), 20)
        self.assertIn("disclaimer", data)

    def test_history_is_written_only_for_persisted_audits(self) -> None:
        history = self.paths.state / "audit_history.jsonl"
        with patch("sentinel.audit.engine.gather_sample", return_value=self.sample):
            self.engine.run(save_baseline=False, export=False)
        self.assertFalse(history.exists())
        with patch("sentinel.audit.engine.gather_sample", return_value=self.sample):
            self.engine.run(save_baseline=True, export=False)
        self.assertTrue(history.exists())
        entries = [json.loads(line) for line in history.read_text(encoding="utf-8").splitlines()]
        audit_entries = [entry for entry in entries if entry.get("event") == "audit"]
        self.assertTrue(audit_entries)
        self.assertEqual(len(audit_entries[-1].get("check_statuses", {})), 20)

    def test_country_lock_adds_gate_reason(self) -> None:
        locked = Settings(auto_export_audit=False, country_lock=True, expected_country="CN")
        engine = AuditEngine(
            self.paths,
            locked,
            self.platform,
            network=FakeNetwork(self.sample.egress),
            browser_store=FakeBrowserStore(),
        )
        with patch("sentinel.audit.engine.gather_sample", return_value=self.sample):
            report = engine.run(save_baseline=False, export=False)
        self.assertFalse(report.gate.allowed)
        self.assertTrue(any("国家锁定" in reason for reason in report.gate.reasons))


if __name__ == "__main__":
    unittest.main()
