"""业务事实 → 机会匹配（R-04：一笔支付不得广播给全部机会）。

BusinessFact 只存一次（数据库唯一）；匹配只产生一个 primary opportunity，
其他机会辅助关联（不重复计收入）；无法确定进入 manual_review。
"""
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import MatchStatus, OpportunityStatus
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Touch
from ...models.business import BusinessFact, OpportunityOutcomeLink
from ...models.revos import ExecutionPlan, Opportunity

FACT_MATCH_VERSION = "fact_match_v1"

# 事实类型 → 允许的机会场景（不符合该场景的事实不匹配）
SCENARIO_FACT_ALLOWED = {
    "appointment": {"dormant_recovery", "overdue_revisit", "no_show", "followup_care",
                    "treatment_interruption", "new_customer", "referral", "package_renewal"},
    "visit": {"dormant_recovery", "overdue_revisit", "followup_care", "treatment_interruption",
              "new_customer", "referral", "package_renewal"},
    "payment": {"dormant_recovery", "overdue_revisit", "followup_care", "treatment_interruption",
                "new_customer", "referral", "package_renewal"},
    "refund": {"dormant_recovery", "overdue_revisit", "followup_care", "treatment_interruption",
               "new_customer", "referral", "package_renewal"},
}


def record_fact(
    db: Session,
    organization_id: str,
    fact_type: str,
    source_system: str,
    source_event_id: str | None,
    occurred_at: datetime,
    customer_id: str | None = None,
    patient_id: str | None = None,
    store_id: str | None = None,
    revenue_amount: float | None = None,
    refund_amount: float | None = None,
    data: dict | None = None,
) -> tuple[BusinessFact, bool]:
    """写入业务事实（幂等：重复 source 事件返回已有事实）。"""
    if source_event_id:
        existing = db.scalar(
            select(BusinessFact).where(
                BusinessFact.organization_id == organization_id,
                BusinessFact.source_system == source_system,
                BusinessFact.source_event_id == source_event_id,
                BusinessFact.deleted_at.is_(None),
            ).limit(1)
        )
        if existing is not None:
            return existing, True
    fact = BusinessFact(
        fact_id=new_id("fact"),
        organization_id=organization_id,
        store_id=store_id,
        customer_id=customer_id,
        patient_id=patient_id,
        fact_type=fact_type,
        source_system=source_system,
        source_event_id=source_event_id,
        occurred_at=occurred_at,
        revenue_amount=Decimal(str(revenue_amount)) if revenue_amount is not None else None,
        refund_amount=Decimal(str(refund_amount)) if refund_amount is not None else None,
        data=data or {},
        match_status=MatchStatus.UNMATCHED,
        match_version=FACT_MATCH_VERSION,
        confidence=Decimal("0"),
    )
    db.add(fact)
    try:
        db.flush()
    except Exception:  # noqa: BLE001  并发唯一冲突 → 幂等返回已有
        db.rollback()
        if source_event_id:
            existing = db.scalar(
                select(BusinessFact).where(
                    BusinessFact.organization_id == organization_id,
                    BusinessFact.source_system == source_system,
                    BusinessFact.source_event_id == source_event_id,
                ).limit(1)
            )
            if existing is not None:
                return existing, True
        raise
    return fact, False


def _fact_in_window(settings, opp: Opportunity, occurred_at: datetime) -> bool:
    """归因窗口：事件发生在机会检测后、观察窗口内（统一 UTC 比较）。"""
    from .common import as_utc
    occurred = as_utc(occurred_at)
    detected = as_utc(opp.detected_at)
    if occurred < (detected - timedelta(days=1)):
        return False
    window_end = detected + timedelta(days=settings.revos_observation_window_days)
    if occurred > window_end:
        return False
    return True


def _has_executing_plan_or_touch(db: Session, opp: Opportunity, occurred_at: datetime) -> tuple[bool, dict]:
    """主 ExecutionPlan 或有效 Touch 存在且 Touch 早于 Outcome。"""
    plan = db.scalar(
        select(ExecutionPlan).where(
            ExecutionPlan.opportunity_id == opp.opportunity_id,
            ExecutionPlan.deleted_at.is_(None),
            ExecutionPlan.review_status == "approved",
        ).order_by(ExecutionPlan.plan_version.desc()).limit(1)
    )
    if plan is not None:
        return True, {"plan_id": plan.execution_plan_id, "plan_version": plan.plan_version}
    touch = db.scalar(
        select(Touch).where(
            Touch.opportunity_id == opp.opportunity_id,
            Touch.deleted_at.is_(None),
            Touch.sent_at <= occurred_at,
            Touch.send_status.in_(["sent", "delivered", "responded"]),
        ).order_by(Touch.sent_at.desc()).limit(1)
    )
    if touch is not None:
        return True, {"touch_id": touch.touch_id, "sent_at": touch.sent_at.isoformat()}
    return False, {}


