"""统一事件流 + Webhook 订阅/投递（需求规格 4.23 / 6）。"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import ActorType
from ..core.ids import new_id
from ..database import Base
from .base import TimestampMixin


class Event(TimestampMixin, Base):
    __tablename__ = "events"

    event_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("event"))
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    schema_version: Mapped[str | None] = mapped_column(String(8), nullable=True)  # RevOS 事件规范版本
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    store_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    actor_type: Mapped[ActorType | None] = mapped_column(Enum(ActorType, native_enum=False, length=16), nullable=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(40), nullable=False)
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 业务链路（如 opp_xxx）
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 前序事件
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WebhookSubscription(TimestampMixin, Base):
    __tablename__ = "webhook_subscriptions"

    subscription_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("webhook_subscription"))
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(512), nullable=False)
    secret: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 为空则用全局 secret
    event_types: Mapped[list | None] = mapped_column(JSON, nullable=True)   # 为空表示全部
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class WebhookDelivery(TimestampMixin, Base):
    __tablename__ = "webhook_deliveries"

    delivery_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("webhook_delivery"))
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)  # RevOS 租户隔离
    subscription_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # success/failed/pending
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
