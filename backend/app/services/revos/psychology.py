"""消费心理策略引擎（规格 03 §9 / 02 目标领域模型 §消费心理规则）。

基于行为证据输出“策略响应倾向”，禁止人格化和武断标签。
每项策略输出 evidence / confidence / sample_size / avoid。
禁止：虚假稀缺、虚假社会认同、恐惧诱导、高压销售。
"""
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.enums import FollowupResult, PsychologyStrategy
from ...models import Followup, Patient, Touch

PSYCHOLOGY_RULE_VERSION = "psychology_v1"

# 各策略最小证据（行为信号 → 倾向）
STRATEGY_SPECS: dict[PsychologyStrategy, dict] = {
    PsychologyStrategy.DOCTOR_TRUST: {
        "name": "医生信任",
        "signals": ["primary_doctor_exists", "followup_replied", "multiple_visits"],
    },
    PsychologyStrategy.RIGHTS_REMINDER: {
        "name": "权益提醒",
        "signals": ["package_remaining", "expiring_package", "coupon_available"],
    },
    PsychologyStrategy.CONVENIENCE: {
        "name": "便利优先",
        "signals": ["nearby_store", "flexible_hours", "online_booking_used"],
    },
    PsychologyStrategy.RISK_REDUCTION: {
        "name": "风险降低",
        "signals": ["treatment_interrupted", "no_show_history", "refund_history"],
    },
    PsychologyStrategy.CARE_AND_EMPATHY: {
        "name": "关怀共情",
        "signals": ["long_dormant", "complaint_resolved", "post_visit_care"],
    },
    PsychologyStrategy.RECIPROCITY: {
        "name": "互惠",
        "signals": ["past_discount_used", "campaign_participated"],
    },
    PsychologyStrategy.COMMITMENT_CONSISTENCY: {
        "name": "承诺一致",
        "signals": ["treatment_plan_active", "package_installed", "prior_commitments"],
    },
}

# 绝对避免项（生成内容时的硬约束）
AVOID_LIST = [
    "虚假稀缺（如'仅剩X个名额'）",
    "虚假社会认同（如'已有X人参加'）",
    "恐惧诱导（如'再不治疗就晚了'）",
    "高压销售（如'今天必须决定'）",
    "疗效承诺（如'保证治愈''根治'）",
]


@dataclass
class StrategySignal:
    code: str
    present: bool
    detail: str | None = None


@dataclass
class StrategyTendency:
    strategy: PsychologyStrategy
    evidence: list[StrategySignal] = field(default_factory=list)
    confidence: float = 0.0
    sample_size: int = 0
    avoid: list[str] = field(default_factory=lambda: list(AVOID_LIST))
    rationale: str = ""


def collect_signals(db: Session, patient: Patient, context: dict | None = None) -> list[StrategySignal]:
    """收集行为证据（不做人格化标签）。"""
    context = context or {}
    signals: list[StrategySignal] = []
    signals.append(StrategySignal("primary_doctor_exists", bool(patient.primary_doctor_id),
                                  patient.primary_doctor_id or None))
    signals.append(StrategySignal("multiple_visits", (patient.total_visits or 0) >= 2))
    signals.append(StrategySignal("long_dormant", bool(context.get("dormant_days") and context["dormant_days"] >= 90)))
    signals.append(StrategySignal("package_remaining", bool(context.get("package_remaining", 0) > 0)))
    signals.append(StrategySignal("treatment_plan_active", bool(context.get("active_treatment"))))
    signals.append(StrategySignal("online_booking_used", False))  # V1 无数据来源，保持 False
    signals.append(StrategySignal("past_discount_used", False))
    signals.append(StrategySignal("campaign_participated", False))

    last_followup = None
    if patient.patient_id:
        last_followup = db.scalar(
            select(Followup).where(Followup.patient_id == patient.patient_id)
            .order_by(Followup.created_at.desc()).limit(1)
        )
    signals.append(StrategySignal(
        "followup_replied",
        bool(last_followup and last_followup.result in (FollowupResult.REPLIED, FollowupResult.INTERESTED,
                                                        FollowupResult.APPOINTMENT_CREATED)),
    ))
    signals.append(StrategySignal(
        "no_show_history",
        bool(db.scalar(select(func.count()).select_from(Touch).where(
            Touch.patient_id == patient.patient_id,
            Touch.reply_type == "no_show",
        ))) if patient.patient_id else False,
    ))
    return signals


def score_tendencies(db: Session, patient: Patient, context: dict | None = None) -> list[StrategyTendency]:
    """对 7 项策略输出响应倾向（evidence + confidence + sample_size）。"""
    signals = collect_signals(db, patient, context)
    signal_map = {s.code: s for s in signals}
    results: list[StrategyTendency] = []

    def _confidence(present: list[str], total: int) -> float:
        return round(min(0.9, 0.5 + 0.4 * (len(present) / max(total, 1))), 2) if present else 0.15

    for strategy, spec in STRATEGY_SPECS.items():
        present = [c for c in spec["signals"] if signal_map.get(c) and signal_map[c].present]
        evidence = [signal_map[c] for c in spec["signals"] if c in signal_map and signal_map[c].present]
        results.append(StrategyTendency(
            strategy=strategy,
            evidence=evidence,
            confidence=_confidence(present, len(spec["signals"])),
            sample_size=0,  # V1 无历史样本，标记方向性
            rationale=f"{spec['name']}：命中 {len(present)}/{len(spec['signals'])} 个行为信号",
        ))
    results.sort(key=lambda t: -t.confidence)
    return results


def select_strategy(db: Session, patient: Patient, context: dict | None = None) -> StrategyTendency:
    """选择当前最佳策略（最高置信度；同分时优先 care_and_empathy/rights_reminder）。"""
    tendencies = score_tendencies(db, patient, context)
    if not tendencies:
        return StrategyTendency(strategy=PsychologyStrategy.CARE_AND_EMPATHY, confidence=0.2,
                                rationale="无行为证据，使用默认关怀策略")
    best = tendencies[0]
    # 同置信度偏好稳定策略
    tie = [t for t in tendencies if abs(t.confidence - best.confidence) < 0.01]
    if len(tie) > 1:
        order = {PsychologyStrategy.CARE_AND_EMPATHY: 0, PsychologyStrategy.RIGHTS_REMINDER: 1,
                 PsychologyStrategy.DOCTOR_TRUST: 2, PsychologyStrategy.CONVENIENCE: 3,
                 PsychologyStrategy.RISK_REDUCTION: 4, PsychologyStrategy.RECIPROCITY: 5,
                 PsychologyStrategy.COMMITMENT_CONSISTENCY: 6}
        tie.sort(key=lambda t: order.get(t.strategy, 9))
        best = tie[0]
    return best
