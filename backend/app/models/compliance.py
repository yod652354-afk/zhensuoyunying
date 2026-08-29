"""内容合规审批（规格 10.3：生成→风险扫描→人工审批→发布留痕）。"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class ContentReview(CommonMixin, Base):
    __tablename__ = "content_reviews"

    content_review_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("content_review"))
    campaign_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    touch_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="wechat")
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)   # [{rule, matched, severity}]
    risk_score: Mapped[float] = mapped_column(default=0.0, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")  # pending/approved/rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(String(512), nullable=True)
    approved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ReviewSession(CommonMixin, Base):
    """每周复盘（Learning 人工闭环：Action→Outcome 复盘记录）。"""

    __tablename__ = "review_sessions"

    review_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("review"))
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engine: Mapped[str] = mapped_column(String(24), nullable=False, default="all")  # recovery/retention/growth/all
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    actions_kept: Mapped[list | None] = mapped_column(JSON, nullable=True)    # 保留的动作
    actions_dropped: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 淘汰的动作
    next_week_plan: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
