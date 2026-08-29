"""Outbox + 持久 Job（R-07：生产持久任务，多实例安全执行）。

- Outbox：业务事务内写入事件，提交后由 worker 投递（事务与事件发布一致性）；
- Job：持久任务（租约/心跳/指数退避/最大重试/死信/人工重放）。
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin, TimestampMixin


class OutboxMessage(TimestampMixin, Base):
    """事务性事件 Outbox（业务提交后最终发布到 Event + Webhook）。"""

    __tablename__ = "outbox_messages"

    outbox_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("outbox"))
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    store_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    object_type: Mapped[str] = mapped_column(String(32), nullable=False)
    object_id: Mapped[str] = mapped_column(String(40), nullable=False)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)  # pending/published/failed
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Job(CommonMixin, Base):
    """持久任务：租约领取 + 心跳 + 退避 + 死信 + 人工重放。"""

    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("job"))
    job_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # daily_ops/connector_sync/attribution/outcome_sync...
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    # pending/leased/done/failed/dead
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_log: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 重试/重放审计
    requeued_by: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 人工重放审计
    requeued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
