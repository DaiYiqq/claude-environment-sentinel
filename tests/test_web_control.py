from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakePlatform, make_report  # noqa: E402

from sentinel.models import AlignmentResult, RestoreResult  # noqa: E402
from sentinel.web_preview import PreviewBackend  # noqa: E402


class FakeSnapshotStore:
    def __init__(self):
        self.snapshot = SimpleNamespace(
            snapshot_id="snap-1",
            created_at="2026-01-01T00:00:00+00:00",
            label="before align",
            reason="web_quick_align",
            modified_items=["A1", "A2", "A3", "A16", "A17"],
            data={"checksum": "checksum"},
        )

    def list(self):
        return [self.snapshot]

    def latest(self):
        return self.snapshot

    def load(self, snapshot_id):
        if snapshot_id != self.snapshot.snapshot_id:
            raise RuntimeError("missing snapshot")
        return self.snapshot


class FakeApp:
    def __init__(self):
        self.platform = FakePlatform()
        self.last_report = make_report()
        self.snapshot_store = FakeSnapshotStore()
        self.request = None
        self.restored = None
        self.align_calls = 0
        self.restore_calls = 0

    def align(self, request, *, egress=None):
        self.align_calls += 1
        self.request = request
        self.egress = egress
        return AlignmentResult(ok=True, snapshot_id="snap-1")

    def restore(self, snapshot_id):
        self.restore_calls += 1
        self.restored = snapshot_id
        self.last_report = make_report()
        return RestoreResult(
            snapshot_id=snapshot_id,
            restored_items=["TZ", "LANG", "LC_ALL"],
            verified=True,
        )


class WebControlBackendTests(unittest.TestCase):
    def test_control_token_and_target(self):
        backend = PreviewBackend(FakeApp())
        control = backend.control()
        self.assertTrue(control["control_enabled"])
        self.assertFalse(control["preview_only"])
        self.assertTrue(control["token"])
        self.assertEqual(control["target"]["country"], "US")
        self.assertTrue(control["target"]["timezone_valid"])

    def test_align_uses_request_fields_and_records_snapshot(self):
        app = FakeApp()
        backend = PreviewBackend(app)
        backend._report = app.last_report
        result = backend.align(
            {
                "timezone": True,
                "language": True,
                "browser_policies": True,
                "confirm_system_timezone": True,
                "confirm": True,
            }
        )
        self.assertTrue(result["result"]["ok"])
        self.assertEqual(app.align_calls, 1)
        self.assertTrue(app.request.timezone)
        self.assertTrue(app.request.language)
        self.assertTrue(app.request.browser_policies)
        self.assertTrue(app.request.confirm_system_timezone)
        self.assertEqual(app.request.reason, "web_quick_align")
        self.assertEqual(backend.last_alignment_snapshot_id, "snap-1")

    def test_align_requires_confirm_and_report(self):
        app = FakeApp()
        backend = PreviewBackend(app)
        with self.assertRaises(ValueError):
            backend.align({"timezone": True})
        app.last_report = None
        with self.assertRaises(RuntimeError):
            backend.align({"timezone": True, "confirm": True})

    def test_restore_latest_and_clear_undo_after_success(self):
        app = FakeApp()
        backend = PreviewBackend(app)
        backend._report = app.last_report
        backend.align({"timezone": True, "confirm": True})
        result = backend.restore("latest", confirm=True)
        self.assertTrue(result["result"]["verified"])
        self.assertEqual(app.restored, "snap-1")
        self.assertIsNone(backend.last_alignment_snapshot_id)

    def test_read_only_mode_has_no_token_and_rejects_writes(self):
        app = FakeApp()
        backend = PreviewBackend(app, control_enabled=False)
        control = backend.control()
        self.assertFalse(control["control_enabled"])
        self.assertTrue(control["preview_only"])
        self.assertIsNone(control["token"])
        with self.assertRaises(RuntimeError):
            backend.align({"timezone": True, "confirm": True})

    def test_operation_lock_rejects_concurrent_action(self):
        app = FakeApp()
        backend = PreviewBackend(app)
        backend._begin_operation("audit")
        try:
            with self.assertRaises(RuntimeError) as ctx:
                backend.align({"timezone": True, "confirm": True})
            self.assertIn("in_progress", str(ctx.exception))
        finally:
            backend._end_operation()


if __name__ == "__main__":
    unittest.main()
