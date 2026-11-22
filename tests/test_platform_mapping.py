from __future__ import annotations

import unittest
from datetime import datetime

from sentinel.tzmap import (
    accept_language_value,
    iana_for_windows_id,
    language_region_conflict,
    offset_for_zone,
    windows_id_for_iana,
)


class MappingTests(unittest.TestCase):
    def test_offsets_without_tzdata(self) -> None:
        self.assertEqual(offset_for_zone("Asia/Shanghai"), 28800)
        self.assertEqual(offset_for_zone("America/Los_Angeles", at=datetime(2026, 11, 22)), -28800)
        self.assertEqual(offset_for_zone("Europe/London", at=datetime(2026, 11, 22)), 0)
        self.assertEqual(offset_for_zone("Australia/Sydney", at=datetime(2026, 11, 22)), 39600)

    def test_windows_roundtrip(self) -> None:
        self.assertEqual(windows_id_for_iana("Asia/Shanghai"), "China Standard Time")
        self.assertEqual(iana_for_windows_id("China Standard Time"), "Asia/Shanghai")

    def test_language_conflict(self) -> None:
        conflict, _ = language_region_conflict("zh", "US")
        self.assertTrue(conflict)
        conflict, _ = language_region_conflict("en", "CN")
        self.assertTrue(conflict)
        conflict, _ = language_region_conflict("en", "US")
        self.assertFalse(conflict)

    def test_accept_language(self) -> None:
        self.assertEqual(accept_language_value("en-US"), "en-US,en")


if __name__ == "__main__":
    unittest.main()
