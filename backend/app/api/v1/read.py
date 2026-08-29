"""Read API：实体注册表驱动的列表/详情端点（需求规格 5.2）。

统一特性：cursor 分页、created_since/updated_since 增量、include_deleted、统一响应包络。
安全：所有列表/详情强制服务端租户 scope（RevOS P0 修复），禁止客户端扩大权限。
注意：模型对象通过闭包捕获而非函数默认参数（避免 FastAPI deepcopy 序列化类对象）。
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from ...core.errors import ClinicOSError
from ...core.pagination import apply_incremental_filters, paginate
from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...schemas.common import build_response_model
from ..deps import ListParams, get_list_params
from .registry import ENTITIES, EntitySpec

router = APIRouter(tags=["Read API"])


def _to_api(resp_model, row) -> dict:
    """模型行 → JSON 兼容字典（枚举转值、时间转 ISO、金额转浮点）。"""
    return resp_model.model_validate(row).model_dump(mode="json")


def _make_list_endpoint(spec: EntitySpec):
    model = spec.model
    pk_attr = getattr(model, spec.pk)
    created_attr = getattr(model, "created_at")
    updated_attr = getattr(model, "updated_at")
    resp_model = build_response_model(model, f"{model.__name__}Out")

    async def list_endpoint(
        params: ListParams = Depends(get_list_params),
        request: Request = None,
        db=Depends(get_db),
        tenant: TenantContext = Depends(get_tenant),
    ):
        query = select(model)
        # 服务端强制租户 scope（员工强制 store）
        query = tenant.scope_query(query, model)
        for param, attr in spec.filters.items():
            value = getattr(params, param, None)
            if value is not None and hasattr(model, attr):
                query = query.where(getattr(model, attr) == value)
        name_q = getattr(params, "name", None)
        if name_q and hasattr(model, "name"):
            query = query.where(model.name.ilike(f"%{name_q}%"))
        query = apply_incremental_filters(
            query, model, pk_attr, updated_attr, created_attr,
            params.created_since, params.created_until,
            params.updated_since, params.updated_until,
            params.include_deleted,
        )
        rows, next_cursor = paginate(db, query, model, pk_attr, updated_attr, params.cursor, params.limit)
        data = [_to_api(resp_model, r) for r in rows]
        total = None
        if params.cursor is None:
            total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
        return {
            "data": data,
            "meta": {
                "next_cursor": next_cursor,
                "has_more": next_cursor is not None,
                "total": total,
                "request_id": request.state.request_id if request else None,
            },
        }

    return list_endpoint


def _make_detail_endpoint(spec: EntitySpec):
    model = spec.model
    pk_attr = getattr(model, spec.pk)
    resp_model = build_response_model(model, f"{model.__name__}Detail")

    async def detail_endpoint(
        entity_id: str,
        request: Request = None,
        db=Depends(get_db),
        include_deleted: bool = Query(default=False),
        tenant: TenantContext = Depends(get_tenant),
    ):
        query = select(model).where(pk_attr == entity_id)
        # 服务端强制租户 scope：跨租户按 ID 直读一律拒绝
        query = tenant.scope_query(query, model)
        if not include_deleted and hasattr(model, "deleted_at"):
            query = query.where(model.deleted_at.is_(None))
        row = db.scalar(query)
        if row is None:
            raise ClinicOSError("NOT_FOUND", f"{spec.summary}中不存在 id={entity_id}", status_code=404)
        return {
            "data": _to_api(resp_model, row),
            "meta": {"request_id": request.state.request_id if request else None},
        }

    return detail_endpoint


for _spec in ENTITIES:
    router.add_api_route(
        f"/{_spec.route}", _make_list_endpoint(_spec), methods=["GET"],
        summary=f"列表 {_spec.summary}", name=f"list_{_spec.route.replace('-', '_')}",
    )
    router.add_api_route(
        f"/{_spec.route}/{{entity_id}}", _make_detail_endpoint(_spec), methods=["GET"],
        summary=f"详情 {_spec.summary}", name=f"get_{_spec.route.replace('-', '_')}",
    )