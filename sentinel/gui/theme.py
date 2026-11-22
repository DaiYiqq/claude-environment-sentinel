"""Small ttk theme for the Sentinel GUI."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

THEME_NAME = os.environ.get("SENTINEL_THEME", "dark").strip().lower()
if THEME_NAME not in {"dark", "light"}:
    THEME_NAME = "dark"

_DARK = {
    "BG": "#0f172a",
    "PANEL": "#162033",
    "PANEL_2": "#1e2b42",
    "TEXT": "#e8eef8",
    "MUTED": "#9fb0c9",
    "ACCENT": "#2dd4bf",
    "ACCENT_DARK": "#0f766e",
    "DANGER": "#f87171",
    "WARN": "#fbbf24",
    "PASS": "#4ade80",
    "PURPLE": "#c084fc",
    "BORDER": "#2b3b56",
    "CODE_BG": "#1e2b42",
    "CODE_FG": "#a5f3fc",
    "LATCH_BG": "#7f1d1d",
    "LATCH_FG": "#fee2e2",
    "LATCH_LINK": "#fecaca",
    "DISABLED": "#64748b",
}
_LIGHT = {
    "BG": "#f3f7fb",
    "PANEL": "#ffffff",
    "PANEL_2": "#eef4fa",
    "TEXT": "#172033",
    "MUTED": "#52647c",
    "ACCENT": "#0f766e",
    "ACCENT_DARK": "#0f766e",
    "DANGER": "#dc2626",
    "WARN": "#b45309",
    "PASS": "#15803d",
    "PURPLE": "#7e22ce",
    "BORDER": "#d3dfec",
    "CODE_BG": "#eef4fa",
    "CODE_FG": "#0e7490",
    "LATCH_BG": "#fee2e2",
    "LATCH_FG": "#7f1d1d",
    "LATCH_LINK": "#991b1b",
    "DISABLED": "#94a3b8",
}
globals().update(_LIGHT if THEME_NAME == "light" else _DARK)

STATUS_COLORS = {
    "pass": PASS,
    "warn": WARN,
    "fail": DANGER,
    "error": PURPLE,
}


def preferred_font(root: tk.Misc) -> str:
    families = set(tkfont.families(root))
    for candidate in ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "Segoe UI"):
        if candidate in families:
            return candidate
    return "TkDefaultFont"


def configure_style(root: tk.Misc) -> str:
    family = preferred_font(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(".", background=BG, foreground=TEXT, font=(family, 10))
    style.configure("TFrame", background=BG)
    style.configure("Panel.TFrame", background=PANEL)
    style.configure("Panel2.TFrame", background=PANEL_2)
    style.configure("TLabel", background=BG, foreground=TEXT, font=(family, 10))
    style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=(family, 9))
    style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=(family, 9))
    style.configure("Title.TLabel", background=BG, foreground=TEXT, font=(family, 20, "bold"))
    style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=(family, 10))
    style.configure("Risk.TLabel", background=PANEL, foreground=ACCENT, font=(family, 34, "bold"))
    style.configure("RiskBad.TLabel", background=PANEL, foreground=DANGER, font=(family, 34, "bold"))
    style.configure("RiskWarn.TLabel", background=PANEL, foreground=WARN, font=(family, 34, "bold"))
    style.configure("H2.TLabel", background=BG, foreground=TEXT, font=(family, 13, "bold"))
    style.configure("PanelH2.TLabel", background=PANEL, foreground=TEXT, font=(family, 13, "bold"))
    style.configure("TButton", background=PANEL_2, foreground=TEXT, borderwidth=0, padding=(10, 7), font=(family, 10))
    style.map(
        "TButton",
        background=[("active", BORDER), ("disabled", PANEL)],
        foreground=[("disabled", DISABLED)],
    )
    style.configure(
        "Accent.TButton",
        background=ACCENT_DARK,
        foreground="#ecfeff",
        borderwidth=0,
        padding=(14, 10),
        font=(family, 11, "bold"),
    )
    style.map("Accent.TButton", background=[("active", "#115e59"), ("disabled", PANEL_2)], foreground=[("disabled", DISABLED)])
    style.configure("Danger.TButton", background="#7f1d1d", foreground="#fee2e2", padding=(12, 8), font=(family, 10, "bold"))
    style.map("Danger.TButton", background=[("active", "#991b1b")])
    style.configure("Big.TButton", padding=(20, 14), font=(family, 12, "bold"))
    style.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=TEXT, borderwidth=0, padding=5)
    style.configure("TCheckbutton", background=BG, foreground=TEXT, font=(family, 10))
    style.configure("Panel.TCheckbutton", background=PANEL, foreground=TEXT, font=(family, 10))
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(14, 8), font=(family, 10))
    style.map("TNotebook.Tab", background=[("selected", PANEL_2)], foreground=[("selected", TEXT)])
    style.configure(
        "Treeview",
        background=PANEL,
        fieldbackground=PANEL,
        foreground=TEXT,
        rowheight=28,
        borderwidth=0,
        font=(family, 9),
    )
    style.configure("Treeview.Heading", background=PANEL_2, foreground=TEXT, borderwidth=0, font=(family, 9, "bold"))
    style.map("Treeview", background=[("selected", ACCENT_DARK)], foreground=[("selected", "#ecfeff")])
    style.configure("Vertical.TScrollbar", background=PANEL_2, troughcolor=BG, borderwidth=0)
    style.configure("Horizontal.TScrollbar", background=PANEL_2, troughcolor=BG, borderwidth=0)
    style.configure("TProgressbar", background=ACCENT, troughcolor=PANEL_2, borderwidth=0)
    style.configure("TSeparator", background=BORDER)
    return family


def status_color(status: str) -> str:
    return STATUS_COLORS.get(status, MUTED)
