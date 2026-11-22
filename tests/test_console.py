from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, make_report, make_sample  # noqa: E402

from sentinel.cli import _print_report  # noqa: E402


class ConsoleRenderTests(unittest.TestCase):
    def _render(self, *, verbose: bool) -> str:
        report = make_report(make_sample(browsers=FakeBrowserStore(policy_values={}).audit_browsers()))
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            _print_report(report, verbose=verbose, no_color=True)
        return buffer.getvalue()

    def test_compact_report_has_summary_but_not_evidence_by_default(self) -> None:
        text = self._render(verbose=False)
        self.assertIn("CLAUDE ENVIRONMENT SENTINEL", text)
        self.assertIn("风险分", text)
        self.assertIn("建议下一步", text)
        self.assertNotIn("本机说明", text)

    def test_verbose_report_includes_evidence(self) -> None:
        text = self._render(verbose=True)
        self.assertIn("·", text)
        self.assertIn("A16", text)

    def test_console_is_plain_when_redirected(self) -> None:
        text = self._render(verbose=False)
        self.assertNotIn("\033[", text)


if __name__ == "__main__":
    unittest.main()
