"""事件总线：业务动作 → 统一事件流（需求规格 4.23）。

所有关键业务变化通过 emit() 落库为 Event 行，并触发 Webhook 投递。
事件回放/补偿：GET /api/v1/events 或各实体 updated_since 增量拉取。
"""
import uuid
from typing import Any

from sqlalchemy.orm import Session

from ..core.enums import ActorType
from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..models.event import Event
from .dispatcher import dispatch_event


def emit(
    db: Session,
    event_type: str,
    organization_id: str,
    object_type: str,
    object_id: str,
    store_id: str | None = None,
    patient_id: str | None = None,
    actor_type: ActorType | str | None = None,
    actor_id: str | None = None,
    payload: dict[str, Any] | None = None,
    source_system: str | None = None,
    trace_id: str | None = None,
    schema_version: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> Event:
    """记录一条业务事件（event_id 全局唯一，用于 Webhook 消费幂等）。

    RevOS 事件规范：事件包含 schema_version、correlation_id（业务链路，
    如机会 opp_xxx）与 causation_id（前序事件），保证证据链完整。
    """
    event = Event(
        event_id=new_id("event"),
        event_type=event_type,
        event_version=1,
        schema_version=schema_version or "1.0",
        occurred_at=utcnow(),
        organization_id=organization_id,
        store_id=store_id,
        patient_id=patient_id,
        actor_type=actor_type if isinstance(actor_type, ActorType) else (ActorType(actor_type) if actor_type else None),
        actor_id=actor_id,
        object_type=object_type,
        object_id=object_id,
        source_system=source_system or "clinicos",
        trace_id=trace_id or f"trace_{uuid.uuid4().hex[:12]}",
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload or {},
    )
    db.add(event)
    db.flush()  # 获取 event_id，交给 dispatcher
    dispatch_event(event, trace_id=event.trace_id)
    return event