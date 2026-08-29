"""机构与门店（需求规格 4.1）。"""
from datetime import date

from sqlalchemy import JSON, Date, Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import BusinessStatus, StoreType
from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..database import Base
from .base import CommonMixin


class Organization(CommonMixin, Base):
    __tablename__ = "organizations"

    organization_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("organization"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)


class Store(CommonMixin, Base):
    __tablename__ = "stores"

    store_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("store"))
    store_name: Mapped[str] = mapped_column(String(128), nullable=False)
    store_type: Mapped[StoreType] = mapped_column(
        Enum(StoreType, native_enum=False, length=32), nullable=False, default=StoreType.TCM_CLINIC
    )
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    city: Mapped[str | None] = mapped_column(String(64), nullable=True)
    open_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    business_status: Mapped[BusinessStatus] = mapped_column(
        Enum(BusinessStatus, native_enum=False, length=16), nullable=False, default=BusinessStatus.ACTIVE
    )
    business_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    timezone: Mapped[str] = mapped_column(String(32), nullable=False, default="Asia/Shanghai")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="CNY")
    number_of_doctors: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_staff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    number_of_rooms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
