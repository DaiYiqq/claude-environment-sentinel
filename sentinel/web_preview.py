"""Local browser console for Claude Environment Sentinel.

The browser surface exposes real audit data and, when control mode is enabled,
two narrowly-scoped write actions: reversible environment alignment and
snapshot restore.  Both reuse the desktop alignment/snapshot engine, require a
per-process control token plus explicit confirmation, and never start Claude or
release the Kill-Switch.  It binds to loopback only.
"""

from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
import secrets
import socket
import sys
import threading
import traceback
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from sentinel import APP_NAME, __version__
from sentinel.align.engine import AlignmentRequest
from sentinel.app import SentinelApp
from sentinel.audit.recommendations import build_recommendations, compact_summary
from sentinel.snapshots import SnapshotError
from sentinel.tzmap import (
    accept_language_value,
    language_for_country,
    locale_for_country,
    offset_for_zone,
    windows_id_for_iana,
)

DEFAULT_PORT = 8790
MAX_PORT_TRIES = 10
MAX_BODY = 1_048_576
STATIC_ROOT = Path(__file__).resolve().parent / "webui"
ALLOWED_STATIC_SUFFIXES = {".html", ".css", ".js", ".svg", ".png", ".ico", ".webp", ".woff2"}
DOCS = {
    "quick-start": ("新手教程", "tutorials/quick-start.md"),
    "tutorial": ("新手教程", "tutorials/quick-start.md"),
    "guide": ("风险指南", "docs/anti-ban-guide.md"),
    "anti-ban": ("风险指南", "docs/anti-ban-guide.md"),
}


