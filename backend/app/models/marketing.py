"""营销：活动 / 活动受众 / 触达事件（需求规格 4.15-4.17）。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import (
    CampaignObjective, CampaignStatus, CampaignType, DeliveryStatus,
    ExperimentGroup, TouchChannel,
)
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Campaign(CommonMixin, Base):
    __tablename__ = "campaigns"

    campaign_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("campaign"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    type: Mapped[CampaignType] = mapped_column(
        Enum(CampaignType, native_enum=False, length=24), nullable=False, default=CampaignType.ALWAYS_ON
    )
    objective: Mapped[CampaignObjective] = mapped_column(
        Enum(CampaignObjective, native_enum=False, length=24), nullable=False, default=CampaignObjective.REACTIVATION
    )
    target_segment: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    actual_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, native_enum=False, length=16), nullable=False, default=CampaignStatus.DRAFT
    )


class CampaignAudience(CommonMixin, Base):
    __tablename__ = "campaign_audiences"

    campaign_audience_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("campaign_audience"))
    campaign_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    segment: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    experiment_group: Mapped[ExperimentGroup] = mapped_column(
        Enum(ExperimentGroup, native_enum=False, length=16), nullable=False, default=ExperimentGroup.NONE
    )


class Touch(CommonMixin, Base):
    __tablename__ = "touches"

    touch_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("touch"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    campaign_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    followup_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    channel: Mapped[TouchChannel] = mapped_column(
        Enum(TouchChannel, native_enum=False, length=24), nullable=False, default=TouchChannel.WECHAT
    )
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    message_template_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    message_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    delivery_status: Mapped[DeliveryStatus | None] = mapped_column(
        Enum(DeliveryStatus, native_enum=False, length=16), nullable=True
    )
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reply_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # ---------- RevOS 执行扩展（旧数据允许为空） ----------
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    content_draft_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
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
