"""医生与员工（需求规格 4.4 / 4.5）。"""
from datetime import date

from sqlalchemy import JSON, Date, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import PersonStatus, StaffRole
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Doctor(CommonMixin, Base):
    __tablename__ = "doctors"

    doctor_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("doctor"))
    doctor_name: Mapped[str] = mapped_column(String(64), nullable=False)
    doctor_status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), nullable=False, default=PersonStatus.ACTIVE
    )
    specialty: Mapped[list | None] = mapped_column(JSON, nullable=True)
    service_categories: Mapped[list | None] = mapped_column(JSON, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    working_schedule: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class Staff(CommonMixin, Base):
    __tablename__ = "staff"

    staff_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("staff"))
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[StaffRole] = mapped_column(
        Enum(StaffRole, native_enum=False, length=32), nullable=False, default=StaffRole.ASSISTANT
    )
    department: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), nullable=False, default=PersonStatus.ACTIVE
    )
