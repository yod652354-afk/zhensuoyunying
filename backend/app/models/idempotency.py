"""幂等记录表（需求规格 R-018 / 5.1）：Idempotency-Key → 已处理结果。"""
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .base import TimestampMixin


class IdempotencyRecord(TimestampMixin, Base):
    __tablename__ = "idempotency_records"

    idempotency_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(40), nullable=False)
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
