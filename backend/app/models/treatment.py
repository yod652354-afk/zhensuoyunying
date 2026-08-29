"""诊后计划与后续建议事件（需求规格 4.9 / 4.10）：复诊漏斗核心。"""
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import RecommendationType, TreatmentPlanStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class TreatmentPlan(CommonMixin, Base):
    __tablename__ = "treatment_plans"

    treatment_plan_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("treatment_plan"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    visit_id: Mapped[str] = mapped_column(String(40), nullable=False)
    doctor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    plan_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recommended_next_visit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recommended_next_visit_min_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recommended_next_visit_max_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    recommended_total_visits: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completed_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_status: Mapped[TreatmentPlanStatus] = mapped_column(
        Enum(TreatmentPlanStatus, native_enum=False, length=16), nullable=False, default=TreatmentPlanStatus.ACTIVE
    )
    next_action: Mapped[str | None] = mapped_column(String(256), nullable=True)
    next_action_owner: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CareRecommendation(CommonMixin, Base):
    __tablename__ = "care_recommendations"

    care_recommendation_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("care_recommendation"))
    visit_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    doctor_id: Mapped[str] = mapped_column(String(40), nullable=False)
    recommended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recommendation_type: Mapped[RecommendationType] = mapped_column(
        Enum(RecommendationType, native_enum=False, length=16), nullable=False, default=RecommendationType.REVISIT
    )
    next_visit_recommended: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recommended_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment_should_be_created: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
