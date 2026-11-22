"""Run app-service calls off the Tk thread and deliver results on the Tk thread."""

from __future__ import annotations

import queue
import threading
import traceback
import tkinter as tk
from typing import Any, Callable


class AsyncRunner:
    def __init__(self, root: tk.Misc) -> None:
        self.root = root
        self._queue: queue.Queue[tuple[str, Any, Any, Any]] = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        self._poll_scheduled = False

    def submit(
        self,
        work: Callable[[], Any],
        *,
        on_success: Callable[[Any], None] | None = None,
        on_error: Callable[[BaseException, str], None] | None = None,
        label: str = "",
    ) -> None:
        with self._lock:
            self._pending += 1

        def runner() -> None:
            try:
                result = work()
                self._queue.put(("ok", result, on_success, label))
            except BaseException as exc:  # keep the Tk loop alive
                detail = traceback.format_exc()
                self._queue.put(("error", exc, (on_error, detail), label))

        thread = threading.Thread(target=runner, name=f"sentinel-task-{label or 'work'}", daemon=True)
        thread.start()
        self._schedule_poll()

    def _schedule_poll(self) -> None:
        if not self._poll_scheduled:
            self._poll_scheduled = True
            self.root.after(80, self._poll)

    def _poll(self) -> None:
        self._poll_scheduled = False
        while True:
            try:
                kind, value, callback, label = self._queue.get_nowait()
            except queue.Empty:
                break
            with self._lock:
                self._pending = max(0, self._pending - 1)
            if kind == "ok":
                if callback:
                    callback(value)
            else:
                if callback:
                    error_callback, detail = callback
                    if error_callback:
                        error_callback(value, detail)
        if self._pending > 0:
            self._schedule_poll()

    @property
    def busy(self) -> bool:
        return self._pending > 0
