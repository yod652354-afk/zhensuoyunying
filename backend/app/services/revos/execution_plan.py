"""ExecutionPlan 服务（规格 03 §10 / 企微规格 §5.2）。

ExecutionPlan 是人工审核的完整对象（不只是文案）：
目标、步骤、渠道/时间/员工、内容与图片、小程序承接、优惠引用、
停止/升级条件、风险检查、实验组、预计成本与增量价值、
不可变版本与内容哈希。

状态：draft → machine_checked → pending_review → approved / rejected / changes_requested
批准版本不可修改；任何修改创建新版本并重新审核。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import OpportunityStatus, PlanStatus, ReviewDecision
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models.revos import Decision, ExecutionPlan, Opportunity
from ..assignment import resolve_assignee


def _default_steps(workflow_code: str | None) -> list[dict]:
    if workflow_code == "dormant_recovery_v1":
        return [
            {"step": "generate_content", "name": "生成内容草稿", "handler": "content_provider"},
            {"step": "machine_compliance_check", "name": "自动合规检查", "handler": "compliance_check"},
            {"step": "human_review", "name": "人工审核完整方案", "handler": "review"},
            {"step": "create_wecom_send_task", "name": "创建企微员工确认任务", "handler": "wecom"},
            {"step": "member_confirm_send", "name": "员工确认发送", "handler": "wecom"},
            {"step": "wait_for_response", "name": "等待客户响应", "handler": "outcome"},
            {"step": "sync_appointment_visit_payment", "name": "预约/到店/支付回流", "handler": "outcome"},
            {"step": "calculate_attribution", "name": "计算增量归因", "handler": "attribution"},
        ]
    return [
        {"step": "generate_content", "name": "生成内容草稿", "handler": "content_provider"},
        {"step": "machine_compliance_check", "name": "自动合规检查", "handler": "compliance_check"},
        {"step": "human_review", "name": "人工审核完整方案", "handler": "review"},
        {"step": "execute", "name": "执行", "handler": "execution"},
        {"step": "collect_outcome", "name": "结果回流", "handler": "outcome"},
    ]


def create_plan(
    db: Session,
    opportunity: Opportunity,
    decision: Decision | None,
    assigned_staff_id: str | None = None,
    causation_event_id: str | None = None,
) -> ExecutionPlan:
    """从 Opportunity + Decision 构建完整 ExecutionPlan（V1）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    store_id = opportunity.store_id
    if not assigned_staff_id:
        patient_id = opportunity.patient_id
        if patient_id:
            try:
                assign_type, assign_id = resolve_assignee(db, patient_id, store_id)
                if assign_type == "staff":
                    assigned_staff_id = assign_id
            except Exception:  # noqa: BLE001  分配失败不阻断方案创建
                pass

    expected_value = Decimal(str(opportunity.expected_revenue or 0)) * Decimal(str(opportunity.probability or 0))
    plan = ExecutionPlan(
        execution_plan_id=new_id("execution_plan"),
        organization_id=opportunity.organization_id,
        store_id=opportunity.store_id,
        opportunity_id=opportunity.opportunity_id,
        decision_id=decision.decision_id if decision else None,
        customer_id=opportunity.customer_id,
        patient_id=opportunity.patient_id,
        plan_version=1,
        goal=f"{opportunity.money_type.value}钱机会 {opportunity.scenario_type.value}：客户激活/转化",
        steps=_default_steps(opportunity.workflow_code),
        assigned_staff_id=assigned_staff_id,
        channel=decision.selected_channel if decision else "enterprise_wechat",
        timing=decision.selected_timing if decision else "workday_10_11",
        offer_reference=None,  # 优惠必须来自门店配置，V1 不自动创建
        compliance_result=None,
        review_status=PlanStatus.DRAFT,
        review_decision=ReviewDecision.PENDING,
        expected_value=expected_value,
        expected_cost=opportunity.expected_cost or Decimal("0"),
        experiment_id=opportunity.experiment_id,
        experiment_group=opportunity.experiment_group,
        status="draft",
    )
    db.add(plan)
    db.flush()
    opportunity.status = OpportunityStatus.APPROVED if opportunity.status == OpportunityStatus.QUALIFIED else opportunity.status
    emit(db, "execution_plan.created", plan.organization_id, "execution_plan", plan.execution_plan_id,
         store_id=plan.store_id, patient_id=plan.patient_id, actor_type=ActorType.AI,
         correlation_id=opportunity.opportunity_id, causation_id=causation_event_id,
         payload={"goal": plan.goal, "channel": plan.channel, "review_status": plan.review_status.value,
                  "expected_value": float(plan.expected_value)})
    return plan


