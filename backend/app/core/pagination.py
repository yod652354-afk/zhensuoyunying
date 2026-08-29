"""Cursor 分页 + 增量同步过滤（需求规格 5.1 / 5.4）。

排序固定为 (updated_at, <pk>) 以保证增量翻页稳定不重不漏。
cursor = base64(json(["<updated_at iso>", "<pk>"]))
"""
import base64
import json
from datetime import datetime, timezone
from typing import Any, TypeVar

from sqlalchemy import Select
from sqlalchemy.orm import InstrumentedAttribute

from .errors import ClinicOSError

T = TypeVar("T")


def encode_cursor(updated_at: datetime | None, pk: Any) -> str:
    raw = json.dumps(
        [updated_at.isoformat() if updated_at else "", str(pk)], ensure_ascii=False
    )
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str | None) -> tuple[datetime | None, str]:
    if not cursor:
        return None, ""
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        ts, pk = json.loads(raw)
    except Exception:
        raise ClinicOSError("INVALID_ARGUMENT", "cursor 格式无效", retryable=False)
    updated_at = datetime.fromisoformat(ts) if ts else None
    return updated_at, pk


def apply_incremental_filters(
    query: Select,
    model: type,
    pk_field: InstrumentedAttribute,
    updated_at_field: InstrumentedAttribute,
    created_at_field: InstrumentedAttribute,
    created_since: datetime | None,
    created_until: datetime | None,
    updated_since: datetime | None,
    updated_until: datetime | None,
    include_deleted: bool,
) -> Select:
    """时间范围过滤（created_since/updated_since 可组合），软删除默认排除。"""
    if not include_deleted and hasattr(model, "deleted_at"):
        query = query.where(model.deleted_at.is_(None))
    if created_since:
        query = query.where(created_at_field >= created_since)
    if created_until:
        query = query.where(created_at_field < created_until)
    if updated_since:
        query = query.where(updated_at_field >= updated_since)
    if updated_until:
        query = query.where(updated_at_field < updated_until)
    return query


def paginate(
    db: Any,
    query: Select,
    model: type,
    pk_field: InstrumentedAttribute,
    updated_at_field: InstrumentedAttribute,
    cursor: str | None,
    limit: int,
) -> tuple[list[T], str | None]:
    """按 (updated_at, pk) 游标翻页；返回 (rows, next_cursor)。"""
    cursor_updated_at, cursor_pk = decode_cursor(cursor)
    if cursor_updated_at is not None or cursor_pk:
        # 字典序比较 (updated_at, pk) > (cursor_updated_at, cursor_pk)
        query = query.where(
            (updated_at_field > cursor_updated_at)
            | (
                (updated_at_field == cursor_updated_at)
                & (pk_field > cursor_pk)
            )
        )
    query = query.order_by(updated_at_field.asc(), pk_field.asc()).limit(limit + 1)
    rows = db.scalars(query).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(getattr(last, updated_at_field.key), getattr(last, pk_field.key))
    return rows, next_cursor


def coerce_datetime(value: str | datetime | None, field: str) -> datetime | None:
    """把查询参数中的 ISO 时间串解析为 aware UTC datetime。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            raise ClinicOSError(
                "INVALID_ARGUMENT", f"{field} 时间格式无效（需 ISO 8601）", retryable=False
            )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)