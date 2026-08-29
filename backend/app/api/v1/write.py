"""Write API（需求规格 5.3）：ClinicOS 回写任务/回访/预约/标签/阶段/活动/触达/实验/归因。

- 关键创建接口支持 Idempotency-Key（R-018）
- 每个业务动作同步产出统一事件（Event），触发 Webhook
- 安全（RevOS P0）：所有写入强制服务端租户 scope；禁止客户端扩大权限
"""
from typing import Optional
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import ActorType, AppointmentStatus, FollowupStatus, TaskStatus
from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant
from ...core.timeutil import utcnow
from ...database import get_db
from ...events.bus import emit
from ...models import (
    Appointment, Campaign, CampaignAudience, Experiment, ExperimentAssignment,
    Followup, Organization, Patient, Store, Task, Touch, Attribution,
)
from ...models.idempotency import IdempotencyRecord
from ...schemas.write import (
    AppointmentCreate, AppointmentUpdate, AssignmentCreate, AttributionCreate,
    AudienceAdd, CampaignCreate, CampaignUpdate, ExperimentCreate,
    FollowupCreate, FollowupUpdate, StageUpdate, TagAdd, TaskCreate, TaskUpdate,
    TouchCreate,
)

router = APIRouter(tags=["Write API"])


def resolve_org_id(db: Session, tenant: TenantContext,
                   store_id: str | None = None, patient_id: str | None = None) -> str:
    """从服务端租户上下文解析 organization_id（不信任客户端传入）。

    客户端传入的 store/patient 若属于其他组织 → 403（禁止扩大 scope）。
    """
    if patient_id:
        p = db.get(Patient, patient_id)
        if p:
            if p.organization_id != tenant.organization_id:
                raise ClinicOSError("FORBIDDEN", "无权操作其他组织的患者", status_code=403, retryable=False)
            return p.organization_id
    if store_id:
        s = db.get(Store, store_id)
        if s:
            if s.organization_id != tenant.organization_id:
                raise ClinicOSError("FORBIDDEN", "无权操作其他组织的门店", status_code=403, retryable=False)
            return s.organization_id
    return tenant.organization_id


def _owned(db: Session, model, entity_id: str, tenant: TenantContext, label: str):
    """按主键取实体并强制租户 scope（跨租户 403）。"""
    entity = db.get(model, entity_id)
    if entity is None or getattr(entity, "deleted_at", None):
        raise ClinicOSError("NOT_FOUND", f"{label}不存在", status_code=404)
    tenant.ensure_scope(entity)
    return entity


def _idempotent(db: Session, request: Request, key: str | None, entity_type: str, pk_field: str, create) -> object:
    """Idempotency-Key 支持：重复请求返回第一次创建的对象，不重复落库。"""
    if key:
        record = db.get(IdempotencyRecord, key)
        if record:
            if record.entity_type != entity_type:
                raise ClinicOSError("CONFLICT", "Idempotency-Key 已被其他实体使用", status_code=409)
            return record.entity_id, True
    obj = create()
    db.flush()
    pk_value = getattr(obj, pk_field)  # 主键默认值在 flush 后生成
    if key:
        db.add(IdempotencyRecord(idempotency_key=key, entity_type=entity_type, entity_id=pk_value))
    return pk_value, False


