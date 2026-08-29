"""Decision Engine（规格 03 §10 / 总体规格 §6.4）。

V1 为规则决策，不引入复杂 Agent 框架。
输出标准 Decision：是否执行、为什么、推荐动作、工作流、渠道、建议时间、
内容策略、是否必须人工审核、执行负责人、停止条件、升级人工条件。

AI 只能从系统允许的动作集合中选择，不得绕过规则。
"""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import PsychologyStrategy
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Patient
from ...models.revos import ContextSnapshot, Decision, Opportunity
from .psychology import StrategyTendency, select_strategy

DECISION_POLICY_VERSION = "decision_policy_v1"

# 系统允许的动作白名单（Decision 只能从中选择）
ALLOWED_ACTIONS = [
    "generate_content",      # 生成内容草稿
    "create_send_task",      # 创建员工发送任务（企微人工确认）
    "assign_plan",           # 分配执行方案
    "suppress",              # 抑制机会
    "record_outcome",        # 记录结果
]

# 渠道白名单
ALLOWED_CHANNELS = ["enterprise_wechat", "wechat", "phone", "sms"]

# 停止条件（任何命中即停止）
STOP_CONDITIONS = ["dnc", "complaint", "consent_denied", "opportunity_expired",
                   "customer_converted", "invalid_contact", "frequency_limit"]

# 升级人工条件
ESCALATION_CONDITIONS = ["risk_blocked", "high_value_opportunity", "customer_complaint"]


@dataclass
class DecisionOutput:
    execute: bool
    rationale: str
    selected_action: str
    candidates: list[dict] = field(default_factory=list)
    channel: str | None = None
    timing: str | None = None
    strategy: StrategyTendency | None = None
    requires_human_review: bool = True
    confidence: float = 0.5
    stop_conditions: list[str] = field(default_factory=lambda: list(STOP_CONDITIONS))
    escalation_conditions: list[str] = field(default_factory=lambda: list(ESCALATION_CONDITIONS))


def decide(
    db: Session,
    opportunity: Opportunity,
    strategy: StrategyTendency | None = None,
    shadow: bool = False,
    force_execute: bool = False,
) -> DecisionOutput:
    """规则决策：机会 → 动作/渠道/时机/策略（默认必须人工审核）。"""
    if opportunity.experiment_group == "control":
        return DecisionOutput(execute=False, rationale="对照组不得生成真实外部触达",
                              selected_action="suppress")
    if opportunity.status.value in ("suppressed", "expired", "won", "lost"):
        return DecisionOutput(execute=False, rationale=f"机会状态 {opportunity.status.value} 不可执行",
                              selected_action="suppress")

    patient = db.get(Patient, opportunity.patient_id) if opportunity.patient_id else None
    if patient is None:
        return DecisionOutput(execute=False, rationale="客户档案缺失", selected_action="suppress")

    if strategy is None:
        strategy = select_strategy(db, patient, opportunity.context_snapshot)

    # 候选方案（2-3 个）
    candidates = [
        {"action": "generate_content", "channel": "enterprise_wechat",
         "rationale": "首触达：生成文案并经人工审核后由员工企微发送"},
        {"action": "create_send_task", "channel": "enterprise_wechat",
         "rationale": "已有模板兜底：直接创建员工确认发送任务"},
        {"action": "assign_plan", "channel": "phone",
         "rationale": "高价值客户：电话关怀 + 预约引导（人工执行）"},
    ]
    selected = candidates[0]
    requires_review = True  # 大健康场景外部触达默认人工审核
    if opportunity.priority_score >= 90:
        selected = candidates[2]
        requires_review = True  # 高价值仍须审核

    confidence = round(min(0.9, 0.4 + float(opportunity.probability or 0) * 0.5
                           + (strategy.confidence or 0) * 0.3), 4)
    output = DecisionOutput(
        execute=True,
        rationale=(f"机会 {opportunity.opportunity_id[:8]}（{opportunity.money_type.value}钱/"
                   f"{opportunity.scenario_type.value}）优先级 {opportunity.priority_score}；"
                   f"策略 {strategy.strategy.value}：{strategy.rationale}"),
        selected_action=selected["action"],
        candidates=candidates,
        channel=selected["channel"],
        timing="workday_10_11" if opportunity.money_type.value == "past" else "workday_16_17",
        strategy=strategy,
        requires_human_review=requires_review,
        confidence=confidence,
    )
    return output


def persist_decision(db: Session, opportunity: Opportunity, output: DecisionOutput,
                     shadow: bool = False, causation_event_id: str | None = None) -> Decision:
    """落库 Decision + ContextSnapshot（冻结决策时刻上下文）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    patient = db.get(Patient, opportunity.patient_id) if opportunity.patient_id else None
    from .common import enum_value
    snapshot = ContextSnapshot(
        snapshot_id=new_id("context_snapshot"),
        organization_id=opportunity.organization_id,
        opportunity_id=opportunity.opportunity_id,
        customer_id=opportunity.customer_id,
        lifecycle_state=enum_value(opportunity.lifecycle_state),
        money_state=enum_value(opportunity.money_type),
        value_tier=str(opportunity.priority_score)[:2],
        risk_flags=[],
        snapshot=opportunity.context_snapshot or {},
        rule_versions={
            "detector": opportunity.detector_version,
            "scoring": opportunity.scoring_version,
            "decision_policy": DECISION_POLICY_VERSION,
            "workflow": opportunity.workflow_code,
        },
    )
    db.add(snapshot)
    decision = Decision(
        decision_id=new_id("decision"),
        organization_id=opportunity.organization_id,
        store_id=opportunity.store_id,
        opportunity_id=opportunity.opportunity_id,
        policy_version=DECISION_POLICY_VERSION,
        candidates=output.candidates,
        selected_action=output.selected_action,
        selected_channel=output.channel,
        selected_timing=output.timing,
        psychology_strategy=output.strategy.strategy if output.strategy else None,
        psychology_evidence={
            "evidence": [s.code for s in (output.strategy.evidence if output.strategy else [])],
            "confidence": output.strategy.confidence if output.strategy else 0,
            "sample_size": output.strategy.sample_size if output.strategy else 0,
            "avoid": output.strategy.avoid if output.strategy else [],
            "rationale": output.strategy.rationale if output.strategy else "",
        },
        confidence=output.confidence,
        requires_human_review=output.requires_human_review,
        stop_conditions=output.stop_conditions,
        escalation_conditions=output.escalation_conditions,
        rationale=output.rationale,
        shadow=shadow,
    )
    db.add(decision)
    db.flush()
    emit(db, "decision.created", decision.organization_id, "decision", decision.decision_id,
         store_id=decision.store_id, patient_id=opportunity.patient_id, actor_type=ActorType.AI,
         correlation_id=opportunity.opportunity_id, causation_id=causation_event_id,
         payload={"selected_action": decision.selected_action, "channel": decision.selected_channel,
                  "requires_human_review": decision.requires_human_review,
                  "psychology_strategy": decision.psychology_strategy.value if decision.psychology_strategy else None,
                  "shadow": shadow})
    return decision
