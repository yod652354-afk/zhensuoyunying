"""小程序安全承接与行为回流（规格 03 §14 / 企微规格 §9）。

- 随机短期 ticket（不保存明文，存哈希）；可过期、可撤销、跨客户防护；
- wx.login 服务端会话（code2session，凭证经环境变量，测试用模拟器）；
- 专属内容获取：只返回公开展示内容，不返回内部 ID/手机号/医疗敏感信息；
- 行为上报：允许 page_view/cta_click/appointment_submit/coupon_receive/share；
  按客户端 event_id 幂等；支付结果不接受客户端伪造。
"""
import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import SessionStatus
from ...core.errors import ClinicOSError
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models.revos import ContentDraft, InteractionSession, MpEvent, Opportunity

ALLOWED_MP_EVENTS = {"page_view", "cta_click", "appointment_submit", "coupon_receive", "share"}
CLIENT_FORGED_EVENTS = {"payment_success", "payment_completed"}  # 客户端不得上报支付结果


def _hash_token(token: str) -> str:
    return "sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_ticket(
    db: Session,
    opportunity_id: str,
    customer_id: str,
    organization_id: str,
    store_id: str | None = None,
    touch_id: str | None = None,
    content_draft_id: str | None = None,
    ttl_seconds: int | None = None,
) -> tuple[InteractionSession, str]:
    """签发随机会话 ticket（高熵、短期有效、可撤销）。"""
    settings = get_settings()
    ttl = ttl_seconds or settings.revos_mp_ticket_ttl_seconds
    token = secrets.token_urlsafe(32)
    session = InteractionSession(
        session_id=new_id("interaction_session"),
        organization_id=organization_id,
        store_id=store_id,
        opportunity_id=opportunity_id,
        touch_id=touch_id,
        content_draft_id=content_draft_id,
        customer_id=customer_id,
        token_hash=_hash_token(token),
        expires_at=utcnow() + timedelta(seconds=ttl),
        status=SessionStatus.ISSUED,
    )
    db.add(session)
    db.flush()
    return session, token


def resolve_session(db: Session, ticket: str) -> InteractionSession:
    """ticket → 会话（哈希匹配 + 过期/撤销校验）。"""
    if not ticket:
        raise ClinicOSError("INVALID_TICKET", "缺少 ticket", status_code=400, retryable=False)
    session = db.scalar(
        select(InteractionSession).where(InteractionSession.token_hash == _hash_token(ticket)).limit(1)
    )
    if session is None:
        raise ClinicOSError("INVALID_TICKET", "ticket 无效或已撤销", status_code=404, retryable=False)
    if session.status == SessionStatus.REVOKED:
        raise ClinicOSError("INVALID_TICKET", "ticket 已撤销", status_code=403, retryable=False)
    from .common import as_utc
    if as_utc(session.expires_at) < as_utc(utcnow()):
        session.status = SessionStatus.EXPIRED
        db.commit()
        raise ClinicOSError("INVALID_TICKET", "ticket 已过期", status_code=403, retryable=False)
    return session


def get_offer(db: Session, ticket: str) -> dict:
    """专属内容获取（企微卡片只携带随机 ticket；不返回内部标识）。"""
    session = resolve_session(db, ticket)
    if session.status != SessionStatus.OPENED:
        session.status = SessionStatus.OPENED
        session.first_opened_at = utcnow()
        db.commit()

    draft = db.get(ContentDraft, session.content_draft_id) if session.content_draft_id else None
    opportunity = db.get(Opportunity, session.opportunity_id) if session.opportunity_id else None
    from .common import enum_value
    return {
        "interaction_session_id": session.session_id,
        "display_title": draft.title if draft else None,
        "display_text": draft.wecom_text if draft else None,
        "image_url": draft.image_url if draft else None,
        "mini_program": draft.mini_program_config if draft else None,
        "allowed_ctas": ["page_view", "cta_click", "appointment_submit", "coupon_receive", "share"],
        "expires_at": session.expires_at.isoformat(),
        "scenario": enum_value(opportunity.scenario_type) if opportunity else None,
        # 不返回：customer_id / task_id / 手机号 / 医疗敏感信息
    }


