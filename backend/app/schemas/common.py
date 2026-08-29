"""统一响应包络（需求规格 5.5）与动态响应模型构建。"""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, create_model
from sqlalchemy import Boolean, Date, DateTime, Enum as SAEnum, Integer, JSON, Numeric, String
from sqlalchemy.orm import DeclarativeMeta

from ..database import Base


class Meta(BaseModel):
    next_cursor: Optional[str] = None
    has_more: bool = False
    request_id: Optional[str] = None


class Envelope(BaseModel):
    data: Any
    meta: Meta = Meta()


def sa_type_to_python(col) -> Any:
    """把 SQLAlchemy 列类型映射为响应模型字段类型。"""
    t = col.type
    if isinstance(t, DateTime):
        return Any  # datetime 由 FastAPI 序列化为 ISO
    if isinstance(t, Date):
        return Any
    if isinstance(t, SAEnum) and t.enum_class is not None:
        return t.enum_class
    if isinstance(t, JSON):
        return Any
    if isinstance(t, Numeric):
        return float
    if isinstance(t, Integer):
        return int
    if isinstance(t, Boolean):
        return bool
    if isinstance(t, String):
        return str
    return Any


def build_response_model(model: DeclarativeMeta, name: str) -> type[BaseModel]:
    """根据 SQLAlchemy 模型自动生成响应 Pydantic 模型（供 OpenAPI 文档使用）。"""
    fields: dict[str, Any] = {}
    for col in model.__table__.columns:
        py = sa_type_to_python(col)
        if col.nullable:
            fields[col.name] = (Optional[py], None)
        else:
            fields[col.name] = (py, ...)
    return create_model(name, __config__=ConfigDict(from_attributes=True), **fields)