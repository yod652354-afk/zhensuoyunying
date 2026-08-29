"""系统用户（员工端/老板端登录，规格 11 员工端与老板端）。"""
from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import PersonStatus
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class User(CommonMixin, Base):
    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("user"))
    username: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="staff")  # boss/staff/admin
    staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)  # 关联员工
    status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), nullable=False, default=PersonStatus.ACTIVE
    )
