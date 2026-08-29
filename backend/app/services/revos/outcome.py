"""Outcome 统一服务（规格 03 §15 / 企微规格 §12）。

统一 Outcome：replied / interested / rejected / appointment / visited / paid /
refunded / dnc / complaint / no_response。

支付和退款结果只能来自可信诊所SaaS或服务端回调，不接受客户端伪造。
DNC/投诉 Outcome 会触发机会抑制与告警。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import MatchStatus, OpportunityStatus, OutcomeType
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Patient
from ...models.business import BusinessFact  # noqa: F401
from ...models.revos import ExecutionPlan, Opportunity, Outcome
from .common import ensure_customer

# 允许由“内部同步”写入的结果类型（可信来源）
TRUSTED_SYNC_TYPES = {"appointment", "visited", "paid", "refunded", "no_response", "replied"}
# 客户端可上报的响应类结果
CLIENT_RESPONSE_TYPES = {"replied", "interested", "rejected", "dnc", "complaint", "no_response"}


def record_outcome(
    db: Session,
    opportunity_id: str,
    outcome_type: str,
    source_event_id: str | None = None,
    occurred_at: datetime | None = None,
    revenue_amount: float | None = None,
    metadata: dict | None = None,
    actor: str | None = None,
    causation_event_id: str | None = None,
    allow_client: bool = False,
) -> Outcome:
    """记录统一业务结果（幂等：同一 (opportunity, outcome_type, source_event_id) 去重）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        raise LookupError(f"opportunity {opportunity_id} 不存在")

    if outcome_type in ("paid", "refunded") and allow_client:
        raise PermissionError("支付/退款结果不能由客户端上报")

    # 枚举强制转换（ORM 列内存值若为原始字符串，后续 .value 会失败）
    outcome_type_enum = OutcomeType(outcome_type) if isinstance(outcome_type, str) else outcome_type

    existing = None
    if source_event_id:
        existing = db.scalar(
            select(Outcome).where(
                Outcome.opportunity_id == opportunity_id,
                Outcome.outcome_type == outcome_type,
                Outcome.source_event_id == source_event_id,
            ).limit(1)
        )
        if existing is not None:
            return existing

    occurred = occurred_at or utcnow()
    outcome = Outcome(
        outcome_id=new_id("outcome"),
        organization_id=opportunity.organization_id,
        store_id=opportunity.store_id,
        opportunity_id=opportunity_id,
        execution_plan_id=opportunity_id,  # 占位：下方按方案修正
        customer_id=opportunity.customer_id,
        patient_id=opportunity.patient_id,
        outcome_type=outcome_type_enum,
        source_event_id=source_event_id,
        occurred_at=occurred,
        revenue_amount=Decimal(str(revenue_amount)) if revenue_amount is not None else None,
        meta=metadata or {},
    )
    # 关联当前方案
    plan = db.scalar(
        select(ExecutionPlan).where(
            ExecutionPlan.opportunity_id == opportunity_id,
            ExecutionPlan.deleted_at.is_(None),
        ).order_by(ExecutionPlan.plan_version.desc()).limit(1)
    )
    outcome.execution_plan_id = plan.execution_plan_id if plan else None
    db.add(outcome)
    db.flush()

    # 结果对机会状态的影响
    if outcome_type in ("dnc", "complaint", "rejected"):
        opportunity.status = OpportunityStatus.SUPPRESSED
        opportunity.suppressed_reason = f"客户{outcome_type}"
        opportunity.suppressed_at = utcnow()
    elif outcome_type in ("appointment", "visited", "paid"):
        if opportunity.status not in (OpportunityStatus.WON,):
            opportunity.status = OpportunityStatus.WON if outcome_type == "paid" else OpportunityStatus.EXECUTING
        if outcome_type == "paid":
            opportunity.won_at = occurred
    elif outcome_type == "no_response":
        pass

    emit(db, "outcome.recorded", outcome.organization_id, "outcome", outcome.outcome_id,
         store_id=outcome.store_id, patient_id=outcome.patient_id, actor_type=ActorType.STAFF if actor else ActorType.SYSTEM,
         actor_id=actor, correlation_id=opportunity_id, causation_id=causation_event_id,
         payload={"outcome_type": outcome.outcome_type, "revenue_amount": float(outcome.revenue_amount or 0),
                  "opportunity_status": opportunity.status.value})
    return outcome


