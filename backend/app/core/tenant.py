"""RevOS 租户安全上下文（P0 修复）。

原则（开发规格 §3 / 审计报告 §4）：
- JWT / API Key 由服务端解析出明确 organization_id；
- 普通员工强制 store 作用域（store_id 由服务端注入，客户端不可扩大）；
- list / detail / write / import / analytics / files / webhooks 全部应用 scope；
- 禁止客户端通过查询参数或请求体扩大租户权限；
- 生产环境拒绝默认开发密钥。

用法：
    tenant: TenantContext = Depends(get_tenant)
    query = tenant.scope_query(query, Model)             # 列表过滤
    tenant.ensure_scope(entity)                           # 详情/写入校验（403）
"""
import json
import logging
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from .auth import TokenError, decode_token
from .errors import ClinicOSError
from ..models import Organization, User

logger = logging.getLogger("clinicos.tenant")

# 默认开发密钥（生产模式必须拒绝）
DEFAULT_API_KEYS = {"dev-key-change-me"}
DEFAULT_WEBHOOK_SECRETS = {"dev-webhook-secret-change-me"}
DEFAULT_AUTH_SECRETS = {"dev-auth-secret-change-me"}


@dataclass
class TenantContext:
    """一次请求的服务端权威租户上下文。"""

    organization_id: str
    store_id: str | None = None          # 员工强制 scope；boss/admin 可为 None（全门店）
    role: str = "api"                    # api / boss / staff / admin / auditor
    actor_type: str = "system"           # system / staff / api
    actor_id: str | None = None          # user_id 或 api key 名
    source: str = "api_key"              # jwt / api_key
    force_store_scope: bool = False      # staff 必须限定门店
    extras: dict = field(default_factory=dict)

    def scope_query(self, query: Select, model: type) -> Select:
        """按租户过滤列表查询：org 必选；员工强制 store。"""
        query = query.where(model.organization_id == self.organization_id)
        if self.force_store_scope and self.store_id:
            query = query.where(model.store_id == self.store_id)
        return query

    def ensure_scope(self, entity) -> None:
        """校验单实体归属：跨租户读取/写入一律 403。"""
        org = getattr(entity, "organization_id", None)
        if org != self.organization_id:
            raise ClinicOSError(
                "FORBIDDEN", "无权访问其他组织的数据", status_code=403, retryable=False
            )
        if self.force_store_scope and self.store_id:
            store = getattr(entity, "store_id", None)
            if store is not None and store != self.store_id:
                raise ClinicOSError(
                    "FORBIDDEN", "无权访问其他门店的数据", status_code=403, retryable=False
                )

    def require_role(self, *roles: str) -> None:
        if self.role not in roles:
            raise ClinicOSError(
                "FORBIDDEN", f"需要角色: {'/'.join(roles)}，当前: {self.role}",
                status_code=403, retryable=False,
            )


def _default_org_id(db: Session) -> str:
    """API Key 未显式映射时的兜底（仅限开发/单租户）。"""
    org = db.scalar(select(Organization).order_by(Organization.created_at.asc()).limit(1))
    if org is None:
        raise HTTPException(status_code=500, detail="系统中尚无 Organization，无法解析租户")
    return org.organization_id


def _resolve_api_key_org(key: str, db: Session) -> str:
    settings = get_settings()
    mapping: dict = {}
    if settings.api_key_org_map.strip():
        try:
            mapping = json.loads(settings.api_key_org_map)
        except ValueError:
            logger.error("API_KEY_ORG_MAP 不是合法 JSON，忽略映射")
    if key in mapping and mapping[key]:
        return str(mapping[key])
    return _default_org_id(db)


def get_tenant(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> TenantContext:
    """认证依赖：解析 JWT 或 API Key 为服务端租户上下文。

    - JWT：org 来自用户记录（不信任 token 内 org 字段以外的声明）；
    - API Key：org 来自 API_KEY_ORG_MAP 或单租户兜底；
    - 员工角色强制 store scope。
    """
    settings = get_settings()
    if authorization and str(authorization).lower().startswith("bearer "):
        token = str(authorization).split(" ", 1)[1].strip()
        try:
            payload = decode_token(token)
        except TokenError as exc:
            raise HTTPException(status_code=401, detail=str(exc))
        user = db.get(User, payload.get("sub"))
        if user is None or user.deleted_at or user.status != "active":
            raise HTTPException(status_code=401, detail="用户不存在或已停用")
        org_id = user.organization_id or _default_org_id(db)
        role = user.role or "staff"
        force_store = role == "staff"
        return TenantContext(
            organization_id=org_id,
            store_id=user.store_id if force_store else None,
            role=role,
            actor_type="staff",
            actor_id=user.user_id,
            source="jwt",
            force_store_scope=force_store,
            extras={"username": user.username, "user_id": user.user_id, "staff_id": user.staff_id},
        )
    if x_api_key:
        if x_api_key not in settings.api_key_list:
            raise HTTPException(status_code=401, detail="API Key 无效")
        org_id = _resolve_api_key_org(x_api_key, db)
        return TenantContext(
            organization_id=org_id,
            role="api",
            actor_type="api",
            actor_id=f"apikey:{x_api_key[:8]}",
            source="api_key",
            extras={"api_key": x_api_key},
        )
    raise HTTPException(status_code=401, detail="缺少认证：需要 Bearer Token 或 X-API-Key")


def assert_production_secrets() -> None:
    """生产模式启动门禁：拒绝默认开发密钥（审计报告 P0）。"""
    settings = get_settings()
    if settings.environment != "production":
        return
    problems: list[str] = []
    keys = set(settings.api_key_list)
    if keys & DEFAULT_API_KEYS or not keys:
        problems.append("API_KEYS 包含默认/空开发密钥")
    if settings.webhook_secret in DEFAULT_WEBHOOK_SECRETS or not settings.webhook_secret:
        problems.append("WEBHOOK_SECRET 为默认值或为空")
    if settings.auth_secret in DEFAULT_AUTH_SECRETS or not settings.auth_secret:
        problems.append("AUTH_SECRET 为默认值或为空")
    if not settings.api_key_org_map.strip():
        problems.append("生产环境必须配置 API_KEY_ORG_MAP（API Key → 组织映射）")
    if problems:
        raise RuntimeError(
            "生产模式安全门禁未通过，拒绝启动：" + "；".join(problems)
        )


def tenant_of_user(db: Session, user: User) -> TenantContext:
    """服务内部构造上下文（后台任务/脚本使用，无 HTTP 请求）。"""
    org_id = user.organization_id or _default_org_id(db)
    force_store = (user.role or "staff") == "staff"
    return TenantContext(
        organization_id=org_id,
        store_id=user.store_id if force_store else None,
        role=user.role or "staff",
        actor_type="staff",
        actor_id=user.user_id,
        source="jwt",
        force_store_scope=force_store,
    )