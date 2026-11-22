from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, make_report, make_sample  # noqa: E402

from sentinel.audit.recommendations import build_recommendations, compact_summary  # noqa: E402


class RecommendationTests(unittest.TestCase):
    def test_failed_checks_come_first(self) -> None:
        sample = make_sample(browsers=FakeBrowserStore(policy_values={}).audit_browsers())
        report = make_report(sample)
        recommendations = build_recommendations(report)
        self.assertTrue(recommendations)
        statuses = [item["status"] for item in recommendations]
        self.assertIn("fail", statuses)
        self.assertEqual(statuses[0], "fail")

    def test_compact_summary_has_no_secret_material(self) -> None:
        text = compact_summary(make_report())
        self.assertIn("风险分", text)
        self.assertIn("建议下一步", text)
        self.assertNotIn("password", text.lower())
        self.assertNotIn("token", text.lower())


if __name__ == "__main__":
    unittest.main()
