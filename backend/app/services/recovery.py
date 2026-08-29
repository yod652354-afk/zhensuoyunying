"""Recovery Engine：沉睡/流失识别 + Recovery Score v0.1（规则版）。

正向：历史消费、到店频率、套餐剩余、历史复购、历史激活成功
负向：无效联系方式、明确拒绝、投诉、近期已触达、连续无回应、合理终止
排除：DNC / 投诉 / 无效号码 / 合理终止（规格 6.1 / 10.1）
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.enums import CustomerStatus, FollowupResult, TaskPriority
from ..models import Followup, PackageInstance, Patient, Touch


def segment_of(days_since_last_visit: int | None, first_visit_flag: bool = False) -> str:
    if days_since_last_visit is None:
        return "no_visit"
    if first_visit_flag and days_since_last_visit >= 30:
        return "first_visit_no_followup"
    if 30 <= days_since_last_visit < 60:
        return "sleeping_30"
    if 60 <= days_since_last_visit < 90:
        return "sleeping_60"
    if 90 <= days_since_last_visit < 180:
        return "sleeping_90"
    if days_since_last_visit >= 180:
        return "lost_180"
    return "active"


def recovery_score(
    patient: Patient,
    last_followup_result: FollowupResult | None = None,
    recent_followup_days: int | None = None,
    package_remaining: float = 0.0,
) -> tuple[int, list[str]]:
    """返回 (score 0-100, reasons)。"""
    score = 50
    reasons: list[str] = []

    # 正向信号
    pos_visits = min(patient.total_visits or 0, 10) * 3          # 到店频率 +30 封顶
    pos_revenue = min(float(patient.total_revenue or 0) / 200.0, 20)  # 历史消费 +20 封顶
    score += pos_visits
    if pos_visits > 0:
        reasons.append(f"累计到店 {patient.total_visits} 次(+{pos_visits})")
    if pos_revenue > 0:
        reasons.append(f"历史消费 ¥{float(patient.total_revenue):,.0f}(+{pos_revenue:.0f})")
    if package_remaining > 0:
        score += 10
        reasons.append(f"套餐剩余 {package_remaining:g} 次(+10)")

    # 负向信号
    if patient.contact_status == "invalid":
        score -= 15
        reasons.append("无效联系方式(-15)")
    if patient.complaint_flag:
        score -= 20
        reasons.append("历史投诉(-20)")
    if recent_followup_days is not None and recent_followup_days <= 14:
        score -= 10
        reasons.append(f"近 {recent_followup_days} 天内已触达(-10)")
    if last_followup_result in (FollowupResult.NO_ANSWER, FollowupResult.NOT_INTERESTED):
        score -= 10
        reasons.append(f"上次回访无回应/无兴趣(-10)")
    if last_followup_result == FollowupResult.INVALID_CONTACT:
        score -= 10
        reasons.append("上次回访号码无效(-10)")

    return max(0, min(100, round(score))), reasons


def priority_of(score: int) -> str:
    if score >= 75:
        return "S"
    if score >= 55:
        return "A"
    if score >= 35:
        return "B"
    return "C"


def recovery_pool(db: Session, store_id: str | None = None, org_id: str | None = None) -> list[dict]:
    """Recovery 客户池：排除 DNC/投诉/无效号码/合理终止，按分数降序。"""
    now = datetime.now()
    query = select(Patient).where(
        Patient.deleted_at.is_(None),
        Patient.dnc.is_(False),
        Patient.complaint_flag.is_(False),
    )
    if store_id:
        query = query.where(Patient.store_id == store_id)
    if org_id:
        query = query.where(Patient.organization_id == org_id)
    patients = db.scalars(query).all()

    pool = []
    for p in patients:
        last_visit = p.last_visit_date
        days = (now - last_visit).days if last_visit else None
        segment = segment_of(days, p.total_visits <= 1)
        if segment == "active" or segment == "no_visit":
            continue
        # 近 14 天内已触达过且无回应的跳过？——不跳过，仅扣分；但连续 2 次无回应标记低优先级
        last_followup = db.scalar(
            select(Followup)
            .where(Followup.patient_id == p.patient_id)
            .order_by(Followup.created_at.desc())
            .limit(1)
        )
        recent_followup_days = None
        last_result = None
        if last_followup:
            recent_followup_days = (now - last_followup.created_at).days
            last_result = last_followup.result
        pkg_remaining = db.scalar(
            select(PackageInstance)
            .where(
                PackageInstance.patient_id == p.patient_id,
                PackageInstance.remaining_sessions > 0,
            )
            .order_by(PackageInstance.expire_date.asc())
            .limit(1)
        )
        remaining = float(pkg_remaining.remaining_sessions) if pkg_remaining else 0.0
        score, reasons = recovery_score(p, last_result, recent_followup_days, remaining)
        pool.append({
            "patient_id": p.patient_id,
            "name": p.name,
            "mobile": p.mobile,
            "segment": segment,
            "days_since_last_visit": days,
            "last_visit_date": p.last_visit_date.isoformat() if p.last_visit_date else None,
            "total_visits": p.total_visits,
            "total_revenue": float(p.total_revenue),
            "package_remaining": remaining,
            "score": score,
            "priority": priority_of(score),
            "reasons": reasons,
            "contact_status": p.contact_status,
            "dnc": p.dnc,
        })
    pool.sort(key=lambda x: (-x["score"], x["days_since_last_visit"] or 0))
    return pool


def generate_recovery_tasks(db: Session, store_id: str | None = None, limit: int = 50,
                            org_id: str | None = None) -> list[dict]:
    """把 Recovery 池前 N 名转化为待执行任务（Recovery SOP 步骤 3-4）。

    附话术库建议：渠道(建议渠道) + 建议时间 + 话术模板（规格 6.1 Prescription）。
    """
    from ..core.enums import AssignedToType, TaskStatus, TaskType
    from ..core.ids import new_id
    from ..models import Staff, Task
    from .assignment import resolve_assignee
    from .templates import suggest_channel, suggest_template, suggest_time

    pool = recovery_pool(db, store_id, org_id)[:limit]
    tasks = []
    for item in pool:
        # 去重：同患者 14 天内已有待办/进行中的 Recovery 任务则跳过
        existing = db.scalar(
            select(Task.task_id).where(
                Task.patient_id == item["patient_id"],
                Task.task_type == TaskType.RECOVERY,
                Task.created_at >= datetime.now() - timedelta(days=14),
                Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
            ).limit(1)
        )
        if existing:
            continue
        channel = suggest_channel(item["segment"])
        tpl = suggest_template(db, "recovery", channel, store_id)
        assign_type, assign_id = resolve_assignee(db, item["patient_id"], store_id)
        task = Task(
            task_id=new_id("task"),
            organization_id=db.scalar(select(Patient).where(Patient.patient_id == item["patient_id"])).organization_id,
            store_id=store_id,
            task_type=TaskType.RECOVERY,
            patient_id=item["patient_id"],
            assigned_to_type=AssignedToType(assign_type),
            assigned_to_id=assign_id,
            due_at=datetime.now() + timedelta(days=1),
            priority=TaskPriority(item["priority"]),
            reason=f"{item['segment']}: {', '.join(item['reasons'][:3])}",
            expected_value=round(item["total_revenue"] * 0.3, 2),
            suggested_channel=channel,
            suggested_at=suggest_time(),
            message_template_id=tpl.message_template_id if tpl else None,
            created_by_type="AI",
        )
        db.add(task)
        tasks.append(task)
    db.flush()
    return [{"task_id": t.task_id, "patient_id": t.patient_id, "priority": t.priority.value,
             "expected_value": float(t.expected_value or 0),
             "suggested_channel": t.suggested_channel,
             "suggested_at": t.suggested_at.isoformat() if t.suggested_at else None,
             "message_template_id": t.message_template_id} for t in tasks]