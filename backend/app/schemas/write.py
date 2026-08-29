"""Write API 请求模型（需求规格 5.3）。"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from ..core.enums import (
    AppointmentStatus, AssignedToType, AttributionModel, AttributionSourceType,
    CampaignObjective, CampaignStatus, CampaignType, ExperimentGroup,
    ExperimentStatus, FollowupChannel, FollowupReason, FollowupResult, FollowupStatus,
    TaskPriority, TaskStatus, TaskType, TouchChannel,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Task ---
class TaskCreate(BaseModel):
    task_type: TaskType
    patient_id: Optional[str] = None
    store_id: Optional[str] = None
    assigned_to_type: AssignedToType
    assigned_to_id: str
    due_at: Optional[datetime] = None
    priority: TaskPriority = TaskPriority.B
    reason: Optional[str] = None
    expected_value: Optional[Decimal] = None
    related_followup_id: Optional[str] = None
    related_campaign_id: Optional[str] = None
    related_experiment_id: Optional[str] = None
    created_by_type: Optional[str] = "AI"


class TaskUpdate(BaseModel):
    status: Optional[TaskStatus] = None
    result: Optional[dict] = None
    due_at: Optional[datetime] = None
    priority: Optional[TaskPriority] = None
    assigned_to_id: Optional[str] = None
    # 执行反馈（员工上传通道）
    feedback_note: Optional[str] = None
    feedback_images: Optional[list[str]] = None
    review_status: Optional[str] = None


# --- Followup ---
class FollowupCreate(BaseModel):
    patient_id: str
    related_visit_id: Optional[str] = None
    related_appointment_id: Optional[str] = None
    staff_id: str
    scheduled_at: Optional[datetime] = None
    reason: FollowupReason = FollowupReason.OTHER
    channel: FollowupChannel = FollowupChannel.PHONE
    next_action: Optional[str] = None
    next_action_at: Optional[datetime] = None


class FollowupUpdate(BaseModel):
    status: Optional[FollowupStatus] = None
    result: Optional[FollowupResult] = None
    customer_response: Optional[str] = None
    completed_at: Optional[datetime] = None
    appointment_created_id: Optional[str] = None
    revenue_generated: Optional[Decimal] = None


# --- Appointment ---
class AppointmentCreate(BaseModel):
    patient_id: str
    store_id: Optional[str] = None
    doctor_id: Optional[str] = None
    staff_id: Optional[str] = None
    service_id: Optional[str] = None
    appointment_at: datetime
    appointment_source: Optional[str] = None
    status: AppointmentStatus = AppointmentStatus.CREATED


class AppointmentUpdate(BaseModel):
    status: Optional[AppointmentStatus] = None
    appointment_at: Optional[datetime] = None
    doctor_id: Optional[str] = None
    cancel_reason: Optional[str] = None
    no_show: Optional[bool] = None
    completed_at: Optional[datetime] = None


# --- Patient ---
class TagAdd(BaseModel):
    tag: str


class StageUpdate(BaseModel):
    stage: str
    status: Optional[str] = None


# --- Campaign ---
class CampaignCreate(BaseModel):
    name: str
    store_id: Optional[str] = None
    type: CampaignType = CampaignType.ALWAYS_ON
    objective: CampaignObjective = CampaignObjective.REACTIVATION
    target_segment: Optional[dict] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    budget: Optional[Decimal] = None
    status: CampaignStatus = CampaignStatus.DRAFT


class CampaignUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[CampaignType] = None
    objective: Optional[CampaignObjective] = None
    target_segment: Optional[dict] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    budget: Optional[Decimal] = None
    actual_cost: Optional[Decimal] = None
    status: Optional[CampaignStatus] = None


class AudienceAdd(BaseModel):
    patient_ids: list[str] = Field(min_length=1)
    segment: Optional[str] = None
    experiment_id: Optional[str] = None
    experiment_group: ExperimentGroup = ExperimentGroup.NONE


# --- Touch ---
class TouchCreate(BaseModel):
    patient_id: str
    campaign_id: Optional[str] = None
    followup_id: Optional[str] = None
    task_id: Optional[str] = None
    staff_id: Optional[str] = None
    channel: TouchChannel = TouchChannel.WECHAT
    sent_at: datetime
    message_template_id: Optional[str] = None
    message_version: Optional[str] = None
    delivery_status: Optional[str] = None


# --- Experiment ---
class ExperimentCreate(BaseModel):
    name: str
    store_id: Optional[str] = None
    engine: str = "recovery"
    objective: Optional[str] = None
    hypothesis: Optional[str] = None
    primary_metric: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: ExperimentStatus = ExperimentStatus.DRAFT


class AssignmentCreate(BaseModel):
    patient_ids: list[str] = Field(min_length=1)
    group: ExperimentGroup


# --- Attribution ---
class AttributionCreate(BaseModel):
    transaction_id: Optional[str] = None
    payment_id: Optional[str] = None
    patient_id: str
    source_type: AttributionSourceType = AttributionSourceType.ORGANIC
    source_id: Optional[str] = None
    campaign_id: Optional[str] = None
    task_id: Optional[str] = None
    touch_id: Optional[str] = None
    experiment_id: Optional[str] = None
    attribution_model: AttributionModel = AttributionModel.RULE_BASED
    attributed_amount: Optional[Decimal] = None
    incremental_amount: Optional[Decimal] = None


# --- Webhook 订阅 ---
class WebhookSubscriptionCreate(BaseModel):
    url: str
    secret: Optional[str] = None
    event_types: Optional[list[str]] = None
    enabled: bool = True