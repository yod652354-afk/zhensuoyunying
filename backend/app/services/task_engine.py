"""经营任务引擎：把 Retention/Growth 预警自动转化为可执行任务（规格 10.2 SOP）。

三大自动闭环：
1) No-show 挽回：appointment.no_show → 挽回任务（电话/企微）
2) 超期复诊：plan 窗口已过且未到店 → 复诊提醒任务
3) 疗程中断：active plan 超期 + 套餐剩余 > 0 → Recovery 任务

去重：同一 患者+类型+原因 近 14 天已有任务则跳过。
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.enums import AppointmentStatus, AssignedToType, TaskPriority, TaskStatus, TaskType
from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..models import Appointment, PackageInstance, Patient, Staff, Task, TreatmentPlan
from .retention import overdue_revisits
from .templates import suggest_channel, suggest_template, suggest_time


def _staff_for(db: Session, store_id: str | None) -> str:
    """按 谁看诊谁负责 + 负载均衡 分配执行人。"""
    from .assignment import resolve_assignee
    _, assign_id = resolve_assignee(db, None, store_id)
    return assign_id


def _recent_task_exists(db: Session, patient_id: str, task_type: str, reason: str) -> bool:
    since = utcnow() - timedelta(days=14)
    return db.scalar(
        select(Task.task_id).where(
            Task.patient_id == patient_id,
            Task.task_type == task_type,
            Task.reason == reason,
            Task.created_at >= since,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
        ).limit(1)
    ) is not None


def _make_task(db: Session, organization_id: str, store_id: str | None,
               task_type: str, patient_id: str, reason: str, priority: str,
               expected_value: float | None = None, staff_id: str | None = None) -> Task | None:
    if _recent_task_exists(db, patient_id, task_type, reason):
        return None
    from .assignment import resolve_assignee
    assign_type, assign_id = resolve_assignee(db, patient_id, store_id)
    t = Task(
        task_id=new_id("task"),
        organization_id=organization_id,
        store_id=store_id,
        task_type=task_type,
        patient_id=patient_id,
        assigned_to_type=AssignedToType(assign_type),
        assigned_to_id=staff_id or assign_id,
        due_at=utcnow() + timedelta(days=1),
        priority=priority,
        reason=reason,
        expected_value=expected_value,
        suggested_channel=suggest_channel(reason),
        suggested_at=suggest_time(),
        message_template_id=(
            tpl.message_template_id if (tpl := suggest_template(db, task_type, suggest_channel(reason), store_id)) else None
        ),
        created_by_type="AI",
    )
    db.add(t)
    return t


def run_retention_engine(db: Session, store_id: str | None = None,
                         org_id: str | None = None) -> dict:
    """扫描 No-show / 超期复诊 / 疗程中断并生成任务。"""
    created: list[dict] = []
    org_ids: dict[str, str] = {}

    def org_of(patient_id: str) -> str:
        if patient_id not in org_ids:
            p = db.get(Patient, patient_id)
            org_ids[patient_id] = p.organization_id if p else ""
        return org_ids[patient_id]

    # 1) No-show 挽回
    no_show_q = select(Appointment).where(
        Appointment.status == AppointmentStatus.NO_SHOW,
        Appointment.deleted_at.is_(None),
    )
    if org_id:
        no_show_q = no_show_q.where(Appointment.organization_id == org_id)
    if store_id:
        no_show_q = no_show_q.where(Appointment.store_id == store_id)
    no_shows = db.scalars(no_show_q).all()
    for appt in no_shows:
        t = _make_task(db, org_of(appt.patient_id), store_id or appt.store_id,
                       TaskType.RETENTION, appt.patient_id, "no_show", "A",
                       expected_value=200.0)
        if t:
            created.append({"task_id": t.task_id, "patient_id": t.patient_id, "reason": "no_show"})

    # 2) 超期复诊
    for item in overdue_revisits(db, store_id, org_id=org_id):
        t = _make_task(db, org_of(item["patient_id"]), store_id,
                       TaskType.RETENTION, item["patient_id"], "overdue_revisit", "A",
                       expected_value=300.0)
        if t:
            created.append({"task_id": t.task_id, "patient_id": t.patient_id, "reason": "overdue_revisit"})

    # 3) 疗程中断（超期 + 套餐剩余）
    today = utcnow().date()
    plan_q = select(TreatmentPlan).where(
        TreatmentPlan.plan_status == "active",
        TreatmentPlan.recommended_next_visit_max_date.isnot(None),
        TreatmentPlan.recommended_next_visit_max_date < today,
    )
    if org_id:
        plan_q = plan_q.where(TreatmentPlan.organization_id == org_id)
    if store_id:
        plan_q = plan_q.where(TreatmentPlan.store_id == store_id)
    plans = db.scalars(plan_q).all()
    for plan in plans:
        pkg = db.scalar(
            select(PackageInstance).where(
                PackageInstance.patient_id == plan.patient_id,
                PackageInstance.remaining_sessions > 0,
                PackageInstance.status == "active",
            ).limit(1)
        )
        if pkg is None:
            continue
        t = _make_task(db, org_of(plan.patient_id), store_id,
                       TaskType.RECOVERY, plan.patient_id, "treatment_interruption", "S",
                       expected_value=float(pkg.remaining_sessions) * 150.0)
        if t:
            created.append({"task_id": t.task_id, "patient_id": t.patient_id, "reason": "treatment_interruption"})

    db.commit()
    return {"created": len(created), "tasks": created}