"""业务事实层 + 机会结果映射（R-04：BusinessFact → OpportunityOutcomeLink → Attribution）。

- BusinessFact：可信业务事实只存一次（预约/到店/支付/退款/回复/投诉等），
  按 (organization_id, source_system, source_event_id) 数据库唯一；
- OpportunityOutcomeLink：事实 → 机会的映射，同一事实只允许一个 primary
  （部分唯一索引 link_type='primary'），其他机会只能辅助关联，不得重复计收入；
- 对照组自然结果：Outcome 标记 organic（control_observation），不关联执行 Action/Touch 贡献。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, JSON, Boolean, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy import text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import MatchStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class BusinessFact(CommonMixin, Base):
    """不可重复的业务事实（事实主系统回流 / RevOS 内部产生）。"""

    __tablename__ = "business_facts"

    __table_args__ = (
        UniqueConstraint("organization_id", "source_system", "source_event_id", name="uq_business_facts_source"),
    )

    fact_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("fact"))
    customer_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("customers.customer_id"), nullable=True, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    fact_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # appointment/visit/payment/refund/order/reply/complaint
    source_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # 原始事件/记录 ID
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)   # 正收入
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)    # 退款（窗口内反向冲减）
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 最小化快照
    # 匹配结果（防广播）
    matched_opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    match_status: Mapped[MatchStatus] = mapped_column(
        Enum(MatchStatus, native_enum=False, length=16), nullable=False, default=MatchStatus.UNMATCHED
    )
    match_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    match_reason: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)


class OpportunityOutcomeLink(CommonMixin, Base):
    """机会 ↔ 事实 映射（同事实一个 primary；辅助关联不重复计收入）。"""

    __tablename__ = "opportunity_outcome_links"

    __table_args__ = (
        Index("uq_links_primary_fact", "fact_id", unique=True,
              sqlite_where=text("link_type = 'primary'"),
              postgresql_where=text("link_type = 'primary'")),
    )

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("link"))
    opportunity_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("opportunities.opportunity_id"), nullable=False, index=True)
    fact_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("business_facts.fact_id"), nullable=False, index=True)
    outcome_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    link_type: Mapped[str] = mapped_column(String(16), nullable=False, default="primary")  # primary/auxiliary/organic_control
    revenue_attributed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
