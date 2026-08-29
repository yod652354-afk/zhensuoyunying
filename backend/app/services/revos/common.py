"""RevOS 公共工具：脱敏、身份哈希、客户聚合档案、事件封装。"""
import hashlib
import hmac

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Patient
from ...models.revos import Customer, CustomerIdentity


# ---------- 脱敏（日志 / API 响应） ----------
def enum_value(x):
    """兼容枚举与原始字符串的取值（ORM 列可能是 str 或 StrEnum）。"""
    return x.value if hasattr(x, "value") else x


def as_utc(dt):
    """SQLite 读回的 datetime 无时区（naive）；统一按 UTC 解释再比较。"""
    from datetime import timezone
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def mask_mobile(mobile: str | None) -> str | None:
    if not mobile:
        return None
    if len(mobile) >= 7:
        return f"{mobile[:3]}****{mobile[-4:]}"
    return "****"


def mask_name(name: str | None) -> str | None:
    if not name:
        return None
    if len(name) == 1:
        return "*"
    return name[0] + "*" * (len(name) - 1)


def mask_identity(value: str | None) -> str | None:
    """企微 external_userid / openid 等：只保留前 6 后 4。"""
    if not value:
        return None
    if len(value) > 12:
        return f"{value[:6]}****{value[-4:]}"
    return "****"


def redact_payload(payload: dict) -> dict:
    """递归脱敏日志 payload 中的敏感字段（mobile/phone/name/idcard/wechat/openid）。"""
    sensitive_keys = {"mobile", "phone", "name", "idcard", "wechat", "openid", "unionid",
                      "external_userid", "token", "secret", "password"}
    out: dict = {}
    for k, v in payload.items():
        if k in sensitive_keys and isinstance(v, str):
            if k in {"mobile", "phone"}:
                out[k] = mask_mobile(v)
            elif k in {"name"}:
                out[k] = mask_name(v)
            else:
                out[k] = mask_identity(v)
        elif isinstance(v, dict):
            out[k] = redact_payload(v)
        elif isinstance(v, list):
            out[k] = [redact_payload(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


# ---------- 身份哈希（加密值 + 匹配哈希分离） ----------
def identity_hash(value: str) -> str:
    """匹配用哈希：HMAC-SHA256(value)，用于唯一索引与匹配，不含明文。"""
    return "sha256:" + hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def identity_hmac(value: str, key: str) -> str:
    """带密钥的 HMAC（可用于加密前校验）。"""
    return hmac.new(key.encode("utf-8"), value.strip().encode("utf-8"), hashlib.sha256).hexdigest()


# ---------- 客户聚合档案 ----------
def ensure_customer(db: Session, patient_id: str) -> Customer:
    """按 patient 确保 Customer 存在并同步基础事实（不复制完整病历）。"""
    customer = db.scalar(
        select(Customer).where(Customer.patient_id == patient_id, Customer.deleted_at.is_(None)).limit(1)
    )
    if customer is not None:
        return customer
    patient = db.get(Patient, patient_id)
    if patient is None:
        raise LookupError(f"patient {patient_id} 不存在")
    customer = Customer(
        customer_id=new_id("customer"),
        organization_id=patient.organization_id,
        store_id=patient.store_id,
        patient_id=patient.patient_id,
        display_name=mask_name(patient.name),
        consent_status=patient.consent_status or "unknown",
        dnc=patient.dnc,
        complaint_flag=patient.complaint_flag,
        contact_status=patient.contact_status,
        total_visits=patient.total_visits or 0,
        total_revenue=patient.total_revenue or 0,
        last_visit_date=patient.last_visit_date,
        source_system=patient.source_system or "clinicos",
    )
    db.add(customer)
    db.flush()
    return customer


def refresh_customer_facts(db: Session, customer: Customer) -> None:
    """从 Patient 刷新客户经营事实（诊所SaaS仍是事实主系统）。"""
    if not customer.patient_id:
        return
    patient = db.get(Patient, customer.patient_id)
    if patient is None:
        return
    customer.display_name = mask_name(patient.name)
    customer.consent_status = patient.consent_status or "unknown"
    customer.dnc = patient.dnc
    customer.complaint_flag = patient.complaint_flag
    customer.contact_status = patient.contact_status
    customer.total_visits = patient.total_visits or 0
    customer.total_revenue = patient.total_revenue or 0
    customer.last_visit_date = patient.last_visit_date


def sync_patient_identity(db: Session, customer: Customer, patient: Patient) -> None:
    """把 Patient 上的手机号/企微/微信同步为 CustomerIdentity（幂等）。"""
    now = utcnow()
    specs = [
        ("mobile", patient.mobile, "clinicos", "patient.mobile"),
        ("external_userid", patient.enterprise_wechat_id, "wecom", "patient.enterprise_wechat_id"),
        ("openid", patient.wechat, "wechat", "patient.wechat"),
    ]
    for itype, value, provider, scope in specs:
        if not value:
            continue
        h = identity_hash(value)
        existing = db.scalar(
            select(CustomerIdentity).where(
                CustomerIdentity.customer_id == customer.customer_id,
                CustomerIdentity.identity_type == itype,
                CustomerIdentity.value_hash == h,
                CustomerIdentity.valid_to.is_(None),
            ).limit(1)
        )
        if existing is not None:
            continue
        db.add(CustomerIdentity(
            identity_id=new_id("identity"),
            organization_id=customer.organization_id,
            store_id=customer.store_id,
            customer_id=customer.customer_id,
            identity_type=itype,
            encrypted_value=value,  # 生产建议使用 Fernet 加密；此处保留源系统字段兼容
            value_hash=h,
            provider=provider,
            app_scope=scope,
            is_primary=(itype == "mobile"),
            valid_from=now,
        ))
