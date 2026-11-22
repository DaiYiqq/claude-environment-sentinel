from __future__ import annotations

import json
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import make_report  # noqa: E402

from sentinel.web_preview import PreviewBackend, make_server  # noqa: E402


class PreviewBackendTests(unittest.TestCase):
    def test_preview_audit_is_read_only(self):
        calls = []

        class App:
            paths = None

            def audit(self, *, save_baseline=True, export=None):
                calls.append((save_baseline, export))
                return make_report()

        backend = PreviewBackend(App())
        result = backend.audit()
        self.assertTrue(result["checks"])
        self.assertEqual(calls, [(False, False)])


class FakeBackend:
    audit_running = False
    action_running = False
    control_enabled = True
    control_token = "test-control-token"

    def __init__(self):
        self.calls = 0
        self.align_body = None
        self.restore_id = None

    def status(self):
        return {
            "app": "Claude Environment Sentinel",
            "preview_only": False,
            "control_enabled": True,
            "platform": "windows",
            "admin": True,
            "desktop_exe": None,
            "snapshots": 0,
            "profiles": 0,
            "killswitch_latched": False,
        }

    def control(self):
        return {
            "ok": True,
            "control_enabled": True,
            "preview_only": False,
            "token": self.control_token,
            "target": {"country": "US", "timezone": "America/Los_Angeles"},
            "snapshots": [],
            "last_alignment_snapshot_id": None,
            "action_running": False,
            "audit_running": False,
        }

    def align(self, body):
        self.align_body = body
        return {
            "ok": True,
            "result": {"ok": True, "snapshot_id": "snap-1", "items": [], "failures": [], "partial": False},
            "report": None,
            "snapshots": [],
            "control": self.control(),
        }

    def restore(self, snapshot_id, *, confirm=False):
        self.restore_id = snapshot_id
        return {
            "ok": True,
            "result": {"snapshot_id": snapshot_id, "restored_items": ["TZ"], "failures": [], "verified": True},
            "report": None,
            "snapshots": [],
            "control": self.control(),
        }

    def audit(self):
        self.calls += 1
        return {
            "report_id": "fake",
            "risk_score": 12,
            "checks": [{"id": "A1", "status": "pass"}],
            "gate": {"allowed": False, "reasons": ["test"]},
            "status_counts": {"pass": 1, "warn": 0, "fail": 0, "error": 0},
            "egress": {},
        }

    def report(self):
        return None

    def snapshots(self):
        return []

    def profiles(self):
        return []

    def history(self):
        return [
            {
                "audit_id": "old",
                "risk_score": 12,
                "gate_allowed": False,
                "country": "US",
                "check_statuses": {"A1": "pass", "A16": "fail"},
            }
        ]

    def console(self):
        return {
            "events": [{"ts": "2026-01-01T00:00:00+00:00", "level": "info", "message": "start"}],
            "recommendations": [{"id": "A16", "status": "fail", "action": "fix browser language"}],
            "summary": "summary",
            "report": None,
            "audit_running": False,
        }

    def docs(self, name):
        if name not in {"tutorial", "guide"}:
            return None
        return {"name": name, "title": name, "markdown": "# test"}


class PreviewHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.backend = FakeBackend()
        cls.server, cls.port = make_server(cls.backend, port=0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)

    def get(self, path, method="GET", body=None, headers=None):
        request = urllib.request.Request(
            self.base + path,
            method=method,
            data=body,
            headers={"Accept": "application/json", **(headers or {})},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, dict(response.headers), response.read()

    def post_json(self, path, payload, token=None, headers=None):
        all_headers = {"Content-Type": "application/json"}
        if token is not None:
            all_headers["X-Sentinel-Token"] = token
        all_headers.update(headers or {})
        return self.get(
            path,
            method="POST",
            body=json.dumps(payload).encode("utf-8"),
            headers=all_headers,
        )

    def test_index_has_local_control_markers(self):
        status, headers, body = self.get("/")
        self.assertEqual(status, 200)
        text = body.decode("utf-8")
        self.assertIn("本地控制 · 写操作需确认", text)
        self.assertIn("Claude Environment Sentinel", text)
        self.assertIn("127.0.0.1", text)
        self.assertIn("theme-init.js", text)
        self.assertIn("控制台", text)
        self.assertIn("theme-toggle", text)
        self.assertIn("历史与对比", text)
        self.assertIn("风险分解", text)
        self.assertIn("导出 JSON", text)
        self.assertIn("打印 / PDF", text)
        self.assertIn("audit-search", text)
        self.assertIn("一键对齐", text)
        self.assertIn("一键还原", text)
        self.assertIn("align-dialog", text)
        self.assertIn("Content-Security-Policy", headers)

    def test_api_status_and_health(self):
        status, _headers, body = self.get("/api/status")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["preview_only"])
        self.assertTrue(data["control_enabled"])
        status, _headers, body = self.get("/api/health")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["ok"])
        self.assertTrue(data["control_enabled"])

    def test_control_endpoint_exposes_scoped_token(self):
        status, _headers, body = self.get("/api/control")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["control_enabled"])
        self.assertEqual(data["token"], "test-control-token")
        self.assertEqual(data["target"]["country"], "US")

    def test_audit_post_returns_report(self):
        status, _headers, body = self.get("/api/audit", method="POST", body=b"{}")
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.calls, 1)
        data = json.loads(body)
        self.assertFalse(data["preview_only"])
        self.assertTrue(data["control_enabled"])

    def test_history_and_console_endpoints(self):
        status, _headers, body = self.get("/api/history")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["history"][0]["audit_id"], "old")
        status, _headers, body = self.get("/api/console")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["events"])
        self.assertTrue(json.loads(body)["recommendations"])

    def test_align_requires_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json("/api/align", {"timezone": True, "confirm": True})
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_align_requires_confirm(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json(
                "/api/align",
                {"timezone": True, "language": True},
                token="test-control-token",
            )
        self.assertEqual(ctx.exception.code, 400)
        ctx.exception.close()

    def test_align_with_token_and_confirm(self):
        status, _headers, body = self.post_json(
            "/api/align",
            {
                "timezone": True,
                "language": True,
                "browser_policies": True,
                "confirm_system_timezone": False,
                "confirm": True,
            },
            token="test-control-token",
        )
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["result"]["ok"])
        self.assertEqual(self.backend.align_body["timezone"], True)
        self.assertEqual(self.backend.align_body["confirm_system_timezone"], False)

    def test_restore_with_token_and_confirm(self):
        status, _headers, body = self.post_json(
            "/api/restore",
            {"snapshot_id": "snap-1", "confirm": True},
            token="test-control-token",
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.backend.restore_id, "snap-1")
        self.assertTrue(json.loads(body)["result"]["verified"])

    def test_wrong_token_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json(
                "/api/align",
                {"timezone": True, "confirm": True},
                token="wrong",
            )
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_non_loopback_host_is_rejected_for_writes(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.post_json(
                "/api/align",
                {"timezone": True, "confirm": True},
                token="test-control-token",
                headers={"Host": "example.com"},
            )
        self.assertEqual(ctx.exception.code, 403)
        ctx.exception.close()

    def test_unknown_docs_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/api/docs?name=../../secrets")
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()

    def test_static_traversal_is_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self.get("/static/../web_preview.py")
        self.assertEqual(ctx.exception.code, 404)
        ctx.exception.close()


if __name__ == "__main__":
    unittest.main()