class PreviewBackend:
    """Small, read-only projection of SentinelApp for the browser."""

    def __init__(self, app: SentinelApp | None = None, *, control_enabled: bool = True) -> None:
        self.app = app or SentinelApp()
        self.control_enabled = bool(control_enabled)
        self.control_token: str | None = secrets.token_urlsafe(32) if self.control_enabled else None
        self._operation_lock = threading.Lock()
        self._operation_kind: str | None = None
        self._report: Any | None = None
        self._report_lock = threading.Lock()
        self._event_lock = threading.Lock()
        self._events: list[dict[str, Any]] = []
        self.last_alignment_snapshot_id: str | None = None
        self.last_alignment: dict[str, Any] | None = None
        self.last_restore: dict[str, Any] | None = None

    @property
    def audit_running(self) -> bool:
        return self._operation_kind == "audit"

    @property
    def action_running(self) -> bool:
        return self._operation_kind in {"align", "restore"}

    def _begin_operation(self, kind: str) -> None:
        if not self._operation_lock.acquire(blocking=False):
            raise RuntimeError(f"{self._operation_kind or 'operation'}_in_progress")
        self._operation_kind = kind

    def _end_operation(self) -> None:
        self._operation_kind = None
        self._operation_lock.release()

    def _set_report(self, report: Any | None) -> None:
        if report is not None:
            with self._report_lock:
                self._report = report

    def status(self) -> dict[str, Any]:
        app = self.app
        try:
            snapshots = app.snapshot_store.list()
        except Exception:
            snapshots = []
        try:
            profiles = app.profile_service.list()
        except Exception:
            profiles = []
        try:
            admin = app.platform.is_admin()
        except Exception:
            admin = False
        exe = app.paths.root / "ClaudeSentinel.exe"
        return {
            "app": APP_NAME,
            "version": __version__,
            "preview_only": not self.control_enabled,
            "control_enabled": self.control_enabled,
            "action_running": self.action_running,
            "platform": app.platform.name,
            "admin": admin,
            "network_enabled": bool(app.settings.network_enabled),
            "killswitch_latched": bool(app.killswitch.latched),
            "snapshots": len(snapshots),
            "profiles": len(profiles),
            "theme": str(getattr(app.settings, "theme", "dark") or "dark"),
            "country_lock": bool(getattr(app.settings, "country_lock", False)),
            "expected_country": str(getattr(app.settings, "expected_country", "") or "").upper(),
            "desktop_exe": str(exe) if exe.is_file() else None,
            "state_root": str(app.paths.root),
        }

    def _event(self, level: str, message: str, detail: Any | None = None) -> None:
        from datetime import datetime

        item = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "level": level,
            "message": message,
            "detail": detail,
        }
        with self._event_lock:
            self._events.append(item)
            self._events = self._events[-200:]

    def audit(self) -> dict[str, Any]:
        self._begin_operation("audit")
        self._event("info", "开始环境采样：时区、网络、DNS、WebRTC、浏览器策略。")
        try:
            # Read-only audit path: no baseline/export writes from this endpoint.
            report = self.app.audit(save_baseline=False, export=False)
            self._set_report(report)
            self._event(
                "success" if report.gate.allowed else "warn",
                f"检测完成：风险分 {report.risk_score}/100，"
                f"门禁{'允许' if report.gate.allowed else '禁止'}。",
                {
                    "risk_score": report.risk_score,
                    "gate_allowed": report.gate.allowed,
                    "counts": report.status_counts,
                },
            )
            return report.to_dict()
        except Exception as exc:
            self._event("error", f"检测失败：{type(exc).__name__}: {exc}")
            raise
        finally:
            self._end_operation()

    def report(self) -> dict[str, Any] | None:
        with self._report_lock:
            return self._report.to_dict() if self._report is not None else None

    def control(self) -> dict[str, Any]:
        report = self.report()
        if report is None:
            last_report = getattr(self.app, "last_report", None)
            if last_report is not None:
                try:
                    report = last_report.to_dict()
                except Exception:
                    report = None
        target: dict[str, Any] | None = None
        admin = False
        platform_name = ""
        try:
            admin = bool(self.app.platform.is_admin())
            platform_name = str(self.app.platform.name)
        except Exception:
            pass
        if report:
            egress = report.get("egress") or {}
            if egress.get("ok"):
                country = str(egress.get("country_code") or "").upper()
                timezone = str(egress.get("timezone") or "")
                locale = locale_for_country(country, language_for_country(country))
                windows_id = windows_id_for_iana(timezone) if timezone else None
                supports_system = bool(getattr(self.app.platform, "supports_system_timezone", False))
                target = {
                    "country": country or None,
                    "timezone": timezone or None,
                    "timezone_valid": bool(timezone and offset_for_zone(timezone) is not None),
                    "locale": locale,
                    "accept_language": accept_language_value(locale),
                    "windows_timezone_id": windows_id,
                    "system_timezone_available": bool(
                        admin and supports_system and (platform_name != "windows" or bool(windows_id))
                    ),
                }
        snapshots = self.snapshots()
        return {
            "ok": True,
            "control_enabled": self.control_enabled,
            "preview_only": not self.control_enabled,
            "token": self.control_token if self.control_enabled else None,
            "admin": admin,
            "platform": platform_name,
            "audit_running": self.audit_running,
            "action_running": self.action_running,
            "target": target,
            "last_alignment_snapshot_id": self.last_alignment_snapshot_id,
            "last_alignment": self.last_alignment,
            "last_restore": self.last_restore,
            "latest_snapshot": snapshots[0] if snapshots else None,
            "snapshots": snapshots,
        }

    def align(self, body: dict[str, Any]) -> dict[str, Any]:
        if not self.control_enabled:
            raise RuntimeError("control_disabled")
        self._begin_operation("align")
        try:
            if body.get("confirm") is not True:
                raise ValueError("confirm_required")
            fields: dict[str, bool] = {}
            for name in ("timezone", "language", "browser_policies", "confirm_system_timezone"):
                value = body.get(name, False)
                if not isinstance(value, bool):
                    raise ValueError(f"invalid_{name}")
                fields[name] = value
            if not (fields["timezone"] or fields["language"] or fields["browser_policies"]):
                raise ValueError("no_alignment_items")
            report = self.app.last_report
            if report is None:
                raise RuntimeError("audit_required")
            egress = report.egress
            if egress is None or not egress.ok or not egress.timezone:
                raise RuntimeError("egress_unavailable")
            request = AlignmentRequest(
                timezone=fields["timezone"],
                language=fields["language"],
                browser_policies=fields["browser_policies"],
                confirm_system_timezone=fields["confirm_system_timezone"],
                expected_country=(egress.country_code or None),
                expected_timezone=egress.timezone,
                reason="web_quick_align",
            )
            self._event(
                "info",
                f"开始一键对齐：时区={fields['timezone']} 语言={fields['language']} "
                f"浏览器={fields['browser_policies']} 系统时区={fields['confirm_system_timezone']}",
            )
            result = self.app.align(request, egress=egress)
            if result.snapshot_id:
                self.last_alignment_snapshot_id = result.snapshot_id
            self.last_alignment = result.to_dict()
            self._set_report(self.app.last_report)
            level = "success" if result.ok else ("warn" if result.partial else "error")
            self._event(
                level,
                f"一键对齐完成：{'成功' if result.ok else ('部分完成' if result.partial else '失败')}，"
                f"快照 {result.snapshot_id or '未创建'}。",
                {"snapshot_id": result.snapshot_id, "failures": result.failures[:8]},
            )
            return {
                "ok": True,
                "result": result.to_dict(),
                "report": self.report(),
                "snapshots": self.snapshots(),
                "control": self.control(),
            }
        except Exception as exc:
            self._event("error", f"一键对齐失败：{type(exc).__name__}: {exc}")
            raise
        finally:
            self._end_operation()

    def restore(self, snapshot_id: str | None, *, confirm: bool = False) -> dict[str, Any]:
        if not self.control_enabled:
            raise RuntimeError("control_disabled")
        if not confirm:
            raise ValueError("confirm_required")
        self._begin_operation("restore")
        try:
            if not snapshot_id or snapshot_id == "latest":
                snapshot = self.app.snapshot_store.latest()
            else:
                snapshot = self.app.snapshot_store.load(str(snapshot_id))
            if snapshot is None:
                raise SnapshotError("no_snapshot")
            self._event("info", f"开始还原快照 {snapshot.snapshot_id}：{snapshot.label}")
            result = self.app.restore(snapshot.snapshot_id)
            self.last_restore = result.to_dict()
            if result.verified and self.last_alignment_snapshot_id == snapshot.snapshot_id:
                self.last_alignment_snapshot_id = None
            self._set_report(self.app.last_report)
            level = "success" if result.verified else "warn"
            self._event(
                level,
                f"快照 {snapshot.snapshot_id} 还原完成："
                f"{'全部匹配' if result.verified else '存在未还原或未匹配项'}。",
                {
                    "snapshot_id": snapshot.snapshot_id,
                    "restored": result.restored_items,
                    "failures": [failure.to_dict() for failure in result.failures[:8]],
                },
            )
            return {
                "ok": True,
                "result": result.to_dict(),
                "report": self.report(),
                "snapshots": self.snapshots(),
                "control": self.control(),
            }
        except Exception as exc:
            self._event("error", f"还原失败：{type(exc).__name__}: {exc}")
            raise
        finally:
            self._end_operation()

    def history(self) -> list[dict[str, Any]]:
        path = self.app.paths.state / "audit_history.jsonl"
        entries: list[dict[str, Any]] = []
        try:
            if path.is_file() and path.stat().st_size <= 6_000_000:
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
                for line in lines[-200:]:
                    try:
                        item = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(item, dict) and item.get("event") == "audit":
                        entries.append(item)
        except OSError:
            entries = []
        # The preview itself never writes history.  Include the current
        # in-memory report as a session-only point so the trend card is useful
        # immediately after a read-only preview audit.
        current = self.report()
        if current and (not entries or entries[-1].get("audit_id") != current.get("report_id")):
            egress = current.get("egress") or {}
            entries.append(
                {
                    "ts": current.get("finished_at") or "",
                    "event": "audit",
                    "audit_id": current.get("report_id"),
                    "risk_score": current.get("risk_score"),
                    "gate_allowed": bool((current.get("gate") or {}).get("allowed")),
                    "counts": current.get("status_counts") or {},
                    "country": egress.get("country_code"),
                    "ip": egress.get("ip"),
                    "egress_timezone": egress.get("timezone"),
                    "failures": [
                        str(check.get("id"))
                        for check in current.get("checks", [])
                        if isinstance(check, dict)
                        and check.get("id")
                        and check.get("status") in ("fail", "error")
                    ],
                    "warnings": [
                        str(check.get("id"))
                        for check in current.get("checks", [])
                        if isinstance(check, dict) and check.get("id") and check.get("status") == "warn"
                    ],
                    "check_statuses": {
                        str(check.get("id")): str(check.get("status"))
                        for check in current.get("checks", [])
                        if isinstance(check, dict) and check.get("id")
                    },
                    "session_only": True,
                }
            )
        return entries[-50:]

    def console(self) -> dict[str, Any]:
        report = self.report()
        recommendations: list[dict[str, Any]] = []
        summary = ""
        if report is not None:
            # Reconstruct a minimal AuditReport-like view for recommendations.
            try:
                from sentinel.audit.recommendations import compact_summary as _summary
                from sentinel.models import AuditReport, CheckResult, EgressInfo, GateResult, Status

                checks = []
                for raw in report.get("checks", []):
                    checks.append(
                        CheckResult(
                            id=raw.get("id", "?"),
                            title=raw.get("title", ""),
                            status=Status(raw.get("status", "warn")),
                            summary=raw.get("summary", ""),
                            evidence=raw.get("evidence") or [],
                            raw=raw.get("raw") or {},
                            weight=int(raw.get("weight") or 1),
                            blocking=bool(raw.get("blocking")),
                            fixable=bool(raw.get("fixable")),
                            explanation=raw.get("explanation") or "",
                        )
                    )
                gate = GateResult(
                    allowed=bool((report.get("gate") or {}).get("allowed")),
                    reasons=(report.get("gate") or {}).get("reasons") or [],
                    risk_score=int(report.get("risk_score") or 0),
                )
                egress_data = report.get("egress") or {}
                egress = EgressInfo(
                    ok=bool(egress_data.get("ok")),
                    ip=egress_data.get("ip"),
                    country_code=egress_data.get("country_code"),
                    timezone=egress_data.get("timezone"),
                    org=egress_data.get("org"),
                    asn=egress_data.get("asn"),
                    ip_type=egress_data.get("ip_type") or "unknown",
                    source=egress_data.get("source") or "unknown",
                )
                reconstructed = AuditReport(
                    report_id=report.get("report_id", "preview"),
                    started_at=report.get("started_at", ""),
                    finished_at=report.get("finished_at", ""),
                    checks=checks,
                    risk_score=int(report.get("risk_score") or 0),
                    gate=gate,
                    egress=egress,
                )
                recommendations = build_recommendations(reconstructed)
                summary = _summary(reconstructed)
            except Exception:
                recommendations = []
                summary = ""
        with self._event_lock:
            events = list(self._events)
        return {
            "events": events,
            "recommendations": recommendations,
            "summary": summary,
            "report": report,
            "audit_running": self.audit_running,
        }

    def snapshots(self) -> list[dict[str, Any]]:
        try:
            result = []
            for snapshot in self.app.snapshot_store.list():
                result.append(
                    {
                        "snapshot_id": snapshot.snapshot_id,
                        "created_at": snapshot.created_at,
                        "label": snapshot.label,
                        "reason": snapshot.reason,
                        "modified_items": snapshot.modified_items,
                        "checksum": str(snapshot.data.get("checksum") or ""),
                    }
                )
            return result
        except Exception:
            return []

    def profiles(self) -> list[dict[str, Any]]:
        try:
            current = self.app.profile_service.current_profile_id
            result = []
            for profile in self.app.profile_service.list():
                environment = profile.get("environment") or {}
                result.append(
                    {
                        "profile_id": profile.get("profile_id"),
                        "name": profile.get("name"),
                        "expected_exit_country": environment.get("expected_exit_country") or None,
                        "timezone": (environment.get("system_timezone") or {}).get("iana") or None,
                        "proxy_label": environment.get("proxy_label") or None,
                        "is_current": profile.get("profile_id") == current,
                        "updated_at": profile.get("updated_at"),
                    }
                )
            return result
        except Exception:
            return []

    def docs(self, name: str) -> dict[str, Any] | None:
        entry = DOCS.get(name)
        if entry is None:
            return None
        title, relative = entry
        path = self.app.paths.root / relative
        if not path.is_file():
            path = Path(__file__).resolve().parent.parent / relative
        try:
            if path.stat().st_size > 2_000_000:
                return {"name": name, "title": title, "markdown": "文档过大，无法预览。"}
            return {"name": name, "title": title, "markdown": path.read_text(encoding="utf-8")}
        except OSError as exc:
            return {"name": name, "title": title, "markdown": f"无法读取文档：{exc}"}


