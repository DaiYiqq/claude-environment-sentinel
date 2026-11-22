"""Command-line interface for automation, diagnostics and recovery."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sentinel.app import SentinelApp
from sentinel.audit.recommendations import build_recommendations, compact_summary
from sentinel.config import AppPaths, Settings, atomic_write_json
from sentinel.align.engine import AlignmentRequest, AlignmentResult
from sentinel.models import AuditReport, Status


def _utf8_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def _app(offline: bool = False) -> SentinelApp:
    paths = AppPaths.discover()
    settings = Settings.load(paths.config_file)
    if offline:
        settings.network_enabled = False
    return SentinelApp(paths=paths, settings=settings)


_ANSI = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}


def _use_color(no_color: bool) -> bool:
    return (not no_color) and sys.stdout.isatty()


def _paint(text: str, color: str, enabled: bool) -> str:
    if not enabled:
        return text
    return f"{_ANSI[color]}{text}{_ANSI['reset']}"


def _print_report(report: AuditReport, *, verbose: bool = False, no_color: bool = False) -> None:
    color = _use_color(no_color)
    status_colors = {"pass": "green", "warn": "yellow", "fail": "red", "error": "magenta"}
    print(_paint("CLAUDE ENVIRONMENT SENTINEL", "cyan", color) + _paint(" / local diagnosis", "dim", color))
    print("─" * 78)
    gate = _paint("允许", "green", color) if report.gate.allowed else _paint("禁止", "red", color)
    print(
        f"风险分 {_paint(str(report.risk_score) + '/100', 'bold', color)}"
        f"    安全启动门禁: {gate}"
    )
    egress = report.egress
    print(
        f"出口   {(egress.country_code if egress else None) or '未知'} / "
        f"{(egress.ip if egress else None) or '未知'} / "
        f"{(egress.timezone if egress else None) or '未知时区'}"
    )
    counts = report.status_counts
    print(
        f"状态   {counts.get('pass', 0)} 通过 · {counts.get('warn', 0)} 警告 · "
        f"{counts.get('fail', 0)} 失败 · {counts.get('error', 0)} 异常"
    )
    print(f"审计   {report.report_id}   基线: {report.baseline_id or '首次运行'}")
    print("")
    print(f"{'ID':<5} {'状态':<7} {'权重':<5} {'阻断':<5} 说明")
    print("─" * 78)
    for check in report.checks:
        label = _paint(check.status.label_zh.ljust(7), status_colors.get(check.status.value, "dim"), color)
        print(
            f"{check.id:<5} {label:<7} {check.weight:<5} "
            f"{'是' if check.blocking else '否':<5} {check.summary}"
        )
        if verbose:
            for evidence in check.evidence:
                print(_paint(f"       · {evidence}", "dim", color))
    print("")
    if report.gate.reasons:
        print(_paint("安全启动被阻止的原因：", "red", color))
        for reason in report.gate.reasons:
            print(f"  - {reason}")
        print("")
    recommendations = build_recommendations(report)
    if recommendations:
        print(_paint("建议下一步", "cyan", color))
        for index, item in enumerate(recommendations, start=1):
            print(f"  {index}. [{item['id']}] {item['action']}")
        print("")
    if not verbose:
        print(_paint("提示：使用 --verbose 查看每项证据行。", "dim", color))
    print("免责声明：本报告只描述本地环境一致性，不承诺账号结果，也不是服务端风控绕过工具。")


def cmd_audit(args: argparse.Namespace) -> int:
    app = _app(offline=args.offline)
    report = app.audit(export=bool(args.json) or None)
    _print_report(report, verbose=args.verbose, no_color=args.no_color)
    if args.json:
        target = Path(args.json).expanduser()
        app.export_report(report, target)
        print(f"\nJSON 已导出: {target}")
    return 0


def cmd_console(args: argparse.Namespace) -> int:
    app = _app()
    report = app.audit(export=False)
    _print_report(report, verbose=args.verbose, no_color=args.no_color)
    print("")
    print(compact_summary(report))
    if args.json:
        target = Path(args.json).expanduser()
        app.export_report(report, target)
        print(f"\nJSON 已导出: {target}")
    return 0


def _print_alignment(result: AlignmentResult) -> None:
    print(f"对齐快照: {result.snapshot_id or '（未创建，未修改任何设置）'}")
    if result.partial:
        print("总体: 部分完成（存在平台限制或需重启浏览器后生效的项）")
    else:
        print(f"总体: {'成功' if result.ok else '未完全成功'}")
    for item in result.items:
        print(f"  [{item.status}] {item.label}: {item.detail}")
    if result.failures:
        print("失败/未完成项：")
        for failure in result.failures:
            print(f"  - {failure}")
    if result.verification:
        print("复检:")
        print(json.dumps(result.verification, ensure_ascii=False, indent=2))


def cmd_align(args: argparse.Namespace) -> int:
    app = _app()
    print("先运行一次审计，以确定目标地区和当前环境…")
    report = app.audit(export=False)
    request = AlignmentRequest(
        timezone=args.timezone or not (args.timezone or args.language or args.browser),
        language=args.language or not (args.timezone or args.language or args.browser),
        browser_policies=args.browser or not (args.timezone or args.language or args.browser),
        confirm_system_timezone=args.confirm_system_timezone,
    )
    if not report.egress or not report.egress.ok:
        print("出口信息不可用，无法确定目标时区/locale；请先修复网络后重试。")
        return 2
    result = app.align(request, egress=report.egress)
    _print_alignment(result)
    if args.json:
        target = Path(args.json).expanduser()
        atomic_write_json(target, result.to_dict(), mode=0o600)
        print(f"\n对齐结果 JSON 已导出: {target}")
    return 0 if result.ok else 1


def cmd_restore(args: argparse.Namespace) -> int:
    app = _app()
    if args.latest and args.id:
        print("--latest 与 --id 不能同时使用。")
        return 2
    if not args.latest and not args.id:
        print("请指定 --latest 或 --id <snapshot_id>。")
        return 2
    snapshots = app.snapshot_store.list()
    if not snapshots:
        print("backups/ 中没有可用快照。")
        return 2
    snapshot = snapshots[0] if args.latest else app.snapshot_store.load(args.id)
    print(f"准备还原快照 {snapshot.snapshot_id}：{snapshot.label}")
    print(f"创建时间: {snapshot.created_at}   修改项: {', '.join(snapshot.modified_items)}")
    if not args.yes:
        answer = input("确认还原？输入 YES 继续: ").strip()
        if answer != "YES":
            print("已取消。")
            return 1
    result = app.restore(snapshot.snapshot_id)
    print(f"还原快照: {result.snapshot_id}")
    print(f"已还原项: {', '.join(result.restored_items) or '无'}")
    if result.failures:
        print("未能还原/需手动处理的项：")
        for failure in result.failures:
            print(f"  - [{failure.severity}] {failure.item}: {failure.detail}")
            if failure.manual_command:
                print(f"      手动命令: {failure.manual_command}")
    else:
        print("没有报告还原失败项。")
    print(f"逐项验证: {'全部匹配' if result.verified else '存在不匹配或未完成项'}")
    for item in result.verification:
        marker = "OK" if item.get("matches") else "MISMATCH"
        print(f"  [{marker}] {item.get('item')}: expected={item.get('expected')!r} actual={item.get('actual')!r}")
    return 0 if result.verified else 1


def cmd_snapshots(args: argparse.Namespace) -> int:
    app = _app()
    items = app.snapshot_store.list()
    if args.action == "list":
        if not items:
            print("没有快照。")
            return 0
        print(f"{'snapshot_id':<32} {'created_at':<28} 修改项 / 标签")
        for snapshot in items:
            print(f"{snapshot.snapshot_id:<32} {snapshot.created_at:<28} {', '.join(snapshot.modified_items)} / {snapshot.label}")
        return 0
    if args.action == "show":
        snapshot = app.snapshot_store.load(args.id)
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
        return 0
    if args.action == "delete":
        if not args.id:
            print("delete 需要 --id。")
            return 2
        app.snapshot_store.delete(args.id)
        print(f"已删除快照 {args.id}（文件删除不可撤销）。")
        return 0
    return 2


def cmd_profiles(args: argparse.Namespace) -> int:
    app = _app()
    service = app.profile_service
    if args.action == "list":
        items = service.list()
        if not items:
            print("没有环境配置包。")
            return 0
        for profile in items:
            marker = "*" if profile.get("profile_id") == service.current_profile_id else " "
            env = profile.get("environment") or {}
            print(
                f"{marker} {profile.get('profile_id')}  {profile.get('name')}  "
                f"country={(env.get('expected_exit_country') or '-')}  "
                f"tz={(env.get('system_timezone') or {}).get('iana') or '-'}"
            )
        return 0
    if args.action == "create":
        if not args.name:
            print("create 需要 --name。")
            return 2
        profile = service.create_from_current(args.name, expected_country=args.country, proxy_label=args.proxy_label or "")
        print(f"已创建配置包: {profile['profile_id']}  {profile['name']}")
        print("声明：只保存环境配置，不保存登录凭证、Cookie、Token 或会话文件。")
        return 0
    if args.action == "export":
        if not args.id or not args.path:
            print("export 需要 --id 和 --path。")
            return 2
        target = service.export_profile(args.id, Path(args.path))
        print(f"已导出配置包: {target}（不含任何身份材料）")
        return 0
    if args.action == "import":
        if not args.path:
            print("import 需要 --path。")
            return 2
        try:
            profile = service.import_profile(Path(args.path))
        except Exception as exc:
            print(f"导入失败: {exc}")
            return 1
        print(f"已导入配置包: {profile['profile_id']}  {profile['name']}")
        return 0
    if args.action == "activate":
        if not args.id:
            print("activate 需要 --id。")
            return 2
        result = service.activate(
            args.id,
            confirm_system_timezone=args.confirm_system_timezone,
            audit_runner=app.verify_audit,
            current_egress=app.last_report.egress if app.last_report else None,
        )
        print(f"配置包切换: {'成功' if result.get('ok') else '未完全成功'}  snapshot={result.get('snapshot_id')}")
        for failure in result.get("failures") or []:
            print(f"  - {failure}")
        if result.get("partial"):
            print("  注意：存在 partial 项，请查看审计结果。")
        return 0 if result.get("ok") else 1
    return 2


def cmd_doctor(args: argparse.Namespace) -> int:
    app = _app()
    print(json.dumps(app.doctor(), ensure_ascii=False, indent=2))
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    from sentinel.gui.main_window import run_smoke_test

    return run_smoke_test()


def cmd_web_preview(args: argparse.Namespace) -> int:
    from sentinel.web_preview import serve

    return serve(
        port=args.port,
        open_browser=not args.no_open,
        control_enabled=not args.read_only,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sentinel",
        description="Claude Environment Sentinel — 本地环境审计、可回滚对齐与 Kill-Switch。",
    )
    parser.epilog = "浏览器控制台：python -m sentinel web-preview --open（仅绑定 127.0.0.1；--read-only 可禁用写操作）"
    sub = parser.add_subparsers(dest="command")
    audit = sub.add_parser("audit", help="运行 20 项环境审计并输出风险分")
    audit.add_argument("--json", help="将完整审计结果导出为 JSON")
    audit.add_argument("--offline", action="store_true", help="不进行网络探测（会失败/警告，用于离线诊断）")
    audit.add_argument("--verbose", action="store_true", help="显示每项证据行")
    audit.add_argument("--no-color", action="store_true", help="禁用 ANSI 颜色")
    audit.set_defaults(func=cmd_audit)

    console = sub.add_parser("console", help="简洁但可展开的诊断控制台")
    console.add_argument("--verbose", action="store_true", help="显示每项证据行")
    console.add_argument("--no-color", action="store_true", help="禁用 ANSI 颜色")
    console.add_argument("--json", help="导出完整审计 JSON")
    console.set_defaults(func=cmd_console)

    align = sub.add_parser("align", help="创建快照并对齐用户级环境")
    align.add_argument("--timezone", action="store_true", help="对齐时区")
    align.add_argument("--language", action="store_true", help="对齐 LANG/LC_ALL")
    align.add_argument("--browser", action="store_true", help="对齐浏览器策略")
    align.add_argument("--confirm-system-timezone", action="store_true", help="显式确认修改系统时区（可能需要管理员）")
    align.add_argument("--json", help="导出对齐结果 JSON")
    align.set_defaults(func=cmd_align)

    restore = sub.add_parser("restore", help="从不可变快照还原")
    restore.add_argument("--latest", action="store_true", help="还原最近快照")
    restore.add_argument("--id", help="指定快照 ID")
    restore.add_argument("--yes", action="store_true", help="已知情并跳过交互确认")
    restore.set_defaults(func=cmd_restore)

    snapshots = sub.add_parser("snapshots", help="查看/删除快照")
    snapshots.add_argument("action", choices=["list", "show", "delete"])
    snapshots.add_argument("--id")
    snapshots.set_defaults(func=cmd_snapshots)

    profiles = sub.add_parser("profiles", help="多环境配置包（不含身份材料）")
    profiles.add_argument("action", choices=["list", "create", "activate", "export", "import"])
    profiles.add_argument("--name")
    profiles.add_argument("--country")
    profiles.add_argument("--proxy-label")
    profiles.add_argument("--id")
    profiles.add_argument("--path")
    profiles.add_argument("--confirm-system-timezone", action="store_true")
    profiles.set_defaults(func=cmd_profiles)

    doctor = sub.add_parser("doctor", help="输出能力自检，不修改系统")
    doctor.set_defaults(func=cmd_doctor)

    smoke = sub.add_parser("smoke-test", help="创建并销毁 GUI 主窗口，不执行审计")
    smoke.set_defaults(func=cmd_smoke)

    preview = sub.add_parser("web-preview", help="启动本地浏览器控制台")
    preview.add_argument("--port", type=int, default=8790, help="监听端口，默认 8790")
    preview.add_argument("--no-open", action="store_true", help="不自动打开浏览器")
    preview.add_argument("--read-only", action="store_true", help="禁用对齐/还原写接口，仅保留只读预览")
    preview.set_defaults(func=cmd_web_preview)
    return parser


def main(argv: list[str] | None = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    if not getattr(args, "command", None):
        from sentinel.gui.bootstrap import run_gui

        return run_gui()
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"Sentinel 执行失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
