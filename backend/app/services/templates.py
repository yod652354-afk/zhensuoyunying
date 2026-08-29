"""话术模板库（Prescription）：为任务推荐 渠道×话术×建议时间。"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.enums import PersonStatus
from ..core.ids import new_id
from ..core.timeutil import utcnow
from ..models import MessageTemplate, Patient


def list_templates(db: Session, store_id: str | None = None, task_type: str | None = None,
                   org_id: str | None = None) -> list[MessageTemplate]:
    q = select(MessageTemplate).where(
        MessageTemplate.deleted_at.is_(None),
        MessageTemplate.status == PersonStatus.ACTIVE,
    )
    if org_id:
        q = q.where(MessageTemplate.organization_id == org_id)
    if store_id:
        q = q.where(MessageTemplate.store_id == store_id)
    if task_type:
        q = q.where(MessageTemplate.task_type == task_type)
    return list(db.scalars(q.order_by(MessageTemplate.created_at.desc())).all())


def create_template(db: Session, organization_id: str, store_id: str | None,
                    name: str, task_type: str, channel: str, content: str,
                    title: str | None = None, version: str = "v1") -> MessageTemplate:
    t = MessageTemplate(
        message_template_id=new_id("message_template"),
        organization_id=organization_id, store_id=store_id,
        name=name, task_type=task_type, channel=channel,
        title=title, content=content, version=version,
        created_by_type="AI",
    )
    db.add(t)
    db.commit()
    return t


def render_template(template: MessageTemplate, patient: Patient | None = None,
                    doctor_name: str | None = None, store_name: str | None = None) -> dict:
    """填充模板变量：{患者姓名} {医生} {门店}。"""
    content = template.content
    title = template.title or ""
    if patient:
        content = content.replace("{患者姓名}", patient.name or "顾客")
        title = title.replace("{患者姓名}", patient.name or "顾客")
    if doctor_name:
        content = content.replace("{医生}", doctor_name)
    if store_name:
        content = content.replace("{门店}", store_name)
    return {"title": title, "content": content}


def suggest_template(db: Session, task_type: str, channel: str | None = None,
                     store_id: str | None = None) -> MessageTemplate | None:
    """按 任务类型+渠道 匹配模板；无渠道偏好则取该类型最新模板。"""
    q = select(MessageTemplate).where(
        MessageTemplate.deleted_at.is_(None),
        MessageTemplate.status == PersonStatus.ACTIVE,
        MessageTemplate.task_type == task_type,
    )
    if channel:
        q = q.where(MessageTemplate.channel == channel)
    if store_id:
        q = q.where(MessageTemplate.store_id == store_id)
    q = q.order_by(MessageTemplate.created_at.desc())
    return db.scalar(q.limit(1))


def suggest_channel(segment: str) -> str:
    """渠道建议：沉睡/流失 走企微/电话；No-show 走电话；复诊提醒走短信/企微。"""
    if segment in ("no_show", "appointment_reminder"):
        return "phone"
    if segment in ("sleeping_30", "sleeping_60"):
        return "enterprise_wechat"
    return "wechat"


def suggest_time() -> datetime:
    """建议时间：工作日上午。"""
    now = utcnow()
    target = now + timedelta(days=1)
    return target.replace(hour=10, minute=0, second=0, microsecond=0)