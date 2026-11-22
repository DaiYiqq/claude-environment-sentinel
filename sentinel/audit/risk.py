"""Risk weights, score and the safe-start gate.

Weight rationale (also kept here so reviewers can audit the model):

High weights — direct, hard-to-explain conflicts between the local profile and
the network exit:
  A8=9   UTC offset mismatch is the clearest time-zone lie.
  A9=8   Language/region conflict is visible in nearly every request surface.
  A5=7   Without a known exit country the whole comparison is ungrounded.
  A11=7  A configured-but-dead proxy is a direct leak path.
  A1=6   The base system zone must be readable for any alignment.
  A12=6  A proxy/TUN split can make different Claude clients exit differently.

Medium weights — meaningful environment consistency signals:
  A2=5, A4=5, A6=5, A7=5, A10=5, A16=5, A17=5.

Lower weights — indirect or noisy signals:
  A3=4, A13=4, A14=4, A18=4, A19=4.
  A15=3 (font fingerprint is weak), A20=3 (drift is a trend signal).

Scoring: PASS contributes 0, WARN contributes 0.35 of its weight, FAIL/ERROR
contributes its full weight.  The result is normalized to 0–100 over the sum
of weights (104).  A block-fail is enforced independently of the score so a
single critical failure cannot be averaged away by many passes.
"""

from __future__ import annotations

from sentinel.models import CheckResult, GateResult, Status

WEIGHTS: dict[str, int] = {
    "A1": 6,
    "A2": 5,
    "A3": 4,
    "A4": 5,
    "A5": 7,
    "A6": 5,
    "A7": 5,
    "A8": 9,
    "A9": 8,
    "A10": 5,
    "A11": 7,
    "A12": 6,
    "A13": 4,
    "A14": 4,
    "A15": 3,
    "A16": 5,
    "A17": 5,
    "A18": 4,
    "A19": 4,
    "A20": 3,
}

# A FAIL/ERROR on these checks blocks safe start even if the weighted score is
# below 60.  WARN never blocks by itself.
BLOCKING: dict[str, bool] = {
    "A1": True,
    "A2": True,
    "A3": True,
    "A4": True,
    "A5": True,
    "A6": True,
    "A7": True,
    "A8": True,
    "A9": True,
    "A10": True,
    "A11": True,
    "A12": False,  # only when settings.require_tun turns a missing TUN into FAIL
    "A13": False,
    "A14": True,
    "A15": False,
    "A16": True,
    "A17": True,
    "A18": False,
    "A19": True,
    "A20": False,
}

TOTAL_WEIGHT = sum(WEIGHTS.values())
WARN_FACTOR = 0.35
RISK_BLOCK_THRESHOLD = 60


def compute_risk_score(checks: list[CheckResult]) -> int:
    weighted = 0.0
    for check in checks:
        weight = WEIGHTS.get(check.id, max(1, check.weight))
        if check.status is Status.PASS:
            factor = 0.0
        elif check.status is Status.WARN:
            factor = WARN_FACTOR
        else:
            factor = 1.0
        weighted += weight * factor
    if TOTAL_WEIGHT <= 0:
        return 0
    return max(0, min(100, round(100 * weighted / TOTAL_WEIGHT)))


def build_gate(
    checks: list[CheckResult],
    risk_score: int,
    *,
    launch_configured: bool,
    killswitch_ready: bool,
    killswitch_reason: str = "",
    extra_reasons: list[str] | None = None,
) -> GateResult:
    blocking = [c for c in checks if c.blocking and c.status in (Status.FAIL, Status.ERROR)]
    reasons: list[str] = list(extra_reasons or [])
    if risk_score >= RISK_BLOCK_THRESHOLD:
        reasons.append(f"风险分 {risk_score} ≥ {RISK_BLOCK_THRESHOLD}，安全启动已禁用。")
    for check in blocking:
        reasons.append(f"{check.id} {check.title}：{check.summary}")
    if not launch_configured:
        reasons.append("未配置可执行的 Claude 启动命令；请在专家模式中指定 CLI 或桌面客户端路径。")
    if not killswitch_ready:
        reasons.append(killswitch_reason or "Kill-Switch 后端不可用，无法确认安全启动后的网络隔离。")
    return GateResult(
        allowed=not reasons,
        reasons=reasons,
        risk_score=risk_score,
        blocking_ids=[c.id for c in blocking],
        launch_configured=launch_configured,
        killswitch_ready=killswitch_ready,
    )
