"""Application paths and persisted, non-secret settings."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _default_root() -> Path:
    """Project root.

    ``SENTINEL_HOME`` allows the user to keep runtime data elsewhere.  The
    default preserves the requested repository layout (``backups/`` next to
    the ``sentinel/`` package).
    """
    env = os.environ.get("SENTINEL_HOME")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd().resolve()
    if (cwd / "sentinel").is_dir():
        return cwd
    package_root = Path(__file__).resolve().parent.parent
    if (package_root / "sentinel").is_dir():
        return package_root
    return cwd


@dataclass(frozen=True)
class AppPaths:
    root: Path
    backups: Path
    logs: Path
    state: Path
    profiles: Path
    tutorials: Path
    docs: Path

    @classmethod
    def discover(cls) -> "AppPaths":
        root = _default_root()
        return cls(
            root=root,
            backups=root / "backups",
            logs=root / "logs",
            state=root / "state",
            profiles=root / "profiles",
            tutorials=root / "tutorials",
            docs=root / "docs",
        )

    def ensure(self) -> None:
        for path in (
            self.root,
            self.backups,
            self.logs,
            self.state,
            self.profiles,
            self.tutorials,
            self.docs,
        ):
            path.mkdir(parents=True, exist_ok=True)
        for marker in (self.backups, self.logs, self.state, self.profiles):
            keep = marker / ".gitkeep"
            if not keep.exists():
                try:
                    keep.touch()
                except OSError:
                    pass

    @property
    def config_file(self) -> Path:
        return self.state / "config.json"

    @property
    def last_audit_file(self) -> Path:
        return self.state / "last_audit.json"

    @property
    def audits_dir(self) -> Path:
        return self.state / "audits"

    @property
    def killswitch_state_file(self) -> Path:
        return self.state / "killswitch.json"


@dataclass
class Settings:
    """User-editable, non-secret configuration.

    Deliberately absent: proxy credentials, Claude tokens, cookies, account
    identities.  Sentinel never needs or stores them.
    """

    schema_version: int = 1
    mode: str = "beginner"  # beginner | expert
    theme: str = "dark"  # dark | light
    country_lock: bool = False
    expected_country: str = ""
    network_enabled: bool = True
    http_timeout_seconds: float = 4.0
    claude_command: str = ""
    claude_arguments: list[str] = field(default_factory=list)
    require_tun: bool = False
    poll_seconds: float = 5.0
    hotkey_enabled: bool = True
    hotkey: str = "ctrl+shift+k"
    auto_export_audit: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Settings":
        base = cls()
        if not isinstance(data, dict):
            return base
        for key, expected in (
            ("mode", str),
            ("theme", str),
            ("country_lock", bool),
            ("expected_country", str),
            ("network_enabled", bool),
            ("http_timeout_seconds", (int, float)),
            ("claude_command", str),
            ("claude_arguments", list),
            ("require_tun", bool),
            ("poll_seconds", (int, float)),
            ("hotkey_enabled", bool),
            ("hotkey", str),
            ("auto_export_audit", bool),
        ):
            if key not in data:
                continue
            value = data[key]
            if isinstance(expected, tuple):
                if isinstance(value, expected) and not isinstance(value, bool):
                    setattr(base, key, value)
            elif isinstance(value, expected):
                setattr(base, key, value)
        # Bounds keep a malformed config from creating a tight polling loop.
        base.http_timeout_seconds = min(30.0, max(1.0, float(base.http_timeout_seconds)))
        base.poll_seconds = min(120.0, max(2.0, float(base.poll_seconds)))
        base.mode = base.mode if base.mode in {"beginner", "expert"} else "beginner"
        base.theme = base.theme if base.theme in {"dark", "light"} else "dark"
        base.expected_country = str(base.expected_country or "").upper()[:8]
        base.claude_arguments = [str(x) for x in base.claude_arguments][:32]
        return base

    @classmethod
    def load(cls, path: Path) -> "Settings":
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return cls()
        return cls.from_dict(raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, self.to_dict())


def atomic_write_json(path: Path, data: Any, *, mode: int = 0o600) -> None:
    """Write JSON atomically.  Used for mutable config/audit state only.

    Immutable snapshots deliberately use a separate O_EXCL path and never
    call this helper.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, mode)
        except OSError:
            pass
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(tmp_name, mode)
        except OSError:
            pass
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass
