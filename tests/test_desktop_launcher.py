from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class DesktopLauncherTests(unittest.TestCase):
    def test_launcher_artifacts_exist(self) -> None:
        exe = ROOT / "ClaudeSentinel.exe"
        if not exe.is_file():
            exe = next(iter(ROOT.glob("dist/*/ClaudeSentinel.exe")), None)
        if exe is None:
            self.skipTest("launcher binary is built from source; run build_desktop_exe.bat")
        self.assertEqual(exe.read_bytes()[:2], b"MZ")
        self.assertTrue((ROOT / "launcher" / "ClaudeSentinel.cs").is_file())
        self.assertTrue((ROOT / "build_desktop_exe.bat").is_file())
        self.assertTrue((ROOT / "run_sentinel_web.bat").is_file())

    def test_launcher_source_finds_pythonw_and_project_root(self) -> None:
        source = (ROOT / "launcher" / "ClaudeSentinel.cs").read_text(encoding="utf-8")
        self.assertIn("pythonw.exe", source)
        self.assertIn("__main__.py", source)
        self.assertIn("-m sentinel", source)


if __name__ == "__main__":
    unittest.main()
