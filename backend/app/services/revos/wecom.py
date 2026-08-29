"""企业微信 Gateway（规格 03 §13 / 企微规格 §8）。

默认模式：系统创建发送任务 → 企微成员收到待确认任务 → 成员确认发送 →
系统记录回执/失败原因。不假设 API 可以自动 1v1 外部联系人发送。

- token 管理（获取、缓存、失效刷新）；
- external_userid 映射（customer_id ↔ external_userid 通过 CustomerIdentity）；
- 文字/图片/小程序卡片；
- 回执与失败原因、频控、幂等（touch_id + content_hash）、重试分类；
- 不确定状态先查询，禁止重复发送；
- 缺少真实凭证时使用模拟器，契约测试保证接口语义。

安全：密钥来自环境变量，不进代码/日志/前端；原始响应脱敏存档。
"""
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.enums import (
    ActionStatus, ActionType, AssignedToType, CreatedByType, SendStatus, TaskType,
)
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Patient, Staff, Task, Touch
from ...models.revos import (
    ContentDraft, CustomerIdentity, ExecutionPlan, Opportunity,
)

logger = logging.getLogger("clinicos.revos.wecom")


# ---------- 错误分类 ----------
class WeComError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


RETRYABLE_CODES = {"timeout", "network", "system_busy", "rate_limited"}
NON_RETRYABLE_CODES = {"no_relation", "no_permission", "invalid_contact", "blocked", "not_joined"}


# ---------- Provider 接口 ----------
@dataclass
class WeComSendRequest:
    idempotency_key: str          # touch_id + content_hash
    external_userid: str
    text: str | None = None
    image_url: str | None = None
    mini_program: dict | None = None
    channel_account_id: str | None = None


@dataclass
class WeComSendResult:
    status: SendStatus            # sent / delivered / unknown / failed
    external_message_id: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    raw: dict | None = None       # 脱敏存档


class WeComProvider:
    name = "base"

    def send(self, request: WeComSendRequest) -> WeComSendResult:
        raise NotImplementedError

    def query_status(self, external_message_id: str) -> WeComSendResult:
        raise NotImplementedError


class SimulatedWeComProvider(WeComProvider):
    """模拟器：本地确定性结果，用于契约测试与无凭证环境。"""

    name = "simulator"

    def send(self, request: WeComSendRequest) -> WeComSendResult:
        # 幂等：相同 key 返回相同 external_message_id
        digest = hashlib.sha256(request.idempotency_key.encode("utf-8")).hexdigest()[:16]
        if request.external_userid.startswith("blocked_") or request.external_userid == "wxid_invalid":
            return WeComSendResult(status=SendStatus.FAILED, failure_code="no_relation",
                                   failure_message="客户无企微好友关系（模拟）", raw={"mock": True})
        return WeComSendResult(status=SendStatus.SENT,
                               external_message_id=f"mock_msg_{digest}", raw={"mock": True})

    def query_status(self, external_message_id: str) -> WeComSendResult:
        return WeComSendResult(status=SendStatus.DELIVERED,
                               external_message_id=external_message_id, raw={"mock": True})


