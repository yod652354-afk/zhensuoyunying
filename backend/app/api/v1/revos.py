"""RevOS 领域 API（规格 03 §18 / 企微规格 §10）。

统一前缀 /api/v1；所有接口执行服务端租户 scope（组织 + 员工门店强制）。
模块：客户档案、状态机、Opportunity、Decision、ExecutionPlan、内容生成与审核、
企微执行/回调、小程序承接、Outcome 与归因、策略注册中心、持久 Job/Outbox、
Connector 接入、三种钱驾驶舱。
"""
import time
from decimal import Decimal

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import ActionType, OutcomeType
from ...core.errors import ClinicOSError
from ...core.ids import new_id
from ...core.tenant import TenantContext, get_tenant
from ...core.timeutil import utcnow
from ...database import get_db
from ...models import Experiment, Organization, Task, Touch, User
from ...models.revos import (
    ActionRecord, ContentDraft, ContentReviewRecord, Customer,
    CustomerIdentity, CustomerStateHistory, Decision, ExecutionPlan,
    InteractionSession, Opportunity, Outcome, StrategyPerformance, StrategyVersion,
)
from ...services.revos import attribution as revos_attribution
from ...services.revos import arbitration as revos_arbitration
from ...services.revos import connector as revos_connector
from ...services.revos import content_provider as revos_content
from ...services.revos import customer_state as revos_state
from ...services.revos import decision as revos_decision
from ...services.revos import execution_plan as revos_plan
from ...services.revos import jobs as revos_jobs
from ...services.revos import mp as revos_mp
from ...services.revos import opportunity as revos_opportunity
from ...services.revos import outcome as revos_outcome
from ...services.revos import outbox as revos_outbox
from ...services.revos import review as revos_review
from ...services.revos import strategy as revos_strategy
from ...services.revos import wecom as revos_wecom

router = APIRouter(tags=["RevOS"])


# ================= 工具 =================
def _owned(db: Session, model, entity_id: str, tenant: TenantContext, label: str):
    entity = db.get(model, entity_id)
    if entity is None or getattr(entity, "deleted_at", None):
        raise ClinicOSError("NOT_FOUND", f"{label}不存在", status_code=404)
    tenant.ensure_scope(entity)
    return entity


def _store_ok(tenant: TenantContext, store_id: str | None) -> str | None:
    if tenant.force_store_scope and tenant.store_id and store_id and store_id != tenant.store_id:
        raise ClinicOSError("FORBIDDEN", "无权查看其他门店数据", status_code=403, retryable=False)
    return store_id


