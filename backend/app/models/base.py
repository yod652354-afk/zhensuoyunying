"""通用列 Mixin：时间戳 / 软删除 / 通用字段（需求规格 3.2）。

使用 declared_attr：每个子类访问时生成独立 Column，避免跨表共享列对象。
"""
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import declared_attr, mapped_column

from ..core.timeutil import utcnow


class TimestampMixin:
    @declared_attr
    def created_at(cls):
        return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    @declared_attr
    def updated_at(cls):
        return mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False, index=True)


class SoftDeleteMixin:
    @declared_attr
    def deleted_at(cls):
        return mapped_column(DateTime(timezone=True), nullable=True)


class CommonMixin(TimestampMixin, SoftDeleteMixin):
    """建议通用字段（规格 3.2），P0 主体对象均携带。

    显式转发 created_at/updated_at/deleted_at（declared_attr 经中间类继承不自动
    生效，须在此重新声明；R-08 消除 Unmanaged access 告警且不再要求模型重复赋值）。
    """

    @declared_attr
    def created_at(cls):
        return mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)

    @declared_attr
    def updated_at(cls):
        return mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False, index=True)

    @declared_attr
    def deleted_at(cls):
        return mapped_column(DateTime(timezone=True), nullable=True)

    @declared_attr
    def organization_id(cls):
        return mapped_column(String(40), nullable=False, index=True)

    @declared_attr
    def store_id(cls):
        return mapped_column(String(40), nullable=True, index=True)

    @declared_attr
    def source_system(cls):
        return mapped_column(String(64), nullable=True)

    @declared_attr
    def created_by_type(cls):
        return mapped_column(String(16), nullable=True)

    @declared_attr
    def created_by_id(cls):
        return mapped_column(String(64), nullable=True)