def sync_from_trusted_event(
    db: Session,
    event_type: str,
    patient_id: str | None,
    occurred_at: datetime | None = None,
    revenue: float | None = None,
    event_id: str | None = None,
    metadata: dict | None = None,
) -> list[Outcome]:
    """从可信诊所SaaS事件回流（R-01/R-04）。

    正确模型：
    - 业务事实只存一次（BusinessFact）；
    - 所有组（含对照组）的预约/到店/支付/退款都进入 Outcome；
    - 对照组 Outcome 标记 organic（control_observation），不关联执行动作收入贡献；
    - 事实 → 机会匹配产生一个 primary（其余 auxiliary 不重复计收入）；
    - 无法确定归属进入 manual_review，不自动广播。
    """
    from .fact_matching import create_primary_link, match_fact, record_fact

    if patient_id is None:
        return []
    mapping = {
        "appointment.created": ("appointment", None, "appointment"),
        "appointment.completed": ("visited", None, "visit"),
        "visit.completed": ("visited", None, "visit"),
        "payment.completed": ("paid", "revenue", "payment"),
        "refund.completed": ("refunded", "refund", "refund"),
    }
    if event_type not in mapping:
        return []
    otype, money_field, fact_type = mapping[event_type]

    patient = db.get(Patient, patient_id)
    if patient is None:
        return []
    customer = ensure_customer(db, patient_id)
    occurred = occurred_at or utcnow()

    # 1) 业务事实（幂等，只存一次）
    revenue_amount = revenue if money_field == "revenue" else None
    refund_amount = revenue if money_field == "refund" else None
    fact, _replayed = record_fact(
        db,
        organization_id=patient.organization_id,
        fact_type=fact_type,
        source_system="clinicos_saas",
        source_event_id=event_id,
        occurred_at=occurred,
        customer_id=customer.customer_id,
        patient_id=patient_id,
        store_id=patient.store_id,
        revenue_amount=revenue_amount,
        refund_amount=refund_amount,
        data={"event_type": event_type, **(metadata or {})},
    )

    # 2) 机会匹配（含对照组：对照组自然结果也记录，但标记 organic）
    fact = match_fact(db, fact)
    opportunities = db.scalars(
        select(Opportunity).where(
            Opportunity.customer_id == customer.customer_id,
            Opportunity.organization_id == patient.organization_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.status.in_([
                OpportunityStatus.QUALIFIED, OpportunityStatus.APPROVED,
                OpportunityStatus.EXECUTING, OpportunityStatus.WON,
            ]),
        )
    ).all()

    results: list[Outcome] = []
    primary_linked = False
    for opp in opportunities:
        is_control = opp.experiment_group == "control"
        if opp.opportunity_id == fact.matched_opportunity_id:
            # 匹配到的 primary：干预归因（若为对照组则不关联执行贡献）
            link_type = "organic_control" if is_control else "primary"
            is_organic = is_control
        elif is_control:
            # 对照组其他活动机会：记录自然结果（organic）
            link_type = "organic_control"
            is_organic = True
        else:
            # 非匹配活动机会：不广播（跳过），避免一笔支付赢多个机会
            continue

        outcome = _record_outcome_for_opportunity(
            db, opp, otype, event_id, occurred, revenue_amount, refund_amount, metadata,
            fact_id=fact.fact_id, is_organic=is_organic,
        )
        results.append(outcome)
        try:
            create_primary_link(db, fact, opp.opportunity_id, outcome_id=outcome.outcome_id,
                                revenue_attributed=(not is_control),
                                link_type=link_type)
            primary_linked = True
        except Exception:  # noqa: BLE001  唯一冲突（已有 primary）→ 幂等
            db.rollback()
            return results

    if not results and fact.match_status == MatchStatus.MATCHED and fact.matched_opportunity_id:
        # 匹配到已 WON/过期机会（不在活动列表）→ 直接建 Outcome + primary link
        opp = db.get(Opportunity, fact.matched_opportunity_id)
        if opp is not None:
            outcome = _record_outcome_for_opportunity(
                db, opp, otype, event_id, occurred, revenue_amount, refund_amount, metadata,
                fact_id=fact.fact_id, is_organic=(opp.experiment_group == "control"),
            )
            results.append(outcome)
            try:
                create_primary_link(db, fact, opp.opportunity_id, outcome_id=outcome.outcome_id,
                                    revenue_attributed=(opp.experiment_group != "control"))
            except Exception:  # noqa: BLE001
                db.rollback()
    return results


