"""Audit-item detail popup used by both beginner and expert modes."""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Callable

from sentinel.gui.theme import BG, MUTED, PANEL, PANEL_2, TEXT, status_color
from sentinel.models import CheckResult


def _readonly_text(parent: tk.Misc, content: str, height: int = 10, font: tuple = ("Consolas", 9)) -> tk.Text:
    frame = ttk.Frame(parent)
    text = tk.Text(
        frame,
        height=height,
        wrap="word",
        background=PANEL_2,
        foreground=TEXT,
        insertbackground=TEXT,
        borderwidth=0,
        padx=10,
        pady=8,
        font=font,
    )
    scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=scroll.set)
    text.insert("1.0", content)
    text.configure(state="disabled")
    text.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    return text  # type: ignore[return-value]


def show_check_detail(
    parent: tk.Misc,
    check: CheckResult,
    *,
    expert: bool = False,
    on_fix: Callable[[str], None] | None = None,
) -> None:
    win = tk.Toplevel(parent)
    win.title(f"{check.id} · {check.title}")
    win.configure(background=BG)
    win.geometry("760x640")
    win.minsize(620, 480)
    win.transient(parent)
    win.grab_set()

    outer = ttk.Frame(win, padding=18)
    outer.pack(fill="both", expand=True)

    header = ttk.Frame(outer)
    header.pack(fill="x")
    ttk.Label(header, text=f"{check.id}  {check.title}", style="H2.TLabel").pack(side="left")
    tk.Label(
        header,
        text=check.status.label_zh,
        background=BG,
        foreground=status_color(check.status.value),
        font=("Microsoft YaHei UI", 10, "bold"),
    ).pack(side="right")

    ttk.Label(outer, text=check.summary, wraplength=700, style="TLabel").pack(fill="x", pady=(10, 8))
    meta = f"权重 {check.weight} · {'阻断项' if check.blocking else '非阻断项'} · {'可对齐' if check.fixable else '仅提示/需手动处理'}"
    ttk.Label(outer, text=meta, style="Muted.TLabel").pack(fill="x")

    ttk.Label(outer, text="通俗解释", style="H2.TLabel").pack(fill="x", pady=(14, 4))
    _readonly_text(outer, check.explanation or "暂无解释。", height=6, font=("Microsoft YaHei UI", 9)).pack(fill="x")

    ttk.Label(outer, text="证据行", style="H2.TLabel").pack(fill="x", pady=(12, 4))
    evidence = "\n".join(f"• {line}" for line in check.evidence) or "（无证据行）"
    _readonly_text(outer, evidence, height=7).pack(fill="x")

    ttk.Label(outer, text="原始采样值（JSON）", style="H2.TLabel").pack(fill="x", pady=(12, 4))
    raw = json.dumps(check.raw, ensure_ascii=False, indent=2, default=str)
    _readonly_text(outer, raw, height=9).pack(fill="x")

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(12, 0))
    if expert and check.fixable and on_fix is not None:
        def do_fix() -> None:
            win.destroy()
            on_fix(check.id)

        ttk.Button(buttons, text="修复此项", style="Accent.TButton", command=do_fix).pack(side="left")
    ttk.Button(buttons, text="关闭", command=win.destroy).pack(side="right")
    win.bind("<Escape>", lambda _event: win.destroy())
