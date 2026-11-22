"""One-shot audit sampling.

Everything is sampled once per audit so individual checks describe the same
moment as closely as possible and the GUI does not trigger repeated network
calls.  Failures are converted into explicit sample errors, never exceptions
that would hide the rest of the report.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sentinel.config import Settings
from sentinel.models import (
    BrowserInfo,
    ClaudeClientInfo,
    EgressInfo,
    EnvValue,
    ProxyProbeInfo,
    ProcessEntry,
    SystemTimezone,
    TunInfo,
)
from sentinel.platform.base import PlatformAdapter
from sentinel.util.net import (
    NetworkProbe,
    is_private_ip,
    is_public_ip,
    read_proxy_env,
    validate_proxy_value,
)
from sentinel.util.proc import run

PROXY_NAME_RE = re.compile(
    r"(clash|mihomo|sing[-_ ]?box|v2ray|xray|verge|nekoray|nekobox|hysteria|tuic|trojan|wireguard|openvpn|ss-local|shadowsocks)",
    re.IGNORECASE,
)
COMMON_PROXY_PORTS = (7890, 7891, 7892, 1080, 10808, 10809, 20171, 2080, 6152, 8889, 9090)
VIRTUAL_INTERFACE_MARKERS = (
    "vpn",
    "vmware",
    "virtual",
    "wsl",
    "hyper-v",
    "vethernet",
    "radmin",
    "tailscale",
    "zerotier",
    "docker",
    "loopback",
    "tun",
    "tap",
    "wireguard",
)
FONT_MARKERS = (
    "simsun",
    "simhei",
    "msyh",
    "microsoftyahei",
    "fz",
    "wqy",
    "wenquanyi",
    "sourcehan",
    "notosanscjk",
    "pingfang",
    "songti",
    "heiti",
    "kaiti",
    "fangsong",
)


@dataclass
class AuditSample:
    system_timezone: SystemTimezone
    user_env: dict[str, EnvValue]
    process_env: dict[str, str | None]
    effective_env: dict[str, str]
    user_language: str | None
    node: dict[str, Any]
    egress: EgressInfo
    proxy: ProxyProbeInfo
    tun: TunInfo
    dns: list[dict[str, Any]]
    webrtc: dict[str, Any]
    fonts: dict[str, Any]
    browsers: list[BrowserInfo]
    claude: ClaudeClientInfo
    clock: dict[str, Any]
    previous: dict[str, Any] | None = None
    require_tun: bool = False
    errors: list[str] = field(default_factory=list)


def probe_node(effective_env: dict[str, str]) -> dict[str, Any]:
    executable = shutil.which("node")
    if not executable:
        return {"available": False, "error": "未在 PATH 中找到 node", "raw": None}
    script = "console.log(JSON.stringify(Intl.DateTimeFormat().resolvedOptions()))"
    result = run([executable, "-e", script], timeout=8, env=effective_env)
    if not result.ok:
        return {
            "available": True,
            "error": result.error or result.stderr.strip() or "node 执行失败",
            "returncode": result.returncode,
            "raw": None,
        }
    parsed: dict[str, Any] | None = None
    for line in reversed(result.stdout.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            parsed = candidate
            break
    if parsed is None:
        return {"available": True, "error": "node 输出不是可解析的 JSON", "raw": result.stdout[:2000]}
    return {"available": True, "error": None, "raw": parsed}


def probe_proxy(
    platform: PlatformAdapter,
    effective_env: dict[str, str],
    processes: list[ProcessEntry] | None = None,
) -> ProxyProbeInfo:
    env = read_proxy_env(effective_env)
    valid = True
    malformed: list[str] = []
    for name, value in env.items():
        ok, reason = validate_proxy_value(name, value)
        if not ok:
            valid = False
            malformed.append(f"{name}: {reason}")
    procs = processes if processes is not None else platform.list_processes()
    matching = [p for p in procs if PROXY_NAME_RE.search(p.name or "") or PROXY_NAME_RE.search(Path(p.exe_path or "").name)]
    ports: set[int] = set(COMMON_PROXY_PORTS)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = env.get(name)
        if not value:
            continue
        candidate = value if "://" in value else "http://" + value
        try:
            from urllib.parse import urlsplit

            parsed = urlsplit(candidate)
            if parsed.port:
                ports.add(int(parsed.port))
        except (ValueError, TypeError):
            pass
    listening = {}
    for port in sorted(ports):
        try:
            from sentinel.util.proc import port_open

            listening[port] = port_open(port)
        except Exception:
            listening[port] = False
    reachable = any(listening.values())
    return ProxyProbeInfo(
        configured=bool(env),
        env={k: v for k, v in env.items()},
        valid=valid and (bool(env) or not malformed),
        malformed=malformed,
        core_processes=matching,
        listening_ports=listening,
        core_running=bool(matching) or reachable,
        socks_or_http_reachable=reachable,
        raw={
            "process_names": [p.name for p in matching],
            "ports_checked": sorted(listening),
        },
    )


def _parse_candidate_ips(sdp: str) -> list[str]:
    found: list[str] = []
    for match in re.finditer(r"a=candidate:[^\r\n]+", sdp):
        line = match.group(0)
        for ip_match in re.finditer(r"(?:\d{1,3}\.){3}\d{1,3}", line):
            found.append(ip_match.group(0))
    return list(dict.fromkeys(found))


def _aiortc_candidates(timeout: float = 4.0) -> dict[str, Any]:
    try:
        import aiortc  # type: ignore  # optional dependency
    except ImportError:
        return {"available": False, "error": "aiortc 未安装", "candidates": []}

    async def gather() -> list[str]:
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

        pc = RTCPeerConnection(
            RTCConfiguration(iceServers=[RTCIceServer(urls="stun:stun.l.google.com:19302")])
        )
        try:
            pc.createDataChannel("sentinel-probe")
            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            deadline = asyncio.get_running_loop().time() + timeout
            while pc.iceGatheringState != "complete" and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.1)
            return _parse_candidate_ips(pc.localDescription.sdp if pc.localDescription else "")
        finally:
            await pc.close()

    try:
        candidates = asyncio.run(asyncio.wait_for(gather(), timeout=timeout + 1.5))
        return {"available": True, "error": None, "candidates": candidates}
    except Exception as exc:  # optional backend must never break the audit
        return {"available": True, "error": str(exc), "candidates": []}


def probe_webrtc(platform: PlatformAdapter, network: NetworkProbe, egress: EgressInfo) -> dict[str, Any]:
    local = platform.local_addresses()
    stun = network.stun_binding()
    aiortc = _aiortc_candidates()
    physical = [
        a
        for a in local
        if not any(marker in str(a.get("interface") or "").lower() for marker in VIRTUAL_INTERFACE_MARKERS)
    ]
    public_local = [a.get("ip") for a in physical if a.get("ip") and is_public_ip(str(a.get("ip")))]
    private_local = [a.get("ip") for a in physical if a.get("ip") and is_private_ip(str(a.get("ip")))]
    candidates = list(aiortc.get("candidates") or [])
    reasons: list[str] = []
    verdict = "warn"
    if stun.get("ok"):
        mapped = stun.get("mapped_ip")
        if mapped and is_public_ip(str(mapped)) and egress.ip and str(mapped) != egress.ip:
            verdict = "fail"
            reasons.append(f"STUN 公网映射 {mapped} 与出口 IP {egress.ip} 不一致")
    if public_local:
        if egress.ip and any(ip != egress.ip for ip in public_local):
            verdict = "fail"
            reasons.append("本机存在非出口公网接口地址")
    if candidates:
        public_candidates = [ip for ip in candidates if is_public_ip(ip)]
        if egress.ip and any(ip != egress.ip for ip in public_candidates):
            verdict = "fail"
            reasons.append("WebRTC ICE 候选包含非出口公网 IP")
        elif any(is_private_ip(ip) for ip in candidates):
            if verdict != "fail":
                verdict = "warn"
            reasons.append("ICE 候选包含 RFC1918 地址（浏览器可能使用 mDNS 隐藏，但本机探测可见）")
        elif not reasons:
            verdict = "pass"
            reasons.append("ICE 候选未发现公网泄漏")
    if verdict != "fail":
        if not stun.get("ok") and not candidates:
            verdict = "warn"
            reasons.append("没有可用的 STUN 或 aiortc 结果，WebRTC 覆盖不足")
        elif stun.get("ok") and not candidates:
            verdict = "warn"
            reasons.append(
                "STUN 出口与主出口一致；未安装可选 aiortc，浏览器 ICE 候选覆盖有限，"
                "请结合 A17 的浏览器 WebRTC 策略判断。"
            )
    if verdict == "warn" and not reasons:
        reasons.append("WebRTC 探测覆盖有限，建议结合 A17 浏览器策略判断")
    return {
        "verdict": verdict,
        "reasons": reasons,
        "local_addresses": local,
        "private_local": private_local,
        "public_local": public_local,
        "stun": stun,
        "aiortc": aiortc,
    }


def scan_fonts(directories: list[Path]) -> dict[str, Any]:
    matches: list[str] = []
    errors: list[str] = []
    scanned = 0
    for directory in directories:
        if not directory.is_dir():
            continue
        try:
            for entry in directory.iterdir():
                if scanned >= 20_000:
                    break
                scanned += 1
                if not entry.is_file():
                    continue
                lowered = entry.name.lower().replace(" ", "")
                if any(marker in lowered for marker in FONT_MARKERS):
                    matches.append(str(entry))
                    if len(matches) >= 30:
                        break
        except OSError as exc:
            errors.append(f"{directory}: {exc}")
    return {
        "matches": matches,
        "count": len(matches),
        "scanned": scanned,
        "directories": [str(d) for d in directories],
        "errors": errors,
    }


def gather_sample(
    *,
    platform: PlatformAdapter,
    network: NetworkProbe,
    browser_store: Any,
    settings: Settings,
    previous: dict[str, Any] | None,
) -> AuditSample:
    errors: list[str] = []
    try:
        system_timezone = platform.get_system_timezone()
    except Exception as exc:
        system_timezone = SystemTimezone(None, None, None, "error", error=str(exc))
        errors.append(f"A1 采样失败: {exc}")
    try:
        user_env = platform.get_user_env_snapshot(["TZ", "LANG", "LC_ALL"])
    except Exception as exc:
        user_env = {name: EnvValue(False, source=f"error: {exc}") for name in ("TZ", "LANG", "LC_ALL")}
        errors.append(f"环境变量采样失败: {exc}")
    process_env = {name: None for name in ("TZ", "LANG", "LC_ALL")}
    try:
        import os

        process_env = {name: os.environ.get(name) for name in ("TZ", "LANG", "LC_ALL")}
    except Exception:
        pass
    try:
        effective_env = platform.effective_env()
    except Exception as exc:
        effective_env = dict(__import__("os").environ)
        errors.append(f"有效环境采样失败: {exc}")
    try:
        user_language = platform.get_user_language()
    except Exception as exc:
        user_language = None
        errors.append(f"系统语言采样失败: {exc}")
    node = probe_node(effective_env)
    try:
        egress = network.egress(force=True)
    except TypeError:
        egress = network.egress()
    try:
        processes = platform.list_processes()
    except Exception as exc:
        processes = []
        errors.append(f"进程列表采样失败: {exc}")
    try:
        proxy = probe_proxy(platform, effective_env, processes)
    except Exception as exc:
        proxy = ProxyProbeInfo(raw={"error": str(exc)})
        errors.append(f"A10/A11 代理采样失败: {exc}")
    try:
        tun = platform.get_tun_info()
    except Exception as exc:
        tun = TunInfo(active=False, source="error", error=str(exc))
        errors.append(f"A12 TUN 采样失败: {exc}")
    dns: list[dict[str, Any]] = []
    if network.enabled:
        try:
            dns = network.dns_egress()
        except Exception as exc:
            dns = [{"resolver": "all", "error": str(exc), "ips": [], "asn": None}]
            errors.append(f"A13 DNS 采样失败: {exc}")
    try:
        webrtc = probe_webrtc(platform, network, egress)
    except Exception as exc:
        webrtc = {"verdict": "warn", "reasons": [f"WebRTC 探测异常: {exc}"], "local_addresses": []}
        errors.append(f"A14 WebRTC 采样失败: {exc}")
    try:
        fonts = scan_fonts(platform.font_dirs())
    except Exception as exc:
        fonts = {"matches": [], "count": 0, "scanned": 0, "directories": [], "errors": [str(exc)]}
        errors.append(f"A15 字体采样失败: {exc}")
    try:
        browsers = browser_store.audit_browsers()
    except Exception as exc:
        browsers = []
        errors.append(f"A16/A17 浏览器策略采样失败: {exc}")
    try:
        claude = platform.detect_claude()
    except Exception as exc:
        claude = ClaudeClientInfo(errors=[str(exc)])
        errors.append(f"A18 Claude 客户端采样失败: {exc}")
    clock = network.clock_sample() if network.enabled else {
        "source": "disabled",
        "skew_seconds": None,
        "error": "网络探测已关闭",
    }
    return AuditSample(
        system_timezone=system_timezone,
        user_env=user_env,
        process_env=process_env,
        effective_env=effective_env,
        user_language=user_language,
        node=node,
        egress=egress,
        proxy=proxy,
        tun=tun,
        dns=dns,
        webrtc=webrtc,
        fonts=fonts,
        browsers=browsers,
        claude=claude,
        clock=clock,
        previous=previous,
        require_tun=bool(settings.require_tun),
        errors=errors,
    )
