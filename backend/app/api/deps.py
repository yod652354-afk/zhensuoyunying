"""公共依赖：请求ID中间件、数据库会话、列表查询参数。"""
import uuid
from typing import Optional

from fastapi import Depends, Query, Request

from ..core.pagination import coerce_datetime


async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:12]}"
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Trace-Id"] = request.state.request_id
    return response


# 统一列表查询参数（需求规格 5.4）：时间增量 + 游标 + 各实体过滤字段
class ListParams:
    def __init__(
        self,
        organization_id: Optional[str] = Query(default=None),
        store_id: Optional[str] = Query(default=None),
        patient_id: Optional[str] = Query(default=None),
        doctor_id: Optional[str] = Query(default=None),
        staff_id: Optional[str] = Query(default=None),
        status: Optional[str] = Query(default=None),
        review_status: Optional[str] = Query(default=None),
        name: Optional[str] = Query(default=None, description='名称模糊搜索'),
        # 各实体附加过滤
        stage: Optional[str] = Query(default=None),
        dnc: Optional[bool] = Query(default=None),
        primary_doctor_id: Optional[str] = Query(default=None),
        source_type: Optional[str] = Query(default=None),
        category: Optional[str] = Query(default=None),
        visit_type: Optional[str] = Query(default=None),
        order_id: Optional[str] = Query(default=None),
        campaign_id: Optional[str] = Query(default=None),
        task_id: Optional[str] = Query(default=None),
        followup_id: Optional[str] = Query(default=None),
        package_instance_id: Optional[str] = Query(default=None),
        experiment_id: Optional[str] = Query(default=None),
        experiment_group: Optional[str] = Query(default=None),
        reason: Optional[str] = Query(default=None),
        task_type: Optional[str] = Query(default=None),
        assigned_to_id: Optional[str] = Query(default=None),
        event_type: Optional[str] = Query(default=None),
        complaint_flag: Optional[bool] = Query(default=None),
        engine: Optional[str] = Query(default=None),
        type: Optional[str] = Query(default=None),
        # 增量与分页
        created_since: Optional[str] = Query(default=None, description="创建时间增量（ISO 8601）"),
        created_until: Optional[str] = Query(default=None),
        updated_since: Optional[str] = Query(default=None, description="更新时间增量（ISO 8601）"),
        updated_until: Optional[str] = Query(default=None),
        cursor: Optional[str] = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
        include_deleted: bool = Query(default=False),
    ):
        self.organization_id = organization_id
        self.store_id = store_id
        self.patient_id = patient_id
        self.doctor_id = doctor_id
        self.staff_id = staff_id
        self.status = status
        self.review_status = review_status
        self.name = name
        self.stage = stage
        self.dnc = dnc
        self.primary_doctor_id = primary_doctor_id
        self.source_type = source_type
        self.category = category
        self.visit_type = visit_type
        self.order_id = order_id
        self.campaign_id = campaign_id
        self.task_id = task_id
        self.followup_id = followup_id
        self.package_instance_id = package_instance_id
        self.experiment_id = experiment_id
        self.experiment_group = experiment_group
        self.reason = reason
        self.task_type = task_type
        self.assigned_to_id = assigned_to_id
        self.event_type = event_type
        self.complaint_flag = complaint_flag
        self.engine = engine
        self.type = type
        self.created_since = coerce_datetime(created_since, "created_since")
        self.created_until = coerce_datetime(created_until, "created_until")
        self.updated_since = coerce_datetime(updated_since, "updated_since")
        self.updated_until = coerce_datetime(updated_until, "updated_until")
        self.cursor = cursor
        self.limit = limit
        self.include_deleted = include_deleted


def get_list_params(params: ListParams = Depends()) -> ListParams:
    return params