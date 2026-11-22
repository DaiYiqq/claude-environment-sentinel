"""Global hotkey backends.

Windows uses RegisterHotKey in a dedicated message-loop thread.  Other
platforms use optional pynput if installed.  Failure is explicit: the GUI says
the emergency hotkey is unavailable instead of pretending it works.
"""

from __future__ import annotations

import ctypes
import os
import threading
from typing import Callable

IS_WINDOWS = os.name == "nt"
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000


def _windows_key_code(key: str) -> int | None:
    key = key.upper().strip()
    if len(key) == 1 and ("A" <= key <= "Z" or "0" <= key <= "9"):
        return ord(key)
    if key.startswith("F") and key[1:].isdigit():
        number = int(key[1:])
        if 1 <= number <= 24:
            return 0x70 + number - 1
    special = {
        "SPACE": 0x20,
        "TAB": 0x09,
        "ESC": 0x1B,
        "ESCAPE": 0x1B,
        "ENTER": 0x0D,
        "HOME": 0x24,
        "END": 0x23,
        "INSERT": 0x2D,
        "DELETE": 0x2E,
        "UP": 0x26,
        "DOWN": 0x28,
        "LEFT": 0x25,
        "RIGHT": 0x27,
    }
    return special.get(key)


def _parse_combination(combination: str) -> tuple[int, int] | None:
    parts = [p.strip().lower() for p in combination.replace(" ", "").split("+") if p.strip()]
    modifiers = MOD_NOREPEAT
    key: str | None = None
    for part in parts:
        if part in {"ctrl", "control"}:
            modifiers |= MOD_CONTROL
        elif part == "shift":
            modifiers |= MOD_SHIFT
        elif part == "alt":
            modifiers |= MOD_ALT
        elif part in {"win", "windows", "meta"}:
            modifiers |= MOD_WIN
        else:
            key = part
    if key is None:
        return None
    code = _windows_key_code(key)
    if code is None:
        return None
    return modifiers, code


class GlobalHotkey:
    def __init__(self, combination: str, callback: Callable[[], None]) -> None:
        self.combination = combination
        self.callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._listener = None
        self._error: str | None = None
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._registration_ok = False

    def available(self) -> tuple[bool, str]:
        if IS_WINDOWS:
            parsed = _parse_combination(self.combination)
            if parsed is None:
                return False, f"无法解析快捷键 {self.combination!r}"
            return True, ""
        try:
            import pynput  # type: ignore  # noqa: F401
        except ImportError:
            return False, "非 Windows 平台需要可选依赖 pynput 才能注册全局热键。"
        return True, ""

    def start(self) -> tuple[bool, str]:
        ok, reason = self.available()
        if not ok:
            self._error = reason
            return False, reason
        if IS_WINDOWS:
            parsed = _parse_combination(self.combination)
            if parsed is None:
                return False, f"无法解析快捷键 {self.combination!r}"
            modifiers, key_code = parsed
            self._thread = threading.Thread(
                target=self._windows_loop,
                args=(modifiers, key_code),
                name="sentinel-hotkey",
                daemon=True,
            )
            self._thread.start()
            self._ready.wait(timeout=2.0)
            if not self._registration_ok:
                return False, self._error or "RegisterHotKey 失败；快捷键可能已被其他程序占用。"
            return True, f"全局热键 {self.combination} 已注册。"
        try:
            from pynput import keyboard  # type: ignore

            mapping = {self._pynput_combination(self.combination): self._invoke}
            self._listener = keyboard.GlobalHotKeys(mapping)
            self._listener.start()
            return True, f"全局热键 {self.combination} 已注册。"
        except Exception as exc:
            self._error = str(exc)
            return False, f"全局热键注册失败: {exc}"

    def _pynput_combination(self, combination: str) -> str:
        parts = [p.strip().lower() for p in combination.split("+") if p.strip()]
        mapping = {"ctrl": "<ctrl>", "control": "<ctrl>", "shift": "<shift>", "alt": "<alt>", "win": "<cmd>"}
        return "+".join(mapping.get(p, p) for p in parts)

    def _invoke(self) -> None:
        try:
            self.callback()
        except Exception:
            pass

    def _windows_loop(self, modifiers: int, key_code: int) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        registered = bool(user32.RegisterHotKey(None, 1, modifiers, key_code))
        self._registration_ok = registered
        if not registered:
            self._error = "RegisterHotKey 失败；快捷键可能已被其他程序占用。"
            self._ready.set()
            return
        self._ready.set()
        try:
            from ctypes import wintypes

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY:
                    self._invoke()
        finally:
            user32.UnregisterHotKey(None, 1)

    def stop(self) -> None:
        with self._lock:
            if IS_WINDOWS:
                user32 = ctypes.windll.user32
                kernel32 = ctypes.windll.kernel32
                if self._thread_id:
                    user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
                if self._thread and self._thread.is_alive():
                    self._thread.join(timeout=2)
                self._thread = None
                self._thread_id = None
            else:
                try:
                    if self._listener is not None:
                        self._listener.stop()
                finally:
                    self._listener = None
