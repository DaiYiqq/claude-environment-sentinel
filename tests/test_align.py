from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, FakeNetwork, FakePlatform, make_paths, make_report, make_sample  # noqa: E402

from sentinel.align.engine import AlignmentEngine, AlignmentRequest  # noqa: E402
from sentinel.config import Settings  # noqa: E402
from sentinel.snapshots import SnapshotStore  # noqa: E402


class RecordingSnapshotStore(SnapshotStore):
    def capture(self, *, reason: str, label: str, modified_items: list[str]):
        self.platform.events.append(("snapshot_capture", None))
        return super().capture(reason=reason, label=label, modified_items=modified_items)


class AlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-align-"))
        self.paths = make_paths(self.root)
        self.platform = FakePlatform()
        self.browser = FakeBrowserStore()
        self.snapshots = RecordingSnapshotStore(self.paths, self.platform, self.browser)
        self.sample = make_sample()
        self.report = make_report(self.sample)
        self.engine = AlignmentEngine(
            self.paths,
            self.platform,
            Settings(),
            network=FakeNetwork(self.sample.egress),
            browser_store=self.browser,
            snapshot_store=self.snapshots,
            audit_runner=lambda: self.report,
        )

    def test_snapshot_precedes_writes_and_alignment_verifies(self) -> None:
        request = AlignmentRequest(
            timezone=True,
            language=True,
            browser_policies=True,
            confirm_system_timezone=True,
        )
        result = self.engine.apply(request, egress=self.sample.egress)
        self.assertTrue(result.snapshot_id)
        self.assertTrue(self.paths.backups.joinpath(f"sentinel-snapshot-{result.snapshot_id}.json").exists())
        self.assertIn(("snapshot_capture", None), self.platform.events)
        snapshot_index = self.platform.events.index(("snapshot_capture", None))
        write_indices = [
            index for index, event in enumerate(self.platform.events)
            if event[0] in {"set_user_env", "set_system_timezone"}
        ]
        self.assertTrue(write_indices)
        self.assertLess(snapshot_index, min(write_indices))
        self.assertTrue(result.ok, result.to_dict())
        self.assertIn("apply_policy", self.browser.events)
        self.assertEqual(self.platform.env["TZ"].value, "America/Los_Angeles")
        self.assertEqual(self.platform.env["LANG"].value, "en-US")
        self.assertTrue(any(event[0] == "set_system_timezone" for event in self.platform.events))

    def test_no_system_timezone_confirmation_is_partial_and_not_ok(self) -> None:
        request = AlignmentRequest(
            timezone=True,
            language=True,
            browser_policies=False,
            confirm_system_timezone=False,
        )
        result = self.engine.apply(request, egress=self.sample.egress)
        self.assertTrue(result.partial)
        self.assertFalse(result.ok)
        self.assertTrue(any(item.status == "partial" and "系统时区" in item.label for item in result.items))
        self.assertFalse(any(event[0] == "set_system_timezone" for event in self.platform.events))

    def test_warning_after_verification_is_not_promoted_to_success(self) -> None:
        sample = make_sample(
            node={"available": True, "error": None, "raw": {"locale": "zh-CN", "timeZone": "America/Los_Angeles"}}
        )
        self.engine.audit_runner = lambda: make_report(sample)
        request = AlignmentRequest(
            timezone=True,
            language=True,
            browser_policies=False,
            confirm_system_timezone=True,
        )
        result = self.engine.apply(request, egress=self.sample.egress)
        self.assertFalse(result.ok)
        self.assertTrue(result.partial)
        self.assertTrue(any("复检未全部通过" in failure for failure in result.failures))

    def test_system_timezone_failure_is_reported(self) -> None:
        self.platform.fail_system_tz = True
        request = AlignmentRequest(
            timezone=True,
            language=False,
            browser_policies=False,
            confirm_system_timezone=True,
        )
        result = self.engine.apply(request, egress=self.sample.egress)
        self.assertFalse(result.ok)
        self.assertTrue(any("fake system tz failure" in failure for failure in result.failures))
        self.assertTrue(result.snapshot_id, "snapshot must remain for rollback after a partial failure")

    def test_font_action_does_not_delete_fonts(self) -> None:
        advice = self.engine.font_advice()
        self.assertIn("不自动删除", advice)


if __name__ == "__main__":
    unittest.main()
