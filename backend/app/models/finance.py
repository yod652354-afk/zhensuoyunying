"""交易账本：订单/明细/付款/退款 + 套餐/会员/核销（需求规格 4.11-4.13）。"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import OrderStatus, PackageStatus, PaymentMethod, PaymentStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class Order(CommonMixin, Base):
    __tablename__ = "orders"

    order_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("order"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    visit_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    salesperson_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    doctor_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    original_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    final_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0, index=True)
    order_status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, native_enum=False, length=24), nullable=False, default=OrderStatus.PENDING
    )
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # R-09 Connector 源 ID


class OrderItem(CommonMixin, Base):
    __tablename__ = "order_items"

    order_item_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("order_item"))
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    service_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    package_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    line_final_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)


class Payment(CommonMixin, Base):
    __tablename__ = "payments"

    payment_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("payment"))
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    payment_method: Mapped[PaymentMethod] = mapped_column(
        Enum(PaymentMethod, native_enum=False, length=16), nullable=False, default=PaymentMethod.WECHAT
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False, length=16), nullable=False, default=PaymentStatus.SUCCEEDED
    )
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # R-09 Connector 源 ID


class Refund(CommonMixin, Base):
    __tablename__ = "refunds"

    refund_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("refund"))
    order_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    payment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    refund_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    refund_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # R-09 Connector 源 ID


class PackageInstance(CommonMixin, Base):
    __tablename__ = "packages"

    package_instance_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("package"))
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    package_template_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    purchase_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expire_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_sessions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    used_sessions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    remaining_sessions: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
    paid_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    status: Mapped[PackageStatus] = mapped_column(
        Enum(PackageStatus, native_enum=False, length=16), nullable=False, default=PackageStatus.ACTIVE
    )


class PackageUsage(CommonMixin, Base):
    __tablename__ = "package_usages"

    package_usage_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("package_usage"))
    package_instance_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    visit_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    service_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sessions_used: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=1)
    remaining_after: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=0)
