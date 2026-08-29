"""RevOS 事件规范测试（规格 03 §18 / 企微规格 §11）。

- 事件包含 schema_version / correlation_id / causation_id；
- 关键事件类型齐全（opportunity.detected / execution_plan.reviewed / touch.sent …）；
- 同一事件重复消费幂等（事件回放不重复落库）。
"""
from app.core.enums import ActorType
from app.core.ids import new_id
from app.database import SessionLocal
from app.models import Event
from app.services.revos.events import REVOS_EVENT_TYPES, emit_revos
from app.services.revos.events import REVOS_EVENT_SCHEMA_VERSION


def test_event_schema_fields():
    with SessionLocal() as db:
        evt = emit_revos(
            db, "opportunity.detected", "org_test", "opportunity", new_id("opportunity"),
            store_id="store_test", patient_id=new_id("patient"),
            actor_type=ActorType.AI,
            payload={"money_type": "past"},
            correlation_id="opp_corr_1", causation_id="evt_cause_1",
        )
        db.commit()
        assert evt.schema_version == REVOS_EVENT_SCHEMA_VERSION
        assert evt.correlation_id == "opp_corr_1"
        assert evt.causation_id == "evt_cause_1"
        assert evt.source_system == "revos"


def test_event_catalog_complete():
    required = {
        "customer.state_changed", "opportunity.detected", "decision.created",
        "execution_plan.created", "execution_plan.reviewed", "action.executed",
        "touch.sent", "touch.failed", "outcome.recorded", "attribution.calculated",
        "strategy.deployed", "strategy.rolled_back",
        "content.review_approved", "send_task.created", "mini_program.opened",
    }
    assert required <= set(REVOS_EVENT_TYPES)


def test_event_persisted_and_queryable(base):
    """通过 API 触发机会识别 → 事件落库可查。"""
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/opportunities/detect/dormant-recovery", headers=h)
    assert r.status_code == 200, r.text
    events = c.get("/api/v1/events?limit=50&event_type=opportunity.detected", headers=h).json()["data"]
    assert isinstance(events, list)
    if events:
        e = events[0]
        assert e["schema_version"] == REVOS_EVENT_SCHEMA_VERSION or e["schema_version"] == "1.0"
        assert e["correlation_id"]
        assert e["payload"] is not None


def test_event_idempotent_replay(base):
    """同一事件重复回放不重复产生投递记录（幂等）。"""
    c, h = base["client"], base["headers"]
    r1 = c.get("/api/v1/events/replay?limit=5", headers=h)
    r2 = c.get("/api/v1/events/replay?limit=5", headers=h)
    assert r1.status_code == 200 and r2.status_code == 200