def match_fact(db: Session, fact: BusinessFact) -> BusinessFact:
    """把事实匹配到机会（一次事实 → 一个 primary；其余 auxiliary；无匹配进人工队列）。"""
    from ...config import get_settings as _gs
    settings = _gs()
    if fact.customer_id is None:
        fact.match_status = MatchStatus.EXCLUDED
        db.flush()
        return fact

    # 候选：同客户的活动机会
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.customer_id == fact.customer_id,
            Opportunity.organization_id == fact.organization_id,
            Opportunity.deleted_at.is_(None),
            Opportunity.status.in_([
                OpportunityStatus.QUALIFIED, OpportunityStatus.APPROVED,
                OpportunityStatus.EXECUTING, OpportunityStatus.WON,
            ]),
        ).order_by(Opportunity.detected_at.desc())
    ).all()

    # 场景资格
    from .common import enum_value
    allowed_scenarios = SCENARIO_FACT_ALLOWED.get(fact.fact_type, set())
    candidates = []
    for opp in opps:
        if enum_value(opp.scenario_type) not in allowed_scenarios:
            continue
        if not _fact_in_window(settings, opp, fact.occurred_at):
            continue
        has_evidence, evidence = _has_executing_plan_or_touch(db, opp, fact.occurred_at)
        candidates.append((opp, has_evidence, evidence))

    if not candidates:
        fact.match_status = MatchStatus.UNMATCHED
        fact.match_reason = {"reason": "NO_ELIGIBLE_OPPORTUNITY_IN_WINDOW"}
        db.flush()
        return fact

    # primary：优先有执行证据（主 Plan / Touch）的机会；其次最新检测
    eligible = [c for c in candidates if c[1]]
    if not eligible:
        # 有候选但都无执行证据 → 无法确定归属 → 人工归因
        fact.match_status = MatchStatus.MANUAL_REVIEW
        fact.match_reason = {"reason": "NO_EXECUTION_EVIDENCE",
                             "candidates": [o.opportunity_id for o, _, _ in candidates[:10]]}
        db.flush()
        return fact

    primary_opp, _, evidence = eligible[0]
    fact.matched_opportunity_id = primary_opp.opportunity_id
    fact.match_status = MatchStatus.MATCHED
    fact.match_reason = {"reason": "PRIMARY_PLAN_OR_TOUCH", **evidence}
    fact.confidence = Decimal("0.9")
    db.flush()

    # 其余候选 → auxiliary 关联（不重复计收入）
    for opp, _, _ in candidates:
        if opp.opportunity_id == primary_opp.opportunity_id:
            continue
        existing_link = db.scalar(
            select(OpportunityOutcomeLink).where(
                OpportunityOutcomeLink.fact_id == fact.fact_id,
                OpportunityOutcomeLink.opportunity_id == opp.opportunity_id,
                OpportunityOutcomeLink.deleted_at.is_(None),
            ).limit(1)
        )
        if existing_link is None:
            db.add(OpportunityOutcomeLink(
                link_id=new_id("link"),
                organization_id=fact.organization_id,
                store_id=fact.store_id,
                opportunity_id=opp.opportunity_id,
                fact_id=fact.fact_id,
                link_type="auxiliary",
                revenue_attributed=False,
            ))
    return fact


def create_primary_link(db: Session, fact: BusinessFact, opportunity_id: str,
                        outcome_id: str | None = None, revenue_attributed: bool = True,
                        link_type: str = "primary") -> OpportunityOutcomeLink:
    """建立 primary 关联（同 fact 只允许一个 primary，数据库唯一保证）。"""
    link = OpportunityOutcomeLink(
        link_id=new_id("link"),
        organization_id=fact.organization_id,
        store_id=fact.store_id,
        opportunity_id=opportunity_id,
        fact_id=fact.fact_id,
        outcome_id=outcome_id,
        link_type=link_type,
        revenue_attributed=revenue_attributed,
    )
    db.add(link)
    db.flush()
    return link
