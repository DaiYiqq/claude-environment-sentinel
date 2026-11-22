from __future__ import annotations

import unittest
from pathlib import Path

from sentinel.audit.explanations import EXPLANATIONS

ROOT = Path(__file__).resolve().parent.parent


class DocumentationTests(unittest.TestCase):
    def test_tutorial_covers_every_check_and_a8_example(self) -> None:
        text = (ROOT / "tutorials" / "quick-start.md").read_text(encoding="utf-8")
        for i in range(1, 21):
            self.assertIn(f"A{i}", text)
        self.assertIn("东八区", text)
        self.assertIn("美国", text)
        self.assertIn("不要一上来就点", text)

    def test_explanations_cover_every_check(self) -> None:
        self.assertEqual(set(EXPLANATIONS), {f"A{i}" for i in range(1, 21)})
        for value in EXPLANATIONS.values():
            self.assertGreater(len(value), 20)

    def test_guide_covers_required_risk_dimensions(self) -> None:
        text = (ROOT / "docs" / "anti-ban-guide.md").read_text(encoding="utf-8")
        for marker in (
            "多维",
            "IP 质量",
            "一致性",
            "行为",
            "新号",
            "老号",
            "条款",
            "服务端风控",
            "稳定性",
        ):
            self.assertIn(marker, text)

    def test_new_ui_features_are_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tutorial = (ROOT / "tutorials" / "quick-start.md").read_text(encoding="utf-8")
        for marker in (
            "昼夜",
            "控制台",
            "国家锁定",
            "趋势",
            "历史对比",
            "风险分解",
            "导出",
            "一键对齐",
            "一键还原",
            "本地控制",
            "--read-only",
        ):
            self.assertIn(marker, readme)
            self.assertIn(marker, tutorial)

    def test_no_absolute_claims(self) -> None:
        bad = ("保证不被封", "永久安全", "绝对防封", "百分百安全")
        for path in (ROOT / "README.md", ROOT / "tutorials" / "quick-start.md", ROOT / "docs" / "anti-ban-guide.md"):
            text = path.read_text(encoding="utf-8")
            for phrase in bad:
                self.assertNotIn(phrase, text, msg=f"{phrase} found in {path}")

    def test_readme_and_layout_exist(self) -> None:
        self.assertTrue((ROOT / "README.md").is_file())
        self.assertTrue((ROOT / "sentinel" / "__main__.py").is_file())
        self.assertTrue((ROOT / "backups").is_dir())
        self.assertTrue((ROOT / "profiles").is_dir())


if __name__ == "__main__":
    unittest.main()
