"""Append-only JSONL logging with size-based rotation."""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel.util.redact import redact_mapping


class JsonlLogger:
    def __init__(self, path: Path, *, max_bytes: int = 5_000_000) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.exists() and self.path.stat().st_size > self.max_bytes:
                rotated = self.path.with_suffix(self.path.suffix + ".1")
                try:
                    if rotated.exists():
                        rotated.unlink()
                    self.path.replace(rotated)
                except OSError:
                    # Rotation failure must not lose the new event.
                    pass
        except OSError:
            pass

    def write(self, event: str, **fields: Any) -> dict[str, Any]:
        now = datetime.now().astimezone()
        record = {
            "ts": now.isoformat(timespec="seconds"),
            "ts_utc": now.astimezone(timezone.utc).isoformat(timespec="seconds"),
            "event": str(event),
            **redact_mapping(fields),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
        with self._lock:
            self._rotate_if_needed()
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(line + "\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
        return record
