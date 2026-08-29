"""任务分配：谁看诊谁负责（规格 11.1 执行人）。

规则优先级：
1. 患者主诊服务员工（primary_staff_id，在职）
2. 患者主诊医生（primary_doctor_id，在职，医生动作类任务）
3. 同门店在职员工中待办任务最少者（负载均衡）
4. 兜底 unassigned
"""
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.enums import PersonStatus, TaskStatus
from ..models import Doctor, Patient, Staff, Task


def resolve_assignee(db: Session, patient_id: str | None, store_id: str | None = None) -> tuple[str, str]:
    """返回 (assigned_to_type, assigned_to_id)。"""
    # 1) 主诊服务员工
    if patient_id:
        p = db.get(Patient, patient_id)
        if p and p.primary_staff_id:
            s = db.get(Staff, p.primary_staff_id)
            if s and s.status == PersonStatus.ACTIVE and s.deleted_at is None:
                return "staff", s.staff_id
        # 2) 主诊医生
        if p and p.primary_doctor_id:
            d = db.get(Doctor, p.primary_doctor_id)
            if d and d.doctor_status == PersonStatus.ACTIVE:
                return "doctor", d.doctor_id

    # 3) 负载均衡：同门店在职员工，按待办任务数最少优先
    q = select(Staff).where(
        Staff.status == PersonStatus.ACTIVE,
        Staff.deleted_at.is_(None),
    )
    if store_id:
        q = q.where(Staff.store_id == store_id)
    staffs = list(db.scalars(q).all())
    if staffs:
        pending_counts = dict(
            db.execute(
                select(Task.assigned_to_id, func.count(Task.task_id))
                .where(
                    Task.assigned_to_id.in_([s.staff_id for s in staffs]),
                    Task.status.in_([TaskStatus.PENDING, TaskStatus.IN_PROGRESS]),
                    Task.deleted_at.is_(None),
                )
                .group_by(Task.assigned_to_id)
            ).all()
        )
        best = min(staffs, key=lambda s: pending_counts.get(s.staff_id, 0))
        return "staff", best.staff_id

    return "staff", "unassigned"