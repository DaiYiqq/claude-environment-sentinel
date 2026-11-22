from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import FakeBrowserStore, FakeNetwork, make_sample  # noqa: E402

from sentinel.audit.checks import CHECKS, run_checks  # noqa: E402
from sentinel.models import (  # noqa: E402
    EgressInfo,
    EnvValue,
    ProxyProbeInfo,
    Status,
    SystemTimezone,
)
from sentinel.util.net import HttpResult, NetworkProbe  # noqa: E402


class AuditCheckTests(unittest.TestCase):
    def test_all_twenty_items_have_evidence_and_raw_values(self) -> None:
        checks = run_checks(make_sample())
        ids = [check.id for check in checks]
        self.assertEqual(ids, [f"A{i}" for i in range(1, 21)])
        self.assertEqual(len(set(ids)), 20)
        for check in checks:
            self.assertIn(check.status, {Status.PASS, Status.WARN, Status.FAIL, Status.ERROR})
            self.assertTrue(check.evidence, f"{check.id} has no evidence")
            self.assertIsInstance(check.raw, dict)

    def test_chinese_system_with_us_exit_is_hard_conflict(self) -> None:
        sample = make_sample(
            system_timezone=SystemTimezone("China Standard Time", "Asia/Shanghai", 28800, "fake"),
            user_env={
                "TZ": EnvValue(True, "Asia/Shanghai", "REG_SZ", "fake"),
                "LANG": EnvValue(True, "zh-CN", "REG_SZ", "fake"),
                "LC_ALL": EnvValue(True, "zh-CN", "REG_SZ", "fake"),
            },
            user_language="zh-CN",
            node={"available": True, "error": None, "raw": {"locale": "zh-CN", "timeZone": "Asia/Shanghai"}},
        )
        by_id = {check.id: check for check in run_checks(sample)}
        self.assertEqual(by_id["A8"].status, Status.FAIL)
        self.assertEqual(by_id["A9"].status, Status.FAIL)
        self.assertIn("中文系统", by_id["A9"].summary + " ".join(by_id["A9"].evidence))

    def test_a10_malformed_proxy_fails(self) -> None:
        proxy = ProxyProbeInfo(
            configured=True,
            env={"HTTP_PROXY": "http://"},
            valid=False,
            malformed=["HTTP_PROXY: 缺少主机名"],
        )
        by_id = {check.id: check for check in run_checks(make_sample(proxy=proxy))}
        self.assertEqual(by_id["A10"].status, Status.FAIL)

    def test_a11_configured_proxy_without_core_fails(self) -> None:
        proxy = ProxyProbeInfo(
            configured=True,
            env={"HTTPS_PROXY": "http://127.0.0.1:7890"},
            valid=True,
            core_running=False,
            socks_or_http_reachable=False,
        )
        by_id = {check.id: check for check in run_checks(make_sample(proxy=proxy))}
        self.assertEqual(by_id["A11"].status, Status.FAIL)

    def test_proxy_credentials_are_redacted_in_evidence_and_raw(self) -> None:
        proxy = ProxyProbeInfo(
            configured=True,
            env={"HTTPS_PROXY": "http://sentinel-user:sentinel-secret@127.0.0.1:7890"},
            valid=True,
            core_running=True,
            socks_or_http_reachable=True,
        )
        by_id = {check.id: check for check in run_checks(make_sample(proxy=proxy))}
        for check_id in ("A10", "A11"):
            blob = " ".join(by_id[check_id].evidence) + repr(by_id[check_id].raw)
            self.assertNotIn("sentinel-secret", blob)
            self.assertNotIn("sentinel-user", blob)

    def test_browser_policy_missing_fails_a16_a17(self) -> None:
        store = FakeBrowserStore(policy_values={})
        sample = make_sample(browsers=store.audit_browsers())
        by_id = {check.id: check for check in run_checks(sample)}
        # Preference exists but is not policy-locked -> warning; WebRTC has no
        # acceptable policy at all -> failure.
        self.assertEqual(by_id["A16"].status, Status.WARN)
        self.assertEqual(by_id["A17"].status, Status.FAIL)

    def test_webrtc_public_leak_fails_a14(self) -> None:
        sample = make_sample(
            webrtc={
                "verdict": "fail",
                "reasons": ["STUN 公网映射与出口不一致"],
                "local_addresses": [],
                "stun": {"ok": True, "mapped_ip": "198.51.100.9"},
                "aiortc": {"available": False, "candidates": []},
            }
        )
        by_id = {check.id: check for check in run_checks(sample)}
        self.assertEqual(by_id["A14"].status, Status.FAIL)

    def test_clock_skew_over_five_minutes_fails(self) -> None:
        sample = make_sample(
            clock={"source": "fake", "server_epoch": 1000.0, "local_epoch": 1400.0, "skew_seconds": 400.0, "error": None}
        )
        by_id = {check.id: check for check in run_checks(sample)}
        self.assertEqual(by_id["A19"].status, Status.FAIL)

    def test_drift_is_warning_not_hard_block(self) -> None:
        previous = {
            "audit_id": "old",
            "system_timezone": {"native_id": "China Standard Time", "iana": "Asia/Shanghai"},
            "user_env": {"TZ": {"exists": True, "value": "Asia/Shanghai"}},
            "egress": {"country_code": "CN"},
            "proxy": {"hosts": ["127.0.0.1:7890"]},
            "browsers": {"chrome": {"accept_language": "zh-CN", "webrtc": "default"}},
        }
        sample = make_sample(previous=previous)
        by_id = {check.id: check for check in run_checks(sample)}
        self.assertEqual(by_id["A20"].status, Status.WARN)
        self.assertFalse(by_id["A20"].blocking)

    def test_cloudflare_fallback(self) -> None:
        probe = NetworkProbe(timeout=2, enabled=True)
        failures = [
            (None, HttpResult("ipinfo", None, error="offline")),
            (None, HttpResult("ip-api", None, error="offline")),
        ]
        trace = HttpResult("trace", 200, body="ip=198.51.100.7\nloc=US\nts=1000\n")
        with patch("sentinel.util.net.http_json", side_effect=failures), patch(
            "sentinel.util.net.http_request", return_value=trace
        ):
            egress = probe.egress(force=True)
        self.assertTrue(egress.ok)
        self.assertEqual(egress.country_code, "US")
        self.assertIn("cloudflare", egress.source)
        self.assertEqual(len(egress.errors), 2)


if __name__ == "__main__":
    unittest.main()
