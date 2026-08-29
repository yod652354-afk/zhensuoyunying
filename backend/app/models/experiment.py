"""实验 / 实验分组 / 收入归因（需求规格 4.21-4.22，P1）。"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import (
    AttributionModel, AttributionSourceType, ExperimentGroup, ExperimentStatus,
)
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Experiment(CommonMixin, Base):
    __tablename__ = "experiments"

    experiment_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("experiment"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    engine: Mapped[str] = mapped_column(String(24), nullable=False)  # recovery/retention/growth
    objective: Mapped[str | None] = mapped_column(String(256), nullable=True)
    hypothesis: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_metric: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus, native_enum=False, length=16), nullable=False, default=ExperimentStatus.DRAFT
    )


class ExperimentAssignment(CommonMixin, Base):
    __tablename__ = "experiment_assignments"

    experiment_assignment_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("experiment_assignment"))
    experiment_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    group: Mapped[ExperimentGroup] = mapped_column(
        Enum(ExperimentGroup, native_enum=False, length=16), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Attribution(CommonMixin, Base):
    __tablename__ = "attributions"

    attribution_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("attribution"))
    transaction_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    payment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_type: Mapped[AttributionSourceType] = mapped_column(
        Enum(AttributionSourceType, native_enum=False, length=16), nullable=False, default=AttributionSourceType.ORGANIC
    )
    source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    touch_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attribution_model: Mapped[AttributionModel] = mapped_column(
        Enum(AttributionModel, native_enum=False, length=16), nullable=False, default=AttributionModel.RULE_BASED
    )
    attributed_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    incremental_amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    # ---------- RevOS 归因扩展（旧数据允许为空） ----------
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    outcome_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    experiment_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    attribution_window_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attribution_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_chain: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 完整追溯证据链
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