def new_plan_version(db: Session, plan: ExecutionPlan, reason: str = "") -> ExecutionPlan:
    """内容修改后创建新版本并重新审核（旧版本保留）。"""
    if plan.immutable and plan.review_status == PlanStatus.APPROVED:
        # 已批准不可修改：新建版本
        pass
    new_plan = ExecutionPlan(
        execution_plan_id=new_id("execution_plan"),
        organization_id=plan.organization_id,
        store_id=plan.store_id,
        opportunity_id=plan.opportunity_id,
        decision_id=plan.decision_id,
        customer_id=plan.customer_id,
        patient_id=plan.patient_id,
        plan_version=plan.plan_version + 1,
        goal=plan.goal,
        steps=plan.steps,
        assigned_staff_id=plan.assigned_staff_id,
        channel=plan.channel,
        timing=plan.timing,
        offer_reference=plan.offer_reference,
        compliance_result=None,
        review_status=PlanStatus.DRAFT,
        review_decision=ReviewDecision.PENDING,
        expected_value=plan.expected_value,
        expected_cost=plan.expected_cost,
        experiment_id=plan.experiment_id,
        experiment_group=plan.experiment_group,
        status="draft",
    )
    db.add(new_plan)
    db.flush()
    if reason:
        new_plan.review_note = reason
    return new_plan


def set_machine_checked(db: Session, plan: ExecutionPlan, compliance_result: dict) -> None:
    plan.compliance_result = compliance_result
    plan.review_status = PlanStatus.MACHINE_CHECKED
    plan.review_decision = ReviewDecision.PENDING
    db.flush()


def submit_for_review(db: Session, plan: ExecutionPlan) -> None:
    if plan.review_status in (PlanStatus.DRAFT, PlanStatus.MACHINE_CHECKED,
                              PlanStatus.CHANGES_REQUESTED):
        plan.review_status = PlanStatus.PENDING_REVIEW


def approve_plan(db: Session, plan: ExecutionPlan, reviewer: str | None = None,
                 note: str | None = None, content_hash: str | None = None) -> None:
    """人工批准：内容哈希固化，方案不可变。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    plan.review_status = PlanStatus.APPROVED
    plan.review_decision = ReviewDecision.APPROVED
    plan.reviewed_by = reviewer
    plan.reviewed_at = utcnow()
    plan.review_note = note
    if content_hash:
        plan.content_hash = content_hash
    plan.immutable = True
    db.flush()
    emit(db, "execution_plan.reviewed", plan.organization_id, "execution_plan", plan.execution_plan_id,
         store_id=plan.store_id, patient_id=plan.patient_id, actor_type=ActorType.STAFF, actor_id=reviewer,
         correlation_id=plan.opportunity_id,
         payload={"decision": "approved", "plan_version": plan.plan_version, "content_hash": plan.content_hash})


def reject_plan(db: Session, plan: ExecutionPlan, reviewer: str | None = None,
                note: str | None = None) -> None:
    from ...events.bus import emit
    from ...core.enums import ActorType

    plan.review_status = PlanStatus.REJECTED
    plan.review_decision = ReviewDecision.REJECTED
    plan.reviewed_by = reviewer
    plan.reviewed_at = utcnow()
    plan.review_note = note
    db.flush()
    emit(db, "execution_plan.reviewed", plan.organization_id, "execution_plan", plan.execution_plan_id,
         store_id=plan.store_id, patient_id=plan.patient_id, actor_type=ActorType.STAFF, actor_id=reviewer,
         correlation_id=plan.opportunity_id,
         payload={"decision": "rejected", "plan_version": plan.plan_version, "note": note})


def request_changes(db: Session, plan: ExecutionPlan, reviewer: str | None = None,
                    note: str | None = None) -> None:
    from ...events.bus import emit
    from ...core.enums import ActorType

    plan.review_status = PlanStatus.CHANGES_REQUESTED
    plan.review_decision = ReviewDecision.CHANGES_REQUESTED
    plan.reviewed_by = reviewer
    plan.reviewed_at = utcnow()
    plan.review_note = note
    db.flush()
    emit(db, "execution_plan.reviewed", plan.organization_id, "execution_plan", plan.execution_plan_id,
         store_id=plan.store_id, patient_id=plan.patient_id, actor_type=ActorType.STAFF, actor_id=reviewer,
         correlation_id=plan.opportunity_id,
         payload={"decision": "changes_requested", "plan_version": plan.plan_version, "note": note})


def get_active_plan(db: Session, opportunity_id: str) -> ExecutionPlan | None:
    """取机会当前有效方案（最高版本，未删除）。"""
    return db.scalar(
        select(ExecutionPlan).where(
            ExecutionPlan.opportunity_id == opportunity_id,
            ExecutionPlan.deleted_at.is_(None),
        ).order_by(ExecutionPlan.plan_version.desc()).limit(1)
    )
