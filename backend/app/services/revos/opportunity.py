"""Opportunity Engine（规格 03 §7 / 企微规格 §2.3 / 总体规格 §6.3）。

- 统一 Detector 接口：Recovery → past money，Retention → current money，Growth → future money；
- 去重：同一客户同一场景同一有效周期只允许一个活动机会；
- 评分：可解释规则（V1 不调用大模型数值评分）；
- 过期、抑制、重新打开、幂等；
- 实验分组在内容生成前完成（对照组不得触达）。
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import MoneyType, OpportunityScenario, OpportunityStatus, TaskType
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Followup, PackageInstance, Patient, Task, TreatmentPlan, Visit
from ...models.revos import Customer, Opportunity
from .common import as_utc, ensure_customer, refresh_customer_facts, sync_patient_identity
from .customer_state import compute_lifecycle, compute_money_state

DETECTOR_VERSION = "detector_v1"
SCORING_VERSION = "scoring_v1"


@dataclass
class OpportunityCandidate:
    """Detector 输出的标准候选机会（统一结构）。"""

    customer_id: str
    patient_id: str
    organization_id: str
    store_id: str | None
    money_type: MoneyType
    scenario_type: OpportunityScenario
    expected_revenue: float
    priority_score: float
    probability: float
    expected_cost: float
    reason_codes: list[str]
    workflow_code: str
    lifecycle_state: str | None = None
    context: dict = field(default_factory=dict)


class BaseDetector:
    """Detector 基类：只产生候选，不直接创建任务。"""

    money_type: MoneyType = MoneyType.FUTURE
    scenario_type: OpportunityScenario = OpportunityScenario.OTHER
    workflow_code: str = "default_v1"
    version: str = DETECTOR_VERSION

    def detect(self, db: Session, store_id: str | None = None, org_id: str | None = None) -> list[OpportunityCandidate]:
        raise NotImplementedError


class PastMoneyDetector(BaseDetector):
    """过去的钱：高价值沉睡客户召回（复用一期 Recovery 规则语义）。"""

    money_type = MoneyType.PAST
    scenario_type = OpportunityScenario.DORMANT_RECOVERY
    workflow_code = "dormant_recovery_v1"

    def detect(self, db: Session, store_id: str | None = None, org_id: str | None = None) -> list[OpportunityCandidate]:
        settings = get_settings()
        now = utcnow()
        dormant_days = settings.revos_dormant_days
        query = select(Patient).where(
            Patient.deleted_at.is_(None),
            Patient.dnc.is_(False),
            Patient.complaint_flag.is_(False),
            Patient.consent_status.in_(["granted", None]),
        )
        if store_id:
            query = query.where(Patient.store_id == store_id)
        if org_id:
            query = query.where(Patient.organization_id == org_id)
        patients = db.scalars(query).all()

        candidates: list[OpportunityCandidate] = []
        for p in patients:
            last_visit = p.last_visit_date
            if last_visit is None:
                continue
            days = (as_utc(now) - as_utc(last_visit)).days
            if days < dormant_days:
                continue
            reasons = [f"DORMANT_{days}_DAYS"]
            revenue = float(p.total_revenue or 0)
            if revenue >= 5000:
                reasons.append("HIGH_HISTORICAL_REVENUE")
            elif revenue >= 2000:
                reasons.append("MID_HISTORICAL_REVENUE")
            pkg = db.scalar(
                select(PackageInstance).where(
                    PackageInstance.patient_id == p.patient_id,
                    PackageInstance.remaining_sessions > 0,
                    PackageInstance.deleted_at.is_(None),
                ).order_by(PackageInstance.expire_date.asc()).limit(1)
            )
            remaining = float(pkg.remaining_sessions) if pkg else 0.0
            if remaining > 0:
                reasons.append(f"PACKAGE_REMAINING_{int(remaining)}")
            # 近 14 天触达过则扣分（不跳过）
            recent_touch = db.scalar(
                select(Task.task_id).where(
                    Task.patient_id == p.patient_id,
                    Task.created_at >= now - timedelta(days=14),
                    Task.deleted_at.is_(None),
                ).limit(1)
            )
            recent_penalty = 10 if recent_touch else 0
            if recent_touch:
                reasons.append("RECENT_TOUCH_14D")
            contactable = 10 if p.contact_status == "valid" else (5 if not p.contact_status else 0)
            score, _ = score_opportunity(
                historical_value=min(revenue / 5000, 1.0) * 100,
                recency=max(0, 100 - days / 10),
                visit_frequency=min((p.total_visits or 0) / 10, 1.0) * 100,
                unfinished_package=min(remaining / 10, 1.0) * 100,
                historical_response=50,
                contactability=contactable * 10,
                recent_touch_penalty=recent_penalty,
            )
            candidates.append(OpportunityCandidate(
                customer_id="",  # detect 阶段填充
                patient_id=p.patient_id,
                organization_id=p.organization_id,
                store_id=p.store_id,
                money_type=self.money_type,
                scenario_type=self.scenario_type,
                expected_revenue=round(revenue * 0.3, 2),
                priority_score=score,
                probability=0.35,
                expected_cost=5.0,
                reason_codes=reasons,
                workflow_code=self.workflow_code,
                lifecycle_state=str(p.customer_status.value) if p.customer_status else None,
                context={
                    "dormant_days": days,
                    "total_visits": p.total_visits,
                    "total_revenue": revenue,
                    "package_remaining": remaining,
                    "contact_status": p.contact_status,
                },
            ))
        return candidates


class CurrentMoneyDetector(BaseDetector):
    """现在的钱：复诊超期 / No-show / 疗程中断（复用一期 Retention 语义）。"""

    money_type = MoneyType.CURRENT
    scenario_type = OpportunityScenario.OVERDUE_REVISIT
    workflow_code = "overdue_revisit_v1"

    def detect(self, db: Session, store_id: str | None = None, org_id: str | None = None) -> list[OpportunityCandidate]:
        now = utcnow()
        today = now.date()
        query = select(TreatmentPlan).where(
            TreatmentPlan.plan_status == "active",
            TreatmentPlan.deleted_at.is_(None),
        )
        if store_id:
            query = query.where(TreatmentPlan.store_id == store_id)
        if org_id:
            query = query.where(TreatmentPlan.organization_id == org_id)
        plans = db.scalars(query).all()
        candidates: list[OpportunityCandidate] = []
        for pl in plans:
            max_date = pl.recommended_next_visit_max_date
            if max_date is None or max_date >= today:
                continue
            # 已有新到店则跳过
            later = db.scalar(
                select(Visit.visit_id).where(
                    Visit.patient_id == pl.patient_id,
                    Visit.visit_at >= pl.recommended_next_visit_max_date,
                    Visit.deleted_at.is_(None),
                ).limit(1)
            )
            if later:
                continue
            patient = db.get(Patient, pl.patient_id)
            if patient is None or patient.dnc or patient.complaint_flag:
                continue
            overdue = (today - max_date).days
            revenue = float(patient.total_revenue or 0)
            score, _ = score_opportunity(
                historical_value=min(revenue / 5000, 1.0) * 100,
                recency=max(0, 100 - overdue * 2),
                visit_frequency=min((patient.total_visits or 0) / 10, 1.0) * 100,
                unfinished_package=50,
                historical_response=50,
                contactability=50,
            )
            candidates.append(OpportunityCandidate(
                customer_id="",
                patient_id=patient.patient_id,
                organization_id=patient.organization_id,
                store_id=patient.store_id or pl.store_id,
                money_type=self.money_type,
                scenario_type=OpportunityScenario.OVERDUE_REVISIT,
                expected_revenue=round(revenue * 0.15, 2),
                priority_score=score,
                probability=0.45,
                expected_cost=3.0,
                reason_codes=[f"OVERDUE_REVISIT_{overdue}_DAYS", "ACTIVE_TREATMENT_PLAN"],
                workflow_code=self.workflow_code,
                lifecycle_state=str(patient.customer_status.value) if patient.customer_status else None,
                context={"treatment_plan_id": pl.treatment_plan_id, "overdue_days": overdue},
            ))
        return candidates


class FutureMoneyDetector(BaseDetector):
    """未来的钱：转介绍 / 新客激活（Growth 场景扩展，V1 提供基础候选）。"""

    money_type = MoneyType.FUTURE
    scenario_type = OpportunityScenario.REFERRAL
    workflow_code = "referral_v1"

    def detect(self, db: Session, store_id: str | None = None, org_id: str | None = None) -> list[OpportunityCandidate]:
        # V1：高价值活跃客户具备转介绍潜力（不触达，仅进入机会池供运营筛选）
        now = utcnow()
        query = select(Patient).where(
            Patient.deleted_at.is_(None),
            Patient.dnc.is_(False),
            Patient.complaint_flag.is_(False),
            Patient.total_visits >= 3,
            Patient.last_visit_date >= now - timedelta(days=60),
        )
        if store_id:
            query = query.where(Patient.store_id == store_id)
        if org_id:
            query = query.where(Patient.organization_id == org_id)
        patients = db.scalars(query).all()
        candidates: list[OpportunityCandidate] = []
        for p in patients:
            revenue = float(p.total_revenue or 0)
            if revenue < 2000:
                continue
            candidates.append(OpportunityCandidate(
                customer_id="",
                patient_id=p.patient_id,
                organization_id=p.organization_id,
                store_id=p.store_id,
                money_type=self.money_type,
                scenario_type=OpportunityScenario.REFERRAL,
                expected_revenue=round(revenue * 0.2, 2),
                priority_score=60,
                probability=0.2,
                expected_cost=2.0,
                reason_codes=["HIGH_VALUE_ACTIVE", "REFERRAL_POTENTIAL"],
                workflow_code=self.workflow_code,
                lifecycle_state=str(p.customer_status.value) if p.customer_status else None,
                context={"total_visits": p.total_visits, "total_revenue": revenue},
            ))
        return candidates


ALL_DETECTORS: list[BaseDetector] = [
    PastMoneyDetector(),
    CurrentMoneyDetector(),
    FutureMoneyDetector(),
]


def score_opportunity(
    historical_value: float = 0,
    recency: float = 0,
    visit_frequency: float = 0,
    unfinished_package: float = 0,
    historical_response: float = 0,
    contactability: float = 0,
    recent_touch_penalty: float = 0,
    complaint_risk_penalty: float = 0,
) -> tuple[float, dict]:
    """V1 机会评分（规格 2.3）：权重可解释，不调用大模型。"""
    raw = (
        historical_value * 0.30
        + recency * 0.20
        + visit_frequency * 0.15
        + unfinished_package * 0.15
        + historical_response * 0.10
        + contactability * 0.10
        - recent_touch_penalty
        - complaint_risk_penalty
    )
    score = max(0.0, min(100.0, round(raw, 2)))
    breakdown = {
        "historical_value": round(historical_value * 0.30, 2),
        "recency": round(recency * 0.20, 2),
        "visit_frequency": round(visit_frequency * 0.15, 2),
        "unfinished_package": round(unfinished_package * 0.15, 2),
        "historical_response": round(historical_response * 0.10, 2),
        "contactability": round(contactability * 0.10, 2),
        "recent_touch_penalty": recent_touch_penalty,
        "complaint_risk_penalty": complaint_risk_penalty,
        "total": score,
    }
    return score, breakdown


def _has_active_opportunity(db: Session, customer_id: str, scenario: OpportunityScenario,
                            cycle_days: int) -> bool:
    """去重：同一客户同一场景同一有效周期存在活动机会。"""
    since = utcnow() - timedelta(days=cycle_days)
    return db.scalar(
        select(Opportunity.opportunity_id).where(
            Opportunity.customer_id == customer_id,
            Opportunity.scenario_type == scenario,
            Opportunity.status.in_([
                OpportunityStatus.CANDIDATE, OpportunityStatus.QUALIFIED,
                OpportunityStatus.APPROVED, OpportunityStatus.EXECUTING,
            ]),
            Opportunity.detected_at >= since,
            Opportunity.deleted_at.is_(None),
        ).limit(1)
    ) is not None


def run_detection(db: Session, store_id: str | None = None, org_id: str | None = None,
                  scenario: str | None = None, shadow: bool = False) -> dict:
    """运行识别任务：Detector → 客户档案 → 去重 → 落库 → 事件。

    shadow=True 时只记录影子机会（status=suppressed + shadow 标记），不进入正常流程。
    """
    from ...events.bus import emit
    from ...core.enums import ActorType

    settings = get_settings()
    now = utcnow()
    expires_at = now + timedelta(days=settings.revos_opportunity_ttl_days)
    if scenario:
        scenario = scenario.replace("-", "_")  # API 路径用连字符，枚举值用下划线
    detectors = ALL_DETECTORS
    if scenario:
        detectors = [d for d in detectors if d.scenario_type.value == scenario]

    created, duplicates, suppressed = [], [], []
    for detector in detectors:
        for cand in detector.detect(db, store_id, org_id):
            customer = ensure_customer(db, cand.patient_id)
            refresh_customer_facts(db, customer)
            sync_patient_identity(db, customer, db.get(Patient, cand.patient_id))
            cand.customer_id = customer.customer_id
            lifecycle, _ = compute_lifecycle(db, db.get(Patient, cand.patient_id), now)
            money, _ = compute_money_state(db, db.get(Patient, cand.patient_id), lifecycle, now)

            if _has_active_opportunity(db, customer.customer_id, cand.scenario_type,
                                       settings.revos_opportunity_ttl_days):
                duplicates.append({"patient_id": cand.patient_id, "scenario": cand.scenario_type.value})
                continue

            opp = Opportunity(
                opportunity_id=new_id("opportunity"),
                organization_id=cand.organization_id,
                store_id=cand.store_id,
                customer_id=customer.customer_id,
                patient_id=cand.patient_id,
                money_type=cand.money_type,
                scenario_type=cand.scenario_type,
                lifecycle_state=lifecycle,
                status=OpportunityStatus.SUPPRESSED if shadow else OpportunityStatus.CANDIDATE,
                priority_score=Decimal(str(cand.priority_score)),
                expected_revenue=Decimal(str(cand.expected_revenue)),
                probability=Decimal(str(cand.probability)),
                expected_cost=Decimal(str(cand.expected_cost)),
                reason_codes=cand.reason_codes,
                context_snapshot=cand.context,
                detector_version=detector.version,
                scoring_version=SCORING_VERSION,
                workflow_code=cand.workflow_code,
                detected_at=now,
                expires_at=expires_at,
                shadow=shadow,
            )
            db.add(opp)
            db.flush()
            created.append(opp.opportunity_id)
            emit(db, "opportunity.detected", opp.organization_id, "opportunity", opp.opportunity_id,
                 store_id=opp.store_id, patient_id=opp.patient_id, actor_type=ActorType.AI,
                 correlation_id=opp.opportunity_id,
                 payload={"money_type": opp.money_type.value, "scenario_type": opp.scenario_type.value,
                          "priority_score": float(opp.priority_score), "status": opp.status.value,
                          "shadow": shadow})
    db.commit()
    return {"created": len(created), "duplicates": len(duplicates), "suppressed": suppressed,
            "opportunity_ids": created, "duplicate_items": duplicates[:20]}


def qualify_opportunity(db: Session, opportunity_id: str, owner_staff_id: str | None = None) -> Opportunity | None:
    """候选机会合格化（进入评审流程）。"""
    opp = db.get(Opportunity, opportunity_id)
    if opp is None or opp.status != OpportunityStatus.CANDIDATE:
        return None
    opp.status = OpportunityStatus.QUALIFIED
    if owner_staff_id:
        opp.owner_staff_id = owner_staff_id
    db.commit()
    return opp


def suppress_opportunity(db: Session, opportunity_id: str, reason: str, by: str | None = None) -> Opportunity | None:
    """人工抑制（不可恢复为执行）。"""
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        return None
    opp.status = OpportunityStatus.SUPPRESSED
    opp.suppressed_reason = reason
    opp.suppressed_by = by
    opp.suppressed_at = utcnow()
    db.commit()
    return opp


def expire_opportunities(db: Session) -> int:
    """过期未处理机会（每日补偿）。"""
    now = utcnow()
    rows = db.scalars(
        select(Opportunity).where(
            Opportunity.status.in_([OpportunityStatus.CANDIDATE, OpportunityStatus.QUALIFIED]),
            Opportunity.expires_at.isnot(None),
            Opportunity.expires_at < now,
            Opportunity.deleted_at.is_(None),
        )
    ).all()
    for opp in rows:
        opp.status = OpportunityStatus.EXPIRED
    db.commit()
    return len(rows)


def reopen_opportunity(db: Session, opportunity_id: str) -> Opportunity | None:
    """重新打开（例如客户回应后）。"""
    opp = db.get(Opportunity, opportunity_id)
    if opp is None:
        return None
    if opp.status in (OpportunityStatus.EXPIRED, OpportunityStatus.LOST):
        opp.status = OpportunityStatus.CANDIDATE
        opp.expires_at = utcnow() + timedelta(days=get_settings().revos_opportunity_ttl_days)
        db.commit()
    return opp


def list_opportunities(db: Session, tenant, money_type: str | None = None,
                       scenario_type: str | None = None, status: str | None = None,
                       store_id: str | None = None, customer_id: str | None = None,
                       limit: int = 100) -> list[Opportunity]:
    """机会池查询（服务端强制租户 scope）。"""
    query = select(Opportunity).where(Opportunity.deleted_at.is_(None))
    query = tenant.scope_query(query, Opportunity)
    if store_id:
        query = query.where(Opportunity.store_id == store_id)
    if money_type:
        query = query.where(Opportunity.money_type == money_type)
    if scenario_type:
        query = query.where(Opportunity.scenario_type == scenario_type)
    if status:
        query = query.where(Opportunity.status == status)
    if customer_id:
        query = query.where(Opportunity.customer_id == customer_id)
    return db.scalars(query.order_by(Opportunity.priority_score.desc()).limit(min(limit, 500))).all()
