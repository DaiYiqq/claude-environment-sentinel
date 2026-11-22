"""Turn an audit report into a short, prioritized action list.

Recommendations are advisory.  They never auto-apply changes and never promise
an account outcome.
"""

from __future__ import annotations

from typing import Any

from sentinel.audit.explanations import FIX_HINTS
from sentinel.models import AuditReport, CheckResult, Status

STATUS_ORDER = {Status.FAIL: 0, Status.ERROR: 0, Status.WARN: 1, Status.PASS: 2}


def build_recommendations(report: AuditReport, *, limit: int = 8) -> list[dict[str, Any]]:
    checks = sorted(
        report.checks,
        key=lambda check: (STATUS_ORDER.get(check.status, 3), check.id),
    )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for check in checks:
        if check.status not in (Status.FAIL, Status.ERROR, Status.WARN):
            continue
        action = FIX_HINTS.get(check.id, "").strip()
        if not action:
            continue
        key = f"{check.id}:{action}"
        if key in seen:
            continue
        seen.add(key)
        result.append(
            {
                "id": check.id,
                "status": check.status.value,
                "title": check.title,
                "summary": check.summary,
                "action": action,
                "priority": "must_fix" if check.status in (Status.FAIL, Status.ERROR) and check.blocking else "should_fix",
            }
        )
        if len(result) >= limit:
            break
    if not result and report.gate and report.gate.reasons:
        for index, reason in enumerate(report.gate.reasons[:limit], start=1):
            result.append(
                {
                    "id": f"GATE-{index}",
                    "status": "fail",
                    "title": "门禁原因",
                    "summary": reason,
                    "action": "按门禁原因逐项处理后重新检测。",
                    "priority": "must_fix",
                }
            )
    return result


def compact_summary(report: AuditReport) -> str:
    """Plain-text summary suitable for clipboard/console export."""
    egress = report.egress
    counts = report.status_counts
    lines = [
        "Claude Environment Sentinel",
        f"风险分: {report.risk_score}/100    安全启动门禁: {'允许' if report.gate.allowed else '禁止'}",
        f"出口: {(egress.country_code if egress else None) or '未知'} / "
        f"{(egress.ip if egress else None) or '未知'} / "
        f"{(egress.timezone if egress else None) or '未知时区'}",
        f"状态: {counts.get('pass', 0)} 通过 · {counts.get('warn', 0)} 警告 · "
        f"{counts.get('fail', 0)} 失败 · {counts.get('error', 0)} 异常",
    ]
    failing = [check for check in report.checks if check.status in (Status.FAIL, Status.ERROR)]
    warning = [check for check in report.checks if check.status is Status.WARN]
    if failing:
        lines.append("失败: " + ", ".join(f"{c.id} {c.title}" for c in failing[:8]))
    if warning:
        lines.append("警告: " + ", ".join(f"{c.id} {c.title}" for c in warning[:8]))
    if report.gate.reasons:
        lines.append("门禁原因:")
        lines.extend(f"  - {reason}" for reason in report.gate.reasons[:8])
    recommendations = build_recommendations(report)
    if recommendations:
        lines.append("建议下一步:")
        for index, item in enumerate(recommendations, start=1):
            lines.append(f"  {index}. [{item['id']}] {item['action']}")
    lines.append("说明: 只降低可控制的本地环境冲突，不承诺账号结果。")
    return "\n".join(lines)


def check_is_blocking_failure(check: CheckResult) -> bool:
    return check.blocking and check.status in (Status.FAIL, Status.ERROR)
