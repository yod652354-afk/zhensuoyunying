"""Revenue Attribution（规格 03 §15 / 企微规格 §12.2-12.3）。

- Treatment/Holdout：入组在生成内容前完成；对照组不得触达；
- 预定义观察窗口；gross / attributed / incremental 分离；
- Incremental Rate = Treatment Rate - Control Rate；
- Incremental Revenue = Eligible Treatment Population × Incremental Rate × 合格收入均值；
- Incremental Contribution = Incremental Revenue × 毛利率 - 触达及优惠成本；
- ROI = Incremental Contribution / 执行成本；
- 小样本只标记方向性结论；
- 每笔归因可追溯完整证据链：Experiment→Opportunity→Content→Review→Task→Touch→Response→Appointment→Visit→Payment→Attribution。
"""
import math
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import OpportunityStatus
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Experiment, Payment
from ...models.revos import (
    ContentDraft, ContentReviewRecord, ExecutionPlan, InteractionSession,
    Opportunity, Outcome, StrategyPerformance,
)

ATTRIBUTION_VERSION = "attribution_v1"
DEFAULT_GROSS_MARGIN = 0.6  # 可配置：毛利率
QUALIFIED_REVENUE_MULTIPLIER = 1.0  # 合格收入均值 = 该客群平均客单价（V1 用 expected_revenue 均值）


def experiment_metrics(db: Session, experiment_id: str,
                       window_days: int | None = None,
                       gross_margin: float | None = None) -> dict:
    """计算实验 Treatment/Holdout 指标（R-01：两组同口径、对照组自然结果计入）。

    - 对照组禁止触达，但自然预约/到店/支付/退款完整进入 Outcome（is_organic）；
    - 两组使用同一观察窗口、同一主要指标（支付/到店率）；
    - 退款在窗口内反向冲减净收入；
    - 增量 = Treatment − Control；禁止把 Treatment 全部收入称为增量收入。
    """
    settings = get_settings()
    window = window_days or settings.revos_observation_window_days
    margin = gross_margin or DEFAULT_GROSS_MARGIN
    experiment = db.get(Experiment, experiment_id)
    if experiment is None:
        return {"error": "实验不存在"}

    since = utcnow() - timedelta(days=window)
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.experiment_id == experiment_id,
            Opportunity.detected_at >= since,
            Opportunity.deleted_at.is_(None),
        )
    ).all()
    if not opps:
        return {"experiment_id": experiment_id, "window_days": window, "error": "无机会数据"}

    groups: dict[str, dict] = {"treatment": {"total": 0, "won": 0, "paid": 0, "visited": 0,
                                             "appointment": 0, "paid_revenue": 0.0, "refund": 0.0,
                                             "net_revenue": 0.0, "outcomes": 0, "dnc": 0, "complaint": 0,
                                             "expected_revenue_sum": 0.0, "touch_cost": 0.0},
                               "control": {"total": 0, "won": 0, "paid": 0, "visited": 0,
                                           "appointment": 0, "paid_revenue": 0.0, "refund": 0.0,
                                           "net_revenue": 0.0, "outcomes": 0, "dnc": 0, "complaint": 0,
                                           "expected_revenue_sum": 0.0, "touch_cost": 0.0}}
    for opp in opps:
        key = "control" if opp.experiment_group == "control" else "treatment"
        g = groups[key]
        g["total"] += 1
        g["expected_revenue_sum"] += float(opp.expected_revenue or 0)
        if opp.status == OpportunityStatus.WON:
            g["won"] += 1
        for outcome in db.scalars(select(Outcome).where(Outcome.opportunity_id == opp.opportunity_id)).all():
            g["outcomes"] += 1
            otype = outcome.outcome_type.value if hasattr(outcome.outcome_type, "value") else outcome.outcome_type
            if otype == "paid":
                g["paid"] += 1
                g["paid_revenue"] += float(outcome.revenue_amount or 0)
            elif otype == "refunded":
                g["refund"] += float(outcome.revenue_amount or 0) or float(
                    (outcome.meta or {}).get("refund_amount") or 0)
            elif otype == "visited":
                g["visited"] += 1
            elif otype == "appointment":
                g["appointment"] += 1
            elif otype == "dnc":
                g["dnc"] += 1
            elif otype == "complaint":
                g["complaint"] += 1
        g["net_revenue"] = g["paid_revenue"] - g["refund"]
        g["touch_cost"] += float(opp.expected_cost or 0)

    t, c = groups["treatment"], groups["control"]

    def rate(n: int, total: int) -> float:
        return round(n / total * 100, 2) if total else 0.0

    # 主要指标：支付率（两组同口径，含对照组自然结果）
    treatment_rate = rate(t["paid"], t["total"])
    control_rate = rate(c["paid"], c["total"])
    incremental_rate = round(treatment_rate - control_rate, 2)
    treatment_visit_rate = rate(t["visited"], t["total"])
    control_visit_rate = rate(c["visited"], c["total"])

    # 合格收入均值（Treatment 组 expected_revenue 均值）
    avg_revenue = (t["expected_revenue_sum"] / t["total"]) if t["total"] else 0.0
    incremental_customers = round(t["total"] * (incremental_rate / 100.0), 2)
    incremental_revenue = round(incremental_customers * avg_revenue * QUALIFIED_REVENUE_MULTIPLIER, 2)
    incremental_contribution = round(incremental_revenue * margin - t["touch_cost"], 2)
    roi = round(incremental_contribution / t["touch_cost"], 4) if t["touch_cost"] else 0.0

    # 方向性标记：小样本
    min_sample = settings.revos_min_experiment_sample
    directional_only = t["total"] < min_sample or c["total"] < min_sample
    significance = _simple_significance(treatment_rate, control_rate, t["total"], c["total"]) if not directional_only else None

    metrics = {
        "experiment_id": experiment_id,
        "window_days": window,
        "sample": {"treatment": t["total"], "control": c["total"]},
        "rates": {
            "treatment_paid_rate": treatment_rate,
            "control_paid_rate": control_rate,
            "incremental_rate": incremental_rate,
            "treatment_visit_rate": treatment_visit_rate,
            "control_visit_rate": control_visit_rate,
        },
        "revenue": {
            "gross_revenue_treatment": round(t["paid_revenue"], 2),
            "gross_revenue_control": round(c["paid_revenue"], 2),
            "refund_treatment": round(t["refund"], 2),
            "refund_control": round(c["refund"], 2),
            "net_revenue_treatment": round(t["net_revenue"], 2),
            "net_revenue_control": round(c["net_revenue"], 2),
            "attributed_revenue": round(t["paid_revenue"] - t["refund"], 2),  # 归因口径：Treatment 净交易
            "incremental_revenue": incremental_revenue,
            "incremental_contribution": incremental_contribution,
            "roi": roi,
        },
        "guardrails": {
            "dnc_treatment": t["dnc"], "dnc_control": c["dnc"],
            "complaint_treatment": t["complaint"], "complaint_control": c["complaint"],
            "touch_cost_treatment": round(t["touch_cost"], 2),
        },
        "directional_only": directional_only,
        "significance": significance,
        "attribution_version": ATTRIBUTION_VERSION,
        "calculated_at": utcnow().isoformat(),
    }
    # 写入 StrategyPerformance（学习数据）
    _write_performance(db, experiment, metrics, margin)
    return metrics


