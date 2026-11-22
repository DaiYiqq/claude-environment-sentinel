from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, FakePlatform, make_paths, make_report, make_sample  # noqa: E402

from sentinel.config import Settings  # noqa: E402
from sentinel.models import EnvValue  # noqa: E402
from sentinel.profiles import ProfileError, ProfileService  # noqa: E402
from sentinel.snapshots import SnapshotStore  # noqa: E402


class ProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="sentinel-profiles-"))
        self.paths = make_paths(self.root)
        self.platform = FakePlatform()
        self.browser = FakeBrowserStore()
        self.snapshots = SnapshotStore(self.paths, self.platform, self.browser)
        self.service = ProfileService(
            self.paths,
            self.platform,
            Settings(),
            browser_store=self.browser,
            snapshot_store=self.snapshots,
        )

    def test_profile_contains_environment_only(self) -> None:
        profile = self.service.create_from_current("账号 A / 美西", expected_country="US", proxy_label="US-LA-01")
        self.assertTrue(self.paths.profiles.joinpath(f"profile-{profile['profile_id']}.json").exists())
        environment = profile["environment"]
        self.assertIn("system_timezone", environment)
        self.assertIn("user_env", environment)
        self.assertNotIn("token", environment)
        self.assertNotIn("cookies", environment)

    def test_sensitive_key_is_rejected(self) -> None:
        profile = self.service.create_from_current("bad", expected_country="US")
        profile["token"] = "not-allowed"
        with self.assertRaises(ValueError):
            self.service.save(profile)
        profile.pop("token")
        profile["environment"]["nested"] = {"cookie": "x"}
        with self.assertRaises(ValueError):
            self.service.save(profile)

    def test_activation_snapshots_first_and_applies_environment(self) -> None:
        profile = self.service.create_from_current("账号 A / 美西", expected_country="US", proxy_label="US-LA-01")
        # Move current environment away from the profile target.
        self.platform.env["TZ"] = EnvValue(True, "Asia/Shanghai", "REG_SZ", "fake")
        self.platform.env["LANG"] = EnvValue(True, "zh-CN", "REG_SZ", "fake")
        self.platform.env["LC_ALL"] = EnvValue(True, "zh-CN", "REG_SZ", "fake")
        report = make_report(make_sample(), gate_allowed=True)
        result = self.service.activate(
            profile["profile_id"],
            confirm_system_timezone=True,
            audit_runner=lambda: report,
        )
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["snapshot_id"])
        self.assertTrue(self.paths.backups.joinpath(f"sentinel-snapshot-{result['snapshot_id']}.json").exists())
        self.assertEqual(self.platform.env["TZ"].value, "America/Los_Angeles")
        self.assertEqual(self.platform.env["LANG"].value, "en-US")
        self.assertEqual(self.service.current_profile_id, profile["profile_id"])

    def test_export_and_import_roundtrip(self) -> None:
        profile = self.service.create_from_current("账号 A / 美西", expected_country="US")
        target = self.root / "profile-export.json"
        self.service.export_profile(profile["profile_id"], target)
        imported = self.service.import_profile(target)
        self.assertNotEqual(imported["profile_id"], profile["profile_id"])
        self.assertIn("导入副本", imported["name"])

    def test_missing_profile_is_explicit(self) -> None:
        with self.assertRaises(ProfileError):
            self.service.load("00000000-0000-0000-0000-000000000000")


if __name__ == "__main__":
    unittest.main()
