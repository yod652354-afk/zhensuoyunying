"""Webhook 订阅管理 + 投递日志 + 测试事件（需求规格 6.3）。

安全（RevOS P0）：订阅/投递日志全部按服务端租户 scope 隔离。
"""
from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...events.bus import emit
from ...models.event import Event, WebhookDelivery, WebhookSubscription
from ...schemas.write import WebhookSubscriptionCreate

router = APIRouter(tags=["Webhook"])


def _sub_out(sub: WebhookSubscription) -> dict:
    return {
        "subscription_id": sub.subscription_id,
        "url": sub.url,
        "event_types": sub.event_types,
        "enabled": sub.enabled,
        "created_at": sub.created_at.isoformat(),
        "updated_at": sub.updated_at.isoformat(),
    }


@router.get("/webhook-subscriptions", summary="订阅列表")
def list_subscriptions(request: Request, tenant: TenantContext = Depends(get_tenant),
                       db: Session = Depends(get_db)):
    subs = db.scalars(
        select(WebhookSubscription).where(WebhookSubscription.organization_id == tenant.organization_id)
    ).all()
    return {"data": [_sub_out(s) for s in subs], "meta": {"request_id": request.state.request_id}}


@router.post("/webhook-subscriptions", summary="创建订阅")
def create_subscription(body: WebhookSubscriptionCreate, request: Request,
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sub = WebhookSubscription(
        organization_id=tenant.organization_id, url=body.url, secret=body.secret,
        event_types=body.event_types, enabled=body.enabled,
    )
    db.add(sub)
    db.commit()
    return {"data": _sub_out(sub), "meta": {"request_id": request.state.request_id}}


@router.patch("/webhook-subscriptions/{subscription_id}", summary="启停/修改订阅")
def update_subscription(subscription_id: str, body: dict, request: Request,
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise ClinicOSError("NOT_FOUND", "订阅不存在", status_code=404)
    tenant.ensure_scope(sub)
    if "enabled" in body:
        sub.enabled = bool(body["enabled"])
    if "event_types" in body:
        sub.event_types = body["event_types"]
    if "secret" in body:
        sub.secret = body["secret"]
    db.commit()
    return {"data": _sub_out(sub), "meta": {"request_id": request.state.request_id}}


@router.delete("/webhook-subscriptions/{subscription_id}", summary="删除订阅")
def delete_subscription(subscription_id: str, request: Request,
                        tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sub = db.get(WebhookSubscription, subscription_id)
    if sub is None:
        raise ClinicOSError("NOT_FOUND", "订阅不存在", status_code=404)
    tenant.ensure_scope(sub)
    db.delete(sub)
    db.commit()
    return {"data": {"subscription_id": subscription_id, "deleted": True}, "meta": {"request_id": request.state.request_id}}


@router.post("/webhooks/test", summary="发送测试事件")
def send_test_event(request: Request, tenant: TenantContext = Depends(get_tenant),
                    db: Session = Depends(get_db)):
    evt = emit(
        db, "webhook.test", tenant.organization_id, "webhook", "test",
        payload={"message": "这是一条测试事件"},
    )
    db.commit()
    return {"data": {"event_id": evt.event_id, "event_type": "webhook.test"},
            "meta": {"request_id": request.state.request_id}}


@router.get("/webhooks/deliveries", summary="投递日志")
def list_deliveries(request: Request, limit: int = 50,
                    tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.organization_id == tenant.organization_id)
        .order_by(WebhookDelivery.created_at.desc())
        .limit(min(limit, 200))
    ).all()
    return {
        "data": [
            {
                "delivery_id": d.delivery_id,
                "subscription_id": d.subscription_id,
                "event_id": d.event_id,
                "event_type": d.event_type,
                "attempt": d.attempt,
                "status": d.status,
                "http_status": d.http_status,
                "error": d.error,
                "delivered_at": d.delivered_at.isoformat() if d.delivered_at else None,
                "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
            }
            for d in rows
        ],
        "meta": {"request_id": request.state.request_id},
    }


@router.get("/events/replay", summary="事件回放（按时间范围补偿）")
def replay_events(request: Request, event_type: str | None = None, since: str | None = None,
                  limit: int = 200,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    """从事件流重放事件，触发 Webhook 再投递（补偿场景，仅本租户事件）。"""
    from ...core.pagination import coerce_datetime
    query = select(Event).where(Event.organization_id == tenant.organization_id)
    if event_type:
        query = query.where(Event.event_type == event_type)
    if since:
        query = query.where(Event.occurred_at >= coerce_datetime(since, "since"))
    query = query.order_by(Event.occurred_at.asc()).limit(min(limit, 500))
    events = db.scalars(query).all()
    from ...events.dispatcher import dispatch_event
    for evt in events:
        dispatch_event(evt)
    return {"data": {"replayed": len(events)}, "meta": {"request_id": request.state.request_id}}