def _record_outcome_for_opportunity(
    db: Session, opp: Opportunity, otype: str, event_id: str | None, occurred: datetime,
    revenue_amount: float | None, refund_amount: float | None, metadata: dict | None,
    fact_id: str | None = None, is_organic: bool = False,
) -> Outcome:
    """为单个机会记录 Outcome（幂等：opportunity/type/source_event 唯一）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType
    outcome_type_enum = OutcomeType(otype) if isinstance(otype, str) else otype
    existing = None
    if event_id:
        existing = db.scalar(
            select(Outcome).where(
                Outcome.opportunity_id == opp.opportunity_id,
                Outcome.outcome_type == outcome_type_enum,
                Outcome.source_event_id == event_id,
            ).limit(1)
        )
        if existing is not None:
            return existing
    outcome = Outcome(
        outcome_id=new_id("outcome"),
        organization_id=opp.organization_id,
        store_id=opp.store_id,
        opportunity_id=opp.opportunity_id,
        execution_plan_id=None,
        customer_id=opp.customer_id,
        patient_id=opp.patient_id,
        outcome_type=outcome_type_enum,
        source_event_id=event_id,
        fact_id=fact_id,
        is_organic=is_organic,
        occurred_at=occurred,
        revenue_amount=Decimal(str(revenue_amount)) if revenue_amount is not None else (
            Decimal("0") if refund_amount is not None else None),
        meta={**(metadata or {}), "refund_amount": refund_amount} if refund_amount is not None else (metadata or {}),
    )
    plan = db.scalar(
        select(ExecutionPlan).where(
            ExecutionPlan.opportunity_id == opp.opportunity_id,
            ExecutionPlan.deleted_at.is_(None),
        ).order_by(ExecutionPlan.plan_version.desc()).limit(1)
    )
    outcome.execution_plan_id = plan.execution_plan_id if plan else None
    db.add(outcome)
    try:
        db.flush()
    except Exception:  # noqa: BLE001  唯一冲突 → 返回已有
        db.rollback()
        existing = db.scalar(
            select(Outcome).where(
                Outcome.opportunity_id == opp.opportunity_id,
                Outcome.outcome_type == outcome_type_enum,
                Outcome.source_event_id == event_id,
            ).limit(1)
        )
        if existing is not None:
            return existing
        raise

    # 结果对机会状态的影响（对照组自然结果同样反映状态，但归因区分 organic）
    if otype in ("dnc", "complaint", "rejected"):
        opp.status = OpportunityStatus.SUPPRESSED
        opp.suppressed_reason = f"客户{otype}"
        opp.suppressed_at = utcnow()
    elif otype in ("appointment", "visited", "paid"):
        if otype == "paid":
            opp.status = OpportunityStatus.WON
            opp.won_at = occurred
        elif opp.status not in (OpportunityStatus.WON, OpportunityStatus.EXECUTING):
            opp.status = OpportunityStatus.EXECUTING

    emit(db, "outcome.recorded", outcome.organization_id, "outcome", outcome.outcome_id,
         store_id=outcome.store_id, patient_id=outcome.patient_id,
         actor_type=ActorType.SYSTEM,
         correlation_id=opp.opportunity_id,
         payload={"outcome_type": outcome.outcome_type, "revenue_amount": float(outcome.revenue_amount or 0),
                  "is_organic": is_organic, "opportunity_status": opp.status.value})
    return outcome


def list_outcomes(db: Session, tenant, opportunity_id: str | None = None,
                  outcome_type: str | None = None, limit: int = 100) -> list[Outcome]:
    query = select(Outcome).where(Outcome.occurred_at.isnot(None))
    query = tenant.scope_query(query, Outcome)
    if opportunity_id:
        query = query.where(Outcome.opportunity_id == opportunity_id)
    if outcome_type:
        query = query.where(Outcome.outcome_type == outcome_type)
    return db.scalars(query.order_by(Outcome.occurred_at.desc()).limit(min(limit, 500))).all()
