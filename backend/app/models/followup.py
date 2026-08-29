"""回访（需求规格 4.14）：Action→Outcome 最关键数据之一。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import (
    FollowupChannel, FollowupReason, FollowupResult, FollowupStatus,
)
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Followup(CommonMixin, Base):
    __tablename__ = "followups"

    followup_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("followup"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    related_visit_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    related_appointment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    staff_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[FollowupReason] = mapped_column(
        Enum(FollowupReason, native_enum=False, length=32), nullable=False, default=FollowupReason.OTHER
    )
    channel: Mapped[FollowupChannel] = mapped_column(
        Enum(FollowupChannel, native_enum=False, length=24), nullable=False, default=FollowupChannel.PHONE
    )
    status: Mapped[FollowupStatus] = mapped_column(
        Enum(FollowupStatus, native_enum=False, length=16), nullable=False, default=FollowupStatus.PENDING
    )
    result: Mapped[FollowupResult | None] = mapped_column(
        Enum(FollowupResult, native_enum=False, length=32), nullable=True
    )
    customer_response: Mapped[str | None] = mapped_column(String(512), nullable=True)
    next_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment_created_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revenue_generated: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
