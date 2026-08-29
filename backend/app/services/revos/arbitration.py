"""触达仲裁器（规格 03 §8 / 企微规格 §2.2）。

对同一客户所有 Opportunity 统一处理：
DNC/投诉/授权、近期触达、机会冲突、价值优先级、门店产能、员工负载、
实验组、渠道限制。同一运营周期只产生一个主要外部 ExecutionPlan；
其他机会保留、合并、延后或抑制。对照组不得生成真实外部触达。
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import MoneyType, OpportunityStatus
from ...core.timeutil import utcnow
from ...models import Patient, Task, Touch
from ...models.revos import Opportunity


class ArbitrationDecision:
    """仲裁结果：选中的主机会 + 被抑制/延后清单。"""

    def __init__(self, primary: Opportunity | None, suppressed: list[Opportunity],
                 deferred: list[Opportunity], reasons: list[str]):
        self.primary = primary
        self.suppressed = suppressed
        self.deferred = deferred
        self.reasons = reasons


def _recent_touches(db: Session, patient_id: str, days: int) -> int:
    """近 N 天实际触达数（只统计已发送/已送达/有回执；未确认任务不算触达）。"""
    since = utcnow() - timedelta(days=days)
    t1 = db.scalar(
        select(func.count()).select_from(Touch).where(
            Touch.patient_id == patient_id, Touch.sent_at >= since,
            Touch.deleted_at.is_(None),
        )
    )
    t2 = db.scalar(
        select(func.count()).select_from(Task).where(
            Task.patient_id == patient_id,
            Task.created_at >= since,
            Task.send_status.in_(["sent", "delivered", "responded", "unknown",
                                  "appointment_created", "visited", "paid", "attributed"]),
            Task.deleted_at.is_(None),
        )
    )
    return int(t1 or 0) + int(t2 or 0)


def _staff_today_touches(db: Session, staff_id: str | None, org_id: str) -> int:
    if not staff_id:
        return 0
    today = utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    q = select(func.count()).select_from(Task).where(
        Task.assigned_to_id == staff_id,
        Task.organization_id == org_id,
        Task.created_at >= start,
        Task.deleted_at.is_(None),
    )
    return int(db.scalar(q) or 0)


def _store_today_touches(db: Session, store_id: str | None, org_id: str) -> int:
    today = utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    q = select(func.count()).select_from(Task).where(
        Task.organization_id == org_id,
        Task.created_at >= start,
        Task.deleted_at.is_(None),
    )
    if store_id:
        q = q.where(Task.store_id == store_id)
    return int(db.scalar(q) or 0)


def check_customer_gate(db: Session, opportunity: Opportunity) -> tuple[bool, str]:
    """发送前合规门禁：DNC / 投诉 / 未授权 / 频控。"""
    patient = db.get(Patient, opportunity.patient_id) if opportunity.patient_id else None
    if patient is None:
        return False, "NO_PATIENT"
    if patient.dnc:
        return False, "DNC"
    if patient.complaint_flag:
        return False, "COMPLAINT"
    if patient.consent_status == "denied":
        return False, "CONSENT_DENIED"
    if patient.contact_status == "invalid":
        return False, "INVALID_CONTACT"
    settings = get_settings()
    recent = _recent_touches(db, opportunity.patient_id, settings.revos_touch_frequency_days)
    if recent >= 1:
        return False, "FREQUENCY_LIMIT_14D"
    return True, ""


def arbitrate_customer(db: Session, customer_id: str) -> ArbitrationDecision:
    """对同一客户的所有活动机会统一仲裁：选出一个主要外部计划。"""
    settings = get_settings()
    now = utcnow()
    cycle_start = now - timedelta(days=settings.revos_arbitration_cycle_days)

    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.customer_id == customer_id,
            Opportunity.status.in_([
                OpportunityStatus.CANDIDATE, OpportunityStatus.QUALIFIED,
                OpportunityStatus.APPROVED, OpportunityStatus.EXECUTING,
            ]),
            Opportunity.deleted_at.is_(None),
        ).order_by(Opportunity.priority_score.desc())
    ).all()
    if not opps:
        return ArbitrationDecision(None, [], [], ["NO_ACTIVE_OPPORTUNITY"])

    reasons: list[str] = []
    suppressed: list[Opportunity] = []
    deferred: list[Opportunity] = []

    # 1) 合规排除 + 实验组保护
    eligible: list[Opportunity] = []
    for opp in opps:
        if opp.experiment_group == "control":
            # 对照组保留 approved，但不得生成内容/任务/触达
            if opp.status == OpportunityStatus.APPROVED:
                deferred.append(opp)
                reasons.append(f"CONTROL_GROUP_{opp.opportunity_id[:8]}")
                continue
            opp.status = OpportunityStatus.SUPPRESSED
            opp.suppressed_reason = "对照组不得生成真实外部触达"
            suppressed.append(opp)
            continue
        ok, code = check_customer_gate(db, opp)
        if not ok:
            opp.status = OpportunityStatus.SUPPRESSED
            opp.suppressed_reason = f"合规门禁:{code}"
            suppressed.append(opp)
            reasons.append(f"GATE_{code}_{opp.opportunity_id[:8]}")
            continue
        eligible.append(opp)

    if not eligible:
        db.commit()
        return ArbitrationDecision(None, suppressed, deferred, reasons or ["ALL_GATED"])

    # 2) 产能：门店/员工当日上限
    patient = db.get(Patient, eligible[0].patient_id) if eligible[0].patient_id else None
    store_id = eligible[0].store_id or (patient.store_id if patient else None)
    staff_id = eligible[0].owner_staff_id
    org_id = eligible[0].organization_id
    store_today = _store_today_touches(db, store_id, org_id)
    if store_today >= settings.revos_store_daily_touch_limit:
        for opp in eligible:
            deferred.append(opp)
        db.commit()
        return ArbitrationDecision(None, suppressed, deferred, ["STORE_CAPACITY_FULL"])
    staff_today = _staff_today_touches(db, staff_id, org_id) if staff_id else 0
    if staff_id and staff_today >= settings.revos_staff_daily_touch_limit:
        # 换负责人不可行时延后该员工任务
        reasons.append("STAFF_CAPACITY_FULL")

    # 3) 价值优先级：期望价值 × 概率 - 成本
    def _value(opp: Opportunity) -> float:
        ev = float(opp.expected_revenue or 0) * float(opp.probability or 0) - float(opp.expected_cost or 0)
        return ev + float(opp.priority_score or 0) * 0.5

    eligible.sort(key=_value, reverse=True)
    primary = eligible[0]
    for opp in eligible[1:]:
        opp.status = OpportunityStatus.SUPPRESSED
        opp.suppressed_reason = "同周期仲裁：保留更高价值机会"
        suppressed.append(opp)
        reasons.append(f"ARBITRATED_OUT_{opp.opportunity_id[:8]}")

    primary.status = OpportunityStatus.QUALIFIED if primary.status == OpportunityStatus.CANDIDATE else primary.status
    db.commit()
    reasons.append(f"PRIMARY_{primary.opportunity_id[:8]}")
    return ArbitrationDecision(primary, suppressed, deferred, reasons)
