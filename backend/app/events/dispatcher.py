"""Webhook 投递器：订阅匹配 → HMAC 签名 → 指数退避重试 → 投递日志。

投递模式（WEBHOOK_DELIVERY_MODE）：
- log  （默认，开发）: 仅记录日志，不真正外发
- http : 通过 httpx 真实投递，含签名与重试

投递在独立守护线程中执行，不阻塞 API 请求。
"""
import hashlib
import hmac
import json
import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..database import SessionLocal
from ..models.event import Event, WebhookDelivery, WebhookSubscription

logger = logging.getLogger("clinicos.webhook")


def _sign(payload: bytes, secret: str, timestamp: str) -> str:
    message = f"{timestamp}.{payload.decode('utf-8')}".encode("utf-8")
    return "sha256=" + hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _deliver_once(sub: WebhookSubscription, event: Event, delivery: WebhookDelivery) -> None:
    settings = get_settings()
    timestamp = str(int(time.time()))
    body = json.dumps(
        {
            "event_id": event.event_id,
            "event_type": event.event_type,
            "event_version": event.event_version,
            "occurred_at": event.occurred_at.isoformat(),
            "organization_id": event.organization_id,
            "store_id": event.store_id,
            "patient_id": event.patient_id,
            "actor": {"type": event.actor_type.value if event.actor_type else None, "id": event.actor_id},
            "object": {"type": event.object_type, "id": event.object_id},
            "trace_id": event.trace_id,
            "data": event.payload or {},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    secret = sub.secret or settings.webhook_secret

    if settings.webhook_delivery_mode == "log":
        logger.info(
            "[webhook:log] %s -> %s | %s | payload=%s",
            event.event_type, sub.url, event.event_id, body.decode("utf-8")[:500],
        )
        delivery.status = "success"
        delivery.http_status = 200
        delivery.delivered_at = utcnow()
        return

    # http 模式：真实投递
    import httpx

    try:
        resp = httpx.post(
            sub.url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Event": event.event_type,
                "X-Webhook-Signature": _sign(body, secret, timestamp),
                "X-Webhook-Timestamp": timestamp,
                "X-Webhook-Id": event.event_id,
            },
            timeout=10.0,
        )
        delivery.http_status = resp.status_code
        delivery.delivered_at = utcnow()
        if 200 <= resp.status_code < 300:
            delivery.status = "success"
        else:
            delivery.status = "failed"
            delivery.error = f"HTTP {resp.status_code}: {resp.text[:300]}"
    except Exception as exc:  # noqa: BLE001
        delivery.status = "failed"
        delivery.error = f"{type(exc).__name__}: {exc}"


def _dispatch_thread(event: Event) -> None:
    """在独立线程中完成订阅匹配与投递（含重试与日志）。"""
    settings = get_settings()
    try:
        with SessionLocal() as db:
            subs = db.scalars(
                select(WebhookSubscription).where(
                    WebhookSubscription.enabled.is_(True),
                )
            ).all()
            for sub in subs:
                if sub.event_types and event.event_type not in sub.event_types:
                    continue
                # 幂等：同一 (subscription, event) 已成功投递过则跳过
                existing = db.scalar(
                    select(WebhookDelivery).where(
                        WebhookDelivery.subscription_id == sub.subscription_id,
                        WebhookDelivery.event_id == event.event_id,
                    )
                )
                if existing is not None:
                    continue
                delivery = WebhookDelivery(
                    delivery_id=new_id("webhook_delivery"),
                    organization_id=event.organization_id,
                    subscription_id=sub.subscription_id,
                    event_id=event.event_id,
                    event_type=event.event_type,
                    attempt=0,
                    status="pending",
                )
                max_retries = max(settings.webhook_max_retries, 1)
                base_seconds = max(settings.webhook_retry_base_seconds, 1.0)
                attempt = 0
                while attempt < max_retries:
                    attempt += 1
                    delivery.attempt = attempt
                    _deliver_once(sub, event, delivery)
                    db.add(delivery)
                    if delivery.status == "success":
                        break
                    if attempt < max_retries:
                        wait = base_seconds * (2 ** (attempt - 1))
                        logger.warning(
                            "[webhook] 投递失败(第%d次) %s -> %s, %s 秒后重试: %s",
                            attempt, event.event_type, sub.url, wait, delivery.error,
                        )
                        db.commit()
                        time.sleep(wait)
                if delivery.status != "success":
                    delivery.next_retry_at = utcnow() + timedelta(minutes=30)
                    logger.error(
                        "[webhook] 投递最终失败 %s -> %s: %s",
                        event.event_type, sub.url, delivery.error,
                    )
                db.commit()
    except Exception:  # noqa: BLE001
        logger.exception("[webhook] 投递线程异常 event=%s", event.event_id)


def dispatch_event(event: Event, trace_id: str | None = None) -> None:
    """异步投递（守护线程），不阻塞请求。"""
    threading.Thread(target=_dispatch_thread, args=(event,), daemon=True).start()

# ---------- 持久化重试 worker ----------
def _retry_pending_loop(stop_event=None, interval: int = 60) -> None:
    """后台线程：定期重试 next_retry_at 已到期的失败投递（规格 6.3 重试）。"""
    import logging as _logging
    _log = _logging.getLogger("clinicos.webhook.retry")
    while True:
        try:
            with SessionLocal() as db:
                now = utcnow()
                pendings = db.scalars(
                    select(WebhookDelivery).where(
                        WebhookDelivery.status == "failed",
                        WebhookDelivery.next_retry_at.isnot(None),
                        WebhookDelivery.next_retry_at <= now,
                    ).limit(50)
                ).all()
                for d in pendings:
                    sub = db.get(WebhookSubscription, d.subscription_id)
                    if sub is None or not sub.enabled:
                        continue
                    evt = db.get(Event, d.event_id)
                    if evt is None:
                        continue
                    d.attempt += 1
                    _deliver_once(sub, evt, d)
                    if d.status == "success":
                        d.next_retry_at = None
                        _log.info("[webhook] 重试成功 %s -> %s", evt.event_type, sub.url)
                    else:
                        d.next_retry_at = utcnow() + timedelta(minutes=30)
                        _log.warning("[webhook] 重试仍失败 %s: %s", evt.event_type, d.error)
                if pendings:
                    db.commit()
        except Exception:  # noqa: BLE001
            _log.exception("重试 worker 异常")
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)


_retry_worker = None
_retry_stop = None


def start_retry_worker(interval: int = 60) -> None:
    """应用启动时调用：启动持久化重试线程。"""
    global _retry_worker, _retry_stop
    if _retry_worker is not None and _retry_worker.is_alive():
        return
    import threading as _threading
    _retry_stop = _threading.Event()
    _retry_worker = _threading.Thread(
        target=_retry_pending_loop, args=(_retry_stop, interval), daemon=True,
        name="webhook-retry-worker",
    )
    _retry_worker.start()


def stop_retry_worker() -> None:
    global _retry_stop
    if _retry_stop is not None:
        _retry_stop.set()
