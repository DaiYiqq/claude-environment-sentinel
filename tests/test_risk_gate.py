from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import all_pass_checks  # noqa: E402

from sentinel.audit.risk import build_gate, compute_risk_score  # noqa: E402
from sentinel.models import Status  # noqa: E402


class RiskGateTests(unittest.TestCase):
    def test_all_pass_is_zero(self) -> None:
        checks = all_pass_checks()
        self.assertEqual(compute_risk_score(checks), 0)
        gate = build_gate(checks, 0, launch_configured=True, killswitch_ready=True)
        self.assertTrue(gate.allowed)

    def test_single_blocking_fail_blocks_even_with_low_score(self) -> None:
        checks = all_pass_checks()
        checks[7] = replace(checks[7], status=Status.FAIL, summary="A8 mismatch")
        risk = compute_risk_score(checks)
        self.assertLess(risk, 60)
        gate = build_gate(checks, risk, launch_configured=True, killswitch_ready=True)
        self.assertFalse(gate.allowed)
        self.assertIn("A8", gate.blocking_ids)

    def test_risk_at_60_blocks(self) -> None:
        checks = all_pass_checks()
        gate = build_gate(checks, 60, launch_configured=True, killswitch_ready=True)
        self.assertFalse(gate.allowed)
        self.assertTrue(any("风险分" in reason for reason in gate.reasons))

    def test_all_fail_is_100(self) -> None:
        checks = [replace(check, status=Status.FAIL) for check in all_pass_checks()]
        self.assertEqual(compute_risk_score(checks), 100)

    def test_warning_does_not_block(self) -> None:
        checks = all_pass_checks()
        checks[14] = replace(checks[14], status=Status.WARN, summary="font warning")
        risk = compute_risk_score(checks)
        gate = build_gate(checks, risk, launch_configured=True, killswitch_ready=True)
        self.assertTrue(gate.allowed)
        self.assertGreater(risk, 0)

    def test_missing_launch_and_killswitch_are_gate_reasons(self) -> None:
        checks = all_pass_checks()
        gate = build_gate(checks, 0, launch_configured=False, killswitch_ready=False)
        self.assertFalse(gate.allowed)
        self.assertGreaterEqual(len(gate.reasons), 2)


if __name__ == "__main__":
    unittest.main()
