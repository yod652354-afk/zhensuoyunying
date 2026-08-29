"""客户全生命周期状态机 + 三种钱价值循环（规格 03 §5-6 / 02 目标领域模型）。

每次关键事件实时重算；另有每日补偿重算（recompute_all）。
每次迁移保存：from/to、触发事件、reason_codes、规则版本、时间和脱敏上下文快照。
状态必须有历史表，不能只保存当前值（总体规格 §6.2）。
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import LifecycleState, MoneyState, ValueTier
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Appointment, PackageInstance, Patient, TreatmentPlan, Visit
from ...models.revos import Customer, CustomerStateHistory
from .common import as_utc, ensure_customer, refresh_customer_facts, sync_patient_identity

# 规则版本：状态机逻辑的不可变版本标识（修改规则必须升版）
STATE_RULE_VERSION = "lifecycle_v1"
MONEY_RULE_VERSION = "money_v1"
VALUE_RULE_VERSION = "value_tier_v1"

# 生命周期时间阈值（天）
ACTIVE_WINDOW_DAYS = 60
AT_RISK_DAYS = 90
DORMANT_DAYS = 180
LOST_DAYS = 365

# 价值等级阈值（累计消费）
TIER_THRESHOLDS = [
    (ValueTier.S, 5000),
    (ValueTier.A, 2000),
    (ValueTier.B, 800),
    (ValueTier.C, 200),
]


def compute_value_tier(total_revenue: float) -> ValueTier:
    for tier, threshold in TIER_THRESHOLDS:
        if total_revenue >= threshold:
            return tier
    return ValueTier.D


def _risk_flags(patient: Patient) -> list[str]:
    flags: list[str] = []
    if patient.dnc:
        flags.append("dnc")
    if patient.complaint_flag:
        flags.append("complaint")
    if patient.contact_status == "invalid":
        flags.append("invalid_contact")
    if patient.consent_status == "denied":
        flags.append("consent_denied")
    return flags


def _has_future_appointment(db: Session, patient_id: str, now: datetime) -> bool:
    return db.scalar(
        select(Appointment.appointment_id).where(
            Appointment.patient_id == patient_id,
            Appointment.appointment_at >= now,
            Appointment.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def _has_active_treatment(db: Session, patient_id: str) -> bool:
    return db.scalar(
        select(TreatmentPlan.treatment_plan_id).where(
            TreatmentPlan.patient_id == patient_id,
            TreatmentPlan.plan_status == "active",
            TreatmentPlan.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def _has_active_package(db: Session, patient_id: str) -> bool:
    return db.scalar(
        select(PackageInstance.package_instance_id).where(
            PackageInstance.patient_id == patient_id,
            PackageInstance.remaining_sessions > 0,
            PackageInstance.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def _last_visit(db: Session, patient_id: str) -> datetime | None:
    return db.scalar(
        select(Visit.visit_at).where(
            Visit.patient_id == patient_id,
            Visit.deleted_at.is_(None),
        ).order_by(Visit.visit_at.desc()).limit(1)
    )


def compute_lifecycle(db: Session, patient: Patient, now: datetime | None = None) -> tuple[LifecycleState, list[str]]:
    """基于诊所事实计算生命周期（可解释规则，返回状态 + reason_codes）。"""
    now = now or utcnow()
    reasons: list[str] = []
    if patient.total_visits is None or patient.total_visits <= 0:
        if _has_future_appointment(db, patient.patient_id, now):
            reasons.append("HAS_FUTURE_APPOINTMENT")
            return LifecycleState.BOOKED, reasons
        reasons.append("NO_VISIT_YET")
        return LifecycleState.LEAD, reasons

    last = _last_visit(db, patient.patient_id) or patient.last_visit_date
    days = (as_utc(now) - as_utc(last)).days if last else None

    if days is None:
        return LifecycleState.ACTIVE, ["NO_LAST_VISIT_DATE"]

    if _has_future_appointment(db, patient.patient_id, now):
        reasons.append("HAS_FUTURE_APPOINTMENT")
        return LifecycleState.BOOKED, reasons

    if _has_active_treatment(db, patient.patient_id):
        reasons.append("ACTIVE_TREATMENT")
        return LifecycleState.IN_SERVICE, reasons

    if days <= ACTIVE_WINDOW_DAYS:
        reasons.append(f"VISITED_WITHIN_{ACTIVE_WINDOW_DAYS}_DAYS")
        return LifecycleState.ACTIVE, reasons
    if days <= AT_RISK_DAYS:
        reasons.append("NO_VISIT_60_90_DAYS")
        return LifecycleState.AT_RISK, reasons
    if days <= DORMANT_DAYS:
        reasons.append("NO_VISIT_90_180_DAYS")
        return LifecycleState.DORMANT, reasons
    if days <= LOST_DAYS:
        reasons.append("NO_VISIT_180_365_DAYS")
        return LifecycleState.LOST, reasons
    reasons.append("NO_VISIT_OVER_365_DAYS")
    return LifecycleState.LOST, reasons


def compute_money_state(db: Session, patient: Patient, lifecycle: LifecycleState, now: datetime | None = None) -> tuple[MoneyState, list[str]]:
    """三种钱判断（Opportunity 分类的客户级主状态）。"""
    now = now or utcnow()
    reasons: list[str] = []
    if lifecycle in (LifecycleState.LEAD,):
        return MoneyState.FUTURE, ["LEAD_NOT_CONVERTED"]
    if lifecycle in (LifecycleState.DORMANT, LifecycleState.LOST):
        return MoneyState.PAST, [f"LIFECYCLE_{lifecycle.value.upper()}"]
    if _has_active_treatment(db, patient.patient_id) or _has_active_package(db, patient.patient_id):
        reasons.append("ACTIVE_SERVICE_OR_PACKAGE")
        return MoneyState.CURRENT, reasons
    if lifecycle in (LifecycleState.ACTIVE, LifecycleState.IN_SERVICE,
                     LifecycleState.BOOKED, LifecycleState.REACTIVATED):
        return MoneyState.CURRENT, [f"LIFECYCLE_{lifecycle.value.upper()}"]
    if lifecycle in (LifecycleState.AT_RISK,):
        return MoneyState.PAST, ["AT_RISK_CHURN_RISK"]
    return MoneyState.FUTURE, ["DEFAULT_FUTURE"]


def recompute(
    db: Session,
    customer_id: str,
    trigger_event_id: str | None = None,
    rule_version: str | None = None,
    now: datetime | None = None,
) -> CustomerStateHistory | None:
    """重算客户状态；若发生迁移则追加历史并返回该记录（否则 None）。"""
    now = now or utcnow()
    customer = db.get(Customer, customer_id)
    if customer is None or not customer.patient_id:
        return None
    patient = db.get(Patient, customer.patient_id)
    if patient is None:
        return None

    refresh_customer_facts(db, customer)
    sync_patient_identity(db, customer, patient)

    lifecycle, lc_reasons = compute_lifecycle(db, patient, now)
    money, money_reasons = compute_money_state(db, patient, lifecycle, now)
    tier = compute_value_tier(float(customer.total_revenue or 0))
    flags = _risk_flags(patient)
    all_reasons = lc_reasons + money_reasons

    changed = (
        customer.lifecycle_state != lifecycle
        or customer.money_state != money
        or customer.value_tier != tier
        or customer.risk_flags != flags
    )
    # 首次重算（无历史）必须记录初始迁移
    has_history = db.scalar(
        select(CustomerStateHistory.state_history_id).where(
            CustomerStateHistory.customer_id == customer.customer_id
        ).limit(1)
    ) is not None
    if not changed and has_history:
        return None

    history = CustomerStateHistory(
        state_history_id=new_id("state"),
        organization_id=customer.organization_id,
        store_id=customer.store_id,
        customer_id=customer.customer_id,
        patient_id=customer.patient_id,
        lifecycle_from=customer.lifecycle_state.value if customer.lifecycle_state else None,
        lifecycle_to=lifecycle,
        money_from=customer.money_state.value if customer.money_state else None,
        money_to=money,
        value_tier=tier,
        risk_flags=flags,
        reason_codes=all_reasons,
        effective_from=now,
        trigger_event_id=trigger_event_id,
        rule_version=rule_version or f"{STATE_RULE_VERSION}/{MONEY_RULE_VERSION}",
        snapshot={
            "total_visits": patient.total_visits,
            "total_revenue": float(patient.total_revenue or 0),
            "last_visit_date": patient.last_visit_date.isoformat() if patient.last_visit_date else None,
            "dnc": patient.dnc,
            "complaint": patient.complaint_flag,
        },
    )
    db.add(history)
    customer.lifecycle_state = lifecycle
    customer.money_state = money
    customer.value_tier = tier
    customer.risk_flags = flags
    customer.state_reason_codes = all_reasons
    customer.state_changed_at = now
    db.flush()
    return history


def recompute_all(db: Session, store_id: str | None = None, org_id: str | None = None,
                  limit: int = 5000) -> int:
    """每日补偿重算：为所有活跃客户刷新状态并记录迁移。"""
    query = select(Customer).where(Customer.deleted_at.is_(None))
    if store_id:
        query = query.where(Customer.store_id == store_id)
    if org_id:
        query = query.where(Customer.organization_id == org_id)
    customers = db.scalars(query.limit(limit)).all()
    transitions = 0
    for c in customers:
        if recompute(db, c.customer_id) is not None:
            transitions += 1
    db.commit()
    return transitions


def ensure_all_customers(db: Session, org_id: str | None = None, store_id: str | None = None) -> int:
    """从 Patient 补齐 Customer 档案（批量）。"""
    query = select(Patient).where(Patient.deleted_at.is_(None))
    if store_id:
        query = query.where(Patient.store_id == store_id)
    if org_id:
        query = query.where(Patient.organization_id == org_id)
    patients = db.scalars(query).all()
    created = 0
    for p in patients:
        existing = db.scalar(
            select(Customer.customer_id).where(
                Customer.patient_id == p.patient_id, Customer.deleted_at.is_(None)
            ).limit(1)
        )
        if existing is None:
            ensure_customer(db, p.patient_id)
            created += 1
    db.commit()
    return created