def _simple_significance(t_rate: float, c_rate: float, t_n: int, c_n: int) -> dict | None:
    """粗略 z 检验（仅方向性参考，不做显著性宣称）。"""
    try:
        p_pool = (t_rate * t_n + c_rate * c_n) / (t_n + c_n) / 100.0
        se = math.sqrt(p_pool * (1 - p_pool) * (1 / t_n + 1 / c_n))
        if se == 0:
            return None
        z = ((t_rate - c_rate) / 100.0) / se
        return {"z": round(z, 3), "note": "粗略 z 检验，仅参考"}
    except Exception:  # noqa: BLE001
        return None


def _write_performance(db: Session, experiment: Experiment, metrics: dict, margin: float) -> None:
    perf = StrategyPerformance(
        performance_id=new_id("strategy_performance"),
        organization_id=experiment.organization_id,
        store_id=experiment.store_id,
        experiment_id=experiment.experiment_id,
        strategy_code=f"experiment:{experiment.experiment_id[:8]}",
        category="experiment",
        sample_size=metrics["sample"]["treatment"] + metrics["sample"]["control"],
        treatment_size=metrics["sample"]["treatment"],
        control_size=metrics["sample"]["control"],
        metrics={
            **metrics["rates"],
            **metrics["revenue"],
            **metrics["guardrails"],
            "gross_margin": margin,
        },
        directional_only=metrics["directional_only"],
        data_quality="directional" if metrics["directional_only"] else "adequate",
        evaluated_at=utcnow(),
    )
    db.add(perf)
    db.flush()


