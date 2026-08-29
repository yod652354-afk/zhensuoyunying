"""RevOS 事件目录与发射封装（规格 03 §18 / 企微规格 §11）。

事件统一包含：event_id / event_type / organization_id / store_id / occurred_at /
actor / object / correlation_id / causation_id / schema_version / data。
"""
from ...core.enums import ActorType
from ...events.bus import emit

REVOS_EVENT_SCHEMA_VERSION = "1.0"

# 事件目录（03 §18 + 企微规格 §11 合并）
REVOS_EVENT_TYPES = [
    "customer.state_changed",
    "opportunity.detected",
    "opportunity.qualified",
    "opportunity.suppressed",
    "opportunity.won",
    "opportunity.lost",
    "decision.created",
    "execution_plan.created",
    "execution_plan.reviewed",
    "action.executed",
    "content.generated",
    "content.machine_checked",
    "content.review_approved",
    "content.review_rejected",
    "content.review_changes_requested",
    "send_task.created",
    "touch.waiting_confirmation",
    "touch.sent",
    "touch.failed",
    "touch.unknown",
    "touch.delivered",
    "customer.responded",
    "mini_program.opened",
    "appointment.created",
    "visit.completed",
    "payment.completed",
    "outcome.recorded",
    "attribution.calculated",
    "strategy.deployed",
    "strategy.rolled_back",
    "strategy.retired",
]


def emit_revos(
    db,
    event_type: str,
    organization_id: str,
    object_type: str,
    object_id: str,
    store_id: str | None = None,
    patient_id: str | None = None,
    actor_type: ActorType | str | None = None,
    actor_id: str | None = None,
    payload: dict | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    source_system: str = "revos",
):
    """RevOS 规范事件发射（自动携带 schema_version / correlation_id）。"""
    return emit(
        db, event_type, organization_id, object_type, object_id,
        store_id=store_id, patient_id=patient_id,
        actor_type=actor_type, actor_id=actor_id,
        payload=payload, source_system=source_system,
        schema_version=REVOS_EVENT_SCHEMA_VERSION,
        correlation_id=correlation_id, causation_id=causation_id,
    )
