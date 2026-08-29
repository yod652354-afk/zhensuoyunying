"""Outbox（R-07）：事务性事件发布。

业务事务内 outbox_publish() 写入 outbox_messages（与业务同一事务）；
独立 worker 轮询并发布到 Event 表 + Webhook 投递（事务提交后最终发布）。
业务回滚时 Outbox 不发布（同一事务）。
"""
import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...database import SessionLocal
from ...models.outbox import OutboxMessage

logger = logging.getLogger("clinicos.revos.outbox")

BASE_BACKOFF_SECONDS = 5.0
MAX_ATTEMPTS = 5


def outbox_publish(
    db: Session,
    event_type: str,
    organization_id: str,
    object_type: str,
    object_id: str,
    store_id: str | None = None,
    payload: dict | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> OutboxMessage:
    """事务内写入 Outbox（与业务同事务提交/回滚）。"""
    msg = OutboxMessage(
        outbox_id=new_id("outbox"),
        organization_id=organization_id,
        store_id=store_id,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        payload=payload or {},
        correlation_id=correlation_id,
        causation_id=causation_id,
        status="pending",
        attempt=0,
    )
    db.add(msg)
    db.flush()
    return msg


def _publish_one(db: Session, msg: OutboxMessage) -> bool:
    """把一条 Outbox 消息发布为 Event 并触发 Webhook。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    try:
        emit(
            db, msg.event_type, msg.organization_id, msg.object_type, msg.object_id,
            store_id=msg.store_id,
            actor_type=ActorType.SYSTEM,
            payload=msg.payload,
            source_system="revos_outbox",
            correlation_id=msg.correlation_id,
            causation_id=msg.causation_id,
        )
        msg.status = "published"
        msg.published_at = utcnow()
        return True
    except Exception as exc:  # noqa: BLE001
        msg.attempt += 1
        msg.error = f"{type(exc).__name__}: {exc}"
        if msg.attempt >= MAX_ATTEMPTS:
            msg.status = "failed"
            msg.next_retry_at = None
        else:
            msg.status = "pending"
            msg.next_retry_at = utcnow() + timedelta(seconds=BASE_BACKOFF_SECONDS * (2 ** (msg.attempt - 1)))
        return False


def outbox_worker_poll(db: Session | None = None, limit: int = 50) -> int:
    """处理一批待发布 Outbox 消息（返回成功发布数）。"""
    session = db or SessionLocal()
    try:
        now = utcnow()
        rows = session.scalars(
            select(OutboxMessage).where(
                OutboxMessage.status == "pending",
                (OutboxMessage.next_retry_at.is_(None)) | (OutboxMessage.next_retry_at <= now),
            ).order_by(OutboxMessage.created_at.asc()).limit(limit)
        ).all()
        published = 0
        for msg in rows:
            if _publish_one(session, msg):
                published += 1
        if rows:
            session.commit()
        return published
    except Exception:  # noqa: BLE001
        session.rollback()
        logger.exception("Outbox worker 异常")
        return 0
    finally:
        if db is None:
            session.close()


def _outbox_loop(stop_event, interval: int = 10) -> None:
    while True:
        try:
            outbox_worker_poll()
        except Exception:  # noqa: BLE001
            pass
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)


_outbox_worker = None
_outbox_stop = None


def start_outbox_worker(interval: int = 10) -> None:
    """应用启动时调用：后台线程轮询 Outbox。"""
    import threading
    global _outbox_worker, _outbox_stop
    if _outbox_worker is not None and _outbox_worker.is_alive():
        return
    _outbox_stop = threading.Event()
    _outbox_worker = threading.Thread(
        target=_outbox_loop, args=(_outbox_stop, interval), daemon=True,
        name="revos-outbox-worker",
    )
    _outbox_worker.start()


def stop_outbox_worker() -> None:
    global _outbox_stop
    if _outbox_stop is not None:
        _outbox_stop.set()
