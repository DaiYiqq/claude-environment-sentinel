from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, FakePlatform, make_paths  # noqa: E402

from sentinel.models import EnvValue  # noqa: E402
from sentinel.snapshots import SnapshotError, SnapshotStore, canonical_checksum  # noqa: E402


class SnapshotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-snap-"))
        self.paths = make_paths(self.root)
        self.platform = FakePlatform()
        self.browser = FakeBrowserStore()
        self.store = SnapshotStore(self.paths, self.platform, self.browser)

    def test_capture_is_immutable_and_checksummed(self) -> None:
        first = self.store.capture(reason="test", label="first", modified_items=["A1", "A2"])
        second = self.store.capture(reason="test", label="second", modified_items=["A3"])
        self.assertNotEqual(first.snapshot_id, second.snapshot_id)
        self.assertTrue(first.path.exists())
        data = json.loads(first.path.read_text(encoding="utf-8"))
        self.assertEqual(data["checksum"], canonical_checksum(data))
        # A later capture must not alter the earlier file.
        original = first.path.read_bytes()
        self.store.capture(reason="test", label="third", modified_items=["A16"])
        self.assertEqual(first.path.read_bytes(), original)
        self.store.load(first.snapshot_id)  # checksum verification path

    def test_corrupted_snapshot_is_rejected(self) -> None:
        snapshot = self.store.capture(reason="test", label="corrupt", modified_items=["A1"])
        data = json.loads(snapshot.path.read_text(encoding="utf-8"))
        data["label"] = "tampered"
        snapshot.path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaises(SnapshotError):
            self.store.load(snapshot.snapshot_id)

    def test_restore_deletes_variables_that_did_not_exist(self) -> None:
        self.platform.env["TZ"] = EnvValue(True, "America/Los_Angeles", "REG_SZ", "fake")
        self.platform.env["LANG"] = EnvValue(False, None, None, "fake")
        self.platform.env["LC_ALL"] = EnvValue(True, "", "REG_SZ", "fake")
        snapshot = self.store.capture(reason="test", label="env", modified_items=["A2", "A3"])
        self.platform.env["TZ"] = EnvValue(True, "Asia/Shanghai", "REG_SZ", "fake")
        self.platform.env["LANG"] = EnvValue(True, "zh-CN", "REG_SZ", "fake")
        self.platform.env["LC_ALL"] = EnvValue(True, "zh-CN", "REG_SZ", "fake")
        result = self.store.restore(snapshot.snapshot_id)
        self.assertEqual(self.platform.env["TZ"].value, "America/Los_Angeles")
        self.assertFalse(self.platform.env["LANG"].exists, "originally absent variable must be deleted")
        self.assertTrue(self.platform.env["LC_ALL"].exists)
        self.assertEqual(self.platform.env["LC_ALL"].value, "", "originally empty value must stay empty")
        self.assertTrue(result.verified, result.to_dict())
        self.assertIn("delete_user_env", [event[0] for event in self.platform.events])

    def test_restore_failure_is_reported_not_hidden(self) -> None:
        self.platform.name = "fake"
        self.platform.fail_system_tz = True
        snapshot = self.store.capture(reason="test", label="failure", modified_items=["A1"])
        result = self.store.restore(snapshot.snapshot_id)
        self.assertFalse(result.verified)
        self.assertTrue(any("系统时区" in failure.item for failure in result.failures))
        self.assertTrue(result.failures[0].manual_command)

    def test_delete_is_explicit_and_removes_file(self) -> None:
        snapshot = self.store.capture(reason="test", label="delete me", modified_items=["A1"])
        self.store.delete(snapshot.snapshot_id)
        self.assertFalse(snapshot.path.exists())
        with self.assertRaises(SnapshotError):
            self.store.delete(snapshot.snapshot_id)


if __name__ == "__main__":
    unittest.main()
