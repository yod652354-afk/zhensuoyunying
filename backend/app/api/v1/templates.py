"""话术模板管理 API（服务端租户 scope）。"""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...models import MessageTemplate, Organization
from ...services.templates import create_template, list_templates

router = APIRouter(tags=["Templates"])


class TemplateBody(BaseModel):
    name: str
    task_type: str = "recovery"
    channel: str = "wechat"
    content: str
    title: Optional[str] = None
    version: str = "v1"
    store_id: Optional[str] = None


@router.get("/message-templates", summary="话术模板列表")
def get_templates(request: Request, store_id: str | None = None,
                  task_type: str | None = None,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    rows = list_templates(db, store_id, task_type, org_id=tenant.organization_id)
    return {"data": [{
        "message_template_id": t.message_template_id, "name": t.name,
        "task_type": t.task_type.value if hasattr(t.task_type, "value") else str(t.task_type),
        "channel": t.channel, "title": t.title, "content": t.content,
        "version": t.version, "status": str(getattr(t.status, "value", t.status)),
    } for t in rows], "meta": {"request_id": request.state.request_id}}


@router.post("/message-templates", summary="创建话术模板")
def post_template(body: TemplateBody, request: Request,
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    t = create_template(db, tenant.organization_id, body.store_id,
                        body.name, body.task_type, body.channel, body.content,
                        body.title, body.version)
    return {"data": {"message_template_id": t.message_template_id, "name": t.name},
            "meta": {"request_id": request.state.request_id}}