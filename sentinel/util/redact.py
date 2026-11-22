"""Redaction and credential-rejection helpers.

Sentinel reads only environment variables, policy values and network metadata.
It never needs Claude credentials, cookies or tokens.  These helpers make that
constraint executable: profile files and logs are rejected/redacted when a
sensitive key appears.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|cookie|password|passwd|secret|credential|session|auth|oauth|jwt|"
    r"api[_-]?key|access[_-]?key|refresh[_-]?token|account[_-]?id|email|"
    r"login|sessionid|bearer)",
    re.IGNORECASE,
)

# These are environment *names*, not values, and are safe to audit.
ALLOWED_SENSITIVE_ENV_NAMES = {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}


def is_sensitive_key(key: str) -> bool:
    if key.upper() in ALLOWED_SENSITIVE_ENV_NAMES:
        return False
    return bool(SENSITIVE_KEY_PATTERN.search(str(key)))


def redact_proxy_url(value: str) -> str:
    """Hide userinfo in a proxy URL while retaining host/port for evidence."""
    raw = value.strip()
    candidate = raw if "://" in raw else "http://" + raw
    try:
        parts = urlsplit(candidate)
    except ValueError:
        return "[unparseable proxy value]"
    if not parts.hostname:
        return "[unparseable proxy value]"
    host = parts.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host + (f":{port}" if port else "")
    if parts.username or parts.password:
        netloc = "***:***@" + netloc
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact_env(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if name.upper() in {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"}:
        return redact_proxy_url(value)
    if is_sensitive_key(name):
        return "[redacted]"
    return value


def redact_mapping(data: Any, *, depth: int = 0) -> Any:
    """Recursively redact values under sensitive key names (bounded)."""
    if depth > 8:
        return data
    if isinstance(data, dict):
        return {
            str(k): ("[redacted]" if is_sensitive_key(str(k)) else redact_mapping(v, depth=depth + 1))
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_mapping(v, depth=depth + 1) for v in data[:2000]]
    return data


def find_sensitive_keys(data: Any, *, prefix: str = "$", depth: int = 0) -> list[str]:
    """Return paths of keys that must never appear in a profile/snapshot."""
    found: list[str] = []
    if depth > 12:
        return found
    if isinstance(data, dict):
        for key, value in data.items():
            key_s = str(key)
            path = f"{prefix}.{key_s}"
            if is_sensitive_key(key_s):
                found.append(path)
            found.extend(find_sensitive_keys(value, prefix=path, depth=depth + 1))
    elif isinstance(data, list):
        for index, value in enumerate(data[:2000]):
            found.extend(find_sensitive_keys(value, prefix=f"{prefix}[{index}]", depth=depth + 1))
    return found


def assert_no_credentials(data: Any, *, label: str = "profile") -> None:
    bad = find_sensitive_keys(data)
    if bad:
        preview = ", ".join(bad[:8])
        raise ValueError(
            f"{label} 包含疑似身份/凭证字段，已拒绝保存：{preview}。"
            "Sentinel 只管理环境配置，不管理 Cookie、Token、会话或登录材料。"
        )