# ================= Task =================
@router.post("/tasks", summary="创建经营任务（P0）")
def create_task(
    body: TaskCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        task = Task(
            organization_id=resolve_org_id(db, tenant, body.store_id, body.patient_id),
            store_id=body.store_id, task_type=body.task_type, patient_id=body.patient_id,
            assigned_to_type=body.assigned_to_type, assigned_to_id=body.assigned_to_id,
            due_at=body.due_at, priority=body.priority, reason=body.reason,
            expected_value=body.expected_value,
            related_followup_id=body.related_followup_id,
            related_campaign_id=body.related_campaign_id,
            related_experiment_id=body.related_experiment_id,
            created_by_type=body.created_by_type,
        )
        db.add(task)
        return task

    pk, replayed = _idempotent(db, request, idempotency_key, "task", "task_id", create)
    db.commit()
    task = db.get(Task, pk)
    if not replayed:
        emit(db, "task.created", task.organization_id, "task", task.task_id,
             store_id=task.store_id, patient_id=task.patient_id,
             actor_type=ActorType.AI, actor_id=task.created_by_id,
             payload={"task_type": task.task_type.value, "priority": task.priority.value,
                      "reason": task.reason, "expected_value": float(task.expected_value or 0)})
        db.commit()
    return {"data": {"task_id": task.task_id}, "meta": {"request_id": request.state.request_id}}


@router.patch("/tasks/{task_id}", summary="更新任务状态/结果/反馈（P0）")
def update_task(task_id: str, body: TaskUpdate, request: Request,
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "任务")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(task, field, value)
    if body.status == "completed":
        task.completed_at = utcnow()
        # 完成即进入待审核（老板审核执行情况）
        task.review_status = "pending"
    db.commit()
    if body.status is not None:
        emit(db, f"task.{body.status.value}", task.organization_id, "task", task.task_id,
             store_id=task.store_id, patient_id=task.patient_id, actor_type=ActorType.STAFF,
             payload={"status": body.status.value, "result": body.result,
                      "has_feedback": bool(body.feedback_note or body.feedback_images)})
        db.commit()
    return {"data": {"task_id": task.task_id, "status": task.status.value,
                     "review_status": task.review_status}, "meta": {"request_id": request.state.request_id}}


class TaskReviewBody(BaseModel):
    """老板审核：通过 / 退回重做（自动催办）。"""
    approved: bool
    note: str | None = None


@router.patch("/tasks/{task_id}/review", summary="审核任务执行情况（通过/退回重做）")
def review_task(task_id: str, body: TaskReviewBody, request: Request,
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    task = _owned(db, Task, task_id, tenant, "任务")
    reviewer = request.headers.get("X-Reviewer") or "boss"
    task.review_status = "approved" if body.approved else "rejected"
    task.reviewed_by = reviewer
    task.reviewed_at = utcnow()
    task.review_note = body.note
    if not body.approved:
        # 退回重做：状态回到进行中，截止时间顺延 1 天（催办）
        task.status = TaskStatus.IN_PROGRESS
        task.due_at = utcnow() + timedelta(days=1)
    db.commit()
    emit(db, "task.reviewed", task.organization_id, "task", task.task_id,
         store_id=task.store_id, patient_id=task.patient_id,
         actor_type=ActorType.STAFF, actor_id=reviewer,
         payload={"approved": body.approved, "review_status": task.review_status,
                  "note": body.note, "repushed": not body.approved})
    db.commit()
    return {"data": {"task_id": task.task_id, "review_status": task.review_status,
                     "status": task.status.value, "repushed": not body.approved},
            "meta": {"request_id": request.state.request_id}}


# ================= Followup =================
@router.post("/followups", summary="创建回访（P0）")
def create_followup(
    body: FollowupCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        fu = Followup(
            organization_id=resolve_org_id(db, tenant, None, body.patient_id),
            patient_id=body.patient_id, related_visit_id=body.related_visit_id,
            related_appointment_id=body.related_appointment_id, staff_id=body.staff_id,
            scheduled_at=body.scheduled_at, reason=body.reason, channel=body.channel,
            next_action=body.next_action, next_action_at=body.next_action_at,
            created_by_type="AI",
        )
        db.add(fu)
        return fu

    pk, replayed = _idempotent(db, request, idempotency_key, "followup", "followup_id", create)
    db.commit()
    fu = db.get(Followup, pk)
    if not replayed:
        emit(db, "followup.created", fu.organization_id, "followup", fu.followup_id,
             store_id=fu.store_id, patient_id=fu.patient_id, actor_type=ActorType.AI,
             payload={"reason": fu.reason.value, "channel": fu.channel.value})
        db.commit()
    return {"data": {"followup_id": fu.followup_id}, "meta": {"request_id": request.state.request_id}}


@router.patch("/followups/{followup_id}", summary="更新回访结果（P0）")
def update_followup(followup_id: str, body: FollowupUpdate, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    fu = _owned(db, Followup, followup_id, tenant, "回访")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(fu, field, value)
    if body.result is not None:
        fu.status = FollowupStatus.COMPLETED
        fu.completed_at = utcnow()
    db.commit()
    if body.result is not None:
        emit(db, "followup.completed", fu.organization_id, "followup", fu.followup_id,
             store_id=fu.store_id, patient_id=fu.patient_id, actor_type=ActorType.STAFF,
             payload={"result": fu.result.value if fu.result else None,
                      "appointment_created_id": fu.appointment_created_id})
        db.commit()
    return {"data": {"followup_id": fu.followup_id, "status": fu.status.value}, "meta": {"request_id": request.state.request_id}}


# ================= Appointment =================
@router.post("/appointments", summary="创建预约（P0）")
def create_appointment(
    body: AppointmentCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        appt = Appointment(
            organization_id=resolve_org_id(db, tenant, body.store_id, body.patient_id),
            store_id=body.store_id, patient_id=body.patient_id, doctor_id=body.doctor_id,
            staff_id=body.staff_id, service_id=body.service_id, appointment_at=body.appointment_at,
            appointment_source=body.appointment_source, status=body.status,
        )
        db.add(appt)
        return appt

    pk, replayed = _idempotent(db, request, idempotency_key, "appointment", "appointment_id", create)
    db.commit()
    appt = db.get(Appointment, pk)
    if not replayed:
        emit(db, "appointment.created", appt.organization_id, "appointment", appt.appointment_id,
             store_id=appt.store_id, patient_id=appt.patient_id,
             payload={"appointment_at": appt.appointment_at.isoformat(), "status": appt.status.value})
        db.commit()
    return {"data": {"appointment_id": appt.appointment_id}, "meta": {"request_id": request.state.request_id}}


@router.patch("/appointments/{appointment_id}", summary="改期/确认/取消/完成预约（P0）")
def update_appointment(appointment_id: str, body: AppointmentUpdate, request: Request,
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    appt = _owned(db, Appointment, appointment_id, tenant, "预约")
    old_status = appt.status
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)
    if body.status == AppointmentStatus.CANCELLED:
        appt.cancelled_at = utcnow()
    if body.status == AppointmentStatus.NO_SHOW:
        appt.no_show = True
    db.commit()
    if body.status is not None and body.status != old_status:
        emit(db, f"appointment.{body.status.value}", appt.organization_id, "appointment", appt.appointment_id,
             store_id=appt.store_id, patient_id=appt.patient_id,
             payload={"old_status": old_status.value, "cancel_reason": appt.cancel_reason})
        db.commit()
    return {"data": {"appointment_id": appt.appointment_id, "status": appt.status.value}, "meta": {"request_id": request.state.request_id}}


# ================= Patient tags / stage =================
@router.post("/patients/{patient_id}/tags", summary="添加标签（P0）")
def add_patient_tag(patient_id: str, body: TagAdd, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    p = _owned(db, Patient, patient_id, tenant, "患者")
    tags = list(p.tags or [])
    if body.tag not in tags:
        tags.append(body.tag)
    p.tags = tags
    db.commit()
    emit(db, "patient.updated", p.organization_id, "patient", p.patient_id,
         store_id=p.store_id, patient_id=p.patient_id,
         payload={"tags": tags})
    db.commit()
    return {"data": {"patient_id": p.patient_id, "tags": tags}, "meta": {"request_id": request.state.request_id}}


@router.delete("/patients/{patient_id}/tags/{tag_id}", summary="移除标签（P1）")
def remove_patient_tag(patient_id: str, tag_id: str, request: Request,
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    p = _owned(db, Patient, patient_id, tenant, "患者")
    tags = [t for t in (p.tags or []) if t != tag_id]
    p.tags = tags
    db.commit()
    return {"data": {"patient_id": p.patient_id, "tags": tags}, "meta": {"request_id": request.state.request_id}}


@router.patch("/patients/{patient_id}/stage", summary="更新经营生命周期（P0）")
def update_patient_stage(patient_id: str, body: StageUpdate, request: Request,
                         tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    p = _owned(db, Patient, patient_id, tenant, "患者")
    from ...core.enums import CustomerStage, CustomerStatus
    p.customer_stage = CustomerStage(body.stage) if isinstance(body.stage, str) else body.stage
    if body.status:
        p.customer_status = CustomerStatus(body.status) if isinstance(body.status, str) else body.status
    db.commit()
    emit(db, "patient.stage_updated", p.organization_id, "patient", p.patient_id,
         store_id=p.store_id, patient_id=p.patient_id,
         payload={"stage": str(getattr(p.customer_stage, "value", p.customer_stage)),
                  "status": str(getattr(p.customer_status, "value", p.customer_status))})
    db.commit()
    return {"data": {"patient_id": p.patient_id, "stage": p.customer_stage.value,
                     "status": p.customer_status.value}, "meta": {"request_id": request.state.request_id}}


# ================= Campaign =================
@router.post("/campaigns", summary="创建活动（P0）")
def create_campaign(
    body: CampaignCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        cmp = Campaign(
            organization_id=resolve_org_id(db, tenant, body.store_id),
            store_id=body.store_id, name=body.name, type=body.type, objective=body.objective,
            target_segment=body.target_segment, start_at=body.start_at, end_at=body.end_at,
            budget=body.budget, status=body.status,
        )
        db.add(cmp)
        return cmp

    pk, replayed = _idempotent(db, request, idempotency_key, "campaign", "campaign_id", create)
    db.commit()
    cmp = db.get(Campaign, pk)
    if not replayed:
        emit(db, "campaign.created", cmp.organization_id, "campaign", cmp.campaign_id,
             store_id=cmp.store_id, payload={"name": cmp.name, "type": cmp.type.value})
        db.commit()
    return {"data": {"campaign_id": cmp.campaign_id}, "meta": {"request_id": request.state.request_id}}


@router.patch("/campaigns/{campaign_id}", summary="更新活动（P1）")
def update_campaign(campaign_id: str, body: CampaignUpdate, request: Request,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    cmp = _owned(db, Campaign, campaign_id, tenant, "活动")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cmp, field, value)
    db.commit()
    return {"data": {"campaign_id": cmp.campaign_id, "status": cmp.status.value}, "meta": {"request_id": request.state.request_id}}


@router.post("/campaigns/{campaign_id}/audience", summary="添加受众/实验分组（P0）")
def add_campaign_audience(campaign_id: str, body: AudienceAdd, request: Request,
                          tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    cmp = _owned(db, Campaign, campaign_id, tenant, "活动")
    added = []
    for pid in body.patient_ids:
        patient = db.get(Patient, pid)
        if patient is None:
            raise ClinicOSError("NOT_FOUND", f"患者 {pid} 不存在", status_code=404)
        tenant.ensure_scope(patient)
        aud = CampaignAudience(
            organization_id=cmp.organization_id, store_id=cmp.store_id,
            campaign_id=campaign_id, patient_id=pid, assigned_at=utcnow(),
            segment=body.segment, experiment_id=body.experiment_id,
            experiment_group=body.experiment_group,
        )
        db.add(aud)
        added.append(aud.campaign_audience_id)
    db.commit()
    emit(db, "campaign.audience_added", cmp.organization_id, "campaign", campaign_id,
         store_id=cmp.store_id, payload={"count": len(added), "experiment_group": body.experiment_group.value})
    db.commit()
    return {"data": {"campaign_id": campaign_id, "audience_ids": added}, "meta": {"request_id": request.state.request_id}}


# ================= Touch =================
@router.post("/touches", summary="记录/触发触达（P1）")
def create_touch(
    body: TouchCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        t = Touch(
            organization_id=resolve_org_id(db, tenant, None, body.patient_id),
            patient_id=body.patient_id, campaign_id=body.campaign_id,
            followup_id=body.followup_id, task_id=body.task_id, staff_id=body.staff_id,
            channel=body.channel, sent_at=body.sent_at,
            message_template_id=body.message_template_id, message_version=body.message_version,
        )
        db.add(t)
        return t

    pk, replayed = _idempotent(db, request, idempotency_key, "touch", "touch_id", create)
    db.commit()
    t = db.get(Touch, pk)
    if not replayed:
        emit(db, "touch.sent", t.organization_id, "touch", t.touch_id,
             store_id=t.store_id, patient_id=t.patient_id,
             payload={"channel": t.channel.value, "campaign_id": t.campaign_id})
        db.commit()
    return {"data": {"touch_id": t.touch_id}, "meta": {"request_id": request.state.request_id}}


# ================= Experiment =================
@router.post("/experiments", summary="创建实验（P1）")
def create_experiment(
    body: ExperimentCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        exp = Experiment(
            organization_id=resolve_org_id(db, tenant, body.store_id),
            store_id=body.store_id, name=body.name, engine=body.engine,
            objective=body.objective, hypothesis=body.hypothesis,
            primary_metric=body.primary_metric, start_at=body.start_at,
            end_at=body.end_at, status=body.status,
        )
        db.add(exp)
        return exp

    pk, replayed = _idempotent(db, request, idempotency_key, "experiment", "experiment_id", create)
    db.commit()
    exp = db.get(Experiment, pk)
    if not replayed:
        emit(db, "experiment.created", exp.organization_id, "experiment", exp.experiment_id,
             store_id=exp.store_id, payload={"name": exp.name, "engine": exp.engine})
        db.commit()
    return {"data": {"experiment_id": exp.experiment_id}, "meta": {"request_id": request.state.request_id}}


@router.post("/experiments/{experiment_id}/assignments", summary="写入实验分组（P1）")
def create_assignments(experiment_id: str, body: AssignmentCreate, request: Request,
                       tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    exp = _owned(db, Experiment, experiment_id, tenant, "实验")
    ids = []
    for pid in body.patient_ids:
        patient = db.get(Patient, pid)
        if patient is None:
            raise ClinicOSError("NOT_FOUND", f"患者 {pid} 不存在", status_code=404)
        tenant.ensure_scope(patient)
        asg = ExperimentAssignment(
            organization_id=exp.organization_id, store_id=exp.store_id,
            experiment_id=experiment_id, patient_id=pid, group=body.group, assigned_at=utcnow(),
        )
        db.add(asg)
        ids.append(asg.experiment_assignment_id)
    db.commit()
    return {"data": {"experiment_id": experiment_id, "assignment_ids": ids,
                     "group": body.group.value}, "meta": {"request_id": request.state.request_id}}


# ================= Attribution =================
@router.post("/attributions", summary="写入归因结果（P1）")
def create_attribution(
    body: AttributionCreate,
    request: Request,
    tenant: TenantContext = Depends(get_tenant),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    db: Session = Depends(get_db),
):
    def create():
        attr = Attribution(
            organization_id=resolve_org_id(db, tenant, None, body.patient_id),
            transaction_id=body.transaction_id, payment_id=body.payment_id,
            patient_id=body.patient_id, source_type=body.source_type, source_id=body.source_id,
            campaign_id=body.campaign_id, task_id=body.task_id, touch_id=body.touch_id,
            experiment_id=body.experiment_id, attribution_model=body.attribution_model,
            attributed_amount=body.attributed_amount, incremental_amount=body.incremental_amount,
        )
        db.add(attr)
        return attr

    pk, replayed = _idempotent(db, request, idempotency_key, "attribution", "attribution_id", create)
    db.commit()
    attr = db.get(Attribution, pk)
    return {"data": {"attribution_id": attr.attribution_id}, "meta": {"request_id": request.state.request_id}}
