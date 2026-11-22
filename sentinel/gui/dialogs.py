"""Modal dialogs for alignment, confirmations and profile creation."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from sentinel.align.engine import AlignmentRequest
from sentinel.gui.theme import BG, MUTED, PANEL, PANEL_2, TEXT
from sentinel.models import AuditReport
from sentinel.tzmap import accept_language_value, language_for_country, locale_for_country, offset_for_zone


def ask_alignment(parent: tk.Misc, report: AuditReport | None, *, is_admin: bool) -> AlignmentRequest | None:
    if report is None:
        messagebox.showinfo("先检测", "请先运行“检测”，再决定如何对齐。", parent=parent)
        return None
    egress = report.egress
    egress_ok = bool(egress and egress.ok)
    if not egress_ok:
        messagebox.showwarning(
            "无法对齐",
            "出口信息不可用，无法确定目标时区/地区。请先修复网络或代理，并重新检测。",
            parent=parent,
        )
        return None
    timezone = (egress.timezone if egress else None) or ""
    country = (egress.country_code if egress else None) or ""
    locale = locale_for_country(country, language_for_country(country))
    accept = accept_language_value(locale)
    tz_ok = bool(timezone and offset_for_zone(timezone) is not None)

    win = tk.Toplevel(parent)
    win.title("一键对齐环境")
    win.configure(background=BG)
    win.geometry("700x620")
    win.minsize(620, 540)
    win.transient(parent)
    win.grab_set()

    outer = ttk.Frame(win, padding=18)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="一键对齐环境", style="H2.TLabel").pack(fill="x")
    ttk.Label(
        outer,
        text="Sentinel 会先创建不可覆盖的原始值快照，再写入用户级设置。",
        style="Muted.TLabel",
    ).pack(fill="x", pady=(4, 12))

    info = ttk.Frame(outer, style="Panel.TFrame", padding=14)
    info.pack(fill="x", pady=(0, 12))
    ttk.Label(info, text=f"目标国家/地区: {country or '未知'}", style="Panel.TLabel").pack(anchor="w")
    ttk.Label(info, text=f"目标时区: {timezone or '出口服务未返回（无法安全对齐时区）'}", style="Panel.TLabel").pack(anchor="w")
    ttk.Label(info, text=f"目标 locale: {locale}", style="Panel.TLabel").pack(anchor="w")
    ttk.Label(info, text=f"浏览器 Accept-Language: {accept}", style="Panel.TLabel").pack(anchor="w")

    timezone_var = tk.BooleanVar(value=tz_ok)
    language_var = tk.BooleanVar(value=True)
    browser_var = tk.BooleanVar(value=True)
    system_tz_var = tk.BooleanVar(value=False)
    understood = tk.BooleanVar(value=False)

    options = ttk.Frame(outer)
    options.pack(fill="x")
    tz_cb = ttk.Checkbutton(
        options,
        text=f"B1 对齐时区（用户级 TZ{f'；系统时区需另行确认' if tz_ok else ''}）",
        variable=timezone_var,
    )
    tz_cb.pack(anchor="w", pady=3)
    if not tz_ok:
        tz_cb.configure(state="disabled")
    ttk.Checkbutton(options, text="B2 对齐 LANG/LC_ALL", variable=language_var).pack(anchor="w", pady=3)
    ttk.Checkbutton(
        options,
        text="B3 写入 Chrome/Edge 的 Accept-Language 与 WebRTC 策略（需重启浏览器）",
        variable=browser_var,
    ).pack(anchor="w", pady=3)
    ttk.Separator(options).pack(fill="x", pady=8)
    ttk.Checkbutton(
        options,
        text="同时修改系统时区（需要管理员权限；会写入快照并可在 C 中还原）",
        variable=system_tz_var,
    ).pack(anchor="w", pady=3)
    if not is_admin:
        ttk.Label(
            options,
            text="当前不是管理员：系统时区与 Windows 防火墙能力不可用，建议以管理员身份重新启动 Sentinel。",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(2, 0))
    ttk.Checkbutton(
        options,
        text="我理解这会修改用户级设置，并已知道快照创建位置。",
        variable=understood,
    ).pack(anchor="w", pady=(10, 0))

    ttk.Label(
        outer,
        text=(
            "注意：Sentinel 只降低本地环境画像与出口地区不一致带来的风险，"
            "不承诺账号结果，也不是服务端风控的绕过工具。"
        ),
        wraplength=650,
        style="Muted.TLabel",
    ).pack(fill="x", pady=(14, 0))

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x", pady=(16, 0))
    result: dict[str, AlignmentRequest | None] = {"value": None}

    def submit() -> None:
        if not understood.get():
            messagebox.showwarning("需要确认", "请勾选“我理解…”，再执行对齐。", parent=win)
            return
        request = AlignmentRequest(
            timezone=bool(timezone_var.get()),
            language=bool(language_var.get()),
            browser_policies=bool(browser_var.get()),
            confirm_system_timezone=bool(system_tz_var.get()),
            expected_country=country or None,
            expected_timezone=timezone or None,
        )
        if not request.any_action:
            messagebox.showwarning("没有选择", "至少选择一个对齐项。", parent=win)
            return
        result["value"] = request
        win.destroy()

    ttk.Button(buttons, text="创建快照并应用", style="Accent.TButton", command=submit).pack(side="left")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    win.wait_window()
    return result["value"]


def ask_profile_details(parent: tk.Misc, default_country: str = "") -> dict[str, str] | None:
    win = tk.Toplevel(parent)
    win.title("创建环境配置包")
    win.configure(background=BG)
    win.geometry("540x360")
    win.transient(parent)
    win.grab_set()
    outer = ttk.Frame(win, padding=18)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="创建环境配置包", style="H2.TLabel").pack(fill="x")
    ttk.Label(
        outer,
        text=(
            "只保存时区、语言、浏览器策略和代理标签/端点。\n"
            "不会保存登录凭证、Cookie、Token、会话文件或账号身份。"
        ),
        style="Muted.TLabel",
        justify="left",
    ).pack(fill="x", pady=(6, 10))
    ttk.Label(outer, text="名称（例如：账号 A / 美西）").pack(anchor="w")
    name_var = tk.StringVar()
    ttk.Entry(outer, textvariable=name_var).pack(fill="x", pady=(3, 8))
    ttk.Label(outer, text="期望出口国家代码（可选，例如 US）").pack(anchor="w")
    country_var = tk.StringVar(value=default_country.upper())
    ttk.Entry(outer, textvariable=country_var).pack(fill="x", pady=(3, 8))
    ttk.Label(outer, text="代理标签（可选，例如 US-LA-01；不要填写密码）").pack(anchor="w")
    proxy_var = tk.StringVar()
    ttk.Entry(outer, textvariable=proxy_var).pack(fill="x", pady=(3, 10))
    result: dict[str, dict[str, str] | None] = {"value": None}

    def submit() -> None:
        if not name_var.get().strip():
            messagebox.showwarning("需要名称", "请填写配置包名称。", parent=win)
            return
        result["value"] = {
            "name": name_var.get().strip(),
            "country": country_var.get().strip().upper(),
            "proxy_label": proxy_var.get().strip(),
        }
        win.destroy()

    buttons = ttk.Frame(outer)
    buttons.pack(fill="x")
    ttk.Button(buttons, text="创建", style="Accent.TButton", command=submit).pack(side="left")
    ttk.Button(buttons, text="取消", command=win.destroy).pack(side="right")
    win.wait_window()
    return result["value"]


def confirm(parent: tk.Misc, title: str, message: str, *, dangerous: bool = False) -> bool:
    return bool(messagebox.askyesno(title, message, parent=parent, icon=("warning" if dangerous else "question")))
