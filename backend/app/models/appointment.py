"""预约与到店/就诊（需求规格 4.7 / 4.8）：两者独立，用于预约率/履约率/no-show/复诊率。"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import AppointmentStatus, VisitStatus, VisitType
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Appointment(CommonMixin, Base):
    __tablename__ = "appointments"

    appointment_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("appointment"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    doctor_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    service_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    appointment_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    appointment_source: Mapped[str | None] = mapped_column(String(24), nullable=True)  # frontdesk/wechat/campaign/AI
    status: Mapped[AppointmentStatus] = mapped_column(
        Enum(AppointmentStatus, native_enum=False, length=16), nullable=False, default=AppointmentStatus.CREATED, index=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    no_show: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    original_appointment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)


class Visit(CommonMixin, Base):
    __tablename__ = "visits"

    visit_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("visit"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    appointment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    doctor_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    visit_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    visit_type: Mapped[VisitType] = mapped_column(
        Enum(VisitType, native_enum=False, length=24), nullable=False, default=VisitType.FOLLOWUP
    )
    service_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_visit_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consultation_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consultation_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    visit_status: Mapped[VisitStatus] = mapped_column(
        Enum(VisitStatus, native_enum=False, length=16), nullable=False, default=VisitStatus.COMPLETED
    )
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # R-09 Connector 源 ID