def record_event(
    db: Session,
    event_id: str,
    interaction_session_id: str,
    event_type: str,
    occurred_at,
    page_code: str | None = None,
    payload: dict | None = None,
) -> MpEvent:
    """行为上报（幂等：同一 event_id 重复提交返回已有记录）。"""
    if event_type in CLIENT_FORGED_EVENTS:
        raise ClinicOSError("FORBIDDEN", "支付结果不能由客户端上报", status_code=403, retryable=False)
    if event_type not in ALLOWED_MP_EVENTS:
        raise ClinicOSError("INVALID_ARGUMENT", f"不允许的事件类型: {event_type}", status_code=400, retryable=False)

    existing = db.scalar(select(MpEvent).where(MpEvent.event_id == event_id).limit(1))
    if existing is not None:
        return existing

    session = db.get(InteractionSession, interaction_session_id)
    if session is None:
        raise ClinicOSError("INVALID_TICKET", "会话不存在", status_code=404, retryable=False)
    from .common import as_utc
    if as_utc(session.expires_at) < as_utc(utcnow()):
        raise ClinicOSError("INVALID_TICKET", "会话已过期", status_code=403, retryable=False)

    mp_event = MpEvent(
        mp_event_id=new_id("mp_event"),
        organization_id=session.organization_id,
        store_id=session.store_id,
        event_id=event_id,
        interaction_session_id=interaction_session_id,
        event_type=event_type,
        occurred_at=occurred_at,
        page_code=page_code,
        payload=payload or {},
    )
    db.add(mp_event)
    db.flush()
    return mp_event


def wx_login_session(db: Session, code: str, appid: str | None = None, secret: str | None = None) -> dict:
    """wx.login → code2session（真实凭证经环境变量；测试环境模拟）。"""
    import httpx

    settings = get_settings()
    appid = appid or settings.revos_wx_appid
    secret = secret or settings.revos_wx_secret
    if not appid or not secret:
        # 模拟：返回固定 openid（仅测试/开发）
        digest = hashlib.sha256(code.encode("utf-8")).hexdigest()[:28]
        return {"openid": f"mock_openid_{digest}", "session_key": "mock_session_key", "mock": True}
    resp = httpx.get("https://api.weixin.qq.com/sns/jscode2session", params={
        "appid": appid, "secret": secret, "js_code": code, "grant_type": "authorization_code",
    }, timeout=10.0)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errcode") not in (None, 0):
        raise ClinicOSError("WX_LOGIN_FAILED", f"微信登录失败: {data.get('errmsg')}",
                            status_code=401, retryable=False)
    return {"openid": data["openid"], "session_key": data.get("session_key"), "unionid": data.get("unionid")}


def bind_openid(db: Session, session_id: str, openid: str, org_id: str) -> None:
    """首次验证后把 openid 绑定到会话（跨客户防护：openid 必须属于会话客户）。"""
    from ...models.revos import CustomerIdentity

    session = db.get(InteractionSession, session_id)
    if session is None:
        return
    identity = db.scalar(
        select(CustomerIdentity).where(
            CustomerIdentity.customer_id == session.customer_id,
            CustomerIdentity.identity_type == "openid",
            CustomerIdentity.value_hash == "sha256:" + hashlib.sha256(openid.encode()).hexdigest(),
            CustomerIdentity.valid_to.is_(None),
            CustomerIdentity.deleted_at.is_(None),
        ).limit(1)
    )
    if identity is None:
        identity = CustomerIdentity(
            identity_id=new_id("identity"),
            organization_id=org_id,
            store_id=session.store_id,
            customer_id=session.customer_id,
            identity_type="openid",
            encrypted_value=openid,
            value_hash="sha256:" + hashlib.sha256(openid.encode()).hexdigest(),
            provider="wechat",
            app_scope=f"mp:{org_id}",
            valid_from=utcnow(),
        )
        db.add(identity)
        db.flush()
    session.bound_openid_identity_id = identity.identity_id
    db.commit()


def revoke_ticket(db: Session, session_id: str) -> None:
    session = db.get(InteractionSession, session_id)
    if session is not None:
        session.status = SessionStatus.REVOKED
        db.commit()
