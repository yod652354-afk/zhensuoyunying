"""产能/可预约资源（需求规格 4.20，P1）。"""
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Capacity(CommonMixin, Base):
    __tablename__ = "capacities"

    capacity_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("capacity"))
    doctor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    room_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    available_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    booked_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
