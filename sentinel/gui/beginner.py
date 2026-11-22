"""Beginner mode: exactly three primary actions plus per-item help."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from sentinel.gui.theme import ACCENT, BG, BORDER, DANGER, MUTED, PANEL, PANEL_2, PASS, TEXT, WARN, status_color
from sentinel.models import AuditReport, CheckResult


class BeginnerFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, controller: Any) -> None:
        super().__init__(parent)
        self.controller = controller
        self._report: AuditReport | None = None
        self._busy = False
        self._safe_running = False
        self._build()

    def _build(self) -> None:
        ttk.Label(
            self,
            text="三步走：先检测，再对齐，最后才安全启动。",
            style="H2.TLabel",
        ).pack(anchor="w")
        ttk.Label(
            self,
            text="不要一上来就点“安全启动”。先看清审计结果，再决定是否对齐。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 12))

        actions = ttk.Frame(self)
        actions.pack(fill="x", pady=(0, 14))
        self.detect_btn = ttk.Button(
            actions, text="1  检测", style="Big.TButton", command=self.controller.on_detect
        )
        self.detect_btn.pack(side="left", padx=(0, 10))
        self.align_btn = ttk.Button(
            actions, text="2  一键对齐", style="Big.TButton", command=self.controller.on_align
        )
        self.align_btn.pack(side="left", padx=(0, 10))
        self.safe_btn = ttk.Button(
            actions,
            text="3  安全启动",
            style="Accent.TButton",
            command=self.controller.on_safe_start_or_stop,
            state="disabled",
        )
        self.safe_btn.pack(side="left")
        self.safe_btn.configure(width=20)

        card = ttk.Frame(self, style="Panel.TFrame", padding=16)
        card.pack(fill="x", pady=(0, 14))
        left = ttk.Frame(card, style="Panel.TFrame")
        left.pack(side="left", fill="y")
        ttk.Label(left, text="当前风险分", style="PanelMuted.TLabel").pack(anchor="w")
        self.risk_label = ttk.Label(left, text="—", style="Risk.TLabel")
        self.risk_label.pack(anchor="w")
        right = ttk.Frame(card, style="Panel.TFrame")
        right.pack(side="left", fill="both", expand=True, padx=(28, 0))
        self.verdict_label = ttk.Label(right, text="尚未检测", style="PanelH2.TLabel")
        self.verdict_label.pack(anchor="w")
        self.reason_label = ttk.Label(
            right,
            text="点击“检测”后，这里会显示安全启动是否被允许，以及原因。",
            style="PanelMuted.TLabel",
            wraplength=760,
            justify="left",
        )
        self.reason_label.pack(anchor="w", pady=(4, 0))
        self.counts_label = ttk.Label(right, text="", style="PanelMuted.TLabel")
        self.counts_label.pack(anchor="w", pady=(8, 0))

        header = ttk.Frame(self)
        header.pack(fill="x")
        ttk.Label(header, text="本次发现的问题", style="H2.TLabel").pack(side="left")
        link = tk.Label(
            header,
            text="新手教程（没操作过时先看这里）",
            background=BG,
            foreground=ACCENT,
            cursor="hand2",
            font=("Microsoft YaHei UI", 9, "underline"),
        )
        link.pack(side="right")
        link.bind("<Button-1>", lambda _event: self.controller.open_tutorial())

        self.scroll_frame = ttk.Frame(self)
        self.scroll_frame.pack(fill="both", expand=True, pady=(6, 0))
        self.canvas = tk.Canvas(
            self.scroll_frame,
            background=BG,
            highlightthickness=0,
            borderwidth=0,
        )
        scrollbar = ttk.Scrollbar(self.scroll_frame, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.inner.bind(
            "<Configure>",
            lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda event: self.canvas.itemconfigure(self._window, width=event.width),
        )
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self._empty_label = ttk.Label(
            self.inner,
            text="还没有检测结果。点击“检测”开始；这一步不会修改任何系统设置。",
            style="Muted.TLabel",
        )
        self._empty_label.pack(anchor="w", pady=18)

    def _on_mousewheel(self, event: tk.Event) -> None:
        try:
            if self.canvas.winfo_containing(event.x_root, event.y_root) is not None:
                self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except (tk.TclError, AttributeError):
            pass

    def set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        self.detect_btn.configure(state=state)
        self.align_btn.configure(state=state)
        self._update_safe_button()
        if busy and label:
            self.verdict_label.configure(text=label)

    def update_report(self, report: AuditReport | None, safe_running: bool = False) -> None:
        self._report = report
        self._safe_running = safe_running
        if report is None:
            self.risk_label.configure(text="—", style="Risk.TLabel")
            self.verdict_label.configure(text="尚未检测")
            self.reason_label.configure(text="点击“检测”后，这里会显示安全启动是否被允许，以及原因。")
            self.counts_label.configure(text="")
            self._rebuild_rows([])
            self._update_safe_button()
            return
        risk = report.risk_score
        style = "Risk.TLabel" if risk < 35 else ("RiskWarn.TLabel" if risk < 60 else "RiskBad.TLabel")
        self.risk_label.configure(text=str(risk), style=style)
        if report.gate.allowed:
            self.verdict_label.configure(text="审计通过，可以安全启动")
            self.reason_label.configure(text="门禁满足：风险分低于 60，没有阻断级失败，且已配置客户端与 Kill-Switch。")
        else:
            self.verdict_label.configure(text="审计未通过，安全启动已禁用")
            reasons = report.gate.reasons[:4]
            extra = "" if len(report.gate.reasons) <= 4 else f"\n…另有 {len(report.gate.reasons) - 4} 条原因，请在专家模式查看。"
            self.reason_label.configure(text="\n".join(f"• {reason}" for reason in reasons) + extra)
        counts = report.status_counts
        self.counts_label.configure(
            text=f"通过 {counts.get('pass', 0)} · 警告 {counts.get('warn', 0)} · "
            f"失败 {counts.get('fail', 0)} · 异常 {counts.get('error', 0)}"
        )
        self._rebuild_rows(report.checks)
        self._update_safe_button()

    def _update_safe_button(self) -> None:
        if self._safe_running:
            self.safe_btn.configure(text="停止安全会话", state="normal" if not self._busy else "disabled")
            return
        enabled = bool(
            self._report is not None
            and self._report.gate.allowed
            and not self._busy
            and not self.controller.killswitch_latched()
        )
        self.safe_btn.configure(text="3  安全启动", state=("normal" if enabled else "disabled"))

    def _rebuild_rows(self, checks: list[CheckResult]) -> None:
        for child in self.inner.winfo_children():
            child.destroy()
        if not checks:
            ttk.Label(
                self.inner,
                text="没有可显示的项目。",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=18)
            return
        # Show failures first, then warnings, then passes, preserving ID order
        # within each status.
        order = {"fail": 0, "error": 0, "warn": 1, "pass": 2}
        sorted_checks = sorted(checks, key=lambda c: (order.get(c.status.value, 3), c.id))
        for check in sorted_checks:
            row = ttk.Frame(self.inner, style="Panel.TFrame", padding=(10, 8))
            row.pack(fill="x", pady=2)
            color = status_color(check.status.value)
            tk.Label(
                row,
                text=check.id,
                width=5,
                anchor="w",
                background=PANEL,
                foreground=MUTED,
                font=("Consolas", 9, "bold"),
            ).pack(side="left")
            tk.Label(
                row,
                text=check.status.label_zh,
                width=7,
                anchor="w",
                background=PANEL,
                foreground=color,
                font=("Microsoft YaHei UI", 9, "bold"),
            ).pack(side="left")
            text = f"{check.title} — {check.summary}"
            tk.Label(
                row,
                text=text,
                anchor="w",
                justify="left",
                background=PANEL,
                foreground=TEXT,
                font=("Microsoft YaHei UI", 9),
            ).pack(side="left", fill="x", expand=True, padx=(6, 8))
            ttk.Button(
                row,
                text="?",
                width=3,
                command=lambda c=check: self.controller.show_detail(c),
            ).pack(side="right")
