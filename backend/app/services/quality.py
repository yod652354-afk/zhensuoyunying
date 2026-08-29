"""数据质量评分（需求规格 8.2）：完整性 / 一致性 / 时效性 / 授权状态 / 敏感边界。"""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Appointment, Order, Patient, Visit


def store_quality_report(db: Session, store_id: str | None = None,
                         org_id: str | None = None) -> dict:
    q = select(Patient).where(Patient.deleted_at.is_(None))
    if store_id:
        q = q.where(Patient.store_id == store_id)
    if org_id:
        q = q.where(Patient.organization_id == org_id)
    patients = db.scalars(q).all()
    n = len(patients)

    # 完整性：关键字段缺失率
    def missing_rate(field_values) -> float:
        if n == 0:
            return 0.0
        missing = sum(1 for v in field_values if v is None or v == "")
        return round(missing / n * 100, 1)

    completeness = {
        "missing_rate_name": missing_rate([p.name for p in patients]),
        "missing_rate_mobile": missing_rate([p.mobile for p in patients]),
        "missing_rate_first_visit": missing_rate([p.first_visit_date for p in patients]),
        "missing_rate_last_visit": missing_rate([p.last_visit_date for p in patients]),
        "missing_rate_total_revenue": missing_rate([p.total_revenue for p in patients]),
        "score": 100.0,
    }
    checks = [
        ("姓名", completeness["missing_rate_name"]),
        ("手机号", completeness["missing_rate_mobile"]),
        ("首次到店", completeness["missing_rate_first_visit"]),
        ("最近到店", completeness["missing_rate_last_visit"]),
        ("累计收入", completeness["missing_rate_total_revenue"]),
    ]
    completeness["score"] = round(100 - sum(m for _, m in checks), 1)
    completeness["details"] = [{"field": f, "missing_rate": m} for f, m in checks]

    # 一致性：能关联到到店/订单的患者占比
    linked_visits = 0
    linked_orders = 0
    for p in patients:
        v = db.scalar(select(Visit).where(Visit.patient_id == p.patient_id).limit(1))
        o = db.scalar(select(Order).where(Order.patient_id == p.patient_id).limit(1))
        if v:
            linked_visits += 1
        if o:
            linked_orders += 1
    consistency = {
        "linked_to_visits_rate": round(linked_visits / n * 100, 1) if n else 0.0,
        "linked_to_orders_rate": round(linked_orders / n * 100, 1) if n else 0.0,
        "score": round(((linked_visits + linked_orders) / (2 * n) * 100), 1) if n else 0.0,
    }

    # 时效性：30 天内是否有新到店
    since30 = datetime.now() - timedelta(days=30)
    recent_visits = db.scalar(
        select(func.count(Visit.visit_id)).where(Visit.visit_at >= since30)
    ) or 0
    timeliness = {
        "recent_visits_30d": recent_visits,
        "score": min(100.0, round(recent_visits * 2, 1)) if recent_visits else 0.0,
    }

    # 授权状态
    granted = sum(1 for p in patients if p.consent_status == "granted")
    dnc = sum(1 for p in patients if p.dnc)
    authorization = {
        "consent_granted_rate": round(granted / n * 100, 1) if n else 0.0,
        "dnc_count": dnc,
        "score": round(granted / n * 100, 1) if n else 0.0,
    }

    total_score = round(
        0.4 * completeness["score"]
        + 0.3 * consistency["score"]
        + 0.15 * timeliness["score"]
        + 0.15 * authorization["score"],
        1,
    )
    return {
        "store_id": store_id,
        "patients_count": n,
        "total_score": total_score,
        "completeness": completeness,
        "consistency": consistency,
        "timeliness": timeliness,
        "authorization": authorization,
        "conclusion": (
            "数据可用，可进入主实验" if total_score >= 80
            else "数据质量中等，需清洗后进入" if total_score >= 60
            else "数据质量不足，建议先补数据"
        ),
    }