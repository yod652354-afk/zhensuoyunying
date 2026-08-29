"""反馈/投诉（需求规格 4.18）：Recovery Score 负向维度。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import FeedbackType
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Feedback(CommonMixin, Base):
    __tablename__ = "feedback"

    feedback_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("feedback"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    visit_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    feedback_type: Mapped[FeedbackType] = mapped_column(
        Enum(FeedbackType, native_enum=False, length=16), nullable=False, default=FeedbackType.REVIEW
    )
    rating: Mapped[float | None] = mapped_column(Numeric(3, 1), nullable=True)
    complaint_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    complaint_category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
