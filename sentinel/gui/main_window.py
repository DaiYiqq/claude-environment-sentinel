"""Main Tk window and controller for Claude Environment Sentinel."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from sentinel import APP_NAME, APP_SLOGAN
from sentinel.align.engine import AlignmentRequest
from sentinel.app import SentinelApp
from sentinel.audit.recommendations import build_recommendations, compact_summary
from sentinel.gui.async_runner import AsyncRunner
from sentinel.gui.beginner import BeginnerFrame
from sentinel.gui.detail_dialog import show_check_detail
from sentinel.gui.dialogs import ask_alignment, ask_profile_details, confirm
from sentinel.gui.expert import ExpertFrame
from sentinel.gui.hotkey import GlobalHotkey
from sentinel.gui.theme import (
    ACCENT,
    BG,
    BORDER,
    DANGER,
    LATCH_BG,
    LATCH_FG,
    LATCH_LINK,
    MUTED,
    PANEL,
    PANEL_2,
    TEXT,
    THEME_NAME,
    configure_style,
)
from sentinel.models import AuditReport, CheckResult


class MainWindow:
    def __init__(self, root: tk.Tk, app: SentinelApp, *, start_hotkey: bool = True) -> None:
        self.root = root
        self.app = app
        self.paths = app.paths
        self.settings = app.settings
        self.font_family = configure_style(root)
        self.runner = AsyncRunner(root)
        self.report: AuditReport | None = app.last_report
        self._safe_running = False
        self._hotkey: GlobalHotkey | None = None
        self._hotkey_status: tuple[bool, str] = (False, "尚未注册")
        self._hotkey_queue: queue.Queue[bool] = queue.Queue()
        self._busy = False
        self._mode = self.settings.mode if self.settings.mode in {"beginner", "expert"} else "beginner"

        root.title(APP_NAME)
        root.geometry("1220x800")
        root.minsize(980, 640)
        root.configure(background=BG)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._build_header()
        self.latch_banner = tk.Frame(root, background=LATCH_BG, padx=16, pady=10)
        self.latch_label = tk.Label(
            self.latch_banner,
            text="Kill-Switch 已锁定：安全启动被禁止，防火墙规则仍然存在。请到专家模式手动解除。",
            background=LATCH_BG,
            foreground=LATCH_FG,
            font=(self.font_family, 10, "bold"),
            anchor="w",
        )
        self.latch_label.pack(side="left", fill="x", expand=True)
        latch_link = tk.Label(
            self.latch_banner,
            text="去解除",
            background=LATCH_BG,
            foreground=LATCH_LINK,
            cursor="hand2",
            font=(self.font_family, 10, "underline"),
        )
        latch_link.pack(side="right")
        latch_link.bind("<Button-1>", lambda _event: self._go_to_killswitch())

        self.container = ttk.Frame(root, padding=(16, 0, 16, 8))
        self.container.pack(fill="both", expand=True)
        self.beginner = BeginnerFrame(self.container, self)
        self.expert = ExpertFrame(self.container, self)
        self.beginner.pack(fill="both", expand=True)
        self.expert.pack_forget()

        self.status_var = tk.StringVar(value="就绪。先检测，再对齐，最后才安全启动。")
        status = tk.Label(
            root,
            textvariable=self.status_var,
            background=PANEL,
            foreground=MUTED,
            anchor="w",
            padx=16,
            pady=6,
            font=(self.font_family, 9),
        )
        status.pack(fill="x", side="bottom")

        self.expert.refresh_settings(self.settings)
        self.refresh_snapshots()
        self.refresh_profiles()
        self.refresh_killswitch()
        self._apply_latch_banner()
        self.beginner.update_report(self.report, safe_running=False)
        self.expert.set_report(self.report)
        self.refresh_console()
        self._apply_mode()
        if start_hotkey and self.settings.hotkey_enabled:
            self._start_hotkey()
        else:
            self._hotkey_status = (False, "已在设置中关闭" if not self.settings.hotkey_enabled else "启动时未注册")
        self.refresh_killswitch()
        self.root.after(200, self._poll_hotkey)

    # --- chrome ----------------------------------------------------------
    def _build_header(self) -> None:
        header = ttk.Frame(self.root, padding=(16, 16, 16, 8))
        header.pack(fill="x")
        left = ttk.Frame(header)
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text=APP_SLOGAN, style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(
            left,
            text=(
                "降低本地环境画像与账号注册地区冲突的风险；不承诺账号结果，"
                "不是服务端风控的绕过工具。"
            ),
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        right = ttk.Frame(header)
        right.pack(side="right")
        self.mode_link = tk.Label(
            right,
            text="专家模式 →",
            background=BG,
            foreground=ACCENT,
            cursor="hand2",
            font=(self.font_family, 10, "underline"),
        )
        self.mode_link.pack(anchor="e")
        self.mode_link.bind("<Button-1>", lambda _event: self.toggle_mode())
        self.theme_link = tk.Label(
            right,
            text=("☀ 浅色模式" if THEME_NAME == "dark" else "☾ 深色模式"),
            background=BG,
            foreground=MUTED,
            cursor="hand2",
            font=(self.font_family, 9, "underline"),
        )
        self.theme_link.pack(anchor="e", pady=(4, 0))
        self.theme_link.bind("<Button-1>", lambda _event: self.toggle_theme())
        self.header_risk = ttk.Label(right, text="尚未检测", style="Muted.TLabel")
        self.header_risk.pack(anchor="e", pady=(6, 0))

    def _apply_mode(self) -> None:
        if self._mode == "expert":
            self.beginner.pack_forget()
            self.expert.pack(fill="both", expand=True)
            self.mode_link.configure(text="← 新手模式")
        else:
            self.expert.pack_forget()
            self.beginner.pack(fill="both", expand=True)
            self.mode_link.configure(text="专家模式 →")
        self.settings.mode = self._mode
        try:
            self.app.save_settings()
        except OSError:
            pass

    def toggle_mode(self) -> None:
        self._mode = "expert" if self._mode == "beginner" else "beginner"
        self._apply_mode()

    def toggle_theme(self) -> None:
        if self._busy:
            messagebox.showwarning("操作进行中", "请等待当前检测或操作完成后再切换主题。", parent=self.root)
            return
        if self.app.launcher.running:
            messagebox.showwarning(
                "安全会话进行中",
                "请先停止受管 Claude 会话，再切换界面主题。",
                parent=self.root,
            )
            return
        current = "light" if THEME_NAME == "light" else "dark"
        target = "dark" if current == "light" else "light"
        if not confirm(
            self.root,
            "切换界面主题",
            f"切换到{'浅色' if target == 'light' else '深色'}模式？\n\n"
            "Tk 界面的颜色在创建时固定，切换会重新打开 Sentinel 窗口；"
            "不会修改环境变量、快照或 Kill-Switch 规则。",
        ):
            return
        self.settings.theme = target
        try:
            self.app.save_settings()
        except OSError as exc:
            messagebox.showerror("保存设置失败", str(exc), parent=self.root)
            return
        self._restart_for_theme(target)

    def _restart_for_theme(self, target: str) -> None:
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
        try:
            self.app.close()
        except Exception:
            pass
        env = os.environ.copy()
        env["SENTINEL_THEME"] = target
        executable = sys.executable
        pythonw = Path(executable).with_name("pythonw.exe")
        if pythonw.is_file():
            executable = str(pythonw)
        try:
            subprocess.Popen(
                [executable, "-m", "sentinel"],
                cwd=str(self.paths.root),
                env=env,
            )
        except OSError as exc:
            messagebox.showerror(
                "主题切换失败",
                f"无法启动新的 Sentinel 窗口：{exc}\n设置已保存，下次启动会使用新主题。",
                parent=self.root,
            )
            return
        self.root.destroy()

    def _go_to_killswitch(self) -> None:
        self._mode = "expert"
        self._apply_mode()
        self.expert.notebook.select(self.expert.kill_tab)

    def open_tutorial(self) -> None:
        self._mode = "expert"
        self._apply_mode()
        self.expert.notebook.select(self.expert.tutorial_tab)

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def _apply_latch_banner(self) -> None:
        if self.app.killswitch.latched:
            if not self.latch_banner.winfo_ismapped():
                self.latch_banner.pack(fill="x", after=self.root.winfo_children()[0])
        else:
            try:
                self.latch_banner.pack_forget()
            except tk.TclError:
                pass

    # --- busy / report ---------------------------------------------------
    def _set_busy(self, busy: bool, label: str = "") -> None:
        self._busy = busy
        self.beginner.set_busy(busy, label)
        self.expert.audit_btn.configure(state=("disabled" if busy else "normal"))
        if busy:
            self.set_status(label or "正在处理…")
        self._update_header_risk()

    def _update_header_risk(self) -> None:
        if self.report is None:
            self.header_risk.configure(text="尚未检测")
        else:
            self.header_risk.configure(
                text=f"风险 {self.report.risk_score}/100 · "
                f"{'门禁允许' if self.report.gate.allowed else '门禁阻止'}"
            )

    def _after_report(self, report: AuditReport) -> None:
        self.report = report
        self._safe_running = self.app.launcher.running
        self.beginner.update_report(report, safe_running=self._safe_running)
        self.expert.set_report(report)
        self._update_header_risk()
        self._set_busy(False)
        self._apply_latch_banner()
        self.refresh_console()
        self.set_status(
            f"检测完成：风险 {report.risk_score}/100，"
            f"{'允许安全启动' if report.gate.allowed else '安全启动被禁用'}。"
        )

    # --- actions ---------------------------------------------------------
    def on_detect(self) -> None:
        if self._busy:
            return
        self._set_busy(True, "正在检测时区、环境变量、网络、DNS、WebRTC、浏览器策略…")
        self.runner.submit(
            self.app.audit,
            on_success=self._after_report,
            on_error=self._task_error,
            label="audit",
        )

    def on_align(self) -> None:
        if self._busy:
            return
        request = ask_alignment(self.root, self.report, is_admin=self.app.platform.is_admin())
        if request is None:
            return
        self._run_alignment(request)

    def _run_alignment(self, request: AlignmentRequest) -> None:
        if self._busy:
            return
        self._set_busy(True, "正在创建快照并写入用户级设置，随后复检…")
        report = self.report

        def work() -> Any:
            return self.app.align(request, egress=report.egress if report else None)

        self.runner.submit(work, on_success=self._after_alignment, on_error=self._task_error, label="align")

    def _after_alignment(self, result: Any) -> None:
        self._set_busy(False)
        report = self.app.last_report or self.app.last_verification_report
        if report is not None:
            self._after_report(report)
        else:
            self.beginner.update_report(self.report, safe_running=self.app.launcher.running)
        self.refresh_snapshots()
        summary = []
        if result.snapshot_id:
            summary.append(f"已创建快照：{result.snapshot_id}")
        summary.append(f"总体状态：{'成功' if result.ok else '未完全成功'}{'（partial）' if result.partial else ''}")
        for item in result.items:
            if item.status in {"failed", "partial"}:
                summary.append(f"[{item.status}] {item.label}: {item.detail}")
        if result.failures:
            summary.append("\n失败/未完成项：")
            summary.extend(f"• {failure}" for failure in result.failures[:8])
        message = "\n".join(summary) or "对齐完成。"
        if result.failures:
            messagebox.showwarning("对齐结果", message, parent=self.root)
        else:
            messagebox.showinfo("对齐结果", message, parent=self.root)
        self.set_status("对齐流程完成，已重新采样关键项。")

    def fix_check(self, check: CheckResult) -> None:
        if not check.fixable:
            messagebox.showinfo("仅提示", "该项没有自动修复；请按详情中的说明手动处理。", parent=self.root)
            return
        timezone = check.id in {"A1", "A2", "A8"}
        language = check.id in {"A3", "A4", "A9"}
        browser = check.id in {"A16", "A17"}
        if not (timezone or language or browser):
            messagebox.showinfo("仅提示", "该项没有一键对齐操作。", parent=self.root)
            return
        confirm_tz = False
        if timezone:
            confirm_tz = confirm(
                self.root,
                "修改系统时区？",
                "是否同时修改系统时区？这会写入快照并可在 C 中还原，可能需要管理员权限。\n"
                "选择“否”则只写用户级 TZ。",
            )
        report = self.report
        if report is None:
            messagebox.showinfo("先检测", "请先运行检测。", parent=self.root)
            return
        request = AlignmentRequest(
            timezone=timezone,
            language=language,
            browser_policies=browser or check.id == "A4",
            confirm_system_timezone=confirm_tz,
            expected_country=report.egress.country_code if report.egress else None,
            expected_timezone=report.egress.timezone if report.egress else None,
        )
        self._run_alignment(request)

    def on_safe_start_or_stop(self) -> None:
        if self._busy:
            return
        if self.app.killswitch.latched:
            messagebox.showwarning(
                "Kill-Switch 已锁定",
                "Kill-Switch 已锁定。请先到专家模式手动解除；锁定期间不会自动移除防火墙规则。",
                parent=self.root,
            )
            return
        if self.app.launcher.running:
            if not confirm(self.root, "停止安全会话", "停止由 Sentinel 托管的 Claude 进程，并移除本次会话的阻断规则？"):
                return
            self._set_busy(True, "正在停止受管 Claude 会话…")
            self.runner.submit(self.app.stop, on_success=self._after_stop, on_error=self._task_error, label="stop")
            return
        if self.app.killswitch.latched:
            messagebox.showwarning(
                "Kill-Switch 已锁定",
                "必须先到专家模式手动解除 Kill-Switch，才能再次安全启动。",
                parent=self.root,
            )
            return
        if self.report is None:
            messagebox.showinfo("先检测", "安全启动前必须先检测。", parent=self.root)
            return
        if not self.report.gate.allowed:
            messagebox.showwarning(
                "审计未通过",
                "审计未通过，安全启动按钮不可用。\n\n" + "\n".join(f"• {r}" for r in self.report.gate.reasons[:8]),
                parent=self.root,
            )
            return
        if not confirm(
            self.root,
            "安全启动",
            "Sentinel 会重新运行一次完整审计；只有门禁通过才会拉起 Claude。\n"
            "启动后 Kill-Switch 会每 5 秒检查出口/代理/TUN，异常时终止进程并阻断出站。\n\n继续？",
        ):
            return
        self._set_busy(True, "正在重新审计并安全启动 Claude…")
        self.runner.submit(self.app.safe_start, on_success=self._after_safe_start, on_error=self._task_error, label="safe-start")

    def _after_safe_start(self, result: Any) -> None:
        self._set_busy(False)
        if result.audit is not None:
            self.report = result.audit
            self.beginner.update_report(self.report, safe_running=bool(result.ok))
            self.expert.set_report(self.report)
            self._update_header_risk()
        self._safe_running = bool(result.ok and self.app.launcher.running)
        self.refresh_killswitch()
        if result.ok:
            self.set_status(f"安全启动成功：PID {result.pid}，Kill-Switch 已布防。")
            messagebox.showinfo("安全启动成功", result.detail, parent=self.root)
        else:
            self.set_status("安全启动被阻止。")
            messagebox.showwarning(
                "安全启动被阻止",
                result.detail + ("\n\n" + "\n".join(f"• {f}" for f in result.failures[:8]) if result.failures else ""),
                parent=self.root,
            )

    def _after_stop(self, result: Any) -> None:
        self._set_busy(False)
        self._safe_running = False
        self.beginner.update_report(self.report, safe_running=False)
        self.refresh_killswitch()
        self.set_status("受管 Claude 会话已停止。")
        if isinstance(result, dict) and result.get("failures"):
            messagebox.showwarning("停止结果", "\n".join(result["failures"]), parent=self.root)

    def _task_error(self, exc: BaseException, detail: str) -> None:
        self._set_busy(False)
        self.set_status("操作失败。")
        messagebox.showerror("Sentinel 操作失败", f"{type(exc).__name__}: {exc}\n\n{detail[-1800:]}", parent=self.root)

    # --- export / detail ------------------------------------------------
    def on_export_report(self) -> None:
        if self.report is None:
            messagebox.showinfo("没有报告", "请先运行检测。", parent=self.root)
            return
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="导出审计 JSON",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            initialfile=f"sentinel-audit-{self.report.report_id}.json",
        )
        if not path:
            return
        try:
            self.app.export_report(self.report, Path(path))
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc), parent=self.root)
            return
        self.set_status(f"已导出：{path}")

    def show_detail(self, check: CheckResult, expert: bool = False) -> None:
        show_check_detail(self.root, check, expert=expert, on_fix=self.fix_check if expert else None)

    def show_snapshot_detail(self, snapshot_id: str) -> None:
        try:
            snapshot = self.app.snapshot_store.load(snapshot_id)
        except Exception as exc:
            messagebox.showerror("无法加载快照", str(exc), parent=self.root)
            return
        self.expert.show_snapshot_json(snapshot.to_dict())

    # --- snapshots -------------------------------------------------------
    def refresh_snapshots(self) -> None:
        try:
            snapshots = self.app.snapshot_store.list()
        except Exception:
            snapshots = []
        self.expert.update_snapshots(snapshots)

    def on_refresh_snapshots(self) -> None:
        self.refresh_snapshots()
        self.set_status("快照列表已刷新。")

    def on_restore_latest(self) -> None:
        snapshots = self.app.snapshot_store.list()
        if not snapshots:
            messagebox.showinfo("没有快照", "backups/ 中没有快照。", parent=self.root)
            return
        self.on_restore_snapshot(snapshots[0].snapshot_id)

    def on_restore_snapshot(self, snapshot_id: str) -> None:
        if self._busy:
            return
        try:
            snapshot = self.app.snapshot_store.load(snapshot_id)
        except Exception as exc:
            messagebox.showerror("快照无效", str(exc), parent=self.root)
            return
        if not confirm(
            self.root,
            "还原快照",
            f"将逐项写回快照 {snapshot.snapshot_id} 的原始值：\n{snapshot.label}\n\n"
            f"修改项：{', '.join(snapshot.modified_items)}\n\n"
            "原本不存在的环境变量会被删除。还原后会自动重新审计并列出未能还原的项。继续？",
            dangerous=True,
        ):
            return
        self._set_busy(True, "正在还原快照并逐项验证…")
        self.runner.submit(
            lambda: self.app.restore(snapshot_id),
            on_success=self._after_restore,
            on_error=self._task_error,
            label="restore",
        )

    def _after_restore(self, result: Any) -> None:
        self._set_busy(False)
        self.refresh_snapshots()
        if self.app.last_report is not None:
            self._after_report(self.app.last_report)
        lines = [f"快照 {result.snapshot_id} 还原完成。"]
        lines.append(f"逐项验证：{'全部匹配' if result.verified else '存在不匹配或未完成项'}")
        if result.failures:
            lines.append("\n未能还原的项：")
            for failure in result.failures:
                lines.append(f"• {failure.item}: {failure.detail}")
                if failure.manual_command:
                    lines.append(f"  手动命令：{failure.manual_command}")
            messagebox.showwarning("还原结果", "\n".join(lines), parent=self.root)
        else:
            messagebox.showinfo("还原结果", "\n".join(lines), parent=self.root)
        self.set_status("还原流程完成。")

    def on_delete_snapshot(self, snapshot_id: str) -> None:
        if not confirm(
            self.root,
            "删除快照",
            f"确定删除快照 {snapshot_id}？文件删除后无法从 Sentinel 恢复。",
            dangerous=True,
        ):
            return
        try:
            self.app.snapshot_store.delete(snapshot_id)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self.root)
            return
        self.refresh_snapshots()
        self.set_status("快照已删除。")

    # --- profiles --------------------------------------------------------
    def refresh_profiles(self) -> None:
        try:
            profiles = self.app.profile_service.list()
            current = self.app.profile_service.current_profile_id
        except Exception:
            profiles, current = [], None
        self.expert.update_profiles(profiles, current)

    def on_refresh_profiles(self) -> None:
        self.refresh_profiles()
        self.set_status("环境配置包列表已刷新。")

    def on_create_profile(self) -> None:
        details = ask_profile_details(self.root, default_country=(self.report.egress.country_code if self.report and self.report.egress else ""))
        if details is None:
            return
        try:
            profile = self.app.profile_service.create_from_current(
                details["name"],
                expected_country=details.get("country") or None,
                proxy_label=details.get("proxy_label") or "",
            )
        except Exception as exc:
            messagebox.showerror("创建失败", str(exc), parent=self.root)
            return
        self.refresh_profiles()
        messagebox.showinfo(
            "配置包已创建",
            f"{profile.get('name')}\n\n声明：只保存环境配置，不保存登录凭证、Cookie、Token 或会话文件。",
            parent=self.root,
        )

    def on_activate_profile(self, profile_id: str) -> None:
        if self._busy:
            return
        try:
            profile = self.app.profile_service.load(profile_id)
        except Exception as exc:
            messagebox.showerror("配置包无效", str(exc), parent=self.root)
            return
        env = profile.get("environment") or {}
        target_tz = (env.get("system_timezone") or {}).get("iana") or "-"
        if not confirm(
            self.root,
            "切换环境配置包",
            f"配置包：{profile.get('name')}\n目标时区：{target_tz}\n期望出口：{env.get('expected_exit_country') or '-'}\n\n"
            "Sentinel 会先为当前环境创建快照，再写回目标环境配置。\n"
            "不会触碰任何 Claude 登录凭证、Cookie 或会话文件；切换账号需你在 Claude 内自行完成。\n\n"
            "继续？",
            dangerous=True,
        ):
            return
        confirm_tz = confirm(
            self.root,
            "修改系统时区？",
            "是否同时修改系统时区？需要管理员权限，并会被快照记录。",
        )
        start_after = confirm(
            self.root,
            "切换后安全启动？",
            "配置包切换并复检通过后，是否立即执行安全启动？",
        )
        self._set_busy(True, "正在归档当前环境、应用目标配置并复检…")

        def work() -> dict[str, Any]:
            result = self.app.profile_service.activate(
                profile_id,
                confirm_system_timezone=confirm_tz,
                audit_runner=self.app.verify_audit,
                current_egress=self.app.last_report.egress if self.app.last_report else None,
            )
            if start_after and result.get("ok"):
                result["safe_start"] = self.app.safe_start()
            return result

        self.runner.submit(work, on_success=self._after_profile_activate, on_error=self._task_error, label="profile-activate")

    def _after_profile_activate(self, result: dict[str, Any]) -> None:
        self._set_busy(False)
        self.refresh_profiles()
        self.refresh_snapshots()
        if self.app.last_report is not None:
            self.report = self.app.last_report
            self.beginner.update_report(self.report, safe_running=self.app.launcher.running)
            self.expert.set_report(self.report)
            self._update_header_risk()
        lines = [f"配置包：{result.get('profile_name') or result.get('profile_id')}"]
        lines.append(f"切换：{'成功' if result.get('ok') else '未完成'}  partial={result.get('partial')}")
        if result.get("snapshot_id"):
            lines.append(f"切换前快照：{result['snapshot_id']}")
        for failure in result.get("failures") or []:
            lines.append(f"• {failure}")
        safe = result.get("safe_start")
        if safe is not None:
            lines.append(f"安全启动：{'成功' if safe.ok else '被阻止'} — {safe.detail}")
        self.refresh_killswitch()
        if result.get("failures") or (safe is not None and not safe.ok):
            messagebox.showwarning("配置包切换", "\n".join(lines), parent=self.root)
        else:
            messagebox.showinfo("配置包切换", "\n".join(lines), parent=self.root)
        self.set_status("环境配置包切换流程完成。")

    def on_delete_profile(self, profile_id: str) -> None:
        try:
            profile = self.app.profile_service.load(profile_id)
        except Exception as exc:
            messagebox.showerror("配置包无效", str(exc), parent=self.root)
            return
        if not confirm(
            self.root,
            "删除配置包",
            f"确定删除环境配置包“{profile.get('name')}”？快照不会被自动删除。",
            dangerous=True,
        ):
            return
        try:
            self.app.profile_service.delete(profile_id)
        except Exception as exc:
            messagebox.showerror("删除失败", str(exc), parent=self.root)
            return
        self.refresh_profiles()

    # --- kill switch -----------------------------------------------------
    def _log_tail(self) -> str:
        path = self.paths.logs / "killswitch.jsonl"
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
            return "\n".join(lines)
        except OSError:
            return ""

    def refresh_killswitch(self) -> None:
        self._apply_latch_banner()
        self.expert.update_killswitch(self.app.killswitch.status(), self._hotkey_status, self._log_tail())
        if self._safe_running:
            self.beginner.update_report(self.report, safe_running=True)
        self.refresh_console()

    def _recent_history(self, limit: int = 20) -> list[dict[str, Any]]:
        path = self.paths.state / "audit_history.jsonl"
        items: list[dict[str, Any]] = []
        try:
            if path.is_file() and path.stat().st_size <= 6_000_000:
                for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-300:]:
                    try:
                        item = json.loads(line)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    if isinstance(item, dict) and item.get("event") == "audit":
                        items.append(item)
        except OSError:
            return []
        return items[-limit:]

    def refresh_console(self) -> None:
        status = self.app.killswitch.status()
        try:
            status["admin"] = self.app.platform.is_admin()
        except Exception:
            status["admin"] = False
        recommendations = build_recommendations(self.report) if self.report is not None else []
        self.expert.update_console(status, self._recent_history(), recommendations, self._hotkey_status)

    def on_refresh_console(self) -> None:
        self.refresh_console()
        self.set_status("控制台已刷新。")

    def on_copy_summary(self) -> None:
        if self.report is None:
            messagebox.showinfo("没有摘要", "请先运行检测。", parent=self.root)
            return
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(compact_summary(self.report))
            self.set_status("诊断摘要已复制到剪贴板。")
        except tk.TclError as exc:
            messagebox.showerror("复制失败", str(exc), parent=self.root)

    def platform_label(self) -> str:
        return {"windows": "Windows", "macos": "macOS", "linux": "Linux"}.get(
            self.app.platform.name, self.app.platform.name
        )

    def on_refresh_killswitch(self) -> None:
        self.refresh_killswitch()
        self.set_status("Kill-Switch 状态已刷新。")

    def on_release_killswitch(self) -> None:
        if self._busy:
            return
        if not confirm(
            self.root,
            "解除 Kill-Switch",
            "将删除 Sentinel 创建的出站阻断规则并清除锁定。\n"
            "这不会自动重启 Claude，也不会撤销环境修改。继续？",
            dangerous=True,
        ):
            return
        self._set_busy(True, "正在删除防火墙规则并解除锁定…")
        self.runner.submit(
            self.app.killswitch.release,
            on_success=self._after_release,
            on_error=self._task_error,
            label="killswitch-release",
        )

    def _after_release(self, result: dict[str, Any]) -> None:
        self._set_busy(False)
        self.refresh_killswitch()
        if result.get("failures"):
            messagebox.showwarning(
                "解除未完全成功",
                "以下规则未能删除：\n" + "\n".join(result["failures"]),
                parent=self.root,
            )
        else:
            messagebox.showinfo("Kill-Switch", "已解除锁定并删除本会话规则。", parent=self.root)
        self.set_status("Kill-Switch 解除操作完成。")

    def on_emergency_stop(self) -> None:
        if not confirm(
            self.root,
            "立即急停",
            "立即终止由 Sentinel 托管的 Claude 进程并阻断其出站网络？\n"
            "如果没有受管会话，不会误杀其他进程。",
            dangerous=True,
        ):
            return
        self._emergency_stop(show_dialog=True)

    def _emergency_stop(self, *, show_dialog: bool) -> None:
        if self._busy:
            return
        self._set_busy(True, "正在执行 Kill-Switch…")
        self.runner.submit(
            lambda: self.app.killswitch.emergency_stop("hotkey"),
            on_success=lambda result: self._after_emergency(result, show_dialog=show_dialog),
            on_error=self._task_error,
            label="killswitch-stop",
        )

    def _after_emergency(self, result: dict[str, Any], *, show_dialog: bool) -> None:
        self._set_busy(False)
        self.refresh_killswitch()
        self._safe_running = self.app.launcher.running and not self.app.killswitch.latched
        if result.get("already_latched"):
            text = "Kill-Switch 已处于锁定状态。"
        elif result.get("ok"):
            text = "Kill-Switch 已触发：进程已终止，防火墙规则已尽力创建。详见日志。"
        else:
            text = str(result.get("detail") or "没有可急停的受管会话。")
        self.set_status(text)
        if show_dialog:
            messagebox.showwarning("Kill-Switch", text, parent=self.root)

    # --- settings / hotkey ----------------------------------------------
    def on_save_settings(self, values: dict[str, Any]) -> None:
        self.settings.claude_command = str(values.get("claude_command") or "")
        self.settings.network_enabled = bool(values.get("network_enabled"))
        self.settings.require_tun = bool(values.get("require_tun"))
        self.settings.country_lock = bool(values.get("country_lock"))
        self.settings.expected_country = str(values.get("expected_country") or "").strip().upper()[:8]
        self.settings.hotkey = str(values.get("hotkey") or "ctrl+shift+k")
        try:
            self.settings.poll_seconds = float(values.get("poll_seconds") or 5)
        except (TypeError, ValueError):
            self.settings.poll_seconds = 5.0
        try:
            self.app.save_settings()
        except OSError as exc:
            messagebox.showerror("保存失败", str(exc), parent=self.root)
            return
        self._start_hotkey(restart=True)
        self.refresh_killswitch()
        self.set_status("设置已保存。")

    def _start_hotkey(self, *, restart: bool = False) -> None:
        if restart and self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
        if not self.settings.hotkey_enabled:
            self._hotkey_status = (False, "已在设置中关闭")
            self.refresh_killswitch()
            return
        helper = GlobalHotkey(self.settings.hotkey, self._hotkey_pressed)
        ok, reason = helper.start()
        if ok:
            self._hotkey = helper
            self._hotkey_status = (True, f"已注册 {self.settings.hotkey}")
        else:
            self._hotkey_status = (False, reason)
        self.refresh_killswitch()

    def _hotkey_pressed(self) -> None:
        # Called from the hotkey thread; never touch Tk from here.
        self._hotkey_queue.put(True)

    def _poll_hotkey(self) -> None:
        try:
            while True:
                self._hotkey_queue.get_nowait()
                self._handle_hotkey()
        except queue.Empty:
            pass
        except tk.TclError:
            return
        try:
            self.root.after(200, self._poll_hotkey)
        except tk.TclError:
            pass

    def _handle_hotkey(self) -> None:
        if self.app.killswitch.armed or self.app.killswitch.latched:
            self._emergency_stop(show_dialog=False)
        else:
            self.set_status("全局急停：当前没有受管 Claude 会话，未误杀其他进程。")
            self.app.killswitch.log.write("killswitch_hotkey_noop", detail="no managed session")

    # --- close -----------------------------------------------------------
    def on_close(self) -> None:
        if self.app.launcher.running and not self.app.killswitch.latched:
            if not confirm(
                self.root,
                "关闭 Sentinel",
                "受管 Claude 会话仍在运行。关闭 Sentinel 会先停止该会话并移除本次阻断规则。\n继续？",
                dangerous=True,
            ):
                return
        if self._hotkey is not None:
            try:
                self._hotkey.stop()
            except Exception:
                pass
        try:
            self.app.close()
        finally:
            self.root.destroy()

    # --- controller properties ------------------------------------------
    def killswitch_latched(self) -> bool:
        return self.app.killswitch.latched


def run_gui() -> int:
    try:
        app = SentinelApp()
        root = tk.Tk()
        MainWindow(root, app)
        root.mainloop()
        return 0
    except Exception as exc:
        try:
            messagebox.showerror("Sentinel 启动失败", f"{type(exc).__name__}: {exc}")
        except Exception:
            print(f"Sentinel 启动失败: {exc}")
        return 1


def run_smoke_test() -> int:
    """Construct the GUI with a withdrawn root, then destroy it."""
    try:
        app = SentinelApp()
        root = tk.Tk()
        root.withdraw()
        window = MainWindow(root, app, start_hotkey=False)
        root.update_idletasks()
        root.update()
        if window._hotkey is not None:
            window._hotkey.stop()
        root.destroy()
        print("GUI smoke test OK")
        return 0
    except Exception as exc:
        print(f"GUI smoke test FAILED: {type(exc).__name__}: {exc}")
        return 1
