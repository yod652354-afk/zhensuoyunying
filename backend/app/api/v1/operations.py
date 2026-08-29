"""运营 API：任务引擎 / 报表 / 对账 / 复盘 / 内容审批 / 员工激励（对照计划书 §10-11、§19）。

安全（RevOS P0）：所有运营端点强制服务端租户 scope。
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...models import Campaign, Organization
from ...services.attribution import campaign_metrics
from ...services.compliance import approve_review, create_review, list_reviews, scan_content
from ...services.reports import reconciliation, revenue_leakage_report, staff_incentive
from ...services.retention import funnel_by_dimension
from ...services.task_engine import run_retention_engine

router = APIRouter(tags=["Operations"])


def _store_ok(tenant: TenantContext, store_id: str | None) -> str | None:
    if tenant.force_store_scope and tenant.store_id and store_id and store_id != tenant.store_id:
        raise ClinicOSError("FORBIDDEN", "无权查看其他门店数据", status_code=403, retryable=False)
    return store_id


# ============ 自动任务引擎（R-02：统一机会流程，禁止旧 Task 绕过审核） ============
@router.post("/analytics/engine/retention-tasks", summary="触发 Retention 引擎（兼容入口：已转为统一机会流程）")
def trigger_engine(request: Request, store_id: str | None = Query(default=None),
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    """兼容入口：不再直接创建旧式 Retention Task，转为统一 Opportunity 流程。"""
    from ...events.bus import emit
    from ...core.enums import ActorType
    from ...services.revos.opportunity import run_detection

    sid = _store_ok(tenant, store_id)
    result = run_detection(db, sid, org_id=tenant.organization_id, scenario="overdue_revisit")
    emit(db, "task.daily_generated", tenant.organization_id, "task", "engine_compat",
         store_id=sid, actor_type=ActorType.AI,
         payload={"converted_to_opportunity": True, "opportunities_created": result["created"]})
    db.commit()
    return {"data": {"converted_to_opportunity": True,
                     "note": "已转为统一 Opportunity 流程（R-02），不再直接创建旧式 Task",
                     "opportunities_created": result["created"]},
            "meta": {"request_id": request.state.request_id}}


# ============ Campaign 归因 ============
@router.get("/analytics/campaigns/{campaign_id}/metrics", summary="Campaign 级增量归因（control vs treatment）")
def get_campaign_metrics(campaign_id: str, request: Request,
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    cmp = db.get(Campaign, campaign_id)
    if cmp is None:
        raise ClinicOSError("NOT_FOUND", "活动不存在", status_code=404)
    tenant.ensure_scope(cmp)
    result = campaign_metrics(db, campaign_id)
    if "error" in result:
        raise ClinicOSError("NOT_FOUND", result["error"], status_code=404)
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/campaigns/metrics-summary", summary="全部活动增量归因汇总")
def get_campaigns_summary(request: Request,
                          tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    rows = []
    for cmp in db.scalars(
        select(Campaign).where(Campaign.deleted_at.is_(None),
                               Campaign.organization_id == tenant.organization_id)
    ).all():
        rows.append(campaign_metrics(db, cmp.campaign_id))
    return {"data": rows, "meta": {"request_id": request.state.request_id}}


# ============ 维度漏斗 ============
@router.get("/analytics/funnel-by-doctor", summary="按医生维度过程漏斗")
def funnel_doctor(request: Request, store_id: str | None = Query(default=None),
                  days: int = Query(default=90),
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": funnel_by_dimension(db, sid, days, by="doctor", org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/funnel-by-staff", summary="按员工维度过程漏斗")
def funnel_staff(request: Request, store_id: str | None = Query(default=None),
                 days: int = Query(default=90),
                 tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": funnel_by_dimension(db, sid, days, by="staff", org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


# ============ 报表与对账 ============
@router.get("/analytics/revenue-leakage-report", summary="Revenue Leakage Report（漏损报表）")
def leakage_report(request: Request, store_id: str | None = Query(default=None),
                   days: int = Query(default=90),
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": revenue_leakage_report(db, sid, days, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/reconciliation", summary="数据对账（每日核对，差异定位到ID）")
def get_reconciliation(request: Request, store_id: str | None = Query(default=None),
                       date: str | None = Query(default=None),
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": reconciliation(db, sid, date, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/staff-incentive", summary="员工激励（按增量价值，非任务数）")
def get_staff_incentive(request: Request, store_id: str | None = Query(default=None),
                        days: int = Query(default=30),
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": staff_incentive(db, sid, days, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


# ============ 内容合规 ============
class ScanBody(BaseModel):
    content: str
    channel: str = "wechat"


class ReviewBody(BaseModel):
    content: str
    campaign_id: str | None = None
    channel: str = "wechat"


class ApproveBody(BaseModel):
    approved: bool
    note: str | None = None


@router.post("/compliance/scan", summary="营销内容风险扫描")
def compliance_scan(body: ScanBody, request: Request,
                    tenant: TenantContext = Depends(get_tenant)):
    return {"data": scan_content(body.content), "meta": {"request_id": request.state.request_id}}


@router.post("/compliance/reviews", summary="提交内容审批（风险扫描→人工审批留痕）")
def submit_review(body: ReviewBody, request: Request,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    review = create_review(db, tenant.organization_id, None, body.campaign_id, body.content, body.channel)
    return {"data": {"content_review_id": review.content_review_id, "risk_score": review.risk_score,
                     "risk_flags": review.risk_flags, "status": review.status},
            "meta": {"request_id": request.state.request_id}}


@router.get("/compliance/reviews", summary="内容审批列表")
def get_reviews(request: Request, status: str | None = Query(default=None),
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    rows = list_reviews(db, None, status)
    rows = [r for r in rows if r.organization_id == tenant.organization_id]
    return {"data": [{
        "content_review_id": r.content_review_id, "campaign_id": r.campaign_id,
        "content_text": r.content_text[:200], "channel": r.channel,
        "risk_flags": r.risk_flags, "risk_score": r.risk_score,
        "status": r.status, "approved": r.approved,
        "reviewed_by": r.reviewed_by, "review_note": r.review_note,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/compliance/reviews/{review_id}/approve", summary="审批内容（通过/驳回，留痕）")
def review_approve(review_id: str, body: ApproveBody, request: Request,
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    reviewer = request.headers.get("X-Reviewer") or "system"
    review = approve_review(db, review_id, reviewer, body.approved, body.note)
    if review is None:
        raise ClinicOSError("NOT_FOUND", "审批记录不存在", status_code=404)
    tenant.ensure_scope(review)
    return {"data": {"content_review_id": review.content_review_id, "status": review.status,
                     "approved": review.approved, "reviewed_by": reviewer},
            "meta": {"request_id": request.state.request_id}}


# ============ 每周复盘（Learning 人工闭环） ============
class ReviewSessionBody(BaseModel):
    period_start: str
    period_end: str
    engine: str = "all"
    summary: str | None = None
    actions_kept: list | None = None
    actions_dropped: list | None = None
    next_week_plan: str | None = None


@router.post("/reviews", summary="创建每周复盘记录")
def create_review_session(body: ReviewSessionBody, request: Request,
                          tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...core.ids import new_id
    from ...core.timeutil import ensure_utc
    from ...models import ReviewSession

    session = ReviewSession(
        review_id=new_id("review"),
        organization_id=tenant.organization_id,
        store_id=tenant.store_id,
        period_start=ensure_utc(datetime.fromisoformat(body.period_start.replace("Z", "+00:00"))) or datetime.now(),
        period_end=ensure_utc(datetime.fromisoformat(body.period_end.replace("Z", "+00:00"))) or datetime.now(),
        engine=body.engine, summary=body.summary,
        actions_kept=body.actions_kept, actions_dropped=body.actions_dropped,
        next_week_plan=body.next_week_plan,
        created_by=request.headers.get("X-Reviewer"),
    )
    db.add(session)
    db.commit()
    return {"data": {"review_id": session.review_id, "engine": session.engine},
            "meta": {"request_id": request.state.request_id}}


@router.get("/reviews", summary="复盘记录列表")
def list_review_sessions(request: Request,
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models import ReviewSession
    rows = db.scalars(
        select(ReviewSession).where(
            ReviewSession.deleted_at.is_(None),
            ReviewSession.organization_id == tenant.organization_id,
        ).order_by(ReviewSession.period_start.desc()).limit(50)
    ).all()
    return {"data": [{
        "review_id": r.review_id, "engine": r.engine,
        "period_start": r.period_start.isoformat() if r.period_start else None,
        "period_end": r.period_end.isoformat() if r.period_end else None,
        "summary": r.summary, "actions_kept": r.actions_kept,
        "actions_dropped": r.actions_dropped, "next_week_plan": r.next_week_plan,
        "created_by": r.created_by,
    } for r in rows], "meta": {"request_id": request.state.request_id}}
