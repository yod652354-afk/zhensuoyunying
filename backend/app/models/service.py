"""项目/服务目录（需求规格 4.6）。recommended_cycle_days 是 Retention 核心。"""
from decimal import Decimal

from sqlalchemy import Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import PersonStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Service(CommonMixin, Base):
    __tablename__ = "services"

    service_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("service"))
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    service_category: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    standard_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    gross_margin: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    recommended_cycle_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    recommended_visit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), nullable=False, default=PersonStatus.ACTIVE
    )
