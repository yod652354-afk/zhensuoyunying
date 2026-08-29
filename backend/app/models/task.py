"""统一经营任务（需求规格 4.19）：Recovery/Retention/Growth 统一载体。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import AssignedToType, CreatedByType, TaskPriority, TaskStatus, TaskType
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Task(CommonMixin, Base):
    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("task"))
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, native_enum=False, length=24), nullable=False, index=True
    )
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    assigned_to_type: Mapped[AssignedToType] = mapped_column(
        Enum(AssignedToType, native_enum=False, length=16), nullable=False
    )
    assigned_to_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority, native_enum=False, length=4), nullable=False, default=TaskPriority.B
    )
    reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    expected_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, native_enum=False, length=16), nullable=False, default=TaskStatus.PENDING, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    related_followup_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # 执行反馈（员工上传通道）
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_images: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 后台审核（老板审核推送）
    review_status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')  # pending/approved/rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    suggested_channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    suggested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    message_template_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_campaign_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # ---------- RevOS 执行扩展（旧数据允许为空） ----------
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    content_draft_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    workflow_instance_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    action_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    channel_account_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    send_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)  # manual/assisted
    external_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    send_status: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # SendStatus
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by_type: Mapped[CreatedByType] = mapped_column(
        Enum(CreatedByType, native_enum=False, length=16), nullable=False, default=CreatedByType.SYSTEM
    )
    created_by_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