class PreviewHandler(BaseHTTPRequestHandler):
    server_version = f"SentinelPreview/{__version__}"
    protocol_version = "HTTP/1.1"
    backend: Any
    static_root: Path = STATIC_ROOT

    # --- response helpers ------------------------------------------------
    def _headers(self, *, content_type: str, length: int, cache: str = "no-store") -> None:
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )

    def _send_bytes(self, status: int, body: bytes, content_type: str, *, cache: str = "no-store") -> None:
        self.send_response(status)
        self._headers(content_type=content_type, length=len(body), cache=cache)
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                self.close_connection = True

    def handle_one_request(self) -> None:
        """Browsers routinely close speculative connections; don't traceback."""
        try:
            BaseHTTPRequestHandler.handle_one_request(self)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            self.close_connection = True

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8")

    def _control_enabled(self) -> bool:
        return bool(getattr(self.backend, "control_enabled", False))

    def _send_error_json(self, status: int, message: str) -> None:
        self._send_json(
            status,
            {
                "ok": False,
                "preview_only": not self._control_enabled(),
                "control_enabled": self._control_enabled(),
                "error": message,
            },
        )

    def _safe_static(self, relative: str) -> Path | None:
        candidate = (self.static_root / relative).resolve()
        try:
            candidate.relative_to(self.static_root.resolve())
        except ValueError:
            return None
        if not candidate.is_file() or candidate.suffix.lower() not in ALLOWED_STATIC_SUFFIXES:
            return None
        return candidate

    def _serve_static(self, relative: str) -> None:
        path = self._safe_static(relative)
        if path is None:
            self._send_error_json(404, "not_found")
            return
        content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        try:
            body = path.read_bytes()
        except OSError:
            self._send_error_json(404, "not_found")
            return
        self._send_bytes(200, body, content_type, cache="public, max-age=30")

    # --- GET -------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            self._serve_static("index.html")
            return
        if path == "/favicon.ico":
            self._serve_static("favicon.svg")
            return
        if path.startswith("/static/"):
            self._serve_static(path[len("/static/") :])
            return
        if path == "/api/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "preview_only": not self._control_enabled(),
                    "control_enabled": self._control_enabled(),
                    "version": __version__,
                    "app": APP_NAME,
                },
            )
            return
        if path == "/api/control":
            try:
                self._send_json(200, self.backend.control())
            except Exception:
                traceback.print_exc()
                self._send_error_json(500, "control_unavailable")
            return
        if path == "/api/status":
            try:
                self._send_json(200, self.backend.status())
            except Exception:
                traceback.print_exc()
                self._send_error_json(500, "status_unavailable")
            return
        if path == "/api/report":
            try:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "preview_only": not self._control_enabled(),
                        "report": self.backend.report(),
                        "audit_running": self.backend.audit_running,
                    },
                )
            except Exception:
                traceback.print_exc()
                self._send_error_json(500, "report_unavailable")
            return
        if path == "/api/snapshots":
            self._send_json(
                200,
                {
                    "ok": True,
                    "preview_only": not self._control_enabled(),
                    "snapshots": self.backend.snapshots(),
                },
            )
            return
        if path == "/api/profiles":
            self._send_json(
                200,
                {
                    "ok": True,
                    "preview_only": not self._control_enabled(),
                    "profiles": self.backend.profiles(),
                },
            )
            return
        if path == "/api/history":
            self._send_json(
                200,
                {
                    "ok": True,
                    "preview_only": not self._control_enabled(),
                    "history": self.backend.history(),
                },
            )
            return
        if path == "/api/console":
            self._send_json(
                200,
                {
                    "ok": True,
                    "preview_only": not self._control_enabled(),
                    **self.backend.console(),
                },
            )
            return
        if path == "/api/docs":
            name = urllib.parse.parse_qs(parsed.query).get("name", ["tutorial"])[0]
            data = self.backend.docs(name)
            if data is None:
                self._send_error_json(404, "unknown_document")
            else:
                self._send_json(
                    200,
                    {
                        "ok": True,
                        "preview_only": not self._control_enabled(),
                        **data,
                    },
                )
            return
        if path == "/api/audit":
            self._send_error_json(405, "use_post_for_audit")
            return
        self._send_error_json(404, "not_found")

    def do_HEAD(self) -> None:  # noqa: N802
        self.do_GET()

    # --- POST helpers -----------------------------------------------------
    def _read_body(self) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY:
            self._send_error_json(413, "request_too_large")
            return None
        if length <= 0:
            return b""
        try:
            return self.rfile.read(length)
        except OSError:
            return b""

    def _parse_json(self, raw: bytes) -> dict[str, Any] | None:
        try:
            data = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_error_json(400, "invalid_json")
            return None
        if not isinstance(data, dict):
            self._send_error_json(400, "json_object_required")
            return None
        return data

    def _host_is_loopback(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        if not host:
            return False
        if host.startswith("["):
            hostname = host[1:].split("]", 1)[0]
        else:
            hostname = host.split(":", 1)[0]
        return hostname.lower() in {"127.0.0.1", "localhost", "::1"}

    def _origin_is_loopback(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parsed = urllib.parse.urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost", "::1"}

    def _authorize_write(self) -> bool:
        if not self._control_enabled():
            self._send_error_json(403, "control_disabled")
            return False
        if not self._host_is_loopback() or not self._origin_is_loopback():
            self._send_error_json(403, "origin_not_allowed")
            return False
        token = self.headers.get("X-Sentinel-Token") or ""
        expected = getattr(self.backend, "control_token", None)
        if not expected or not token or not hmac.compare_digest(str(token), str(expected)):
            self._send_error_json(403, "invalid_control_token")
            return False
        content_type = (self.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            self._send_error_json(415, "json_content_type_required")
            return False
        return True

    def _handle_write(self, path: str, raw: bytes) -> None:
        data = self._parse_json(raw)
        if data is None:
            return
        if data.get("confirm") is not True:
            self._send_error_json(400, "confirm_required")
            return
        try:
            if path == "/api/align":
                result = self.backend.align(data)
            else:
                result = self.backend.restore(
                    str(data.get("snapshot_id") or "latest"),
                    confirm=True,
                )
            self._send_json(
                200,
                {
                    "ok": True,
                    "control_enabled": True,
                    "preview_only": False,
                    "action_running": self.backend.action_running,
                    **result,
                },
            )
        except RuntimeError as exc:
            code = str(exc)
            if code.endswith("_in_progress"):
                self._send_error_json(409, code)
            elif code in {"audit_required", "egress_unavailable"}:
                self._send_error_json(409, code)
            elif code == "control_disabled":
                self._send_error_json(403, code)
            else:
                self._send_error_json(500, "action_failed")
        except SnapshotError as exc:
            self._send_error_json(400, f"snapshot_error: {exc}")
        except ValueError as exc:
            self._send_error_json(400, str(exc))
        except Exception as exc:
            traceback.print_exc()
            self._send_error_json(500, f"action_failed: {type(exc).__name__}")

    # --- POST ------------------------------------------------------------
    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path not in {"/api/audit", "/api/align", "/api/restore"}:
            self._send_error_json(405 if path.startswith("/api/") else 404, "not_found")
            return
        raw = self._read_body()
        if raw is None:
            return
        if path in {"/api/align", "/api/restore"}:
            if self._authorize_write():
                self._handle_write(path, raw)
            return
        try:
            report = self.backend.audit()
            self._send_json(
                200,
                {
                    "ok": True,
                    "control_enabled": self._control_enabled(),
                    "preview_only": not self._control_enabled(),
                    "report": report,
                },
            )
        except RuntimeError as exc:
            code = str(exc)
            if code.endswith("_in_progress"):
                self._send_error_json(409, code)
            else:
                self._send_error_json(500, "audit_failed")
        except Exception as exc:
            traceback.print_exc()
            self._send_error_json(500, f"audit_failed: {type(exc).__name__}")

    def log_message(self, fmt: str, *args: Any) -> None:
        # Do not log report bodies or proxy details.
        sys.stderr.write("[preview] %s - %s\n" % (self.address_string(), fmt % args))


class PreviewHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def make_server(
    backend: Any,
    *,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    tries: int = MAX_PORT_TRIES,
) -> tuple[PreviewHTTPServer, int]:
    handler = type(
        "BoundPreviewHandler",
        (PreviewHandler,),
        {"backend": backend, "static_root": STATIC_ROOT},
    )
    last_error: OSError | None = None
    for candidate in range(port, port + max(1, tries)):
        try:
            server = PreviewHTTPServer((host, candidate), handler)
            return server, int(server.server_address[1])
        except OSError as exc:
            last_error = exc
            if exc.errno in (48, 98, 10048):  # EADDRINUSE / WSAEADDRINUSE
                continue
            raise
    raise OSError(f"无法绑定本地预览端口 {port}-{port + tries - 1}: {last_error}")


def serve(
    *,
    port: int = DEFAULT_PORT,
    open_browser: bool = True,
    backend: Any | None = None,
    host: str = "127.0.0.1",
    control_enabled: bool = True,
) -> int:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("预览服务器只允许绑定 loopback 地址")
    backend = backend or PreviewBackend(control_enabled=control_enabled)
    server, actual_port = make_server(backend, host=host, port=port)
    url = f"http://127.0.0.1:{actual_port}/"
    print(f"{APP_NAME} 本地浏览器控制台已启动: {url}", flush=True)
    if getattr(backend, "control_enabled", False):
        print(
            "本地控制模式：对齐/快照还原需要页面二次确认，会先创建不可变快照；"
            "启动 Claude 与 Kill-Switch 仍在桌面版。",
            flush=True,
        )
    else:
        print("只读预览：对齐、快照还原、启动 Claude、解除 Kill-Switch 请使用桌面版。", flush=True)
    if open_browser:
        timer = threading.Timer(0.6, lambda: webbrowser.open_new_tab(url))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        print("\n预览服务已停止。", flush=True)
    finally:
        server.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Claude Environment Sentinel 本地浏览器控制台")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口，默认 8790")
    parser.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--host", default="127.0.0.1", help="仅允许 loopback 地址")
    parser.add_argument("--read-only", action="store_true", help="禁用对齐/还原写接口，仅保留只读预览")
    args = parser.parse_args(argv)
    try:
        return serve(
            port=args.port,
            open_browser=not args.no_open,
            host=args.host,
            control_enabled=not args.read_only,
        )
    except (OSError, ValueError) as exc:
        print(f"无法启动浏览器控制台: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
