"""经营报表：Revenue Leakage Report（规格 19 交付物）+ 数据对账（规格 7）+ 员工激励（规格 11.1）。"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.enums import AppointmentStatus, FollowupResult, TaskStatus, TaskType
from ..models import (
    Appointment, Followup, Order, Patient, Payment, Refund, Task, Visit,
)
from .retention import funnel_by_dimension, retention_funnel


def revenue_leakage_report(db: Session, store_id: str | None = None, days: int = 90,
                           org_id: str | None = None) -> dict:
    """漏损报表：可追回收入、过程漏损金额、按节点/医生/项目分布（规格 8.1 六表 + 11.2）。"""
    from .recovery import recovery_pool
    from .retention import overdue_revisits

    pool = recovery_pool(db, store_id, org_id)
    recoverable = sum(float(i["total_revenue"]) * 0.3 for i in pool)
    high_value = [i for i in pool if i["total_revenue"] >= 500]

    funnel = retention_funnel(db, store_id, days, org_id=org_id)
    overdue = overdue_revisits(db, store_id, org_id=org_id)

    # 按项目大类统计近 90 天收入与复诊
    since = datetime.now() - timedelta(days=days)
    visit_q = select(Visit).where(Visit.visit_at >= since)
    if org_id:
        visit_q = visit_q.where(Visit.organization_id == org_id)
    if store_id:
        visit_q = visit_q.where(Visit.store_id == store_id)
    visits = db.scalars(visit_q).all()
    cat_stats: dict[str, dict] = {}
    for v in visits:
        cat = v.service_category or "未分类"
        g = cat_stats.setdefault(cat, {"category": cat, "visits": 0, "revenue": 0.0})
        g["visits"] += 1
        rev = db.scalar(
            select(func.coalesce(func.sum(Order.final_amount), 0)).where(
                Order.patient_id == v.patient_id,
                Order.created_at >= v.visit_at - timedelta(days=1),
                Order.created_at <= v.visit_at + timedelta(days=1),
            )
        )
        g["revenue"] += float(rev or 0)

    return {
        "window_days": days,
        "recoverable_revenue": round(recoverable, 2),
        "recovery_pool_size": len(pool),
        "high_value_sleeping": len(high_value),
        "leak_by_node": funnel["leak_nodes"],
        "adjusted_retention_rate": funnel["adjusted_retention_rate"],
        "overdue_revisits": len(overdue),
        "overdue_value": round(sum(o.get("overdue_days", 0) for o in overdue) * 80.0, 2),  # 每超期天折算
        "by_category": sorted(cat_stats.values(), key=lambda x: -x["revenue"]),
        "by_doctor": funnel_by_dimension(db, store_id, days, by="doctor", org_id=org_id),
        "by_staff": funnel_by_dimension(db, store_id, days, by="staff", org_id=org_id),
    }


def reconciliation(db: Session, store_id: str | None = None, date_str: str | None = None,
                   org_id: str | None = None) -> dict:
    """数据对账（规格 7）：按门店核对 患者数/到店数/订单金额/退款金额，并定位差异 ID。"""
    day = date_str
    if not day:
        day = datetime.now().strftime("%Y-%m-%d")
    day_start = datetime.fromisoformat(f"{day}T00:00:00")
    day_end = day_start + timedelta(days=1)

    def q_count(model, field, status_field=None, status_val=None):
        stmt = select(func.count()).select_from(model).where(field >= day_start, field < day_end)
        if status_field is not None and status_val is not None:
            stmt = stmt.where(status_field == status_val)
        if org_id and hasattr(model, "organization_id"):
            stmt = stmt.where(model.organization_id == org_id)
        if store_id and hasattr(model, "store_id"):
            stmt = stmt.where(model.store_id == store_id)
        return db.scalar(stmt) or 0

    new_patients = q_count(Patient, Patient.created_at)
    visits = q_count(Visit, Visit.visit_at)
    appts_created = q_count(Appointment, Appointment.created_at)
    appts_completed = q_count(Appointment, Appointment.completed_at, Appointment.status, AppointmentStatus.COMPLETED)
    no_shows = q_count(Appointment, Appointment.appointment_at, Appointment.status, AppointmentStatus.NO_SHOW)
    orders_amount = db.scalar(
        select(func.coalesce(func.sum(Order.final_amount), 0)).where(
            Order.created_at >= day_start, Order.created_at < day_end,
            Order.order_status != "cancelled",
        )
    ) or 0
    payments_amount = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.paid_at >= day_start, Payment.paid_at < day_end, Payment.status == "succeeded",
        )
    ) or 0
    refunds_amount = db.scalar(
        select(func.coalesce(func.sum(Refund.refund_amount), 0)).where(
            Refund.refund_at >= day_start, Refund.refund_at < day_end,
        )
    ) or 0

    # 差异定位：订单金额 vs 支付金额（允许跨日支付差异，列出明细）
    diffs = []
    orders = db.scalars(
        select(Order).where(Order.created_at >= day_start, Order.created_at < day_end)
    ).all()
    for o in orders:
        paid = db.scalar(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.order_id == o.order_id, Payment.status == "succeeded",
            )
        ) or 0
        if abs(float(o.final_amount) - float(paid)) > 0.01:
            diffs.append({"type": "order_payment_mismatch", "order_id": o.order_id,
                          "order_amount": float(o.final_amount), "paid_amount": float(paid)})

    return {
        "date": day,
        "store_id": store_id,
        "counters": {
            "new_patients": new_patients,
            "visits": visits,
            "appointments_created": appts_created,
            "appointments_completed": appts_completed,
            "no_shows": no_shows,
        },
        "amounts": {
            "orders_amount": round(float(orders_amount), 2),
            "payments_amount": round(float(payments_amount), 2),
            "refunds_amount": round(float(refunds_amount), 2),
            "net_revenue": round(float(payments_amount) - float(refunds_amount), 2),
        },
        "differences": diffs,
        "balance_ok": not diffs,
    }


def staff_incentive(db: Session, store_id: str | None = None, days: int = 30,
                    org_id: str | None = None) -> list[dict]:
    """员工激励：有效执行/预约/回店/增量（规格 11.1：显示经营结果，避免只按任务数排名）。"""
    from ..models import Staff

    since = datetime.now() - timedelta(days=days)
    task_q = select(Task).where(Task.created_at >= since, Task.assigned_to_type == "staff")
    if org_id:
        task_q = task_q.where(Task.organization_id == org_id)
    if store_id:
        task_q = task_q.where(Task.store_id == store_id)
    tasks = db.scalars(task_q).all()
    by_staff: dict[str, dict] = {}
    for t in tasks:
        g = by_staff.setdefault(t.assigned_to_id, {
            "staff_id": t.assigned_to_id, "name": t.assigned_to_id,
            "tasks_total": 0, "tasks_completed": 0, "converted": 0,
            "appointments_created": 0, "incremental_value": 0.0,
        })
        g["tasks_total"] += 1
        if t.status == TaskStatus.COMPLETED:
            g["tasks_completed"] += 1
            g["incremental_value"] += float(t.expected_value or 0)
        if t.status == TaskStatus.COMPLETED and t.result and t.result.get("outcome") in ("converted", "appointment_created"):
            g["converted"] += 1
        if t.status == TaskStatus.COMPLETED and t.related_followup_id:
            fu = db.get(Followup, t.related_followup_id)
            if fu and fu.result in (FollowupResult.APPOINTMENT_CREATED, FollowupResult.CONVERTED, FollowupResult.VISITED):
                g["appointments_created"] += 1
                g["incremental_value"] += float(fu.revenue_generated or 0)

    staff_names = {s.staff_id: s.name for s in db.scalars(select(Staff)).all()}
    rows = []
    for g in by_staff.values():
        g["name"] = staff_names.get(g["staff_id"], g["staff_id"])
        g["completion_rate"] = round(g["tasks_completed"] / g["tasks_total"] * 100, 1) if g["tasks_total"] else 0
        g["incremental_value"] = round(g["incremental_value"], 2)
        rows.append(g)
    # 按增量价值排序（不以任务数排名）
    rows.sort(key=lambda x: -x["incremental_value"])
    return rows