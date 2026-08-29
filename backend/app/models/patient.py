"""患者主档 + 来源（需求规格 4.2 / 4.3）。"""
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import CustomerStage, CustomerStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Patient(CommonMixin, Base):
    __tablename__ = "patients"

    patient_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("patient"))
    name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True)  # male/female/other
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    mobile: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    wechat: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enterprise_wechat_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    first_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    total_visits: Mapped[int] = mapped_column(default=0, nullable=False)
    total_revenue: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    primary_doctor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    primary_staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    customer_status: Mapped[CustomerStatus] = mapped_column(
        Enum(CustomerStatus, native_enum=False, length=16), nullable=False, default=CustomerStatus.NEW
    )
    customer_stage: Mapped[CustomerStage] = mapped_column(
        Enum(CustomerStage, native_enum=False, length=16), nullable=False, default=CustomerStage.FIRST_VISIT
    )
    tags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    referrer_patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # 合规：授权与免打扰（规格 P0：DNC 全局生效）
    consent_status: Mapped[str | None] = mapped_column(String(16), nullable=True, default="unknown")  # granted/denied/unknown
    dnc: Mapped[bool] = mapped_column(default=False, nullable=False)
    complaint_flag: Mapped[bool] = mapped_column(default=False, nullable=False)
    contact_status: Mapped[str | None] = mapped_column(String(16), nullable=True)  # valid/invalid/unknown


class LeadSource(CommonMixin, Base):
    __tablename__ = "lead_sources"

    source_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("lead_source"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)  # douyin/meituan/xiaohongshu/wechat/referral/walk_in...
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    ad_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(128), nullable=True)
    salesperson_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    first_touch_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conversion_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