def attribution_trace(db: Session, opportunity_id: str) -> dict:
    """任意归因收入可追溯完整证据链（规格 §12.3）。"""
    opportunity = db.get(Opportunity, opportunity_id)
    if opportunity is None:
        return {"error": "机会不存在"}
    chain: dict = {"opportunity": _opp_out(opportunity)}
    if opportunity.experiment_id:
        exp = db.get(Experiment, opportunity.experiment_id)
        chain["experiment"] = {"experiment_id": exp.experiment_id, "name": exp.name,
                               "group": opportunity.experiment_group} if exp else None

    plans = db.scalars(
        select(ExecutionPlan).where(
            ExecutionPlan.opportunity_id == opportunity_id,
            ExecutionPlan.deleted_at.is_(None),
        ).order_by(ExecutionPlan.plan_version.asc())
    ).all()
    chain["plans"] = [_plan_out(p) for p in plans]

    drafts = db.scalars(
        select(ContentDraft).where(ContentDraft.opportunity_id == opportunity_id)
        .order_by(ContentDraft.version.asc())
    ).all()
    chain["content_versions"] = [{
        "content_draft_id": d.content_draft_id, "version": d.version,
        "generation_mode": d.generation_mode, "provider": d.model_provider,
        "content_hash": d.content_hash, "status": d.status.value,
    } for d in drafts]

    reviews = db.scalars(
        select(ContentReviewRecord).where(
            ContentReviewRecord.content_draft_id.in_([d.content_draft_id for d in drafts])
        ).order_by(ContentReviewRecord.created_at.asc())
    ).all() if drafts else []
    chain["reviews"] = [{
        "review_id": r.review_id, "review_type": r.review_type.value,
        "decision": r.decision.value, "risk_level": r.risk_level.value,
        "reviewer_id": r.reviewer_id, "content_hash": r.content_hash,
    } for r in reviews]

    from ...models import Task, Touch
    tasks = db.scalars(select(Task).where(Task.opportunity_id == opportunity_id)).all()
    chain["send_tasks"] = [{
        "task_id": t.task_id, "send_status": t.send_status, "confirmed_by": t.confirmed_by,
        "confirmed_at": t.confirmed_at.isoformat() if t.confirmed_at else None,
        "external_message_id": t.external_message_id, "content_hash": t.content_hash,
    } for t in tasks]
    touches = db.scalars(select(Touch).where(Touch.opportunity_id == opportunity_id)).all()
    chain["touches"] = [{
        "touch_id": t.touch_id, "channel": t.channel.value, "sent_at": t.sent_at.isoformat(),
        "send_status": t.send_status, "failure_code": t.failure_code,
    } for t in touches]

    sessions = db.scalars(
        select(InteractionSession).where(InteractionSession.opportunity_id == opportunity_id)
    ).all()
    chain["interaction_sessions"] = [{
        "session_id": s.session_id, "status": s.status.value,
        "first_opened_at": s.first_opened_at.isoformat() if s.first_opened_at else None,
    } for s in sessions]

    outcomes = db.scalars(
        select(Outcome).where(Outcome.opportunity_id == opportunity_id).order_by(Outcome.occurred_at.asc())
    ).all()
    chain["outcomes"] = [{
        "outcome_id": o.outcome_id, "outcome_type": o.outcome_type.value,
        "occurred_at": o.occurred_at.isoformat(), "revenue_amount": float(o.revenue_amount or 0),
        "source_event_id": o.source_event_id,
    } for o in outcomes]

    payments = db.scalars(
        select(Payment).where(Payment.patient_id == opportunity.patient_id).order_by(Payment.paid_at.desc()).limit(5)
    ).all() if opportunity.patient_id else []
    chain["payments"] = [{
        "payment_id": p.payment_id, "amount": float(p.amount or 0),
        "status": p.status.value if p.status else None,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
    } for p in payments]
    return chain


def _opp_out(opp: Opportunity) -> dict:
    from .common import enum_value
    return {
        "opportunity_id": opp.opportunity_id,
        "money_type": enum_value(opp.money_type), "scenario_type": enum_value(opp.scenario_type),
        "status": enum_value(opp.status), "priority_score": float(opp.priority_score or 0),
        "expected_revenue": float(opp.expected_revenue or 0),
        "reason_codes": opp.reason_codes, "detector_version": opp.detector_version,
        "scoring_version": opp.scoring_version, "workflow_code": opp.workflow_code,
        "experiment_group": enum_value(opp.experiment_group),
    }


def _plan_out(p: ExecutionPlan) -> dict:
    from .common import enum_value
    return {
        "execution_plan_id": p.execution_plan_id, "plan_version": p.plan_version,
        "review_status": enum_value(p.review_status), "review_decision": enum_value(p.review_decision),
        "reviewed_by": p.reviewed_by, "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "content_hash": p.content_hash, "immutable": p.immutable,
        "expected_value": float(p.expected_value or 0), "expected_cost": float(p.expected_cost or 0),
    }