# ================= 客户经营档案 =================
@router.get("/customers", summary="RevOS 统一客户列表")
def list_customers(request: Request, store_id: str | None = Query(default=None),
                   lifecycle_state: str | None = Query(default=None),
                   money_state: str | None = Query(default=None),
                   value_tier: str | None = Query(default=None),
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    query = select(Customer).where(Customer.deleted_at.is_(None))
    query = tenant.scope_query(query, Customer)
    if sid:
        query = query.where(Customer.store_id == sid)
    if lifecycle_state:
        query = query.where(Customer.lifecycle_state == lifecycle_state)
    if money_state:
        query = query.where(Customer.money_state == money_state)
    if value_tier:
        query = query.where(Customer.value_tier == value_tier)
    rows = db.scalars(query.order_by(Customer.updated_at.desc()).limit(200)).all()
    return {"data": [_customer_out(c) for c in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/customers/{customer_id}", summary="客户经营档案详情")
def get_customer(customer_id: str, request: Request,
                 tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    customer = _owned(db, Customer, customer_id, tenant, "客户")
    return {"data": _customer_out(customer), "meta": {"request_id": request.state.request_id}}


@router.get("/customers/{customer_id}/revenue-profile", summary="客户三种钱画像")
def customer_revenue_profile(customer_id: str, request: Request,
                             tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    customer = _owned(db, Customer, customer_id, tenant, "客户")
    opps = db.scalars(
        select(Opportunity).where(
            Opportunity.customer_id == customer_id,
            Opportunity.deleted_at.is_(None),
        ).order_by(Opportunity.detected_at.desc()).limit(50)
    ).all()
    states = db.scalars(
        select(CustomerStateHistory).where(CustomerStateHistory.customer_id == customer_id)
        .order_by(CustomerStateHistory.effective_from.desc()).limit(30)
    ).all()
    return {"data": {
        "customer_id": customer.customer_id,
        "lifecycle_state": customer.lifecycle_state.value,
        "money_state": customer.money_state.value,
        "value_tier": customer.value_tier.value,
        "risk_flags": customer.risk_flags,
        "state_reason_codes": customer.state_reason_codes,
        "total_visits": customer.total_visits,
        "total_revenue": float(customer.total_revenue or 0),
        "last_visit_date": customer.last_visit_date.isoformat() if customer.last_visit_date else None,
        "opportunities": [{
            "opportunity_id": o.opportunity_id, "money_type": o.money_type.value,
            "scenario_type": o.scenario_type.value, "status": o.status.value,
            "priority_score": float(o.priority_score or 0), "expected_revenue": float(o.expected_revenue or 0),
        } for o in opps],
        "state_history": [{
            "lifecycle_from": s.lifecycle_from, "lifecycle_to": s.lifecycle_to.value,
            "money_from": s.money_from, "money_to": s.money_to.value,
            "reason_codes": s.reason_codes, "effective_from": s.effective_from.isoformat(),
            "rule_version": s.rule_version,
        } for s in states],
    }, "meta": {"request_id": request.state.request_id}}


def _customer_out(c: Customer) -> dict:
    return {
        "customer_id": c.customer_id, "patient_id": c.patient_id,
        "display_name": c.display_name,
        "lifecycle_state": c.lifecycle_state.value,
        "money_state": c.money_state.value,
        "value_tier": c.value_tier.value,
        "risk_flags": c.risk_flags, "state_reason_codes": c.state_reason_codes,
        "consent_status": c.consent_status, "dnc": c.dnc, "complaint_flag": c.complaint_flag,
        "total_visits": c.total_visits, "total_revenue": float(c.total_revenue or 0),
        "last_visit_date": c.last_visit_date.isoformat() if c.last_visit_date else None,
        "store_id": c.store_id,
    }


@router.get("/customer-identities", summary="客户身份列表（脱敏）")
def list_identities(request: Request, customer_id: str | None = Query(default=None),
                    identity_type: str | None = Query(default=None),
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(CustomerIdentity).where(CustomerIdentity.deleted_at.is_(None))
    query = tenant.scope_query(query, CustomerIdentity)
    if customer_id:
        query = query.where(CustomerIdentity.customer_id == customer_id)
    if identity_type:
        query = query.where(CustomerIdentity.identity_type == identity_type)
    rows = db.scalars(query.limit(200)).all()
    from ...services.revos.common import mask_identity
    return {"data": [{
        "identity_id": i.identity_id, "customer_id": i.customer_id,
        "identity_type": i.identity_type.value,
        "value_masked": mask_identity(i.encrypted_value),
        "provider": i.provider, "app_scope": i.app_scope, "is_primary": i.is_primary,
        "verified_at": i.verified_at.isoformat() if i.verified_at else None,
        "valid_from": i.valid_from.isoformat(), "valid_to": i.valid_to.isoformat() if i.valid_to else None,
    } for i in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/customer-states", summary="客户状态迁移历史")
def list_state_history(request: Request, customer_id: str | None = Query(default=None),
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(CustomerStateHistory)
    query = tenant.scope_query(query, CustomerStateHistory)
    if customer_id:
        query = query.where(CustomerStateHistory.customer_id == customer_id)
    rows = db.scalars(query.order_by(CustomerStateHistory.effective_from.desc()).limit(200)).all()
    return {"data": [{
        "state_history_id": s.state_history_id, "customer_id": s.customer_id,
        "lifecycle_from": s.lifecycle_from, "lifecycle_to": s.lifecycle_to.value,
        "money_from": s.money_from, "money_to": s.money_to.value,
        "value_tier": s.value_tier.value, "reason_codes": s.reason_codes,
        "effective_from": s.effective_from.isoformat(), "rule_version": s.rule_version,
    } for s in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/state-transitions", summary="状态迁移统计（按 from/to 聚合）")
def state_transitions(request: Request, tenant: TenantContext = Depends(get_tenant),
                      db: Session = Depends(get_db)):
    rows = db.scalars(
        select(CustomerStateHistory).where(
            CustomerStateHistory.organization_id == tenant.organization_id
        ).limit(2000)
    ).all()
    agg: dict[str, int] = {}
    for r in rows:
        key = f"{r.lifecycle_from or '-'}→{r.lifecycle_to.value}"
        agg[key] = agg.get(key, 0) + 1
    return {"data": {"transitions": agg}, "meta": {"request_id": request.state.request_id}}


@router.post("/customers/recompute-all", summary="全量重算客户状态（每日补偿）")
def recompute_all_customers(request: Request, store_id: str | None = Query(default=None),
                            tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    tenant.require_role("boss", "admin", "api")
    sid = _store_ok(tenant, store_id)
    created = revos_state.ensure_all_customers(db, org_id=tenant.organization_id, store_id=sid)
    transitions = revos_state.recompute_all(db, store_id=sid, org_id=tenant.organization_id)
    return {"data": {"customers_created": created, "transitions": transitions},
            "meta": {"request_id": request.state.request_id}}


# ================= Opportunity =================
@router.post("/opportunities/detect/{scenario}", summary="运行机会识别（dormant-recovery/overdue-revisit/referral/all）")
def detect_opportunities(scenario: str, request: Request,
                         store_id: str | None = Query(default=None),
                         shadow: bool = Query(default=False),
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    tenant.require_role("boss", "admin", "api")
    sid = _store_ok(tenant, store_id)
    result = revos_opportunity.run_detection(db, sid, org_id=tenant.organization_id,
                                             scenario=scenario, shadow=shadow)
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/opportunities", summary="统一机会池")
def list_opportunities(request: Request, money_type: str | None = Query(default=None),
                       scenario_type: str | None = Query(default=None),
                       status: str | None = Query(default=None),
                       store_id: str | None = Query(default=None),
                       customer_id: str | None = Query(default=None),
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    rows = revos_opportunity.list_opportunities(db, tenant, money_type, scenario_type, status,
                                                sid, customer_id)
    return {"data": [_opp_out(o) for o in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/opportunities/{opportunity_id}", summary="机会详情 + 时间线")
def get_opportunity(opportunity_id: str, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    return {"data": _opp_out(opp), "meta": {"request_id": request.state.request_id}}


@router.patch("/opportunities/{opportunity_id}/suppress", summary="人工抑制机会")
def suppress_opportunity(opportunity_id: str, body: dict, request: Request,
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    opp = revos_opportunity.suppress_opportunity(db, opportunity_id,
                                                 reason=body.get("reason") or "人工抑制",
                                                 by=tenant.actor_id)
    return {"data": {"opportunity_id": opp.opportunity_id, "status": opp.status.value},
            "meta": {"request_id": request.state.request_id}}


@router.post("/opportunities/{opportunity_id}/qualify", summary="机会合格化")
def qualify_opportunity(opportunity_id: str, request: Request,
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    opp = revos_opportunity.qualify_opportunity(db, opportunity_id, owner_staff_id=tenant.actor_id)
    return {"data": {"opportunity_id": opp.opportunity_id, "status": opp.status.value},
            "meta": {"request_id": request.state.request_id}}


class AssignExperimentBody(BaseModel):
    experiment_id: str
    group: str = "treatment_a"  # treatment_a / control


@router.post("/opportunities/{opportunity_id}/assign-experiment", summary="机会实验分组（内容生成前）")
def assign_experiment(opportunity_id: str, body: AssignExperimentBody, request: Request,
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    exp = _owned(db, Experiment, body.experiment_id, tenant, "实验")
    if opp.experiment_id and opp.experiment_id != body.experiment_id:
        raise ClinicOSError("CONFLICT", "机会已属于其他实验", status_code=409)
    opp.experiment_id = body.experiment_id
    opp.experiment_group = body.group
    db.commit()
    return {"data": {"opportunity_id": opp.opportunity_id, "experiment_id": body.experiment_id,
                     "group": body.group}, "meta": {"request_id": request.state.request_id}}


@router.post("/opportunities/{opportunity_id}/arbitrate", summary="对客户触发统一仲裁")
def arbitrate(opportunity_id: str, request: Request,
              tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    result = revos_arbitration.arbitrate_customer(db, opp.customer_id)
    return {"data": {
        "primary": result.primary.opportunity_id if result.primary else None,
        "suppressed": [o.opportunity_id for o in result.suppressed],
        "deferred": [o.opportunity_id for o in result.deferred],
        "reasons": result.reasons,
    }, "meta": {"request_id": request.state.request_id}}


@router.post("/opportunities/{opportunity_id}/decide", summary="生成 Decision（Next Best Action）")
def decide_opportunity(opportunity_id: str, request: Request,
                       shadow: bool = Query(default=False),
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    output = revos_decision.decide(db, opp, shadow=shadow)
    if not output.execute:
        return {"data": {"execute": False, "rationale": output.rationale},
                "meta": {"request_id": request.state.request_id}}
    decision = revos_decision.persist_decision(db, opp, output, shadow=shadow)
    db.commit()
    return {"data": {"decision_id": decision.decision_id, "selected_action": decision.selected_action,
                     "channel": decision.selected_channel, "requires_human_review": decision.requires_human_review,
                     "psychology_strategy": decision.psychology_strategy.value if decision.psychology_strategy else None,
                     "rationale": decision.rationale}, "meta": {"request_id": request.state.request_id}}


# ================= Decision / ExecutionPlan =================
@router.get("/decisions", summary="决策记录列表")
def list_decisions(request: Request, opportunity_id: str | None = Query(default=None),
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(Decision)
    query = tenant.scope_query(query, Decision)
    if opportunity_id:
        query = query.where(Decision.opportunity_id == opportunity_id)
    rows = db.scalars(query.order_by(Decision.created_at.desc()).limit(100)).all()
    return {"data": [{
        "decision_id": d.decision_id, "opportunity_id": d.opportunity_id,
        "selected_action": d.selected_action, "selected_channel": d.selected_channel,
        "selected_timing": d.selected_timing,
        "psychology_strategy": d.psychology_strategy.value if d.psychology_strategy else None,
        "requires_human_review": d.requires_human_review, "confidence": float(d.confidence or 0),
        "policy_version": d.policy_version, "shadow": d.shadow, "rationale": d.rationale,
    } for d in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/opportunities/{opportunity_id}/execution-plan", summary="创建 ExecutionPlan")
def create_execution_plan(opportunity_id: str, request: Request,
                          tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    decision = db.scalar(
        select(Decision).where(Decision.opportunity_id == opportunity_id)
        .order_by(Decision.created_at.desc()).limit(1)
    )
    plan = revos_plan.create_plan(db, opp, decision)
    db.commit()
    return {"data": {"execution_plan_id": plan.execution_plan_id, "plan_version": plan.plan_version,
                     "review_status": plan.review_status.value, "goal": plan.goal},
            "meta": {"request_id": request.state.request_id}}


@router.get("/execution-plans", summary="执行方案列表")
def list_plans(request: Request, status: str | None = Query(default=None),
               opportunity_id: str | None = Query(default=None),
               tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(ExecutionPlan).where(ExecutionPlan.deleted_at.is_(None))
    query = tenant.scope_query(query, ExecutionPlan)
    if status:
        query = query.where(ExecutionPlan.review_status == status)
    if opportunity_id:
        query = query.where(ExecutionPlan.opportunity_id == opportunity_id)
    rows = db.scalars(query.order_by(ExecutionPlan.created_at.desc()).limit(200)).all()
    return {"data": [_plan_out(p) for p in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/execution-plans/{plan_id}", summary="执行方案详情")
def get_plan(plan_id: str, request: Request,
             tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    plan = _owned(db, ExecutionPlan, plan_id, tenant, "执行方案")
    return {"data": _plan_out(plan), "meta": {"request_id": request.state.request_id}}


class ReviewBody(BaseModel):
    decision: str = Field(..., description="approved / rejected / changes_requested")
    review_note: str | None = None
    expected_content_hash: str | None = None


@router.post("/execution-plans/{plan_id}/review", summary="人工审核完整执行方案")
def review_plan(plan_id: str, body: ReviewBody, request: Request,
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    plan = _owned(db, ExecutionPlan, plan_id, tenant, "执行方案")
    if tenant.force_store_scope and plan.assigned_staff_id and tenant.actor_id == plan.assigned_staff_id:
        # 员工不得审批自己的高风险内容
        tenant.require_role("boss", "admin")
    plan = revos_review.review_plan(db, plan, body.decision, reviewer=tenant.actor_id,
                                    note=body.review_note,
                                    expected_content_hash=body.expected_content_hash,
                                    reviewer_role=tenant.role)
    db.commit()
    return {"data": {"execution_plan_id": plan.execution_plan_id,
                     "review_status": plan.review_status.value,
                     "content_hash": plan.content_hash},
            "meta": {"request_id": request.state.request_id}}


# ================= Content =================
@router.post("/opportunities/{opportunity_id}/generate-content", summary="生成内容草稿（Treatment 组）")
def generate_content(opportunity_id: str, request: Request,
                     strategy_code: str | None = Query(default=None),
                     tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    if opp.experiment_group == "control":
        raise ClinicOSError("FORBIDDEN", "对照组不得生成内容/任务/触达", status_code=403, retryable=False)
    plan = revos_plan.get_active_plan(db, opportunity_id)
    draft = revos_content.generate_content(db, opp, plan.execution_plan_id if plan else None,
                                           strategy_code=strategy_code, actor=tenant.actor_id)
    db.commit()
    return {"data": {"content_draft_id": draft.content_draft_id, "title": draft.title,
                     "status": draft.status.value, "content_hash": draft.content_hash,
                     "risk_flags": draft.risk_flags},
            "meta": {"request_id": request.state.request_id}}


@router.get("/content-drafts", summary="内容草稿列表（审核中心）")
def list_drafts(request: Request, status: str | None = Query(default=None),
                store_id: str | None = Query(default=None),
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    rows = revos_review.list_pending_reviews(db, tenant, sid, status)
    return {"data": [_draft_out(d) for d in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/content-drafts/{draft_id}", summary="内容草稿详情")
def get_draft(draft_id: str, request: Request,
              tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    return {"data": _draft_out(draft), "meta": {"request_id": request.state.request_id}}


@router.get("/content-drafts/{draft_id}/versions", summary="草稿版本历史")
def draft_versions(draft_id: str, request: Request,
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    versions = db.scalars(
        select(ContentDraft).where(
            ContentDraft.opportunity_id == draft.opportunity_id,
            ContentDraft.deleted_at.is_(None),
        ).order_by(ContentDraft.version.asc())
    ).all()
    return {"data": [_draft_out(v) for v in versions], "meta": {"request_id": request.state.request_id}}


@router.post("/content-drafts/{draft_id}/machine-check", summary="自动合规检查")
def machine_check(draft_id: str, request: Request,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    from ...models.revos import Opportunity
    opp = db.get(Opportunity, draft.opportunity_id)
    record = revos_review.ensure_machine_checked(db, draft)
    if draft.execution_plan_id:
        plan = db.get(ExecutionPlan, draft.execution_plan_id)
        if plan is not None:
            revos_plan.set_machine_checked(db, plan, {"risk_level": record.risk_level.value,
                                                      "rule_count": len(record.rule_results or [])})
    db.commit()
    return {"data": {"review_id": record.review_id, "risk_level": record.risk_level.value,
                     "rule_results": record.rule_results},
            "meta": {"request_id": request.state.request_id}}


@router.post("/content-drafts/{draft_id}/review", summary="人工审核内容草稿")
def human_review_draft(draft_id: str, body: ReviewBody, request: Request,
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    record = revos_review.human_review(db, draft, body.decision, reviewer=tenant.actor_id,
                                       note=body.review_note,
                                       expected_content_hash=body.expected_content_hash,
                                       reviewer_role=tenant.role)
    db.commit()
    return {"data": {"review_id": record.review_id, "decision": record.decision.value,
                     "risk_level": record.risk_level.value},
            "meta": {"request_id": request.state.request_id}}


@router.post("/content-drafts/{draft_id}/request-change", summary="要求修改（创建新版本并重新审核）")
def request_change(draft_id: str, body: ReviewBody, request: Request,
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    record = revos_review.human_review(db, draft, "changes_requested", reviewer=tenant.actor_id,
                                       note=body.review_note, reviewer_role=tenant.role)
    db.commit()
    return {"data": {"review_id": record.review_id, "decision": "changes_requested"},
            "meta": {"request_id": request.state.request_id}}


@router.post("/content-drafts/{draft_id}/regenerate", summary="重新生成（新版本草稿）")
def regenerate_draft(draft_id: str, request: Request,
                     tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    opp = db.get(Opportunity, draft.opportunity_id)
    latest = db.scalar(
        select(ContentDraft).where(
            ContentDraft.opportunity_id == draft.opportunity_id,
            ContentDraft.deleted_at.is_(None),
        ).order_by(ContentDraft.version.desc()).limit(1)
    )
    new_draft = revos_content.generate_content(db, opp, draft.execution_plan_id,
                                               strategy_code=latest.strategy_code if latest else None,
                                               actor=tenant.actor_id)
    new_draft.version = (latest.version if latest else 1) + 1
    if draft.execution_plan_id:
        plan = db.get(ExecutionPlan, draft.execution_plan_id)
        if plan is not None:
            new_plan = revos_plan.new_plan_version(db, plan, reason="内容重新生成")
            new_draft.execution_plan_id = new_plan.execution_plan_id
            plan.status = "aborted"
    db.commit()
    return {"data": {"content_draft_id": new_draft.content_draft_id, "version": new_draft.version},
            "meta": {"request_id": request.state.request_id}}


# ================= 企微执行 =================
@router.post("/content-drafts/{draft_id}/create-send-task", summary="创建企微员工确认发送任务")
def create_send_task(draft_id: str, request: Request,
                     tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    draft = _owned(db, ContentDraft, draft_id, tenant, "内容草稿")
    if draft.status != "approved":
        raise ClinicOSError("FORBIDDEN", "内容未批准，不能创建发送任务", status_code=403, retryable=False)
    plan = None
    if draft.execution_plan_id:
        plan = db.get(ExecutionPlan, draft.execution_plan_id)
    if plan is None:
        opp = db.get(Opportunity, draft.opportunity_id)
        decision = db.scalar(
            select(Decision).where(Decision.opportunity_id == draft.opportunity_id)
            .order_by(Decision.created_at.desc()).limit(1)
        )
        plan = revos_plan.create_plan(db, opp, decision)
        draft.execution_plan_id = plan.execution_plan_id
        plan.content_draft_id = draft.content_draft_id
        db.flush()
    task = revos_wecom.create_send_task(db, plan, draft)
    db.commit()
    return {"data": {"task_id": task.task_id, "send_status": task.send_status,
                     "assigned_to_id": task.assigned_to_id},
            "meta": {"request_id": request.state.request_id}}


@router.get("/send-tasks", summary="发送任务列表（员工端今日执行）")
def list_send_tasks(request: Request, status: str | None = Query(default=None),
                    assigned_to_id: str | None = Query(default=None),
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(Task).where(Task.deleted_at.is_(None), Task.opportunity_id.isnot(None))
    query = tenant.scope_query(query, Task)
    if tenant.force_store_scope:
        query = query.where(Task.assigned_to_id == tenant.actor_id)
    elif assigned_to_id:
        query = query.where(Task.assigned_to_id == assigned_to_id)
    if status:
        query = query.where(Task.send_status == status)
    rows = db.scalars(query.order_by(Task.created_at.desc()).limit(200)).all()
    return {"data": [{
        "task_id": t.task_id, "patient_id": t.patient_id, "opportunity_id": t.opportunity_id,
        "content_draft_id": t.content_draft_id, "assigned_to_id": t.assigned_to_id,
        "send_status": t.send_status, "failure_code": t.failure_code,
        "failure_message": t.failure_message, "external_message_id": t.external_message_id,
        "confirmed_by": t.confirmed_by, "content_hash": t.content_hash,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    } for t in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/send-tasks/{task_id}/prepare-wecom", summary="员工准备发送（解析 external_userid + 预检）")
def prepare_wecom(task_id: str, request: Request,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "发送任务")
    result = revos_wecom.prepare_wecom(db, task)
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.post("/send-tasks/{task_id}/confirm-sent", summary="员工确认已发送")
def confirm_sent(task_id: str, request: Request,
                 tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "发送任务")
    touch = revos_wecom.confirm_sent(db, task, staff_id=tenant.actor_id)
    return {"data": {"touch_id": touch.touch_id, "send_status": touch.send_status,
                     "external_message_id": touch.external_message_id,
                     "failure_code": touch.failure_code},
            "meta": {"request_id": request.state.request_id}}


class FailBody(BaseModel):
    failure_code: str = "staff_cancelled"
    failure_message: str = "员工确认无法发送"


@router.post("/send-tasks/{task_id}/mark-failed", summary="标记发送失败/不适合联系")
def mark_failed(task_id: str, body: FailBody, request: Request,
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "发送任务")
    revos_wecom.mark_failed(db, task, body.failure_code, body.failure_message, staff_id=tenant.actor_id)
    return {"data": {"task_id": task.task_id, "send_status": task.send_status},
            "meta": {"request_id": request.state.request_id}}


class ResponseBody(BaseModel):
    outcome_type: str = "replied"
    note: str | None = None


@router.post("/send-tasks/{task_id}/record-response", summary="记录客户回复结果")
def record_response(task_id: str, body: ResponseBody, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "发送任务")
    if not task.opportunity_id:
        raise ClinicOSError("INVALID_STATE", "任务未关联机会", status_code=409)
    outcome = revos_outcome.record_outcome(
        db, task.opportunity_id, body.outcome_type,
        metadata={"note": body.note, "via": "staff_task"}, actor=tenant.actor_id, allow_client=True,
    )
    task.send_status = "responded"
    db.commit()
    return {"data": {"outcome_id": outcome.outcome_id, "outcome_type": outcome.outcome_type.value},
            "meta": {"request_id": request.state.request_id}}


@router.get("/touches/{touch_id}", summary="触达详情（含回执）")
def get_touch(touch_id: str, request: Request,
              tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    touch = _owned(db, Touch, touch_id, tenant, "触达")
    return {"data": {
        "touch_id": touch.touch_id, "channel": touch.channel.value,
        "sent_at": touch.sent_at.isoformat(), "send_status": touch.send_status,
        "external_message_id": touch.external_message_id, "failure_code": touch.failure_code,
        "failure_message": touch.failure_message, "confirmed_by": touch.confirmed_by,
        "content_hash": touch.content_hash, "opportunity_id": touch.opportunity_id,
        "patient_id": touch.patient_id,
    }, "meta": {"request_id": request.state.request_id}}


# ================= Outcome 与归因 =================
class SyncBody(BaseModel):
    event_type: str
    patient_id: str
    occurred_at: str | None = None
    revenue: float | None = None
    event_id: str | None = None
    metadata: dict | None = None


@router.post("/outcomes/sync", summary="可信诊所SaaS结果回流（服务端）")
def sync_outcomes(body: SyncBody, request: Request,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...core.timeutil import ensure_utc
    from datetime import datetime
    occurred = None
    if body.occurred_at:
        occurred = ensure_utc(datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00")))
    results = revos_outcome.sync_from_trusted_event(
        db, body.event_type, body.patient_id, occurred, body.revenue, body.event_id, body.metadata)
    db.commit()
    return {"data": {"synced": len(results),
                     "outcome_ids": [o.outcome_id for o in results]},
            "meta": {"request_id": request.state.request_id}}


@router.get("/opportunities/{opportunity_id}/outcomes", summary="机会结果列表")
def opportunity_outcomes(opportunity_id: str, request: Request,
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    rows = revos_outcome.list_outcomes(db, tenant, opportunity_id=opportunity_id)
    return {"data": [{
        "outcome_id": o.outcome_id, "outcome_type": o.outcome_type.value,
        "occurred_at": o.occurred_at.isoformat(), "revenue_amount": float(o.revenue_amount or 0),
        "source_event_id": o.source_event_id, "metadata": o.meta,
    } for o in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/experiments/{experiment_id}/calculate", summary="计算实验增量指标（Treatment/Holdout）")
def calculate_experiment(experiment_id: str, request: Request,
                         window_days: int | None = Query(default=None),
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    exp = _owned(db, Experiment, experiment_id, tenant, "实验")
    result = revos_attribution.experiment_metrics(db, experiment_id, window_days=window_days)
    if "error" in result:
        raise ClinicOSError("NOT_FOUND", result["error"], status_code=404)
    db.commit()
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/experiments/{experiment_id}/metrics", summary="实验指标（计算并缓存）")
def experiment_metrics(experiment_id: str, request: Request,
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    exp = _owned(db, Experiment, experiment_id, tenant, "实验")
    result = revos_attribution.experiment_metrics(db, experiment_id)
    if "error" in result:
        raise ClinicOSError("NOT_FOUND", result["error"], status_code=404)
    db.commit()
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/attributions/{opportunity_id}/trace", summary="归因证据链（完整追溯）")
def attribution_trace(opportunity_id: str, request: Request,
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, opportunity_id, tenant, "机会")
    chain = revos_attribution.attribution_trace(db, opportunity_id)
    if "error" in chain:
        raise ClinicOSError("NOT_FOUND", chain["error"], status_code=404)
    return {"data": chain, "meta": {"request_id": request.state.request_id}}


# ================= 小程序 =================
@router.post("/mp/sessions/issue", summary="签发小程序承接 ticket（服务端）")
def issue_mp_ticket(body: dict, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    opp = _owned(db, Opportunity, body.get("opportunity_id", ""), tenant, "机会")
    session, token = revos_mp.issue_ticket(
        db, opp.opportunity_id, opp.customer_id, opp.organization_id, opp.store_id,
        touch_id=body.get("touch_id"), content_draft_id=body.get("content_draft_id"),
    )
    db.commit()
    return {"data": {"interaction_session_id": session.session_id, "ticket": token,
                     "expires_at": session.expires_at.isoformat()},
            "meta": {"request_id": request.state.request_id}}


@router.get("/mp/sessions/{ticket}/offer", summary="小程序获取专属内容（ticket 换内容）")
def mp_offer(ticket: str, request: Request, db: Session = Depends(get_db)):
    # 无认证：ticket 本身就是凭据（高熵、短期、可撤销）
    data = revos_mp.get_offer(db, ticket)
    db.commit()
    return {"data": data, "meta": {"request_id": request.state.request_id}}


class MpEventBody(BaseModel):
    event_id: str
    interaction_session_id: str
    event_type: str
    occurred_at: str
    page_code: str | None = None
    payload: dict | None = None


@router.post("/mp/events", summary="小程序行为上报（幂等）")
def mp_events(body: MpEventBody, request: Request, db: Session = Depends(get_db)):
    from ...core.timeutil import ensure_utc
    from datetime import datetime
    occurred = ensure_utc(datetime.fromisoformat(body.occurred_at.replace("Z", "+00:00"))) or utcnow()
    mp_event = revos_mp.record_event(db, body.event_id, body.interaction_session_id,
                                     body.event_type, occurred, body.page_code, body.payload)
    db.commit()
    return {"data": {"mp_event_id": mp_event.mp_event_id, "duplicate": False},
            "meta": {"request_id": request.state.request_id}}


@router.post("/mp/login", summary="wx.login code 换会话（openid）")
def mp_login(body: dict, request: Request, db: Session = Depends(get_db)):
    data = revos_mp.wx_login_session(db, body.get("code", ""))
    return {"data": {"openid": data.get("openid"), "mock": data.get("mock", False)},
            "meta": {"request_id": request.state.request_id}}


# ================= 策略注册中心 =================
class StrategyBody(BaseModel):
    category: str
    code: str
    definition: dict
    change_reason: str | None = None


@router.post("/strategy-versions", summary="注册策略新版本")
def register_strategy(body: StrategyBody, request: Request,
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sv = revos_strategy.register_strategy(db, body.category, body.code, body.definition,
                                          owner=tenant.actor_id, change_reason=body.change_reason,
                                          organization_id=tenant.organization_id)
    return {"data": {"strategy_version_id": sv.strategy_version_id, "category": sv.category,
                     "code": sv.code, "version": sv.version, "status": sv.status.value},
            "meta": {"request_id": request.state.request_id}}


@router.get("/strategy-versions", summary="策略版本列表")
def list_strategies(request: Request, category: str | None = Query(default=None),
                    code: str | None = Query(default=None), status: str | None = Query(default=None),
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    rows = revos_strategy.list_versions(db, tenant, category, code, status)
    return {"data": [{
        "strategy_version_id": s.strategy_version_id, "category": s.category,
        "code": s.code, "version": s.version, "status": s.status.value,
        "content_hash": s.content_hash, "owner": s.owner, "change_reason": s.change_reason,
        "rollback_version": s.rollback_version,
        "effective_from": s.effective_from.isoformat() if s.effective_from else None,
    } for s in rows], "meta": {"request_id": request.state.request_id}}


class TransitionBody(BaseModel):
    target: str
    reason: str | None = None


@router.post("/strategy-versions/{strategy_version_id}/transition", summary="策略状态流转")
def transition_strategy(strategy_version_id: str, body: TransitionBody, request: Request,
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sv = _owned(db, StrategyVersion, strategy_version_id, tenant, "策略版本")
    sv = revos_strategy.transition(db, strategy_version_id, body.target,
                                   approver=tenant.actor_id, reason=body.reason)
    db.commit()
    return {"data": {"strategy_version_id": sv.strategy_version_id, "status": sv.status.value},
            "meta": {"request_id": request.state.request_id}}


@router.post("/strategy-versions/{strategy_version_id}/rollback", summary="策略回滚")
def rollback_strategy(strategy_version_id: str, body: TransitionBody, request: Request,
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sv = _owned(db, StrategyVersion, strategy_version_id, tenant, "策略版本")
    sv = revos_strategy.rollback(db, strategy_version_id, body.reason or "人工回滚", actor=tenant.actor_id)
    db.commit()
    return {"data": {"strategy_version_id": sv.strategy_version_id, "status": sv.status.value},
            "meta": {"request_id": request.state.request_id}}


@router.get("/strategy-performance", summary="策略效果列表")
def list_performance(request: Request, strategy_code: str | None = Query(default=None),
                     tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    query = select(StrategyPerformance)
    query = tenant.scope_query(query, StrategyPerformance)
    if strategy_code:
        query = query.where(StrategyPerformance.strategy_code == strategy_code)
    rows = db.scalars(query.order_by(StrategyPerformance.created_at.desc()).limit(200)).all()
    return {"data": [{
        "performance_id": p.performance_id, "strategy_code": p.strategy_code,
        "category": p.category, "sample_size": p.sample_size,
        "treatment_size": p.treatment_size, "control_size": p.control_size,
        "metrics": p.metrics, "directional_only": p.directional_only,
        "data_quality": p.data_quality, "evaluated_at": p.evaluated_at.isoformat() if p.evaluated_at else None,
    } for p in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/strategy-performance/guardrails", summary="护栏评估（DNC/投诉超阈值建议）")
def guardrails(request: Request, strategy_code: str | None = Query(default=None),
               tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    alerts = revos_strategy.evaluate_guardrails(db, strategy_code)
    return {"data": alerts, "meta": {"request_id": request.state.request_id}}


# ================= 三种钱驾驶舱 =================
@router.get("/analytics/revos/cockpit", summary="三种钱驾驶舱（统一 Opportunity/Outcome 数据源）")
def cockpit(request: Request, store_id: str | None = Query(default=None),
            tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    opp_q = select(Opportunity).where(Opportunity.deleted_at.is_(None))
    opp_q = tenant.scope_query(opp_q, Opportunity)
    if sid:
        opp_q = opp_q.where(Opportunity.store_id == sid)
    opps = db.scalars(opp_q).all()
    money_groups: dict[str, dict] = {}
    for m in ("future", "current", "past"):
        money_groups[m] = {
            "opportunity_customers": 0, "expected_amount": 0.0,
            "pending_amount": 0.0, "executing_amount": 0.0,
            "won_incremental": 0.0, "opportunity_count": 0,
            "status_breakdown": {},
        }
    for opp in opps:
        m = opp.money_type.value
        g = money_groups.setdefault(m, {
            "opportunity_customers": 0, "expected_amount": 0.0,
            "pending_amount": 0.0, "executing_amount": 0.0,
            "won_incremental": 0.0, "opportunity_count": 0, "status_breakdown": {},
        })
        g["opportunity_count"] += 1
        g["expected_amount"] += float(opp.expected_revenue or 0)
        g["status_breakdown"][opp.status.value] = g["status_breakdown"].get(opp.status.value, 0) + 1
        if opp.status.value in ("candidate", "qualified", "approved"):
            g["pending_amount"] += float(opp.expected_revenue or 0)
        elif opp.status.value == "executing":
            g["executing_amount"] += float(opp.expected_revenue or 0)
        elif opp.status.value == "won":
            g["won_incremental"] += float(opp.expected_revenue or 0)

    # 客户去重统计
    for opp in opps:
        m = opp.money_type.value
        money_groups[m]["opportunity_customers"] = len({
            o.customer_id for o in opps if o.money_type.value == m
        })

    outcome_rows = db.scalars(
        select(Outcome).where(Outcome.organization_id == tenant.organization_id).limit(2000)
    ).all()
    conversion_funnel = {"replied": 0, "appointment": 0, "visited": 0, "paid": 0,
                         "dnc": 0, "complaint": 0}
    for o in outcome_rows:
        if o.outcome_type.value in conversion_funnel:
            conversion_funnel[o.outcome_type.value] += 1

    return {"data": {
        "money_groups": money_groups,
        "conversion_funnel": conversion_funnel,
        "attribution_trust": "directional" if len(outcome_rows) < 100 else "adequate",
        "note": "三种钱为 Opportunity 分类，同一客户可有多个机会；同一运营周期仅一个主要外部计划",
    }, "meta": {"request_id": request.state.request_id}}


# ================= 企微回调（R-06） =================
class WecomCallbackQuery(BaseModel):
    msg_signature: str | None = None
    timestamp: str | None = None
    nonce: str | None = None


@router.post("/wecom/callback", summary="企微回调（验签 + 幂等状态更新）")
def wecom_callback(request: Request, body: dict = None,
                   msg_signature: str | None = Query(default=None),
                   timestamp: str | None = Query(default=None),
                   nonce: str | None = Query(default=None),
                   db: Session = Depends(get_db)):
    """接收企微回调。真实回调为 AES 加密 XML；验签公式 SHA1(sort(token,timestamp,nonce,encrypt))。

    简化接入：body 传标准化事件 {"event_type","external_message_id","send_status",
    "member_userid","occurred_at"}；验签用 REVOS_WECOM_TOKEN（缺省环境变量）。
    """
    import os
    from ...config import get_settings
    settings = get_settings()
    token = os.environ.get("REVOS_WECOM_TOKEN", "") or "dev-wecom-callback-token"
    encrypt_msg = str((body or {}).get("encrypt") or "")
    signature = msg_signature or (body or {}).get("msg_signature") or ""
    ts = timestamp or (body or {}).get("timestamp") or str(int(time.time()))
    nc = nonce or (body or {}).get("nonce") or ""
    if not revos_wecom.verify_wecom_signature(token, ts, nc, encrypt_msg, signature):
        raise ClinicOSError("FORBIDDEN", "回调签名无效", status_code=403, retryable=False)
    if not body:
        raise ClinicOSError("INVALID_ARGUMENT", "缺少回调事件", status_code=400)
    event = body.get("event", body)
    result = revos_wecom.handle_wecom_callback(
        db,
        event_type=str(event.get("event_type") or "wecom.send_status"),
        external_message_id=str(event.get("external_message_id") or event.get("msgid") or ""),
        send_status=str(event.get("send_status") or "unknown"),
        member_userid=event.get("member_userid"),
        occurred_at=event.get("occurred_at"),
    )
    db.commit()
    return {"data": result, "meta": {"request_id": request.state.request_id}}


# ================= 持久 Job / Outbox（R-07） =================
@router.get("/jobs", summary="Job 列表（状态查询）")
def list_jobs(request: Request, status: str | None = Query(default=None),
              job_type: str | None = Query(default=None),
              tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.outbox import Job as JobModel
    rows = revos_jobs.list_jobs(db, tenant, status, job_type)
    return {"data": [{
        "job_id": j.job_id, "job_type": j.job_type, "status": j.status,
        "attempt": j.attempt, "max_attempts": j.max_attempts,
        "lease_until": j.lease_until.isoformat() if j.lease_until else None,
        "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
        "last_error": j.last_error, "requeued_by": j.requeued_by,
        "created_at": j.created_at.isoformat() if j.created_at else None,
        "payload": j.payload,
    } for j in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/jobs", summary="创建 Job（人工触发）")
def create_job(body: dict, request: Request,
               tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    job = revos_jobs.enqueue_job(
        db, tenant.organization_id, str(body.get("job_type", "daily_ops")),
        payload=body.get("payload"), store_id=tenant.store_id,
        max_attempts=int(body.get("max_attempts") or 5),
    )
    db.commit()
    return {"data": {"job_id": job.job_id, "status": job.status},
            "meta": {"request_id": request.state.request_id}}


@router.post("/jobs/{job_id}/requeue", summary="人工重放 Job（死信/失败重新入队，保留审计）")
def requeue_job(job_id: str, request: Request,
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.outbox import Job as JobModel
    job = _owned(db, JobModel, job_id, tenant, "任务")
    job = revos_jobs.requeue_job(db, job_id, by=tenant.actor_id)
    db.commit()
    return {"data": {"job_id": job.job_id, "status": job.status},
            "meta": {"request_id": request.state.request_id}}


@router.post("/outbox/poll", summary="手动触发 Outbox 发布（管理员/测试）")
def outbox_poll(request: Request, tenant: TenantContext = Depends(get_tenant),
                db: Session = Depends(get_db)):
    tenant.require_role("boss", "admin", "api")
    published = revos_outbox.outbox_worker_poll(db)
    return {"data": {"published": published}, "meta": {"request_id": request.state.request_id}}


# ================= Connector（R-09） =================
class ConnectorBody(BaseModel):
    name: str
    kind: str = "clinicos_saas"
    base_url: str | None = None
    auth_type: str = "api_key"
    api_key_ref: str | None = None
    field_mapping: dict | None = None
    entity_enabled: dict | None = None
    enabled: bool = True


@router.get("/connectors", summary="Connector 配置列表")
def list_connectors(request: Request, tenant: TenantContext = Depends(get_tenant),
                    db: Session = Depends(get_db)):
    from ...models.connector import ConnectorConfig
    query = select(ConnectorConfig).where(ConnectorConfig.deleted_at.is_(None))
    query = tenant.scope_query(query, ConnectorConfig)
    rows = db.scalars(query).all()
    return {"data": [{
        "connector_id": c.connector_id, "name": c.name, "kind": c.kind,
        "base_url": c.base_url, "auth_type": c.auth_type, "api_key_ref": c.api_key_ref,
        "entity_enabled": c.entity_enabled, "enabled": c.enabled,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    } for c in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/connectors", summary="创建 Connector 配置")
def create_connector(body: ConnectorBody, request: Request,
                     tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.connector import ConnectorConfig
    c = ConnectorConfig(
        connector_id=new_id("connector"),
        organization_id=tenant.organization_id,
        store_id=tenant.store_id,
        name=body.name, kind=body.kind, base_url=body.base_url,
        auth_type=body.auth_type, api_key_ref=body.api_key_ref,
        field_mapping=body.field_mapping, entity_enabled=body.entity_enabled,
        enabled=body.enabled,
    )
    db.add(c)
    db.commit()
    return {"data": {"connector_id": c.connector_id}, "meta": {"request_id": request.state.request_id}}


@router.post("/connectors/{connector_id}/sync", summary="触发同步（入队 Job）")
def sync_connector(connector_id: str, request: Request, mode: str = Query(default="incremental"),
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.connector import ConnectorConfig
    connector = _owned(db, ConnectorConfig, connector_id, tenant, "连接器")
    job = revos_connector.enqueue_connector_sync(db, connector, mode)
    db.commit()
    return {"data": {"job_id": job.job_id, "status": job.status},
            "meta": {"request_id": request.state.request_id}}


@router.post("/connectors/{connector_id}/webhook", summary="Connector Webhook 实时事件（服务端）")
def connector_webhook(connector_id: str, body: dict, request: Request,
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.connector import ConnectorConfig
    connector = _owned(db, ConnectorConfig, connector_id, tenant, "连接器")
    result = revos_connector.handle_webhook_event(db, connector, body)
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/connectors/{connector_id}/runs", summary="同步运行记录")
def connector_runs(connector_id: str, request: Request,
                   tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.connector import ConnectorConfig, ConnectorRun
    connector = _owned(db, ConnectorConfig, connector_id, tenant, "连接器")
    rows = db.scalars(
        select(ConnectorRun).where(
            ConnectorRun.connector_id == connector_id,
            ConnectorRun.deleted_at.is_(None),
        ).order_by(ConnectorRun.started_at.desc()).limit(50)
    ).all()
    return {"data": [{
        "run_id": r.run_id, "entity": r.entity, "sync_mode": r.sync_mode,
        "status": r.status, "pulled": r.pulled, "inserted": r.inserted,
        "skipped": r.skipped, "error": r.error,
        "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    } for r in rows], "meta": {"request_id": request.state.request_id}}


@router.get("/reconciliation/diffs", summary="对账差异列表（定位到 ID）")
def reconciliation_diffs(request: Request, diff_date: str | None = Query(default=None),
                         entity: str | None = Query(default=None),
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models.connector import ReconciliationDiff
    query = select(ReconciliationDiff).where(ReconciliationDiff.deleted_at.is_(None))
    query = tenant.scope_query(query, ReconciliationDiff)
    if diff_date:
        query = query.where(ReconciliationDiff.diff_date == diff_date)
    if entity:
        query = query.where(ReconciliationDiff.entity == entity)
    rows = db.scalars(query.order_by(ReconciliationDiff.created_at.desc()).limit(100)).all()
    return {"data": [{
        "diff_id": d.diff_id, "diff_date": d.diff_date, "entity": d.entity,
        "field": d.field, "source_value": d.source_value, "revos_value": d.revos_value,
        "entity_id": d.entity_id, "status": d.status,
    } for d in rows], "meta": {"request_id": request.state.request_id}}


# ================= 待人工归因队列（R-04） =================
@router.get("/attribution/manual-review-queue", summary="待人工归因队列")
def manual_review_queue(request: Request, tenant: TenantContext = Depends(get_tenant),
                        db: Session = Depends(get_db)):
    from ...models.business import BusinessFact
    from ...core.enums import MatchStatus
    query = select(BusinessFact).where(
        BusinessFact.match_status == MatchStatus.MANUAL_REVIEW,
        BusinessFact.deleted_at.is_(None),
    )
    query = tenant.scope_query(query, BusinessFact)
    rows = db.scalars(query.order_by(BusinessFact.occurred_at.desc()).limit(100)).all()
    return {"data": [{
        "fact_id": f.fact_id, "fact_type": f.fact_type, "occurred_at": f.occurred_at.isoformat(),
        "revenue_amount": float(f.revenue_amount or 0), "refund_amount": float(f.refund_amount or 0),
        "match_reason": f.match_reason, "patient_id": f.patient_id,
        "source_system": f.source_system, "source_event_id": f.source_event_id,
    } for f in rows], "meta": {"request_id": request.state.request_id}}


# ================= 输出辅助 =================
def _opp_out(opp: Opportunity) -> dict:
    return {
        "opportunity_id": opp.opportunity_id, "customer_id": opp.customer_id,
        "patient_id": opp.patient_id, "money_type": opp.money_type.value,
        "scenario_type": opp.scenario_type.value, "lifecycle_state": opp.lifecycle_state.value,
        "status": opp.status.value, "priority_score": float(opp.priority_score or 0),
        "expected_revenue": float(opp.expected_revenue or 0),
        "probability": float(opp.probability or 0),
        "expected_cost": float(opp.expected_cost or 0),
        "reason_codes": opp.reason_codes, "context_snapshot": opp.context_snapshot,
        "detector_version": opp.detector_version, "scoring_version": opp.scoring_version,
        "workflow_code": opp.workflow_code, "experiment_id": opp.experiment_id,
        "experiment_group": opp.experiment_group, "owner_staff_id": opp.owner_staff_id,
        "detected_at": opp.detected_at.isoformat() if opp.detected_at else None,
        "expires_at": opp.expires_at.isoformat() if opp.expires_at else None,
        "store_id": opp.store_id,
    }


def _plan_out(p: ExecutionPlan) -> dict:
    return {
        "execution_plan_id": p.execution_plan_id, "opportunity_id": p.opportunity_id,
        "decision_id": p.decision_id, "plan_version": p.plan_version, "goal": p.goal,
        "steps": p.steps, "assigned_staff_id": p.assigned_staff_id, "channel": p.channel,
        "timing": p.timing, "content_draft_id": p.content_draft_id,
        "offer_reference": p.offer_reference, "compliance_result": p.compliance_result,
        "review_status": p.review_status.value, "review_decision": p.review_decision.value,
        "reviewed_by": p.reviewed_by, "reviewed_at": p.reviewed_at.isoformat() if p.reviewed_at else None,
        "review_note": p.review_note, "content_hash": p.content_hash,
        "expected_value": float(p.expected_value or 0), "expected_cost": float(p.expected_cost or 0),
        "experiment_id": p.experiment_id, "experiment_group": p.experiment_group,
        "status": p.status, "immutable": p.immutable,
    }


def _draft_out(d: ContentDraft) -> dict:
    return {
        "content_draft_id": d.content_draft_id, "opportunity_id": d.opportunity_id,
        "execution_plan_id": d.execution_plan_id, "version": d.version,
        "generation_mode": d.generation_mode, "model_provider": d.model_provider,
        "model_name": d.model_name, "strategy_code": d.strategy_code,
        "title": d.title, "wecom_text": d.wecom_text, "image_url": d.image_url,
        "mini_program_config": d.mini_program_config, "risk_flags": d.risk_flags,
        "content_hash": d.content_hash, "estimated_cost": float(d.estimated_cost or 0),
        "status": d.status.value, "created_at": d.created_at.isoformat() if d.created_at else None,
    }
