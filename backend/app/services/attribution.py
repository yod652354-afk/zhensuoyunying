"""归因与实验：Treatment vs Holdout/Control 增量计算（需求规格 9.1）。

Incremental Lift = Treatment Rate − Control Rate
Incremental Customers = Eligible × Lift
Incremental Revenue = Incremental Customers × 平均归因客单
"""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.enums import ExperimentGroup, PaymentStatus
from ..models import Campaign, CampaignAudience, Experiment, ExperimentAssignment, Payment, Visit
from .significance import experiment_significance


def experiment_metrics(db: Session, experiment_id: str) -> dict:
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        return {"error": "实验不存在"}
    assignments = db.scalars(
        select(ExperimentAssignment).where(ExperimentAssignment.experiment_id == experiment_id)
    ).all()
    control_patients = [a.patient_id for a in assignments if a.group == ExperimentGroup.CONTROL]
    treatment_patients = [a.patient_id for a in assignments if a.group != ExperimentGroup.CONTROL]
    all_patients = control_patients + treatment_patients

    start = exp.start_at or datetime(1970, 1, 1)
    end = exp.end_at or datetime.now()

    def rate_and_revenue(patient_ids: list[str]) -> tuple[float, float, float]:
        if not patient_ids:
            return 0.0, 0.0, 0.0
        visits = db.scalars(
            select(Visit).where(
                Visit.patient_id.in_(patient_ids),
                Visit.visit_at >= start,
                Visit.visit_at <= end,
            )
        ).all()
        visited_patients = {v.patient_id for v in visits}
        rate = len(visited_patients) / len(patient_ids)
        payments = db.scalars(
            select(Payment).where(
                Payment.patient_id.in_(patient_ids),
                Payment.paid_at >= start,
                Payment.paid_at <= end,
                Payment.status == PaymentStatus.SUCCEEDED,
            )
        ).all()
        revenue = sum(float(p.amount) for p in payments)
        return rate, revenue, len(payments)

    c_rate, c_rev, c_pay = rate_and_revenue(control_patients)
    t_rate, t_rev, t_pay = rate_and_revenue(treatment_patients)

    lift = t_rate - c_rate
    eligible = len(treatment_patients)
    incremental_customers = eligible * lift
    avg_ticket = (t_rev / t_pay) if t_pay else 0.0
    incremental_revenue = incremental_customers * avg_ticket
    total_cost = 0.0  # 活动成本见 Campaign.budget/actual_cost，实验层面默认不计
    roi = (incremental_revenue / total_cost) if total_cost > 0 else None

    significance = experiment_significance(eligible, t_rate, len(control_patients), c_rate)
    return {
        "experiment_id": experiment_id,
        "name": exp.name,
        "engine": exp.engine,
        "status": exp.status.value,
        "hypothesis": exp.hypothesis,
        "primary_metric": exp.primary_metric,
        "control": {"n": len(control_patients), "visit_rate": round(c_rate * 100, 2),
                    "revenue": round(c_rev, 2), "payments": c_pay},
        "treatment": {"n": eligible, "visit_rate": round(t_rate * 100, 2),
                      "revenue": round(t_rev, 2), "payments": t_pay},
        "incremental_lift_pp": round(lift * 100, 2),
        "incremental_customers": round(incremental_customers, 2),
        "avg_attributed_ticket": round(avg_ticket, 2),
        "incremental_revenue": round(incremental_revenue, 2),
        "total_cost": round(total_cost, 2),
        "roi": round(roi, 2) if roi is not None else None,
        "significance": significance,
    }


def all_experiments_metrics(db: Session, org_id: str | None = None) -> list[dict]:
    q = select(Experiment).where(Experiment.deleted_at.is_(None))
    if org_id:
        q = q.where(Experiment.organization_id == org_id)
    exps = db.scalars(q).all()
    return [experiment_metrics(db, e.experiment_id) for e in exps]

def campaign_metrics(db: Session, campaign_id: str) -> dict:
    """Campaign 级增量归因：按 campaign_audiences 的 control vs treatment 对比（规格 9 / 6.3）。

    输出：分组回店率、增量 Lift、增量客户、增量收入（同样采用 Treatment−Control 口径）。
    """
    cmp = db.get(Campaign, campaign_id)
    if cmp is None:
        return {"error": "活动不存在"}
    audiences = db.scalars(
        select(CampaignAudience).where(CampaignAudience.campaign_id == campaign_id)
    ).all()
    if not audiences:
        return {"campaign_id": campaign_id, "name": cmp.name if cmp else "",
                "audience_total": 0, "note": "尚无受众（未设置对照组/实验组）"}
    control_ids = [a.patient_id for a in audiences if a.experiment_group == "control"]
    treatment_ids = [a.patient_id for a in audiences if a.experiment_group != "control" and a.experiment_group != "none"]

    start = cmp.start_at or (datetime(1970, 1, 1) if cmp else datetime(1970, 1, 1))
    end = cmp.end_at or datetime.now()

    def rate_and_rev(patient_ids: list[str]) -> tuple:
        if not patient_ids:
            return 0.0, 0.0, 0
        visits = db.scalars(
            select(Visit).where(
                Visit.patient_id.in_(patient_ids),
                Visit.visit_at >= start,
                Visit.visit_at <= end,
            )
        ).all()
        visited = {v.patient_id for v in visits}
        rate = len(visited) / len(patient_ids)
        pays = db.scalars(
            select(Payment).where(
                Payment.patient_id.in_(patient_ids),
                Payment.paid_at >= start,
                Payment.paid_at <= end,
                Payment.status == "succeeded",
            )
        ).all()
        return rate, sum(float(p.amount) for p in pays), len(pays)

    c_rate, c_rev, c_pay = rate_and_rev(control_ids)
    t_rate, t_rev, t_pay = rate_and_rev(treatment_ids)
    lift = t_rate - c_rate
    incremental_customers = len(treatment_ids) * lift
    avg_ticket = (t_rev / t_pay) if t_pay else 0.0
    incremental_revenue = incremental_customers * avg_ticket
    cost = (float(cmp.budget or 0) + float(cmp.actual_cost or 0)) if cmp else 0.0
    significance = experiment_significance(len(treatment_ids), t_rate, len(control_ids), c_rate)
    return {
        "campaign_id": campaign_id,
        "name": cmp.name if cmp else "",
        "status": cmp.status.value if cmp and hasattr(cmp.status, "value") else str(getattr(cmp, "status", "")),
        "audience_total": len(audiences),
        "control": {"n": len(control_ids), "visit_rate": round(c_rate * 100, 2), "revenue": round(c_rev, 2)},
        "treatment": {"n": len(treatment_ids), "visit_rate": round(t_rate * 100, 2), "revenue": round(t_rev, 2)},
        "incremental_lift_pp": round(lift * 100, 2),
        "incremental_customers": round(incremental_customers, 2),
        "avg_attributed_ticket": round(avg_ticket, 2),
        "incremental_revenue": round(incremental_revenue, 2),
        "total_cost": round(cost, 2),
        "roi": round(incremental_revenue / cost, 2) if cost > 0 else None,
        "significance": significance,
    }
