"""老板端经营驾驶舱（需求规格 11.2）：过去的钱 / 现在的钱 / 未来的钱 + 异常。"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.enums import TaskStatus, TaskType
from ..models import Campaign, Followup, Patient, Task
from .attribution import all_experiments_metrics
from .compliance import list_reviews
from .reports import staff_incentive
from .recovery import recovery_pool
from .retention import due_today_revisits, overdue_revisits, retention_funnel


def dashboard(db: Session, store_id: str | None = None, org_id: str | None = None) -> dict:
    pool = recovery_pool(db, store_id, org_id)

    # ---- 过去的钱 ----
    recoverable = sum(
        float(item["total_revenue"]) * 0.3 for item in pool[:50]
    )
    task_q = select(Task).where(Task.deleted_at.is_(None))
    if org_id:
        task_q = task_q.where(Task.organization_id == org_id)
    if store_id:
        task_q = task_q.where(Task.store_id == store_id)
    recovered_tasks = db.scalars(
        task_q.where(Task.task_type == TaskType.RECOVERY, Task.status == TaskStatus.COMPLETED)
    ).all()
    incremental_recovered = sum(float(t.expected_value or 0) for t in recovered_tasks)
    fu_q = select(Followup).where(Followup.result.isnot(None), Followup.deleted_at.is_(None))
    if org_id:
        fu_q = fu_q.where(Followup.organization_id == org_id)
    if store_id:
        fu_q = fu_q.where(Followup.store_id == store_id)
    followups_done = db.scalars(fu_q).all()
    converted_revenue = sum(float(f.revenue_generated or 0) for f in followups_done)

    # ---- 现在的钱 ----
    due_today = due_today_revisits(db, store_id, org_id)
    overdue = overdue_revisits(db, store_id, org_id)
    funnel = retention_funnel(db, store_id, org_id=org_id)

    # ---- 未来的钱 ----
    camp_q = select(Campaign).where(Campaign.status == "running", Campaign.deleted_at.is_(None))
    if org_id:
        camp_q = camp_q.where(Campaign.organization_id == org_id)
    running_campaigns = db.scalars(camp_q).all()
    growth_tasks = db.scalars(
        task_q.where(Task.task_type == TaskType.GROWTH)
    ).all()
    executed = sum(1 for t in growth_tasks if t.status in (TaskStatus.COMPLETED, TaskStatus.IN_PROGRESS))
    execution_rate = round(executed / len(growth_tasks) * 100, 1) if growth_tasks else 0.0
    expected_growth = sum(
        float(t.expected_value or 0) for t in growth_tasks if t.status == TaskStatus.PENDING
    )

    # ---- 异常 ----
    anomalies = []
    high_value_lost = [i for i in pool if i["segment"] == "lost_180" and i["total_revenue"] >= 500]
    if high_value_lost:
        anomalies.append({
            "type": "high_value_lost",
            "message": f"高价值流失 {len(high_value_lost)} 人（历史消费≥¥500 且超过180天未到店）",
            "severity": "high",
            "sample": [{"patient_id": i["patient_id"], "name": i["name"]} for i in high_value_lost[:5]],
        })
    leak = funnel["leak_nodes"][0] if funnel["leak_nodes"] else None
    if leak and leak["drop"] > 0:
        anomalies.append({
            "type": "funnel_leak",
            "message": f"过程漏斗漏损最大节点：{leak['from']}→{leak['to']}（流失 {leak['drop']} 人）",
            "severity": "medium",
            "sample": leak,
        })
    slow_q = select(Task.assigned_to_id, func.count(Task.task_id)).where(Task.status == TaskStatus.PENDING)
    if org_id:
        slow_q = slow_q.where(Task.organization_id == org_id)
    if store_id:
        slow_q = slow_q.where(Task.store_id == store_id)
    slow_staff = db.execute(slow_q.group_by(Task.assigned_to_id)).all()
    if slow_staff:
        worst = max(slow_staff, key=lambda x: x[1])
        if worst[1] >= 5:
            anomalies.append({
                "type": "staff_backlog",
                "message": f"员工 {worst[0]} 积压任务 {worst[1]} 条未处理",
                "severity": "low",
                "sample": {"assigned_to_id": worst[0], "pending": worst[1]},
            })

    # ---- 本月总结果（规格 11.2）----
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_tasks = db.scalars(task_q.where(Task.created_at >= month_start)).all()
    month_recovery = sum(float(t.expected_value or 0) for t in month_tasks
                         if t.task_type == TaskType.RECOVERY and t.status == TaskStatus.COMPLETED)
    month_retention = sum(float(t.expected_value or 0) for t in month_tasks
                          if t.task_type == TaskType.RETENTION and t.status == TaskStatus.COMPLETED)
    month_growth = sum(float(t.expected_value or 0) for t in month_tasks
                       if t.task_type == TaskType.GROWTH and t.status == TaskStatus.COMPLETED)
    month_total = month_recovery + month_retention + month_growth

    # ---- 员工激励 ----
    incentives = staff_incentive(db, store_id, days=30, org_id=org_id)

    # ---- 内容待审 ----
    pending_reviews = [r for r in list_reviews(db, store_id) if r.status == "pending"]

    return {
        "monthly_summary": {
            "recovery": round(month_recovery, 2),
            "retention": round(month_retention, 2),
            "growth": round(month_growth, 2),
            "total_incremental": round(month_total, 2),
        },
        "staff_incentive": incentives,
        "pending_reviews": len(pending_reviews),
        "past_money": {
            "recoverable_revenue": round(recoverable, 2),
            "incremental_recovered": round(incremental_recovered + converted_revenue, 2),
            "recovery_roi": round((incremental_recovered + converted_revenue) / max(1, recoverable) * 5, 2),
            "pool_size": len(pool),
        },
        "present_money": {
            "due_today": len(due_today),
            "overdue": len(overdue),
            "adjusted_retention_rate": funnel["adjusted_retention_rate"],
            "funnel_leak_top": leak,
        },
        "future_money": {
            "running_campaigns": len(running_campaigns),
            "execution_rate": execution_rate,
            "expected_growth_revenue": round(expected_growth, 2),
        },
        "anomalies": anomalies,
        "experiments": all_experiments_metrics(db, org_id=org_id),
    }