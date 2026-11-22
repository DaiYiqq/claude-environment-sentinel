"""A1–A20 check implementations.

Each check consumes the single AuditSample and returns one CheckResult with
status, human-readable evidence and raw sampled values.  No check silently
swallows an exception; the audit engine catches unknown errors and turns them
into an ERROR item with the traceback message.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from sentinel.audit.explanations import explanation_for, fix_hint_for
from sentinel.audit.probes import AuditSample
from sentinel.audit.risk import BLOCKING, WEIGHTS
from sentinel.align.browsers import BROWSER_BY_KEY, WEBRTC_NAMES
from sentinel.models import BrowserInfo, CheckResult, EnvValue, Status
from sentinel.tzmap import (
    COUNTRY_LANGUAGES,
    accept_language_value,
    language_for_country,
    language_region_conflict,
    locale_for_country,
    normalize_language,
    offset_for_zone,
)
from sentinel.util.redact import redact_proxy_url

FIX_ACTIONS = {
    "A1": "timezone",
    "A2": "timezone",
    "A3": "language",
    "A8": "timezone",
    "A9": "language",
    "A16": "browser",
    "A17": "browser",
    "A15": "font_notice",
}


def _make(
    sample: AuditSample,
    check_id: str,
    title: str,
    status: Status,
    summary: str,
    evidence: list[str],
    raw: dict[str, Any],
    *,
    blocking: bool | None = None,
    fixable: bool | None = None,
) -> CheckResult:
    return CheckResult(
        id=check_id,
        title=title,
        status=status,
        summary=summary,
        evidence=[str(line) for line in evidence if line is not None],
        raw=raw,
        weight=WEIGHTS.get(check_id, 1),
        blocking=BLOCKING.get(check_id, False) if blocking is None else blocking,
        fixable=bool(FIX_ACTIONS.get(check_id)) if fixable is None else fixable,
        fix_action=FIX_ACTIONS.get(check_id),
        explanation=explanation_for(check_id) + ("\n修复提示：" + fix_hint_for(check_id) if fix_hint_for(check_id) else ""),
    )


def _env_text(name: str, value: EnvValue, process_value: str | None) -> str:
    user = f'"{value.value}"' if value.exists and value.value is not None else "<未设置>"
    process = f'"{process_value}"' if process_value is not None else "<未设置>"
    return f"{name}: 用户级={user} (来源 {value.source}); 当前进程={process}"


def _egress_brief(sample: AuditSample) -> dict[str, Any]:
    return sample.egress.to_dict()


def check_a1(sample: AuditSample) -> CheckResult:
    tz = sample.system_timezone
    raw = tz.to_dict()
    evidence = [
        f"native_id = {tz.native_id!r}; iana = {tz.iana!r}; utc_offset_seconds = {tz.utc_offset_seconds}",
        f"source = {tz.source}; error = {tz.error!r}",
    ]
    if tz.native_id or tz.iana:
        return _make(sample, "A1", "系统时区可读取", Status.PASS, f"系统时区为 {tz.native_id or tz.iana}。", evidence, raw)
    return _make(sample, "A1", "系统时区可读取", Status.FAIL, "无法读取系统时区，后续时区一致性判断不可靠。", evidence, raw)


def check_a2(sample: AuditSample) -> CheckResult:
    tz_value = sample.user_env.get("TZ", EnvValue(False))
    process_tz = sample.process_env.get("TZ")
    system = sample.system_timezone
    evidence = [
        _env_text("TZ", tz_value, process_tz),
        f"系统时区 native={system.native_id!r}, iana={system.iana!r}, offset={system.utc_offset_seconds}",
    ]
    raw = {
        "user_TZ": tz_value.to_dict(),
        "process_TZ": process_tz,
        "system": system.to_dict(),
    }
    if not tz_value.exists:
        return _make(
            sample,
            "A2",
            "用户 TZ 与系统时区一致",
            Status.WARN,
            "TZ 未设置。Node/CLI 会继承系统时区，因此不一定有问题，但缺少显式一致性。",
            evidence,
            raw,
        )
    value = tz_value.value or ""
    zone_offset = offset_for_zone(value)
    if zone_offset is None:
        evidence.append(f"TZ={value!r} 不是可识别的 IANA 时区")
        return _make(sample, "A2", "用户 TZ 与系统时区一致", Status.FAIL, f"用户级 TZ 值 {value!r} 无效。", evidence, raw)
    if system.utc_offset_seconds is None:
        evidence.append("系统时区偏移不可读")
        return _make(sample, "A2", "用户 TZ 与系统时区一致", Status.WARN, "系统时区偏移不可读，无法完成比对。", evidence, raw)
    evidence.append(f"TZ 偏移={zone_offset}s; 系统偏移={system.utc_offset_seconds}s")
    if system.iana and value == system.iana:
        return _make(sample, "A2", "用户 TZ 与系统时区一致", Status.PASS, "用户 TZ 与系统时区为同一 IANA 时区。", evidence, raw)
    if zone_offset == system.utc_offset_seconds:
        return _make(sample, "A2", "用户 TZ 与系统时区一致", Status.PASS, "用户 TZ 与系统时区偏移一致。", evidence, raw)
    return _make(sample, "A2", "用户 TZ 与系统时区一致", Status.FAIL, "用户 TZ 与系统时区偏移不一致。", evidence, raw)


def check_a3(sample: AuditSample) -> CheckResult:
    lang = sample.user_env.get("LANG", EnvValue(False))
    lc_all = sample.user_env.get("LC_ALL", EnvValue(False))
    evidence = [
        _env_text("LANG", lang, sample.process_env.get("LANG")),
        _env_text("LC_ALL", lc_all, sample.process_env.get("LC_ALL")),
        f"系统语言样本 = {sample.user_language!r}",
    ]
    raw = {
        "LANG": lang.to_dict(),
        "LC_ALL": lc_all.to_dict(),
        "system_language": sample.user_language,
    }
    if not lang.exists and not lc_all.exists:
        return _make(
            sample,
            "A3",
            "用户语言环境有效",
            Status.WARN,
            "LANG/LC_ALL 均未设置，程序会回退到系统语言；缺少显式一致性。",
            evidence,
            raw,
        )
    for name, value in (("LANG", lang), ("LC_ALL", lc_all)):
        if value.exists and value.value is not None:
            text = value.value.strip()
            if not text:
                evidence.append(f"{name} 存在但为空字符串")
                return _make(sample, "A3", "用户语言环境有效", Status.FAIL, f"{name} 为空字符串。", evidence, raw)
            if not any(ch.isalpha() for ch in text):
                evidence.append(f"{name}={text!r} 不含语言字母")
                return _make(sample, "A3", "用户语言环境有效", Status.FAIL, f"{name} 的值不是有效 locale。", evidence, raw)
    lang_primary = normalize_language(lang.value if lang.exists else None)
    lc_primary = normalize_language(lc_all.value if lc_all.exists else None)
    if lang_primary and lc_primary and lang_primary != lc_primary:
        evidence.append(f"语言主标签冲突: LANG={lang_primary}, LC_ALL={lc_primary}")
        return _make(sample, "A3", "用户语言环境有效", Status.FAIL, "LANG 与 LC_ALL 指向不同语言。", evidence, raw)
    if (lang.exists and (lang.value or "").strip().upper() in {"C", "POSIX"}) or (
        lc_all.exists and (lc_all.value or "").strip().upper() in {"C", "POSIX"}
    ):
        return _make(sample, "A3", "用户语言环境有效", Status.WARN, "LANG/LC_ALL 被设为 C/POSIX，可能缺少地区语言信息。", evidence, raw)
    return _make(sample, "A3", "用户语言环境有效", Status.PASS, "LANG/LC_ALL 格式有效且互相一致。", evidence, raw)


def check_a4(sample: AuditSample) -> CheckResult:
    node = sample.node
    raw = dict(node)
    if not node.get("available"):
        return _make(
            sample,
            "A4",
            "Node Intl 默认环境可采样",
            Status.WARN,
            "未安装 Node 或不在 PATH 中，无法采样 Intl；按教程安装 Node 后重新检测。",
            [str(node.get("error") or "node 不可用")],
            raw,
        )
    if node.get("error") or not isinstance(node.get("raw"), dict):
        return _make(
            sample,
            "A4",
            "Node Intl 默认环境可采样",
            Status.WARN,
            "Node 存在但 Intl 采样失败，不能确认真实运行时环境。",
            [str(node.get("error") or "无法解析 node 输出")],
            raw,
        )
    info = node["raw"]
    evidence = [f"Node resolvedOptions: {info}"]
    expected_zone = (sample.user_env.get("TZ").value if sample.user_env.get("TZ", EnvValue(False)).exists else None) or sample.system_timezone.iana
    node_zone = info.get("timeZone")
    expected_offset = offset_for_zone(expected_zone)
    node_offset = offset_for_zone(node_zone)
    if expected_zone and node_zone and str(expected_zone) == str(node_zone):
        evidence.append(f"期望时区={expected_zone!r}; Node 时区={node_zone!r}; IANA 名称一致")
    elif expected_offset is not None and node_offset is not None:
        evidence.append(f"期望时区={expected_zone!r} (offset {expected_offset}s); Node 时区={node_zone!r} (offset {node_offset}s)")
        if expected_offset != node_offset:
            return _make(sample, "A4", "Node Intl 默认环境可采样", Status.FAIL, "Node 看到的时区与 Sentinel/系统时区不一致。", evidence, raw)
    expected_language = normalize_language(
        (sample.user_env.get("LC_ALL").value if sample.user_env.get("LC_ALL", EnvValue(False)).exists else None)
        or (sample.user_env.get("LANG").value if sample.user_env.get("LANG", EnvValue(False)).exists else None)
        or sample.user_language
    )
    node_language = normalize_language(str(info.get("locale") or ""))
    evidence.append(f"期望语言={expected_language!r}; Node locale={info.get('locale')!r}")
    if expected_language and node_language and expected_language != node_language:
        evidence.append(
            "Windows 上 Node 的 ICU 默认 locale 由系统决定，LANG/LC_ALL 可能不生效；"
            "Sentinel 将其作为警告，绝不伪报通过。"
        )
        return _make(
            sample,
            "A4",
            "Node Intl 默认环境可采样",
            Status.WARN,
            f"Node locale 是 {node_language}，与期望 {expected_language} 不一致（平台限制，详见证据）。",
            evidence,
            raw,
        )
    return _make(sample, "A4", "Node Intl 默认环境可采样", Status.PASS, "Node Intl 采样成功，时区/语言与期望一致。", evidence, raw)


def check_a5(sample: AuditSample) -> CheckResult:
    egress = sample.egress
    raw = _egress_brief(sample)
    evidence = [
        f"source={egress.source}; ip={egress.ip!r}; country={egress.country_code!r}; timezone={egress.timezone!r}",
        f"errors={egress.errors}",
    ]
    if not egress.ok:
        return _make(sample, "A5", "出口 IP 国家/地区可确认", Status.FAIL, "所有出口探测均失败，无法确认网络地区。", evidence, raw)
    if not egress.country_code:
        return _make(sample, "A5", "出口 IP 国家/地区可确认", Status.WARN, "出口 IP 可读取，但缺少国家代码。", evidence, raw)
    return _make(sample, "A5", "出口 IP 国家/地区可确认", Status.PASS, f"出口国家/地区为 {egress.country_code}。", evidence, raw)


def check_a6(sample: AuditSample) -> CheckResult:
    egress = sample.egress
    raw = _egress_brief(sample)
    evidence = [
        f"ASN={egress.asn!r}; org={egress.org!r}; ip_type={egress.ip_type!r}; privacy_flags={egress.privacy_flags}",
        f"source={egress.source}",
    ]
    if not egress.ok:
        return _make(sample, "A6", "出口 IP 的 ASN 与类型", Status.WARN, "出口信息不可用，无法判断 IP 类型。", evidence, raw)
    if egress.ip_type == "proxy" or any("tor" in f for f in egress.privacy_flags):
        return _make(sample, "A6", "出口 IP 的 ASN 与类型", Status.FAIL, "出口被标记为代理/Tor，风险较高。", evidence, raw)
    if egress.ip_type == "datacenter":
        return _make(sample, "A6", "出口 IP 的 ASN 与类型", Status.WARN, "出口看起来是机房/云 IP，可能被大量账号共用。", evidence, raw)
    if egress.ip_type in {"mobile", "residential"}:
        return _make(sample, "A6", "出口 IP 的 ASN 与类型", Status.PASS, f"出口类型为 {egress.ip_type}。", evidence, raw)
    return _make(sample, "A6", "出口 IP 的 ASN 与类型", Status.WARN, "出口类型未知，无法确认 IP 质量。", evidence, raw)


def check_a7(sample: AuditSample) -> CheckResult:
    current = sample.egress
    previous = sample.previous or {}
    prev_egress = previous.get("egress") if isinstance(previous.get("egress"), dict) else {}
    evidence = [
        f"当前 IP={current.ip!r}, country={current.country_code!r}",
        f"上次 IP={prev_egress.get('ip')!r}, country={prev_egress.get('country_code')!r}",
    ]
    raw = {"current": {"ip": current.ip, "country": current.country_code}, "previous": prev_egress, "baseline": not bool(previous)}
    if not previous:
        return _make(sample, "A7", "出口 IP 与上次审计一致", Status.PASS, "首次运行，已建立出口 IP 基线。", evidence, raw)
    if not prev_egress.get("ip"):
        return _make(sample, "A7", "出口 IP 与上次审计一致", Status.PASS, "上次没有可用出口记录，本次作为新基线。", evidence, raw)
    if current.ip == prev_egress.get("ip"):
        return _make(sample, "A7", "出口 IP 与上次审计一致", Status.PASS, "出口 IP 与上次审计相同。", evidence, raw)
    if current.country_code and prev_egress.get("country_code") and current.country_code != prev_egress.get("country_code"):
        return _make(sample, "A7", "出口 IP 与上次审计一致", Status.FAIL, "出口国家/地区发生变化。", evidence, raw)
    return _make(sample, "A7", "出口 IP 与上次审计一致", Status.WARN, "出口 IP 变化，但国家/地区未变。", evidence, raw)


def check_a8(sample: AuditSample) -> CheckResult:
    egress = sample.egress
    system_offset = sample.system_timezone.utc_offset_seconds
    target_offset = offset_for_zone(egress.timezone)
    evidence = [
        f"系统时区={sample.system_timezone.native_id!r}/{sample.system_timezone.iana!r}, offset={system_offset}s",
        f"出口时区={egress.timezone!r}, offset={target_offset}s",
    ]
    raw = {
        "system": sample.system_timezone.to_dict(),
        "egress_timezone": egress.timezone,
        "system_offset": system_offset,
        "egress_offset": target_offset,
        "tolerance_seconds": 7200,
    }
    if not egress.ok:
        return _make(sample, "A8", "系统时区与出口地区偏移匹配", Status.WARN, "出口信息不可用，无法比对时区偏移。", evidence, raw)
    if target_offset is None:
        evidence.append("出口服务没有返回可识别的 IANA 时区")
        return _make(sample, "A8", "系统时区与出口地区偏移匹配", Status.WARN, "出口时区未知，无法判断 ±2 小时容差。", evidence, raw)
    if system_offset is None:
        return _make(sample, "A8", "系统时区与出口地区偏移匹配", Status.WARN, "系统时区偏移不可读。", evidence, raw)
    delta = abs(system_offset - target_offset)
    evidence.append(f"偏移差={delta}s；容差=7200s")
    if delta <= 7200:
        return _make(sample, "A8", "系统时区与出口地区偏移匹配", Status.PASS, f"系统时区与出口时区相差 {delta / 3600:.1f} 小时，在 ±2 小时容差内。", evidence, raw)
    return _make(
        sample,
        "A8",
        "系统时区与出口地区偏移匹配",
        Status.FAIL,
        f"系统时区与出口时区相差 {delta / 3600:.1f} 小时，超过 ±2 小时容差。",
        evidence,
        raw,
    )


def check_a9(sample: AuditSample) -> CheckResult:
    language = None
    for name in ("LC_ALL", "LANG"):
        value = sample.user_env.get(name, EnvValue(False))
        if value.exists and value.value:
            language = normalize_language(value.value)
            break
    if not language:
        language = normalize_language(sample.user_language) or normalize_language(
            str((sample.node.get("raw") or {}).get("locale") or "")
        )
    country = sample.egress.country_code
    evidence = [
        f"系统语言样本={language!r}; 出口国家={country!r}",
        f"该国常见语言集合={sorted(COUNTRY_LANGUAGES.get((country or '').upper(), set())) or '未知'}",
    ]
    raw = {"language": language, "country": country, "country_languages": sorted(COUNTRY_LANGUAGES.get((country or "").upper(), set()))}
    if not language:
        return _make(sample, "A9", "系统语言与出口地区匹配", Status.WARN, "语言样本不足，无法判断地区一致性。", evidence, raw)
    if not country:
        return _make(sample, "A9", "系统语言与出口地区匹配", Status.WARN, "出口国家未知，无法判断语言一致性。", evidence, raw)
    hard_conflict, explanation = language_region_conflict(language, country)
    evidence.append(explanation)
    if hard_conflict:
        return _make(sample, "A9", "系统语言与出口地区匹配", Status.FAIL, explanation, evidence, raw)
    expected = COUNTRY_LANGUAGES.get(country.upper(), set())
    if language in expected:
        return _make(sample, "A9", "系统语言与出口地区匹配", Status.PASS, f"语言 {language} 与出口地区 {country} 的常见语言一致。", evidence, raw)
    return _make(sample, "A9", "系统语言与出口地区匹配", Status.WARN, f"语言 {language} 与出口地区 {country} 不是典型组合，但不构成硬冲突。", evidence, raw)


def _proxy_hosts(env: dict[str, str]) -> set[str]:
    hosts: set[str] = set()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = env.get(name)
        if not value:
            continue
        candidate = value if "://" in value else "http://" + value
        try:
            parts = urlsplit(candidate)
            if parts.hostname:
                hosts.add(f"{parts.hostname}:{parts.port or ''}")
        except ValueError:
            continue
    return hosts


def check_a10(sample: AuditSample) -> CheckResult:
    proxy = sample.proxy
    env = proxy.env
    evidence = [
        f"{name}={redact_proxy_url(value)!r}" for name, value in sorted(env.items())
    ] or ["未设置 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY"]
    raw = {
        "env": {k: redact_proxy_url(v) for k, v in env.items()},
        "malformed": proxy.malformed,
        "hosts": sorted(_proxy_hosts(env)),
    }
    if not env:
        return _make(sample, "A10", "代理环境变量有效", Status.WARN, "未设置代理环境变量；如果使用 TUN/系统代理，这可能是正常的。", evidence, raw)
    if proxy.malformed:
        evidence.extend(proxy.malformed)
        return _make(sample, "A10", "代理环境变量有效", Status.FAIL, "代理环境变量格式非法，部分程序可能直连。", evidence, raw)
    hosts = _proxy_hosts(env)
    if len(hosts) > 1:
        evidence.append(f"不同代理变量指向不同主机: {sorted(hosts)}")
        return _make(sample, "A10", "代理环境变量有效", Status.WARN, "HTTP/HTTPS/ALL 代理指向不同出口，需确认是否符合预期。", evidence, raw)
    return _make(sample, "A10", "代理环境变量有效", Status.PASS, "代理环境变量格式有效且指向一致。", evidence, raw)


def check_a11(sample: AuditSample) -> CheckResult:
    proxy = sample.proxy
    raw = proxy.to_dict()
    raw["env"] = {
        name: (redact_proxy_url(value) if name != "NO_PROXY" else value)
        for name, value in (proxy.env or {}).items()
    }
    evidence = [
        f"configured={proxy.configured}; core_running={proxy.core_running}; reachable={proxy.socks_or_http_reachable}",
        f"匹配进程={[p.name for p in proxy.core_processes]}; 监听端口={proxy.listening_ports}",
    ]
    if proxy.configured:
        if not proxy.core_running:
            return _make(sample, "A11", "代理内核存活", Status.FAIL, "配置了代理变量，但没有发现代理内核或监听端口。", evidence, raw)
        if not proxy.socks_or_http_reachable:
            return _make(sample, "A11", "代理内核存活", Status.WARN, "发现代理进程，但常见代理端口未监听。", evidence, raw)
        return _make(sample, "A11", "代理内核存活", Status.PASS, "代理内核在运行且检测到监听端口。", evidence, raw)
    if proxy.core_running and proxy.socks_or_http_reachable:
        return _make(sample, "A11", "代理内核存活", Status.PASS, "检测到代理内核/端口，但未设置代理环境变量（可能使用 TUN/系统代理）。", evidence, raw)
    if proxy.core_running:
        return _make(sample, "A11", "代理内核存活", Status.WARN, "发现代理服务进程，但常见代理端口未监听，且未设置代理变量。", evidence, raw)
    return _make(sample, "A11", "代理内核存活", Status.WARN, "未检测到代理内核，当前可能是直连模式。", evidence, raw)


def check_a12(sample: AuditSample) -> CheckResult:
    tun = sample.tun
    raw = {"tun": tun.to_dict(), "proxy_configured": sample.proxy.configured, "require_tun": sample.require_tun}
    evidence = [
        f"active={tun.active}; source={tun.source}; adapters={tun.adapters}",
        f"代理变量已配置={sample.proxy.configured}; require_tun={sample.require_tun}",
    ]
    if tun.active:
        return _make(sample, "A12", "TUN/虚拟网卡状态", Status.PASS, "检测到活动的 TUN/虚拟网卡。", evidence, raw)
    if sample.require_tun:
        return _make(
            sample,
            "A12",
            "TUN/虚拟网卡状态",
            Status.FAIL,
            "设置要求 TUN 模式，但未检测到活动 TUN。",
            evidence,
            raw,
            blocking=True,
        )
    if sample.proxy.configured:
        return _make(sample, "A12", "TUN/虚拟网卡状态", Status.WARN, "配置了代理但未检测到 TUN；CLI 可能绕过浏览器代理。", evidence, raw)
    return _make(sample, "A12", "TUN/虚拟网卡状态", Status.WARN, "未检测到 TUN，当前可能是直连或系统代理模式。", evidence, raw)


def check_a13(sample: AuditSample) -> CheckResult:
    entries = sample.dns
    raw = {"dns": entries, "egress_asn": sample.egress.asn}
    evidence = [
        f"{entry.get('resolver')}: ips={entry.get('ips')}, asn={entry.get('asn')}, org={entry.get('org')}, error={entry.get('error')}"
        for entry in entries
    ] or ["没有 DNS 探测结果"]
    if not entries:
        return _make(sample, "A13", "DNS 出口与代理出口一致", Status.WARN, "DoH 探测没有返回结果。", evidence, raw)
    usable = [entry for entry in entries if entry.get("asn")]
    if len(usable) < 2:
        return _make(sample, "A13", "DNS 出口与代理出口一致", Status.WARN, "可用的 DNS ASN 样本不足，无法比对。", evidence, raw)
    asns = {str(entry.get("asn")) for entry in usable}
    if len(asns) > 1:
        return _make(sample, "A13", "DNS 出口与代理出口一致", Status.WARN, f"两个 DoH 解析器看到的 ASN 不一致: {sorted(asns)}。", evidence, raw)
    egress_asn = sample.egress.asn
    if egress_asn and all(str(entry.get("asn")) != str(egress_asn) for entry in usable):
        return _make(sample, "A13", "DNS 出口与代理出口一致", Status.WARN, f"DNS 出口 ASN 与主出口 ASN 不同（{sorted(asns)} vs {egress_asn}）。", evidence, raw)
    return _make(sample, "A13", "DNS 出口与代理出口一致", Status.PASS, "DNS 出口 ASN 与代理/主出口一致。", evidence, raw)


def check_a14(sample: AuditSample) -> CheckResult:
    data = sample.webrtc
    verdict = str(data.get("verdict") or "warn")
    reasons = [str(x) for x in (data.get("reasons") or [])]
    raw = {
        "verdict": verdict,
        "reasons": reasons,
        "local_addresses": data.get("local_addresses"),
        "stun": data.get("stun"),
        "aiortc": data.get("aiortc"),
    }
    evidence = reasons + [
        f"local_addresses={data.get('local_addresses')}",
        f"stun={data.get('stun')}",
        f"aiortc_available={(data.get('aiortc') or {}).get('available')}",
    ]
    status = {"pass": Status.PASS, "fail": Status.FAIL}.get(verdict, Status.WARN)
    summary = {
        "pass": "WebRTC 探测未发现公网出口泄漏。",
        "fail": "WebRTC 探测发现公网地址与出口 IP 不一致。",
    }.get(verdict, "WebRTC 探测覆盖不足，已标记为警告。")
    return _make(sample, "A14", "WebRTC 地址泄漏检查", status, summary, evidence, raw)


def check_a15(sample: AuditSample) -> CheckResult:
    fonts = sample.fonts
    matches = [str(p) for p in (fonts.get("matches") or [])]
    raw = fonts
    evidence = [
        f"扫描目录={fonts.get('directories')}; scanned={fonts.get('scanned')}; matches={len(matches)}",
        *[f"命中: {path}" for path in matches[:12]],
    ]
    if fonts.get("errors"):
        evidence.extend(f"扫描错误: {err}" for err in fonts["errors"][:5])
    if matches:
        return _make(sample, "A15", "字体地区特征", Status.WARN, f"发现 {len(matches)} 个典型中文办公字体文件（仅标记，不删除）。", evidence, raw)
    if fonts.get("errors"):
        return _make(sample, "A15", "字体地区特征", Status.WARN, "字体目录扫描不完整。", evidence, raw)
    return _make(sample, "A15", "字体地区特征", Status.PASS, "未发现被标记的典型中文办公字体。", evidence, raw)


def _expected_accept_language(sample: AuditSample) -> tuple[str, str]:
    locale = locale_for_country(sample.egress.country_code, language_for_country(sample.egress.country_code))
    return locale, accept_language_value(locale)


def _accept_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    return [segment.split(";", 1)[0].strip().lower() for segment in value.split(",") if segment.strip()]


def check_a16(sample: AuditSample) -> CheckResult:
    browsers = [b for b in sample.browsers if b.installed]
    locale, expected_accept = _expected_accept_language(sample)
    expected_lang = normalize_language(locale)
    raw = {
        "expected_locale": locale,
        "expected_accept_language": expected_accept,
        "browsers": [b.to_dict() for b in browsers],
    }
    evidence = [f"出口地区建议 locale={locale}; Accept-Language≈{expected_accept}"]
    if not browsers:
        return _make(sample, "A16", "浏览器 Accept-Language 策略", Status.WARN, "未检测到 Chrome/Edge，跳过浏览器语言策略检查。", evidence, raw)
    statuses: list[Status] = []
    for browser in browsers:
        definition = BROWSER_BY_KEY[browser.key]
        policy = browser.policy or {}
        entry = _first_policy_value(policy, definition.accept_names)
        pref = (browser.preferences or {}).get("accept_languages")
        if entry:
            value = str(entry.get("value") or "")
            tokens = _accept_tokens(value)
            lang_tokens = {normalize_language(token) for token in tokens}
            evidence.append(f"{browser.name}: 策略 {entry.get('name')}={value!r} (来源 {entry.get('effective_hive')})")
            if expected_lang and expected_lang in lang_tokens:
                statuses.append(Status.PASS)
            else:
                statuses.append(Status.FAIL)
        elif pref:
            tokens = _accept_tokens(str(pref))
            evidence.append(f"{browser.name}: 只有用户偏好，未策略锁定: {pref!r}")
            statuses.append(Status.WARN if expected_lang in {normalize_language(t) for t in tokens} else Status.FAIL)
        else:
            evidence.append(f"{browser.name}: 未读取到 Accept-Language 策略或偏好")
            statuses.append(Status.FAIL)
        if browser.running:
            evidence.append(f"{browser.name}: 浏览器正在运行，策略通常需要重启后完全生效。")
    if any(status is Status.FAIL for status in statuses):
        final = Status.FAIL
        summary = "至少一个浏览器的 Accept-Language 缺失或与出口地区不匹配。"
    elif any(status is Status.WARN for status in statuses):
        final = Status.WARN
        summary = "浏览器语言偏好存在，但没有策略锁定，用户以后可能改回。"
    else:
        final = Status.PASS
        summary = "浏览器 Accept-Language 策略与出口地区一致。"
    return _make(sample, "A16", "浏览器 Accept-Language 策略", final, summary, evidence, raw)


def _first_policy_value(policy: dict[str, Any], names: tuple[str, ...]) -> dict[str, Any] | None:
    values = policy.get("values", {}) if isinstance(policy, dict) else {}
    for name in names:
        entry = values.get(name)
        if not isinstance(entry, dict):
            continue
        effective = entry.get("effective") if "effective" in entry else entry
        if isinstance(effective, dict) and effective.get("exists"):
            return {"name": name, **effective, "effective_hive": entry.get("effective_hive", "unknown")}
    return None


def check_a17(sample: AuditSample) -> CheckResult:
    browsers = [b for b in sample.browsers if b.installed]
    raw = {"browsers": [b.to_dict() for b in browsers]}
    evidence: list[str] = []
    if not browsers:
        return _make(sample, "A17", "浏览器 WebRTC 策略", Status.WARN, "未检测到 Chrome/Edge，跳过 WebRTC 策略检查。", evidence or ["没有浏览器"], raw)
    statuses: list[Status] = []
    for browser in browsers:
        entry = _first_policy_value(browser.policy or {}, WEBRTC_NAMES)
        value = str(entry.get("value") or "") if entry else ""
        evidence.append(f"{browser.name}: WebRTC 策略={value!r} (来源 {entry.get('effective_hive') if entry else '缺失'})")
        lowered = value.strip().lower()
        if lowered == "disable_non_proxied_udp":
            statuses.append(Status.PASS)
        elif lowered == "default_public_interface_only":
            statuses.append(Status.WARN)
        else:
            statuses.append(Status.FAIL)
    if any(status is Status.FAIL for status in statuses):
        final = Status.FAIL
        summary = "至少一个浏览器没有禁用非代理 UDP，WebRTC 可能绕过代理。"
    elif any(status is Status.WARN for status in statuses):
        final = Status.WARN
        summary = "浏览器 WebRTC 策略不是最严格的 disable_non_proxied_udp。"
    else:
        final = Status.PASS
        summary = "浏览器 WebRTC 策略为 disable_non_proxied_udp。"
    return _make(sample, "A17", "浏览器 WebRTC 策略", final, summary, evidence, raw)


def check_a18(sample: AuditSample) -> CheckResult:
    info = sample.claude
    raw = info.to_dict()
    evidence = [
        f"client_types={info.client_types}; version={info.version!r}; cli={info.cli_path!r}; desktop={info.desktop_path!r}",
        "identity_inspected=false（不读取登录态、Cookie、Token 或会话文件）",
    ]
    if info.detected:
        if info.version:
            return _make(sample, "A18", "Claude 客户端类型与版本", Status.PASS, f"检测到 {', '.join(info.client_types)}，版本 {info.version}。", evidence, raw)
        return _make(sample, "A18", "Claude 客户端类型与版本", Status.WARN, "检测到客户端，但版本采样失败。", evidence, raw)
    return _make(
        sample,
        "A18",
        "Claude 客户端类型与版本",
        Status.WARN,
        "未检测到 Claude CLI/桌面客户端；安全启动需要在专家模式指定命令。",
        evidence + [f"errors={info.errors}"],
        raw,
    )


def check_a19(sample: AuditSample) -> CheckResult:
    clock = sample.clock
    skew = clock.get("skew_seconds")
    raw = dict(clock)
    evidence = [
        f"source={clock.get('source')!r}; server_epoch={clock.get('server_epoch')!r}; "
        f"local_epoch={clock.get('local_epoch')!r}; skew_seconds={skew!r}",
        f"error={clock.get('error')!r}",
    ]
    if skew is None:
        return _make(sample, "A19", "系统时钟偏差", Status.WARN, "无法获取可信时间，不能确认时钟偏差。", evidence, raw)
    value = abs(float(skew))
    if value > 300:
        return _make(sample, "A19", "系统时钟偏差", Status.FAIL, f"时钟偏差约 {value:.0f} 秒，超过 5 分钟。", evidence, raw)
    if value > 30:
        return _make(sample, "A19", "系统时钟偏差", Status.WARN, f"时钟偏差约 {value:.0f} 秒，建议开启自动同步。", evidence, raw)
    return _make(sample, "A19", "系统时钟偏差", Status.PASS, f"时钟偏差约 {value:.0f} 秒，在可接受范围内。", evidence, raw)


def _baseline_value(previous: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = previous
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def check_a20(sample: AuditSample) -> CheckResult:
    previous = sample.previous
    raw: dict[str, Any] = {"changes": [], "has_previous": bool(previous)}
    if not previous:
        return _make(sample, "A20", "关键配置漂移", Status.PASS, "首次运行，建立漂移基线。", ["没有上一次审计记录"], raw)
    changes: list[dict[str, Any]] = []

    def add(label: str, current: Any, previous_value: Any) -> None:
        if current != previous_value:
            changes.append({"item": label, "previous": previous_value, "current": current})

    add(
        "系统时区",
        (sample.system_timezone.native_id, sample.system_timezone.iana),
        (
            _baseline_value(previous, ("system_timezone", "native_id")),
            _baseline_value(previous, ("system_timezone", "iana")),
        ),
    )
    for name in ("TZ", "LANG", "LC_ALL"):
        current_env = sample.user_env.get(name, EnvValue(False))
        add(
            f"环境变量 {name}",
            {"exists": current_env.exists, "value": current_env.value},
            {
                "exists": _baseline_value(previous, ("user_env", name, "exists")),
                "value": _baseline_value(previous, ("user_env", name, "value")),
            },
        )
    add("出口国家", sample.egress.country_code, _baseline_value(previous, ("egress", "country_code")))
    current_proxy_hosts = sorted(_proxy_hosts(sample.proxy.env))
    add("代理变量目标", current_proxy_hosts, _baseline_value(previous, ("proxy", "hosts")) or [])
    current_browser: dict[str, Any] = {}
    for browser in sample.browsers:
        if not browser.installed:
            continue
        definition = BROWSER_BY_KEY[browser.key]
        accept = _first_policy_value(browser.policy or {}, definition.accept_names)
        webrtc = _first_policy_value(browser.policy or {}, WEBRTC_NAMES)
        current_browser[browser.key] = {
            "accept_language": (accept or {}).get("value"),
            "webrtc": (webrtc or {}).get("value"),
        }
    add("浏览器策略", current_browser, _baseline_value(previous, ("browsers",)) or {})
    raw["changes"] = changes
    evidence = [f"{change['item']}: {change['previous']!r} -> {change['current']!r}" for change in changes] or ["没有关键项变化"]
    if len(changes) == 0:
        return _make(sample, "A20", "关键配置漂移", Status.PASS, "关键配置与上次审计一致。", evidence, raw)
    if len(changes) <= 2:
        return _make(sample, "A20", "关键配置漂移", Status.WARN, f"检测到 {len(changes)} 项关键配置漂移。", evidence, raw)
    return _make(sample, "A20", "关键配置漂移", Status.WARN, f"检测到 {len(changes)} 项关键配置漂移，建议确认是否为预期变化。", evidence, raw)


CHECKS = (
    check_a1,
    check_a2,
    check_a3,
    check_a4,
    check_a5,
    check_a6,
    check_a7,
    check_a8,
    check_a9,
    check_a10,
    check_a11,
    check_a12,
    check_a13,
    check_a14,
    check_a15,
    check_a16,
    check_a17,
    check_a18,
    check_a19,
    check_a20,
)


def run_checks(sample: AuditSample) -> list[CheckResult]:
    results: list[CheckResult] = []
    for check in CHECKS:
        results.append(check(sample))
    return results
