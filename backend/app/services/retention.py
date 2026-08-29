"""Retention Engine：诊后过程漏斗 + 复诊预警（需求规格 6.2 / 10.2）。

漏斗节点：建议 → 交接 → 当场预约 → 预约提醒 → 履约 → 二次干预 → 最终复诊
（MVP 以 建议→预约→履约→复诊 为核心可计算节点）
"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.enums import AppointmentStatus, TreatmentPlanStatus, VisitType
from ..models import Appointment, CareRecommendation, Doctor, Followup, Patient, TreatmentPlan, Visit


def retention_funnel(db: Session, store_id: str | None = None, days: int = 90,
                     org_id: str | None = None) -> dict:
    """统计窗口内初诊/复诊的过程漏斗。"""
    since = datetime.now() - timedelta(days=days)
    base_q = select(Visit).where(Visit.visit_at >= since)
    if store_id:
        base_q = base_q.where(Visit.store_id == store_id)
    if org_id:
        base_q = base_q.where(Visit.organization_id == org_id)
    visits = db.scalars(base_q).all()

    total = len(visits)
    with_rec = 0
    rec_ids = []
    for v in visits:
        rec = db.scalar(
            select(CareRecommendation).where(CareRecommendation.visit_id == v.visit_id).limit(1)
        )
        if rec and rec.next_visit_recommended:
            with_rec += 1
            rec_ids.append(rec.care_recommendation_id)

    # 有建议的 visit 中：已建预约 / 预约履约 / 实际复诊
    appointed = 0
    fulfilled = 0
    revisited = 0
    appt_q = select(Appointment).where(Appointment.patient_id.in_([v.patient_id for v in visits]))
    if store_id:
        appt_q = appt_q.where(Appointment.store_id == store_id)
    for v in visits:
        rec = db.scalar(
            select(CareRecommendation).where(CareRecommendation.visit_id == v.visit_id).limit(1)
        )
        if not (rec and rec.next_visit_recommended):
            continue
        appt = db.scalar(
            select(Appointment)
            .where(
                Appointment.patient_id == v.patient_id,
                Appointment.appointment_at >= v.visit_at,
            )
            .order_by(Appointment.appointment_at.asc())
            .limit(1)
        )
        if appt is not None:
            appointed += 1
            if appt.status == AppointmentStatus.COMPLETED:
                fulfilled += 1
        later_visit = db.scalar(
            select(Visit).where(
                Visit.patient_id == v.patient_id,
                Visit.visit_at > v.visit_at,
            ).limit(1)
        )
        if later_visit is not None:
            revisited += 1

    def rate(n: int) -> float:
        return round(n / total * 100, 1) if total else 0.0

    funnel = [
        {"node": "到店(基数)", "count": total, "rate": 100.0},
        {"node": "医生给出后续建议", "count": with_rec, "rate": rate(with_rec)},
        {"node": "已创建预约", "count": appointed, "rate": rate(appointed)},
        {"node": "预约履约", "count": fulfilled, "rate": rate(fulfilled)},
        {"node": "实际复诊", "count": revisited, "rate": rate(revisited)},
    ]
    # 漏损节点：相邻节点人数差最大的地方
    leaks = []
    for i in range(len(funnel) - 1):
        drop = funnel[i]["count"] - funnel[i + 1]["count"]
        leaks.append({"from": funnel[i]["node"], "to": funnel[i + 1]["node"], "drop": drop})
    leaks.sort(key=lambda x: -x["drop"])
    return {
        "window_days": days,
        "total_visits": total,
        "funnel": funnel,
        "leak_nodes": leaks[:3],
        "adjusted_retention_rate": rate(revisited),
    }


def overdue_revisits(db: Session, store_id: str | None = None,
                     org_id: str | None = None) -> list[dict]:
    """超期复诊预警：计划窗口已过且无新到店。"""
    today = datetime.now().date()
    query = select(TreatmentPlan).where(
        TreatmentPlan.plan_status == TreatmentPlanStatus.ACTIVE,
        TreatmentPlan.recommended_next_visit_max_date.isnot(None),
        TreatmentPlan.recommended_next_visit_max_date < today,
    )
    if store_id:
        query = query.where(TreatmentPlan.store_id == store_id)
    if org_id:
        query = query.where(TreatmentPlan.organization_id == org_id)
    plans = db.scalars(query).all()
    result = []
    for pl in plans:
        later = db.scalar(
            select(Visit).where(
                Visit.patient_id == pl.patient_id,
                Visit.visit_at >= pl.recommended_next_visit_max_date,
            ).limit(1)
        )
        if later is None:
            overdue_days = (today - pl.recommended_next_visit_max_date).days
            p = db.get(Patient, pl.patient_id)
            result.append({
                "treatment_plan_id": pl.treatment_plan_id,
                "patient_id": pl.patient_id,
                "patient_name": p.name if p else None,
                "doctor_id": pl.doctor_id,
                "overdue_days": overdue_days,
                "recommended_window": [
                    pl.recommended_next_visit_min_date.isoformat() if pl.recommended_next_visit_min_date else None,
                    pl.recommended_next_visit_max_date.isoformat(),
                ],
                "completed_visits": pl.completed_visits,
            })
    result.sort(key=lambda x: -x["overdue_days"])
    return result


def due_today_revisits(db: Session, store_id: str | None = None,
                       org_id: str | None = None) -> list[dict]:
    """今日应复诊：建议窗口覆盖今天。"""
    today = datetime.now().date()
    query = select(TreatmentPlan).where(
        TreatmentPlan.plan_status == TreatmentPlanStatus.ACTIVE,
        TreatmentPlan.recommended_next_visit_min_date <= today,
        TreatmentPlan.recommended_next_visit_max_date >= today,
    )
    if store_id:
        query = query.where(TreatmentPlan.store_id == store_id)
    if org_id:
        query = query.where(TreatmentPlan.organization_id == org_id)
    plans = db.scalars(query).all()
    return [{
        "treatment_plan_id": pl.treatment_plan_id,
        "patient_id": pl.patient_id,
        "doctor_id": pl.doctor_id,
    } for pl in plans]

def funnel_by_dimension(db: Session, store_id: str | None = None, days: int = 90,
                        by: str = "doctor", org_id: str | None = None) -> list[dict]:
    """按医生/员工统计过程漏斗：识别"哪个医生建议率低 / 哪个员工履约差"。

    返回每维度：基数到店、建议、预约、履约、复诊 与各自率，并标记异常节点。
    """
    from ..models import CareRecommendation
    from sqlalchemy import select as _select

    since = datetime.now() - timedelta(days=days)
    q = _select(Visit).where(Visit.visit_at >= since)
    if store_id:
        q = q.where(Visit.store_id == store_id)
    if org_id:
        q = q.where(Visit.organization_id == org_id)
    visits = db.scalars(q).all()

    groups: dict[str, dict] = {}
    for v in visits:
        key = v.doctor_id if by == "doctor" else (v.staff_id or "unknown")
        g = groups.setdefault(key, {"id": key, "total": 0, "with_rec": 0, "appointed": 0,
                                    "fulfilled": 0, "revisited": 0})
        g["total"] += 1
        rec = db.scalar(
            _select(CareRecommendation)
            .where(CareRecommendation.visit_id == v.visit_id, CareRecommendation.next_visit_recommended.is_(True))
            .limit(1)
        )
        if rec:
            g["with_rec"] += 1
            appt = db.scalar(
                _select(Appointment)
                .where(Appointment.patient_id == v.patient_id, Appointment.appointment_at >= v.visit_at)
                .order_by(Appointment.appointment_at.asc())
                .limit(1)
            )
            if appt is not None:
                g["appointed"] += 1
                if appt.status == AppointmentStatus.COMPLETED:
                    g["fulfilled"] += 1
            later = db.scalar(
                _select(Visit).where(Visit.patient_id == v.patient_id, Visit.visit_at > v.visit_at).limit(1)
            )
            if later is not None:
                g["revisited"] += 1

    # 名称解析
    names = {}
    if by == "doctor":
        for d in db.scalars(_select(Doctor)).all():
            names[d.doctor_id] = d.doctor_name
    result = []
    for g in groups.values():
        def rate(n):
            return round(n / g["total"] * 100, 1) if g["total"] else 0.0
        result.append({
            "id": g["id"],
            "name": names.get(g["id"], g["id"]),
            "total": g["total"],
            "recommendation_rate": rate(g["with_rec"]),
            "appointment_rate": rate(g["appointed"]),
            "fulfillment_rate": rate(g["fulfilled"]),
            "revisit_rate": rate(g["revisited"]),
            "flagged": g["total"] >= 5 and rate(g["with_rec"]) < 30,  # 建议率<30% 标异常
        })
    result.sort(key=lambda x: -x["total"])
    return result
