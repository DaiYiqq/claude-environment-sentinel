"""Expert mode: full audit table, snapshots, profiles, kill switch and settings."""

from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from sentinel.gui.theme import (
    ACCENT,
    BG,
    BORDER,
    DANGER,
    MUTED,
    PANEL,
    PANEL_2,
    PASS,
    PURPLE,
    TEXT,
    WARN,
    status_color,
)
from sentinel.gui.tutorial_view import MarkdownView
from sentinel.models import AuditReport, CheckResult


class ExpertFrame(ttk.Frame):
    def __init__(self, parent: tk.Misc, controller: Any) -> None:
        super().__init__(parent)
        self.controller = controller
        self._report: AuditReport | None = None
        self._build()

    def _build(self) -> None:
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.audit_tab = ttk.Frame(self.notebook, padding=12)
        self.snapshots_tab = ttk.Frame(self.notebook, padding=12)
        self.profiles_tab = ttk.Frame(self.notebook, padding=12)
        self.kill_tab = ttk.Frame(self.notebook, padding=12)
        self.settings_tab = ttk.Frame(self.notebook, padding=12)
        self.console_tab = ttk.Frame(self.notebook, padding=12)
        self.tutorial_tab = ttk.Frame(self.notebook, padding=12)
        self.guide_tab = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(self.audit_tab, text="审计")
        self.notebook.add(self.snapshots_tab, text="快照")
        self.notebook.add(self.profiles_tab, text="环境配置包")
        self.notebook.add(self.kill_tab, text="Kill-Switch")
        self.notebook.add(self.console_tab, text="控制台")
        self.notebook.add(self.settings_tab, text="设置")
        self.notebook.add(self.tutorial_tab, text="新手教程")
        self.notebook.add(self.guide_tab, text="风险指南")
        self._build_audit_tab()
        self._build_snapshots_tab()
        self._build_profiles_tab()
        self._build_killswitch_tab()
        self._build_console_tab()
        self._build_settings_tab()
        self._build_docs_tabs()

    # --- audit -----------------------------------------------------------
    def _build_audit_tab(self) -> None:
        bar = ttk.Frame(self.audit_tab)
        bar.pack(fill="x", pady=(0, 8))
        self.audit_btn = ttk.Button(bar, text="重新检测", style="Accent.TButton", command=self.controller.on_detect)
        self.audit_btn.pack(side="left")
        ttk.Button(bar, text="导出 JSON", command=self.controller.on_export_report).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="一键对齐", command=self.controller.on_align).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="还原最近快照", command=self.controller.on_restore_latest).pack(side="left", padx=(8, 0))
        self.risk_text = ttk.Label(bar, text="尚未检测", style="Muted.TLabel")
        self.risk_text.pack(side="right")

        paned = ttk.PanedWindow(self.audit_tab, orient="vertical")
        paned.pack(fill="both", expand=True)
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)
        columns = ("id", "status", "weight", "blocking", "summary")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "id": ("ID", 55, "center"),
            "status": ("状态", 75, "center"),
            "weight": ("权重", 55, "center"),
            "blocking": ("阻断", 55, "center"),
            "summary": ("项目与摘要", 700, "w"),
        }
        for key, (label, width, anchor) in headings.items():
            self.tree.heading(key, text=label)
            self.tree.column(key, width=width, anchor=anchor)
        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.tree.tag_configure("pass", foreground=PASS)
        self.tree.tag_configure("warn", foreground=WARN)
        self.tree.tag_configure("fail", foreground=DANGER)
        self.tree.tag_configure("error", foreground=PURPLE)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self._open_selected())

        detail = ttk.Frame(paned, style="Panel.TFrame", padding=12)
        paned.add(detail, weight=2)
        self.detail_title = ttk.Label(detail, text="选择一项查看证据", style="PanelH2.TLabel")
        self.detail_title.pack(anchor="w")
        self.detail_body = tk.Text(
            detail,
            height=8,
            wrap="word",
            background=PANEL,
            foreground=TEXT,
            borderwidth=0,
            padx=8,
            pady=6,
            font=("Microsoft YaHei UI", 9),
        )
        self.detail_body.pack(fill="both", expand=True, pady=(6, 8))
        self.detail_body.configure(state="disabled")
        buttons = ttk.Frame(detail, style="Panel.TFrame")
        buttons.pack(fill="x")
        self.detail_btn = ttk.Button(
            buttons, text="查看完整证据/解释", command=self._open_selected, state="disabled"
        )
        self.detail_btn.pack(side="left")
        self.fix_btn = ttk.Button(
            buttons, text="修复此项", style="Accent.TButton", command=self._fix_selected, state="disabled"
        )
        self.fix_btn.pack(side="left", padx=(8, 0))

    def _on_select(self, _event: tk.Event | None = None) -> None:
        selection = self.tree.selection()
        if not selection or self._report is None:
            return
        check_id = selection[0]
        check = next((c for c in self._report.checks if c.id == check_id), None)
        if check is None:
            return
        self.detail_title.configure(text=f"{check.id} · {check.title} · {check.status.label_zh}")
        lines = [check.summary, "", *[f"• {line}" for line in check.evidence]]
        self.detail_body.configure(state="normal")
        self.detail_body.delete("1.0", "end")
        self.detail_body.insert("1.0", "\n".join(lines))
        self.detail_body.configure(state="disabled")
        self.detail_btn.configure(state="normal")
        self.fix_btn.configure(state=("normal" if check.fixable else "disabled"))

    def _selected_check(self) -> CheckResult | None:
        selection = self.tree.selection()
        if not selection or self._report is None:
            return None
        return next((c for c in self._report.checks if c.id == selection[0]), None)

    def _open_selected(self) -> None:
        check = self._selected_check()
        if check is not None:
            self.controller.show_detail(check, expert=True)

    def _fix_selected(self) -> None:
        check = self._selected_check()
        if check is not None:
            self.controller.fix_check(check)

    # --- snapshots -------------------------------------------------------
    def _build_snapshots_tab(self) -> None:
        ttk.Label(self.snapshots_tab, text="不可变快照", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            self.snapshots_tab,
            text="文件写入 backups/，带校验和且不会被覆盖。删除操作需要你明确确认。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 8))
        columns = ("id", "created", "label", "items")
        self.snapshot_tree = ttk.Treeview(self.snapshots_tab, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (
            ("id", "snapshot_id", 230),
            ("created", "创建时间", 170),
            ("label", "标签", 260),
            ("items", "修改项", 180),
        ):
            self.snapshot_tree.heading(key, text=label)
            self.snapshot_tree.column(key, width=width, anchor="w")
        self.snapshot_tree.pack(fill="both", expand=True)
        bar = ttk.Frame(self.snapshots_tab)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="刷新", command=self.controller.on_refresh_snapshots).pack(side="left")
        ttk.Button(bar, text="查看内容", command=self._view_snapshot).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="还原选中快照", command=self._restore_snapshot).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="删除选中快照", style="Danger.TButton", command=self._delete_snapshot).pack(side="right")

    def _snapshot_id(self) -> str | None:
        selection = self.snapshot_tree.selection()
        return str(selection[0]) if selection else None

    def _view_snapshot(self) -> None:
        snapshot_id = self._snapshot_id()
        if snapshot_id:
            self.controller.show_snapshot_detail(snapshot_id)

    def _restore_snapshot(self) -> None:
        snapshot_id = self._snapshot_id()
        if snapshot_id:
            self.controller.on_restore_snapshot(snapshot_id)

    def _delete_snapshot(self) -> None:
        snapshot_id = self._snapshot_id()
        if snapshot_id:
            self.controller.on_delete_snapshot(snapshot_id)

    # --- profiles --------------------------------------------------------
    def _build_profiles_tab(self) -> None:
        banner = ttk.Frame(self.profiles_tab, style="Panel.TFrame", padding=10)
        banner.pack(fill="x", pady=(0, 8))
        ttk.Label(
            banner,
            text=(
                "只管理环境配置，不管理身份材料。\n"
                "配置包不保存登录凭证、Cookie、Token、会话文件或账号身份；切换账号需你在 Claude 内自行登录切换。"
            ),
            style="Panel.TLabel",
            justify="left",
        ).pack(anchor="w")
        columns = ("name", "country", "timezone", "current")
        self.profile_tree = ttk.Treeview(self.profiles_tab, columns=columns, show="headings", selectmode="browse")
        for key, label, width in (
            ("name", "名称", 260),
            ("country", "期望出口", 100),
            ("timezone", "时区", 180),
            ("current", "当前", 80),
        ):
            self.profile_tree.heading(key, text=label)
            self.profile_tree.column(key, width=width, anchor="w")
        self.profile_tree.pack(fill="both", expand=True)
        bar = ttk.Frame(self.profiles_tab)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="新建配置包", style="Accent.TButton", command=self.controller.on_create_profile).pack(side="left")
        ttk.Button(bar, text="刷新", command=self.controller.on_refresh_profiles).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="切换并可选安全启动", command=self._activate_profile).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="删除", style="Danger.TButton", command=self._delete_profile).pack(side="right")

    def _profile_id(self) -> str | None:
        selection = self.profile_tree.selection()
        return str(selection[0]) if selection else None

    def _activate_profile(self) -> None:
        profile_id = self._profile_id()
        if profile_id:
            self.controller.on_activate_profile(profile_id)

    def _delete_profile(self) -> None:
        profile_id = self._profile_id()
        if profile_id:
            self.controller.on_delete_profile(profile_id)

    # --- kill switch -----------------------------------------------------
    def _build_killswitch_tab(self) -> None:
        ttk.Label(self.kill_tab, text="Kill-Switch", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            self.kill_tab,
            text=(
                "安全启动后每 5 秒检查出口国家、出口 IP、代理内核和 TUN。"
                "触发后会终止 Claude 进程树并创建出站阻断规则，只有手动解除才会恢复。"
            ),
            style="Muted.TLabel",
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(2, 10))
        self.kill_latched = ttk.Label(self.kill_tab, text="未锁定", style="H2.TLabel")
        self.kill_latched.pack(anchor="w")
        self.kill_status = ttk.Label(self.kill_tab, text="未布防", style="Muted.TLabel", justify="left")
        self.kill_status.pack(anchor="w", pady=(2, 8))
        bar = ttk.Frame(self.kill_tab)
        bar.pack(fill="x")
        ttk.Button(bar, text="立即急停（受管会话）", style="Danger.TButton", command=self.controller.on_emergency_stop).pack(side="left")
        ttk.Button(bar, text="解除锁定并删除规则", command=self.controller.on_release_killswitch).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="刷新", command=self.controller.on_refresh_killswitch).pack(side="left", padx=(8, 0))
        self.hotkey_status = ttk.Label(self.kill_tab, text="", style="Muted.TLabel")
        self.hotkey_status.pack(anchor="w", pady=(10, 4))
        ttk.Label(self.kill_tab, text="最近 Kill-Switch 日志", style="H2.TLabel").pack(anchor="w", pady=(8, 4))
        self.kill_log = tk.Text(
            self.kill_tab,
            height=14,
            wrap="word",
            background=PANEL,
            foreground=TEXT,
            borderwidth=0,
            font=("Consolas", 9),
        )
        self.kill_log.pack(fill="both", expand=True)
        self.kill_log.configure(state="disabled")

    def update_killswitch(self, status: dict[str, Any], hotkey: tuple[bool, str], log_tail: str = "") -> None:
        latched = bool(status.get("latched"))
        self.kill_latched.configure(
            text=("已锁定：安全启动被禁止，直到手动解除" if latched else "未锁定"),
            style=("RiskBad.TLabel" if latched else "H2.TLabel"),
        )
        armed = bool(status.get("armed"))
        lines = [
            f"armed={armed}  pid={status.get('pid')}  session={status.get('session_id')}",
            f"expected_country={status.get('expected_country')}  expected_ip={status.get('expected_ip')}",
            f"proxy_core_expected={status.get('expected_proxy_core')}  tun_expected={status.get('expected_tun')}",
            f"rules={status.get('rules')}",
        ]
        if status.get("last_trigger"):
            trigger = status["last_trigger"]
            lines.append(
                f"last_trigger: {trigger.get('triggered_at')} {trigger.get('check_id')} "
                f"{trigger.get('reason')}"
            )
        self.kill_status.configure(text="\n".join(lines))
        ok, reason = hotkey
        self.hotkey_status.configure(
            text=(f"全局热键已注册：{self.controller.settings.hotkey}" if ok else f"全局热键不可用：{reason}")
        )
        self.kill_log.configure(state="normal")
        self.kill_log.delete("1.0", "end")
        self.kill_log.insert("1.0", log_tail or "（暂无日志）")
        self.kill_log.configure(state="disabled")

    # --- console ---------------------------------------------------------
    def _build_console_tab(self) -> None:
        ttk.Label(self.console_tab, text="控制台", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            self.console_tab,
            text="详细但克制：摘要、最近审计历史、门禁与建议。证据级细节仍在审计页。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 8))
        self.console_status = ttk.Label(self.console_tab, text="等待检测", style="PanelH2.TLabel")
        self.console_status.pack(anchor="w", pady=(0, 8))
        history_frame = ttk.Frame(self.console_tab)
        history_frame.pack(fill="both", expand=True)
        ttk.Label(history_frame, text="最近审计历史", style="H2.TLabel").pack(anchor="w", pady=(0, 4))
        columns = ("time", "risk", "gate", "country", "timezone")
        self.console_history = ttk.Treeview(history_frame, columns=columns, show="headings", height=8)
        for key, label, width in (
            ("time", "时间", 180),
            ("risk", "风险", 60),
            ("gate", "门禁", 80),
            ("country", "出口", 80),
            ("timezone", "出口时区", 170),
        ):
            self.console_history.heading(key, text=label)
            self.console_history.column(key, width=width, anchor="w")
        self.console_history.pack(fill="both", expand=True)
        rec_frame = ttk.Frame(self.console_tab)
        rec_frame.pack(fill="x", pady=(10, 0))
        ttk.Label(rec_frame, text="建议下一步", style="H2.TLabel").pack(anchor="w")
        self.console_recommendations = tk.Text(
            rec_frame,
            height=8,
            wrap="word",
            background=PANEL,
            foreground=TEXT,
            borderwidth=0,
            padx=10,
            pady=8,
            font=("Microsoft YaHei UI", 9),
        )
        self.console_recommendations.pack(fill="x", pady=(4, 0))
        self.console_recommendations.configure(state="disabled")
        bar = ttk.Frame(self.console_tab)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="刷新控制台", command=self.controller.on_refresh_console).pack(side="left")
        ttk.Button(bar, text="复制摘要", command=self.controller.on_copy_summary).pack(side="left", padx=(8, 0))

    def update_console(
        self,
        status: dict[str, Any],
        history: list[dict[str, Any]],
        recommendations: list[dict[str, Any]],
        hotkey: tuple[bool, str],
    ) -> None:
        latched = bool(status.get("latched"))
        armed = bool(status.get("armed"))
        ok, reason = hotkey
        self.console_status.configure(
            text=(
                f"{self.controller.platform_label()} · "
                f"{'管理员' if status.get('admin') else '普通权限'} · "
                f"Kill-Switch {'已锁定' if latched else ('已布防' if armed else '未布防')} · "
                f"热键 {'可用' if ok else '不可用'}"
            )
        )
        self.console_history.delete(*self.console_history.get_children())
        for index, item in enumerate(reversed(history[-20:])):
            self.console_history.insert(
                "",
                "end",
                iid=f"history-{index}",
                values=(
                    item.get("ts", ""),
                    item.get("risk_score", ""),
                    "允许" if item.get("gate_allowed") else "禁止",
                    item.get("country") or "-",
                    item.get("egress_timezone") or item.get("system_timezone") or "-",
                ),
            )
        self.console_recommendations.configure(state="normal")
        self.console_recommendations.delete("1.0", "end")
        if recommendations:
            for index, item in enumerate(recommendations, start=1):
                self.console_recommendations.insert(
                    "end",
                    f"{index}. [{item.get('id')}] {item.get('action')}\n",
                )
        else:
            self.console_recommendations.insert("end", "当前没有需要优先处理的建议。\n")
        if not ok and reason:
            self.console_recommendations.insert("end", f"\n热键提示: {reason}\n")
        self.console_recommendations.configure(state="disabled")

    # --- settings --------------------------------------------------------
    def _build_settings_tab(self) -> None:
        ttk.Label(self.settings_tab, text="设置（不含任何凭证）", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            self.settings_tab,
            text="这里不保存代理密码、Cookie、Token 或 Claude 登录信息。代理软件需由你自行配置。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 10))
        form = ttk.Frame(self.settings_tab)
        form.pack(fill="x")
        ttk.Label(form, text="Claude 启动命令（留空则自动探测 CLI/桌面客户端）").grid(row=0, column=0, sticky="w", pady=4)
        self.claude_cmd_var = tk.StringVar()
        ttk.Entry(form, textvariable=self.claude_cmd_var, width=90).grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(form, text="浏览…", command=self._browse_claude).grid(row=1, column=1, padx=(8, 0))
        self.network_var = tk.BooleanVar(value=True)
        self.require_tun_var = tk.BooleanVar(value=False)
        self.country_lock_var = tk.BooleanVar(value=False)
        self.expected_country_var = tk.StringVar(value="")
        self.hotkey_var = tk.StringVar(value="ctrl+shift+k")
        self.poll_var = tk.StringVar(value="5")
        ttk.Checkbutton(form, text="启用网络探测（关闭后 A5/A8/A9/A13/A19 无法完整判断）", variable=self.network_var).grid(row=2, column=0, sticky="w", pady=3)
        ttk.Checkbutton(form, text="要求 TUN 模式（缺失时 A12 会阻断安全启动）", variable=self.require_tun_var).grid(row=3, column=0, sticky="w", pady=3)
        lock_row = ttk.Frame(form)
        lock_row.grid(row=4, column=0, sticky="w", pady=3)
        ttk.Checkbutton(lock_row, text="锁定出口国家（不一致时阻断安全启动）", variable=self.country_lock_var).pack(side="left")
        ttk.Label(lock_row, text="  国家代码：").pack(side="left")
        ttk.Entry(lock_row, textvariable=self.expected_country_var, width=8).pack(side="left")
        ttk.Label(lock_row, text="例如 US / JP / CN", style="Muted.TLabel").pack(side="left", padx=(6, 0))
        row = ttk.Frame(form)
        row.grid(row=5, column=0, sticky="w", pady=3)
        ttk.Label(row, text="全局急停快捷键：").pack(side="left")
        ttk.Entry(row, textvariable=self.hotkey_var, width=22).pack(side="left")
        ttk.Label(row, text="   轮询秒数：").pack(side="left")
        ttk.Entry(row, textvariable=self.poll_var, width=8).pack(side="left")
        form.columnconfigure(0, weight=1)
        ttk.Button(self.settings_tab, text="保存设置", style="Accent.TButton", command=self._save_settings).pack(anchor="w", pady=(12, 0))
        self.settings_note = ttk.Label(self.settings_tab, text="", style="Muted.TLabel")
        self.settings_note.pack(anchor="w", pady=(8, 0))

    def _browse_claude(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="选择 Claude 启动程序",
            filetypes=[("Executable", "*.exe *.cmd *.bat"), ("All files", "*.*")],
        )
        if path:
            self.claude_cmd_var.set(path)

    def _save_settings(self) -> None:
        try:
            poll = float(self.poll_var.get())
        except ValueError:
            messagebox.showwarning("设置无效", "轮询秒数必须是数字。", parent=self)
            return
        self.controller.on_save_settings(
            {
                "claude_command": self.claude_cmd_var.get().strip(),
                "network_enabled": bool(self.network_var.get()),
                "require_tun": bool(self.require_tun_var.get()),
                "country_lock": bool(self.country_lock_var.get()),
                "expected_country": self.expected_country_var.get().strip().upper(),
                "hotkey": self.hotkey_var.get().strip() or "ctrl+shift+k",
                "poll_seconds": poll,
            }
        )
        self.settings_note.configure(text="已保存。下一次检测/安全启动会使用新设置。")

    def refresh_settings(self, settings: Any) -> None:
        self.claude_cmd_var.set(settings.claude_command)
        self.network_var.set(settings.network_enabled)
        self.require_tun_var.set(settings.require_tun)
        self.country_lock_var.set(settings.country_lock)
        self.expected_country_var.set(settings.expected_country)
        self.hotkey_var.set(settings.hotkey)
        self.poll_var.set(str(settings.poll_seconds))

    # --- docs ------------------------------------------------------------
    def _build_docs_tabs(self) -> None:
        self.tutorial_view = MarkdownView(self.tutorial_tab, font_family=self.controller.font_family)
        self.tutorial_view.pack(fill="both", expand=True)
        self.guide_view = MarkdownView(self.guide_tab, font_family=self.controller.font_family)
        self.guide_view.pack(fill="both", expand=True)
        self.tutorial_view.load_file(self.controller.paths.tutorials / "quick-start.md")
        self.guide_view.load_file(self.controller.paths.docs / "anti-ban-guide.md")

    def reload_docs(self) -> None:
        self.tutorial_view.load_file(self.controller.paths.tutorials / "quick-start.md")
        self.guide_view.load_file(self.controller.paths.docs / "anti-ban-guide.md")

    # --- report / refresh ------------------------------------------------
    def set_report(self, report: AuditReport | None) -> None:
        self._report = report
        self.tree.delete(*self.tree.get_children())
        if report is None:
            self.risk_text.configure(text="尚未检测")
            return
        self.risk_text.configure(
            text=f"风险 {report.risk_score}/100 · {'允许安全启动' if report.gate.allowed else '安全启动被禁用'}"
        )
        for check in report.checks:
            self.tree.insert(
                "",
                "end",
                iid=check.id,
                values=(
                    check.id,
                    check.status.label_zh,
                    check.weight,
                    "是" if check.blocking else "否",
                    f"{check.title} — {check.summary}",
                ),
                tags=(check.status.value,),
            )
        if report.checks:
            first = report.checks[0].id
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._on_select()

    def update_snapshots(self, snapshots: list[Any]) -> None:
        self.snapshot_tree.delete(*self.snapshot_tree.get_children())
        for snapshot in snapshots:
            self.snapshot_tree.insert(
                "",
                "end",
                iid=snapshot.snapshot_id,
                values=(
                    snapshot.snapshot_id,
                    snapshot.created_at,
                    snapshot.label,
                    ", ".join(snapshot.modified_items),
                ),
            )

    def update_profiles(self, profiles: list[dict[str, Any]], current_id: str | None) -> None:
        self.profile_tree.delete(*self.profile_tree.get_children())
        for profile in profiles:
            env = profile.get("environment") or {}
            self.profile_tree.insert(
                "",
                "end",
                iid=str(profile.get("profile_id")),
                values=(
                    profile.get("name"),
                    env.get("expected_exit_country") or "-",
                    (env.get("system_timezone") or {}).get("iana") or "-",
                    "当前" if profile.get("profile_id") == current_id else "",
                ),
            )

    def show_snapshot_json(self, data: dict[str, Any]) -> None:
        win = tk.Toplevel(self)
        win.title("快照内容")
        win.geometry("820x680")
        win.configure(background=BG)
        text = tk.Text(
            win,
            wrap="word",
            background=PANEL,
            foreground=TEXT,
            font=("Consolas", 9),
            padx=12,
            pady=10,
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        text.configure(state="disabled")