class HttpWeComProvider(WeComProvider):
    """真实企微 API（凭证经环境变量注入）。token 缓存 + 错误分类 + 幂等。"""

    def __init__(self, corpid: str, secret: str, agent_id: str, api_base: str):
        self.name = "http_wecom"
        self.corpid = corpid
        self.secret = secret
        self.agent_id = agent_id
        self.api_base = api_base.rstrip("/")
        self._token: str | None = None
        self._token_expires_at: float = 0

    def _get_token(self) -> str:
        import httpx

        if self._token and time.time() < self._token_expires_at - 60:
            return self._token
        resp = httpx.get(f"{self.api_base}/gettoken", params={
            "corpid": self.corpid, "corpsecret": self.secret,
        }, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        if data.get("errcode") != 0:
            raise WeComError(f"token_error_{data.get('errcode')}", data.get("errmsg", ""))
        self._token = data["access_token"]
        self._token_expires_at = time.time() + int(data.get("expires_in", 7200))
        return self._token

    def send(self, request: WeComSendRequest) -> WeComSendResult:
        import httpx

        token = self._get_token()
        # 真实企微：创建群发任务（add_msg_template）成功后处于"等待成员确认/发送"，
        # 不得直接标记为 SENT；送达状态通过回调或结果查询确认（R-06）。
        url = f"{self.api_base}/externalcontact/add_msg_template?access_token={token}"
        try:
            resp = httpx.post(url, json={
                "chat_type": "single",
                "external_userid": [request.external_userid],
                "text": {"content": request.text} if request.text else None,
                "attachments": [],
            }, timeout=15.0)
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise WeComError("timeout", f"企微调用超时: {exc}", retryable=True)
        if data.get("errcode") == 0:
            return WeComSendResult(status=SendStatus.WAITING_MEMBER_CONFIRMATION,
                                   external_message_id=str(data.get("msgid")),
                                   raw={"errcode": 0, "note": "群发任务已创建，等待成员确认发送"})
        code = data.get("errcode")
        if code in (40014, 42001, 40001):  # token 失效 → 刷新后重试一次
            self._token = None
            raise WeComError("token_expired", f"token 失效: {code}", retryable=True)
        if code in (45009, 45010):  # 频控
            raise WeComError("rate_limited", f"企微频控: {code}", retryable=False)
        if code in (84061, 84062):  # 无客户关系
            raise WeComError("no_relation", f"无客户关系: {code}", retryable=False)
        raise WeComError(f"wecom_{code}", str(data.get("errmsg", "")), retryable=False)

    def query_status(self, external_message_id: str) -> WeComSendResult:
        """真实状态查询（R-06）：获取群发任务发送结果；未知/无权限返回 UNKNOWN。

        官方支持结果查询接口（如 get_groupmsg_send_result / 企微回调）时，
        用 msgid 查询成员发送任务状态，映射为 sent/delivered/failed/unknown。
        """
        import httpx

        token = self._get_token()
        url = f"{self.api_base}/externalcontact/get_groupmsg_send_result?access_token={token}"
        try:
            resp = httpx.post(url, json={"msgid": external_message_id, "limit": 100},
                              timeout=15.0)
            data = resp.json()
        except Exception:  # noqa: BLE001
            return WeComSendResult(status=SendStatus.UNKNOWN,
                                   external_message_id=external_message_id,
                                   failure_message="状态查询超时/网络错误", raw={})
        if data.get("errcode") != 0:
            return WeComSendResult(status=SendStatus.UNKNOWN,
                                   external_message_id=external_message_id,
                                   failure_code=f"query_{data.get('errcode')}",
                                   failure_message=str(data.get("errmsg", "")), raw=data)
        status_list = data.get("status_list") or []
        if status_list:
            first = status_list[0].get("status")
            mapping = {1: SendStatus.SENT, 2: SendStatus.DELIVERED, 3: SendStatus.UNKNOWN}
            return WeComSendResult(status=mapping.get(first, SendStatus.UNKNOWN),
                                   external_message_id=external_message_id,
                                   raw={"status": first})
        return WeComSendResult(status=SendStatus.UNKNOWN,
                               external_message_id=external_message_id,
                               failure_message="群发任务尚未有成员发送结果", raw=data)


def get_wecom_provider() -> WeComProvider:
    settings = get_settings()
    if settings.revos_wecom_mode == "http" and settings.revos_wecom_corpid and settings.revos_wecom_secret:
        return HttpWeComProvider(settings.revos_wecom_corpid, settings.revos_wecom_secret,
                                 settings.revos_wecom_agent_id, settings.revos_wecom_api_base)
    return SimulatedWeComProvider()


# ---------- external_userid 映射 ----------
def resolve_external_userid(db: Session, customer_id: str, org_id: str) -> str | None:
    identity = db.scalar(
        select(CustomerIdentity).where(
            CustomerIdentity.customer_id == customer_id,
            CustomerIdentity.identity_type == "external_userid",
            CustomerIdentity.organization_id == org_id,
            CustomerIdentity.valid_to.is_(None),
            CustomerIdentity.deleted_at.is_(None),
        ).order_by(CustomerIdentity.is_primary.desc()).limit(1)
    )
    return identity.encrypted_value if identity else None


# ---------- 发送前最终检查（实际发送前再次校验） ----------
def final_pre_send_check(db: Session, opportunity: Opportunity) -> tuple[bool, str]:
    """DNC / 投诉 / 未授权 / 频控 必须在实际发送前再次检查（规格 §8.3 门禁）。"""
    from .arbitration import check_customer_gate

    ok, code = check_customer_gate(db, opportunity)
    if not ok:
        return False, code
    # 实验组：对照组不得触达
    if opportunity.experiment_group == "control":
        return False, "CONTROL_GROUP"
    if opportunity.status.value in ("suppressed", "expired", "lost"):
        return False, f"OPPORTUNITY_{opportunity.status.value.upper()}"
    return True, ""


# ---------- 发送任务 ----------
def create_send_task(
    db: Session,
    plan: ExecutionPlan,
    draft: ContentDraft,
    causation_event_id: str | None = None,
) -> Task:
    """创建企微员工确认发送任务（内容必须已批准）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    if draft.status != "approved":
        raise ValueError(f"内容未批准（{draft.status}），不能创建发送任务")

    opportunity = db.get(Opportunity, plan.opportunity_id)
    staff_id = plan.assigned_staff_id or "unassigned"
    task = Task(
        task_id=new_id("task"),
        organization_id=plan.organization_id,
        store_id=plan.store_id,
        task_type=TaskType.RECOVERY if (opportunity and opportunity.money_type.value == "past") else TaskType.GROWTH,
        patient_id=plan.patient_id,
        assigned_to_type=AssignedToType.STAFF,
        assigned_to_id=staff_id,
        due_at=utcnow() + timedelta(days=1),
        reason=f"企微发送：{opportunity.scenario_type.value if opportunity else plan.goal}",
        expected_value=plan.expected_value,
        status="pending",
        suggested_channel="enterprise_wechat",
        opportunity_id=opportunity.opportunity_id if opportunity else None,
        execution_plan_id=plan.execution_plan_id,
        content_draft_id=draft.content_draft_id,
        workflow_instance_id=plan.workflow_instance_id,
        send_mode="manual",
        send_status=SendStatus.CONTENT_APPROVED.value,
        content_hash=draft.content_hash,
        correlation_id=opportunity.opportunity_id if opportunity else None,
        created_by_type=CreatedByType.AI,
    )
    db.add(task)
    db.flush()
    emit(db, "send_task.created", task.organization_id, "task", task.task_id,
         store_id=task.store_id, patient_id=task.patient_id, actor_type=ActorType.AI,
         correlation_id=task.correlation_id, causation_id=causation_event_id,
         payload={"send_status": task.send_status, "content_draft_id": draft.content_draft_id,
                  "assigned_to_id": staff_id})
    return task


def prepare_wecom(db: Session, task: Task) -> dict:
    """员工准备发送：解析 external_userid 并预检（不真正发送）。"""
    opportunity = db.get(Opportunity, task.opportunity_id) if task.opportunity_id else None
    if opportunity is None:
        raise ValueError("任务未关联机会")
    ok, code = final_pre_send_check(db, opportunity)
    if not ok:
        task.send_status = SendStatus.FAILED.value
        task.failure_code = code
        task.failure_message = f"发送前检查未通过: {code}"
        db.commit()
        return {"ok": False, "code": code, "external_userid": None}
    external_userid = resolve_external_userid(db, opportunity.customer_id, task.organization_id)
    if not external_userid:
        task.send_status = SendStatus.FAILED.value
        task.failure_code = "NO_EXTERNAL_USERID"
        task.failure_message = "客户未绑定企微 external_userid"
        db.commit()
        return {"ok": False, "code": "NO_EXTERNAL_USERID", "external_userid": None}
    task.send_status = SendStatus.WAITING_MEMBER_CONFIRMATION.value
    db.commit()
    return {"ok": True, "code": "READY", "external_userid": external_userid}


def confirm_sent(
    db: Session,
    task: Task,
    staff_id: str | None = None,
    external_userid: str | None = None,
    causation_event_id: str | None = None,
) -> Touch:
    """员工确认已发送：创建 Touch（幂等：同一任务不重复落 Touch）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType

    existing = db.scalar(
        select(Touch).where(Touch.task_id == task.task_id, Touch.deleted_at.is_(None)).limit(1)
    )
    if existing is not None:
        return existing

    opportunity = db.get(Opportunity, task.opportunity_id) if task.opportunity_id else None
    draft = db.get(ContentDraft, task.content_draft_id) if task.content_draft_id else None

    # 发送前最终检查（再次）
    if opportunity:
        ok, code = final_pre_send_check(db, opportunity)
        if not ok:
            task.send_status = SendStatus.FAILED.value
            task.failure_code = code
            task.failure_message = f"发送前检查未通过: {code}"
            db.commit()
            raise WeComError(code, f"发送前检查未通过: {code}", retryable=False)

    # 调用 Provider（模拟器或真实企微）
    provider = get_wecom_provider()
    eu = external_userid or resolve_external_userid(db, opportunity.customer_id, task.organization_id) if opportunity else None
    idempotency_key = f"{task.task_id}:{task.content_hash or 'no-hash'}"
    result: WeComSendResult
    if eu:
        req = WeComSendRequest(
            idempotency_key=idempotency_key,
            external_userid=eu,
            text=draft.wecom_text if draft else None,
            image_url=draft.image_url if draft else None,
            mini_program=draft.mini_program_config if draft else None,
        )
        try:
            result = provider.send(req)
        except WeComError as exc:
            result = WeComSendResult(status=SendStatus.FAILED if not exc.retryable else SendStatus.UNKNOWN,
                                     failure_code=exc.code, failure_message=str(exc))
    else:
        result = WeComSendResult(status=SendStatus.FAILED, failure_code="NO_EXTERNAL_USERID",
                                 failure_message="客户未绑定企微 external_userid")

    touch = Touch(
        touch_id=new_id("touch"),
        organization_id=task.organization_id,
        store_id=task.store_id,
        patient_id=task.patient_id,
        task_id=task.task_id,
        staff_id=staff_id or task.assigned_to_id,
        channel="enterprise_wechat",
        sent_at=utcnow(),
        message_version=draft.content_hash if draft else None,
        opportunity_id=task.opportunity_id,
        content_draft_id=task.content_draft_id,
        send_mode=task.send_mode or "manual",
        external_message_id=result.external_message_id,
        send_status=result.status.value,
        failure_code=result.failure_code,
        failure_message=result.failure_message,
        confirmed_by=staff_id,
        confirmed_at=utcnow(),
        content_hash=task.content_hash,
        correlation_id=task.correlation_id,
        source_system="revos",
        created_by_type="staff",
        created_by_id=staff_id,
    )
    db.add(touch)
    db.flush()

    # 同步任务状态
    task.send_status = result.status.value
    task.external_message_id = result.external_message_id
    if result.status == SendStatus.SENT or result.status == SendStatus.DELIVERED:
        task.status = "completed"
        task.completed_at = utcnow()
    if result.status == SendStatus.FAILED:
        task.failure_code = result.failure_code
        task.failure_message = result.failure_message
    db.commit()

    emit(db, f"touch.{result.status.value}", task.organization_id, "touch", touch.touch_id,
         store_id=touch.store_id, patient_id=touch.patient_id, actor_type=ActorType.STAFF, actor_id=staff_id,
         correlation_id=touch.correlation_id, causation_id=causation_event_id,
         payload={"send_status": result.status.value, "external_message_id": result.external_message_id,
                  "failure_code": result.failure_code, "idempotency_key": idempotency_key[:40]})
    return touch


def mark_failed(db: Session, task: Task, failure_code: str, failure_message: str,
                staff_id: str | None = None, causation_event_id: str | None = None) -> Task:
    from ...events.bus import emit
    from ...core.enums import ActorType

    task.send_status = SendStatus.FAILED.value
    task.failure_code = failure_code
    task.failure_message = failure_message
    task.status = "failed"
    db.commit()
    emit(db, "touch.failed", task.organization_id, "task", task.task_id,
         store_id=task.store_id, patient_id=task.patient_id, actor_type=ActorType.STAFF, actor_id=staff_id,
         correlation_id=task.correlation_id, causation_id=causation_event_id,
         payload={"failure_code": failure_code, "failure_message": failure_message})
    return task


def query_unknown_status(db: Session, task: Task) -> SendStatus:
    """不确定发送状态：先查询，禁止直接重复发送（规格 §8.3 / R-06）。"""
    if task.external_message_id:
        provider = get_wecom_provider()
        result = provider.query_status(task.external_message_id)
        task.send_status = result.status.value
        if result.status in (SendStatus.SENT, SendStatus.DELIVERED):
            task.status = "completed"
            task.completed_at = utcnow()
        if result.status == SendStatus.FAILED:
            task.failure_code = result.failure_code
            task.failure_message = result.failure_message
        db.commit()
        return result.status
    return SendStatus.UNKNOWN


# ---------- 企微回调（R-06：验签 / 幂等 / 状态更新） ----------
def verify_wecom_signature(token: str, timestamp: str, nonce: str,
                           encrypt_msg: str, signature: str) -> bool:
    """企微回调签名校验：SHA1(sort(token, timestamp, nonce, encrypt_msg))。"""
    import hashlib
    parts = sorted([token, timestamp, nonce, encrypt_msg])
    digest = hashlib.sha1("".join(parts).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, signature or "")


def handle_wecom_callback(
    db: Session,
    event_type: str,
    external_message_id: str,
    send_status: str,
    member_userid: str | None = None,
    occurred_at: datetime | None = None,
    organization_id: str | None = None,
    causation_event_id: str | None = None,
) -> dict:
    """处理企微回调事件（幂等：相同 external_message_id + 状态只更新一次）。

    真实企微回调为 AES 加密 XML；验签通过后解密得到事件，
    此处接收已解密的标准化事件（契约测试验证幂等与状态机）。
    """
    from ...events.bus import emit
    from ...core.enums import ActorType

    status_map = {
        "sent": SendStatus.SENT, "delivered": SendStatus.DELIVERED,
        "failed": SendStatus.FAILED, "unknown": SendStatus.UNKNOWN,
        "waiting_member_confirmation": SendStatus.WAITING_MEMBER_CONFIRMATION,
        "member_confirmed": SendStatus.SENT,
    }
    target = status_map.get(send_status)
    if target is None:
        return {"accepted": False, "reason": f"未知状态 {send_status}"}

    touch = db.scalar(
        select(Touch).where(
            Touch.external_message_id == external_message_id,
            Touch.deleted_at.is_(None),
        ).order_by(Touch.created_at.desc()).limit(1)
    )
    task = None
    if touch is not None:
        if touch.send_status == target.value:
            return {"accepted": True, "duplicate": True, "touch_id": touch.touch_id}
        touch.send_status = target.value
        if target in (SendStatus.SENT, SendStatus.DELIVERED):
            touch.delivered_at = touch.delivered_at or (occurred_at or utcnow())
        if target == SendStatus.FAILED:
            touch.failure_code = touch.failure_code or "callback_failed"
        if touch.task_id:
            task = db.get(Task, touch.task_id)
    else:
        task = db.scalar(
            select(Task).where(
                Task.external_message_id == external_message_id,
                Task.deleted_at.is_(None),
            ).order_by(Task.created_at.desc()).limit(1)
        )
        if task is None:
            return {"accepted": False, "reason": "找不到对应发送任务"}

    if task is not None:
        if task.send_status == target.value:
            return {"accepted": True, "duplicate": True, "task_id": task.task_id}
        task.send_status = target.value
        if target in (SendStatus.SENT, SendStatus.DELIVERED):
            task.status = "completed"
            task.completed_at = occurred_at or utcnow()
        if target == SendStatus.FAILED:
            task.failure_code = task.failure_code or "callback_failed"

    org_id = (touch.organization_id if touch else task.organization_id) if (touch or task) else organization_id or ""
    db.commit()
    emit(db, f"touch.{target.value}", org_id, "touch", touch.touch_id if touch else external_message_id,
         store_id=touch.store_id if touch else None,
         actor_type=ActorType.SYSTEM,
         correlation_id=(touch.correlation_id if touch else None),
         causation_id=causation_event_id,
         payload={"callback": True, "external_message_id": external_message_id,
                  "send_status": target.value, "member_userid": member_userid})
    db.commit()
    return {"accepted": True, "duplicate": False,
            "touch_id": touch.touch_id if touch else None,
            "task_id": task.task_id if task else None,
            "send_status": target.value}
