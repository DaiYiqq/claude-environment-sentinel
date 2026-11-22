"""GUI bootstrap that selects the saved day/night theme before Tk imports.

Tk widget colors are baked at construction time.  Setting the environment
before importing ``sentinel.gui.main_window`` lets the theme palette initialize
consistently without rebuilding every widget in-process.
"""

from __future__ import annotations

import os


def run_gui() -> int:
    try:
        from sentinel.app import SentinelApp

        app = SentinelApp()
        theme = app.settings.theme if app.settings.theme in {"dark", "light"} else "dark"
        os.environ["SENTINEL_THEME"] = theme

        import tkinter as tk

        from sentinel.gui.main_window import MainWindow

        root = tk.Tk()
        MainWindow(root, app)
        root.mainloop()
        return 0
    except Exception as exc:
        try:
            from tkinter import messagebox

            messagebox.showerror("Sentinel 启动失败", f"{type(exc).__name__}: {exc}")
        except Exception:
            print(f"Sentinel 启动失败: {exc}")
        return 1
