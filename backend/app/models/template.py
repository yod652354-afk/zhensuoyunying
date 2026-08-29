"""话术模板库（Prescription 能力：建议渠道/时间/话术，规格 6.1）。"""
from sqlalchemy import Enum, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import PersonStatus, TaskType
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class MessageTemplate(CommonMixin, Base):
    __tablename__ = "message_templates"

    message_template_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("message_template"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    task_type: Mapped[TaskType] = mapped_column(
        Enum(TaskType, native_enum=False, length=24), nullable=False, default=TaskType.RECOVERY
    )
    channel: Mapped[str] = mapped_column(String(24), nullable=False, default="phone")  # phone/sms/wechat/enterprise_wechat
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(16), nullable=False, default="v1")
    status: Mapped[PersonStatus] = mapped_column(
        Enum(PersonStatus, native_enum=False, length=16), nullable=False, default=PersonStatus.ACTIVE
    )
