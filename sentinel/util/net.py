"""Network probes implemented with the standard library.

All requests are bounded, read-only and never send credentials.  Endpoints:
  * ipinfo.io / ip-api.com / Cloudflare trace for the current exit;
  * Cloudflare and Google DoH for resolver egress comparison;
  * Cloudflare trace / HTTP Date for clock skew;
  * a minimal RFC 5389 STUN binding request for a WebRTC-adjacent leak check.

The tool never contacts claude.ai and never submits account data.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import struct
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sentinel.models import EgressInfo
from sentinel.util.redact import redact_proxy_url

USER_AGENT = "ClaudeEnvironmentSentinel/1.0 (+local diagnostic; no account data)"
MAX_BYTES = 262_144


@dataclass
class HttpResult:
    url: str
    status: int | None
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    error: str | None = None
    elapsed_ms: int = 0
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return self.status is not None and 200 <= self.status < 300 and not self.error


def http_request(
    url: str,
    *,
    timeout: float = 4.0,
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> HttpResult:
    started = time.monotonic()
    req_headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain;q=0.9, */*;q=0.5"}
    if headers:
        req_headers.update(headers)
    request = urllib.request.Request(url, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=max(1.0, float(timeout))) as response:
            raw = response.read(MAX_BYTES + 1)
            truncated = len(raw) > MAX_BYTES
            body = raw[:MAX_BYTES].decode("utf-8", "replace")
            return HttpResult(
                url=url,
                status=int(getattr(response, "status", response.getcode())),
                headers={str(k): str(v) for k, v in response.headers.items()},
                body=body,
                elapsed_ms=int((time.monotonic() - started) * 1000),
                truncated=truncated,
            )
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(MAX_BYTES).decode("utf-8", "replace")
        except Exception:
            body = ""
        return HttpResult(
            url=url,
            status=exc.code,
            headers={str(k): str(v) for k, v in exc.headers.items()} if exc.headers else {},
            body=body,
            error=f"HTTP {exc.code}",
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return HttpResult(
            url=url,
            status=None,
            error=str(getattr(exc, "reason", exc)),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def http_json(
    url: str,
    *,
    timeout: float = 4.0,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, HttpResult]:
    result = http_request(url, timeout=timeout, headers=headers)
    if not result.ok:
        return None, result
    try:
        parsed = json.loads(result.body)
    except json.JSONDecodeError as exc:
        result.error = f"JSON 解析失败: {exc}"
        return None, result
    return parsed if isinstance(parsed, dict) else None, result


def parse_asn(org: str | None) -> str | None:
    if not org:
        return None
    match = re.match(r"\s*(AS\d+)", org, re.IGNORECASE)
    if match:
        return match.group(1).upper()
    return None


def classify_ip(org: str | None, privacy: dict[str, Any] | None = None) -> tuple[str, list[str]]:
    privacy = privacy or {}
    flags: list[str] = []
    lowered = (org or "").lower()
    if privacy.get("proxy") or privacy.get("vpn"):
        flags.append("proxy/vpn")
    if privacy.get("tor"):
        flags.append("tor")
    if privacy.get("hosting"):
        flags.append("hosting")
    if privacy.get("mobile"):
        flags.append("mobile")
    datacenter_words = (
        "hosting",
        "datacenter",
        "data center",
        "cloud",
        "vps",
        "server",
        "amazon",
        "aws",
        "google cloud",
        "microsoft azure",
        "azure",
        "digitalocean",
        "linode",
        "ovh",
        "hetzner",
        "vultr",
        "oracle cloud",
        "alibaba",
        "tencent cloud",
        "leaseweb",
        "choopa",
        "contabo",
        "colo",
    )
    mobile_words = ("mobile", "cellular", "wireless", "4g", "5g", "lte")
    if "tor" in flags:
        return "proxy", flags
    if "proxy/vpn" in flags or "proxy" in flags:
        return "proxy", flags
    if any(word in lowered for word in mobile_words) or "mobile" in flags:
        return "mobile", flags + ([] if "mobile" in flags else ["mobile-keyword"])
    if privacy.get("hosting") or any(word in lowered for word in datacenter_words):
        return "datacenter", flags + ([] if "hosting" in flags else ["datacenter-keyword"])
    if flags:
        return "unknown", flags
    if org:
        return "residential", flags
    return "unknown", flags


def _extract_text_answers(payload: dict[str, Any]) -> list[str]:
    answers = payload.get("Answer")
    if not isinstance(answers, list):
        return []
    values: list[str] = []
    for answer in answers:
        if not isinstance(answer, dict):
            continue
        if int(answer.get("type") or 0) != 16:  # TXT
            continue
        data = str(answer.get("data") or "").strip()
        data = data.strip('"')
        if data:
            values.append(data)
    return values


def is_private_ip(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_private or ipaddress.ip_address(value).is_loopback
    except ValueError:
        return False


def is_public_ip(value: str) -> bool:
    try:
        addr = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast or addr.is_reserved)


def local_ipv4_addresses() -> list[str]:
    found: set[str] = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(str(info[4][0]))
    except OSError:
        pass
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            found.add(str(probe.getsockname()[0]))
        finally:
            probe.close()
    except OSError:
        pass
    return sorted(found)


def read_proxy_env(environ: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    result: dict[str, str] = {}
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        if name in source and source[name] is not None:
            result[name.upper()] = str(source[name])
    return result


def validate_proxy_value(name: str, value: str) -> tuple[bool, str | None]:
    if name == "NO_PROXY":
        return True, None
    raw = value.strip()
    if not raw:
        return False, "空值"
    candidate = raw if "://" in raw else "http://" + raw
    try:
        parsed = urllib.parse.urlsplit(candidate)
        if not parsed.hostname:
            return False, "缺少主机名"
        _ = parsed.port
    except ValueError as exc:
        return False, str(exc)
    return True, None


def public_proxy_view(env: dict[str, str]) -> dict[str, str]:
    return {k: (redact_proxy_url(v) if k != "NO_PROXY" else v) for k, v in env.items()}


def _parse_trace(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


class NetworkProbe:
    """Cached, bounded network probes.  Safe to call from worker threads."""

    def __init__(self, *, timeout: float = 4.0, enabled: bool = True, cache_ttl: float = 20.0) -> None:
        self.timeout = max(1.0, float(timeout))
        self.enabled = bool(enabled)
        self.cache_ttl = max(0.0, float(cache_ttl))
        self._lock = threading.Lock()
        self._egress: EgressInfo | None = None
        self._egress_at = 0.0
        self._ip_cache: dict[str, tuple[float, dict[str, Any]]] = {}

    def egress(self, *, force: bool = False) -> EgressInfo:
        if not self.enabled:
            return EgressInfo(ok=False, source="disabled", errors=["网络探测已在设置中关闭"])
        with self._lock:
            if not force and self._egress is not None and (time.monotonic() - self._egress_at) < self.cache_ttl:
                return self._egress
        info = self._fetch_egress()
        with self._lock:
            self._egress = info
            self._egress_at = time.monotonic()
        return info

    def _fetch_egress(self) -> EgressInfo:
        errors: list[str] = []
        info, err = self._ipinfo()
        if info is not None:
            return info
        errors.append(f"ipinfo: {err}")
        info, err = self._ipapi()
        if info is not None:
            info.errors = errors
            return info
        errors.append(f"ip-api: {err}")
        info, err = self._cloudflare()
        if info is not None:
            info.errors = errors
            return info
        errors.append(f"cloudflare: {err}")
        return EgressInfo(
            ok=False,
            source="none",
            fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            errors=errors,
        )

    def _ipinfo(self) -> tuple[EgressInfo | None, str | None]:
        payload, result = http_json("https://ipinfo.io/json", timeout=self.timeout)
        if payload is None:
            return None, result.error or "无响应"
        ip = payload.get("ip")
        if not ip:
            return None, "响应缺少 ip"
        org = str(payload.get("org") or "") or None
        asn_obj = payload.get("asn")
        asn = str(asn_obj.get("asn") or "") if isinstance(asn_obj, dict) else parse_asn(org)
        privacy = payload.get("privacy") if isinstance(payload.get("privacy"), dict) else {}
        ip_type, flags = classify_ip(org, privacy)
        return (
            EgressInfo(
                ok=True,
                ip=str(ip),
                country_code=str(payload.get("country") or "").upper() or None,
                region=str(payload.get("region") or "") or None,
                city=str(payload.get("city") or "") or None,
                timezone=str(payload.get("timezone") or "") or None,
                org=org,
                asn=asn,
                ip_type=ip_type,
                privacy_flags=flags,
                source="ipinfo.io",
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw={"ipinfo": payload},
            ),
            None,
        )

    def _ipapi(self) -> tuple[EgressInfo | None, str | None]:
        fields = (
            "status,message,country,countryCode,regionName,city,isp,org,as,asname,"
            "timezone,query,proxy,hosting,mobile"
        )
        url = "http://ip-api.com/json/?" + urllib.parse.urlencode({"fields": fields})
        payload, result = http_json(url, timeout=self.timeout)
        if payload is None:
            return None, result.error or "无响应"
        if payload.get("status") != "success":
            return None, str(payload.get("message") or "查询失败")
        ip = payload.get("query")
        if not ip:
            return None, "响应缺少 query"
        org = str(payload.get("org") or payload.get("isp") or "") or None
        asn = parse_asn(str(payload.get("as") or "")) or parse_asn(org)
        privacy = {
            "proxy": bool(payload.get("proxy")),
            "hosting": bool(payload.get("hosting")),
            "mobile": bool(payload.get("mobile")),
        }
        ip_type, flags = classify_ip(org, privacy)
        return (
            EgressInfo(
                ok=True,
                ip=str(ip),
                country_code=str(payload.get("countryCode") or "").upper() or None,
                country_name=str(payload.get("country") or "") or None,
                region=str(payload.get("regionName") or "") or None,
                city=str(payload.get("city") or "") or None,
                timezone=str(payload.get("timezone") or "") or None,
                org=org,
                asn=asn,
                ip_type=ip_type,
                privacy_flags=flags,
                source="ip-api.com (HTTP; free tier has no TLS)",
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw={"ip_api": payload},
            ),
            None,
        )

    def _cloudflare(self) -> tuple[EgressInfo | None, str | None]:
        result = http_request("https://www.cloudflare.com/cdn-cgi/trace", timeout=self.timeout)
        if not result.ok:
            return None, result.error or f"HTTP {result.status}"
        trace = _parse_trace(result.body)
        ip = trace.get("ip")
        if not ip:
            return None, "trace 缺少 ip"
        return (
            EgressInfo(
                ok=True,
                ip=ip,
                country_code=str(trace.get("loc") or "").upper() or None,
                timezone=None,
                source="cloudflare trace (无时区/ASN)",
                fetched_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                raw={"trace": trace},
            ),
            None,
        )

    def lookup_ip(self, ip: str) -> dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            cached = self._ip_cache.get(ip)
            if cached and now - cached[0] < 300:
                return cached[1]
        result: dict[str, Any] = {"ip": ip}
        payload, http_result = http_json(f"https://ipinfo.io/{urllib.parse.quote(ip)}/json", timeout=self.timeout)
        if payload:
            org = str(payload.get("org") or "") or None
            result.update(
                {
                    "asn": parse_asn(org),
                    "org": org,
                    "country": str(payload.get("country") or "") or None,
                    "source": "ipinfo.io",
                }
            )
        else:
            payload, http_result = http_json(
                f"http://ip-api.com/json/{urllib.parse.quote(ip)}?fields=status,country,countryCode,isp,org,as,proxy,hosting,mobile",
                timeout=self.timeout,
            )
            if payload and payload.get("status") == "success":
                org = str(payload.get("org") or payload.get("isp") or "") or None
                result.update(
                    {
                        "asn": parse_asn(str(payload.get("as") or "")) or parse_asn(org),
                        "org": org,
                        "country": str(payload.get("countryCode") or "") or None,
                        "source": "ip-api.com",
                    }
                )
            else:
                result["error"] = http_result.error or "IP 归属查询失败"
        with self._lock:
            self._ip_cache[ip] = (now, result)
        return result

    def dns_egress(self) -> list[dict[str, Any]]:
        queries = [
            (
                "cloudflare",
                "https://1.1.1.1/dns-query?name=whoami.cloudflare&type=TXT",
                "https://cloudflare-dns.com/dns-query?name=whoami.cloudflare&type=TXT",
            ),
            (
                "google",
                "https://8.8.8.8/resolve?name=o-o.myaddr.l.google.com&type=TXT",
                "https://dns.google/resolve?name=o-o.myaddr.l.google.com&type=TXT",
            ),
        ]
        results: list[dict[str, Any]] = []
        for resolver, primary_url, fallback_url in queries:
            item: dict[str, Any] = {
                "resolver": resolver,
                "url": None,
                "ips": [],
                "asn": None,
                "org": None,
                "error": None,
            }
            payload = None
            http_result = None
            for url in (primary_url, fallback_url):
                payload, http_result = http_json(
                    url,
                    timeout=self.timeout,
                    headers={"Accept": "application/dns-json"},
                )
                item["url"] = url
                if payload is not None:
                    break
            if payload is None:
                item["error"] = (http_result.error if http_result else None) or "DoH 无响应"
                results.append(item)
                continue
            ips = _extract_text_answers(payload)
            item["ips"] = ips
            if not ips:
                item["error"] = "DoH 响应中没有 TXT 记录"
                results.append(item)
                continue
            lookup = self.lookup_ip(ips[0])
            item.update(
                {
                    "asn": lookup.get("asn"),
                    "org": lookup.get("org"),
                    "country": lookup.get("country"),
                    "error": lookup.get("error"),
                }
            )
            results.append(item)
        return results

    def clock_sample(self) -> dict[str, Any]:
        result = http_request("https://www.cloudflare.com/cdn-cgi/trace", timeout=self.timeout)
        local_epoch = time.time()
        if result.ok:
            trace = _parse_trace(result.body)
            ts = trace.get("ts")
            if ts:
                try:
                    server_epoch = float(ts)
                    return {
                        "source": "cloudflare trace ts",
                        "server_epoch": server_epoch,
                        "local_epoch": local_epoch,
                        "skew_seconds": round(local_epoch - server_epoch, 1),
                        "error": None,
                    }
                except ValueError:
                    pass
        for url in ("https://www.cloudflare.com/", "https://time.is/"):
            header_result = http_request(url, timeout=self.timeout)
            date_header = header_result.headers.get("Date")
            if date_header:
                try:
                    from email.utils import parsedate_to_datetime

                    server = parsedate_to_datetime(date_header)
                    if server.tzinfo is None:
                        server = server.replace(tzinfo=timezone.utc)
                    return {
                        "source": f"HTTP Date {url}",
                        "server_epoch": server.timestamp(),
                        "local_epoch": local_epoch,
                        "skew_seconds": round(local_epoch - server.timestamp(), 1),
                        "error": None,
                    }
                except (TypeError, ValueError):
                    continue
        return {
            "source": "unavailable",
            "server_epoch": None,
            "local_epoch": local_epoch,
            "skew_seconds": None,
            "error": "无法获取可信时间（Cloudflare trace / HTTP Date 均失败）",
        }

    def stun_binding(self, server: str = "stun.l.google.com", port: int = 19302) -> dict[str, Any]:
        transaction_id = os.urandom(12)
        cookie = 0x2112A442
        packet = struct.pack("!HHI12s", 0x0001, 0, cookie, transaction_id)
        try:
            addresses = socket.getaddrinfo(server, port, socket.AF_INET, socket.SOCK_DGRAM)
            if not addresses:
                return {"ok": False, "error": "STUN 域名无地址", "server": server}
            family, socktype, proto, _canon, sockaddr = addresses[0]
            with socket.socket(family, socktype, proto) as sock:
                sock.settimeout(self.timeout)
                sock.sendto(packet, sockaddr)
                data, _peer = sock.recvfrom(2048)
        except (OSError, TimeoutError) as exc:
            return {"ok": False, "error": str(exc), "server": server}
        if len(data) < 20:
            return {"ok": False, "error": "STUN 响应过短", "server": server}
        msg_type, msg_len, resp_cookie = struct.unpack("!HHI", data[:8])
        if msg_type != 0x0101 or resp_cookie != cookie:
            return {"ok": False, "error": "STUN 响应格式不匹配", "server": server}
        offset = 20
        end = min(len(data), 20 + msg_len)
        while offset + 4 <= end:
            attr_type, attr_len = struct.unpack("!HH", data[offset : offset + 4])
            value = data[offset + 4 : offset + 4 + attr_len]
            offset += 4 + attr_len + ((4 - attr_len % 4) % 4)
            if attr_type in (0x0020, 0x0001) and len(value) >= 8:
                family = value[1]
                if family != 0x01:
                    continue
                mapped_port = struct.unpack("!H", value[2:4])[0]
                mapped_ip = socket.inet_ntoa(value[4:8])
                if attr_type == 0x0020:
                    mapped_port ^= 0x2112
                    mapped_ip = socket.inet_ntoa(
                        bytes(b ^ c for b, c in zip(value[4:8], struct.pack("!I", cookie)))
                    )
                return {
                    "ok": True,
                    "server": server,
                    "mapped_ip": mapped_ip,
                    "mapped_port": mapped_port,
                    "error": None,
                }
        return {"ok": False, "error": "STUN 响应没有映射地址", "server": server}

    @staticmethod
    def proxy_env() -> dict[str, str]:
        return read_proxy_env()
