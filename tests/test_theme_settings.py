from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

from sentinel.config import Settings

ROOT = Path(__file__).resolve().parent.parent


class ThemeSettingsTests(unittest.TestCase):
    def test_settings_theme_and_country_lock_roundtrip(self) -> None:
        settings = Settings.from_dict(
            {
                "theme": "light",
                "country_lock": True,
                "expected_country": "us",
                "mode": "expert",
            }
        )
        self.assertEqual(settings.theme, "light")
        self.assertTrue(settings.country_lock)
        self.assertEqual(settings.expected_country, "US")
        self.assertEqual(settings.mode, "expert")
        self.assertEqual(Settings.from_dict({"theme": "neon"}).theme, "dark")

    def test_palette_follows_environment_before_import(self) -> None:
        script = (
            "from sentinel.gui import theme;"
            "print(theme.THEME_NAME);"
            "print(theme.BG);"
            "print(theme.TEXT)"
        )
        base = {k: v for k, v in os.environ.items() if k != "SENTINEL_THEME"}
        light = dict(base, SENTINEL_THEME="light")
        dark = dict(base, SENTINEL_THEME="dark")
        light_result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            env=light,
            capture_output=True,
            text=True,
            timeout=20,
        )
        dark_result = subprocess.run(
            [sys.executable, "-B", "-c", script],
            cwd=ROOT,
            env=dark,
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(light_result.returncode, 0, light_result.stderr)
        self.assertEqual(dark_result.returncode, 0, dark_result.stderr)
        light_lines = light_result.stdout.strip().splitlines()
        dark_lines = dark_result.stdout.strip().splitlines()
        self.assertEqual(light_lines[0], "light")
        self.assertEqual(dark_lines[0], "dark")
        self.assertNotEqual(light_lines[1], dark_lines[1])


if __name__ == "__main__":
    unittest.main()
