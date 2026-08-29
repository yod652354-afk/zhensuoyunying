"""经营分析端点：驱动运营后台前端（老板驾驶舱 / Recovery 池 / Retention 漏斗 / 质量 / 实验）。

安全（RevOS P0）：所有分析强制服务端租户 scope，客户端 store_id 不得扩大权限。
"""
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...services.attribution import all_experiments_metrics, experiment_metrics
from ...services.dashboard import dashboard
from ...services.quality import store_quality_report
from ...services.recovery import generate_recovery_tasks, recovery_pool
from ...services.retention import due_today_revisits, overdue_revisits, retention_funnel

router = APIRouter(tags=["Analytics"])


def _store_ok(tenant: TenantContext, store_id: str | None) -> str | None:
    """员工强制门店：传入其他门店 store_id 直接拒绝。"""
    if tenant.force_store_scope and tenant.store_id and store_id and store_id != tenant.store_id:
        raise ClinicOSError("FORBIDDEN", "无权查看其他门店数据", status_code=403, retryable=False)
    return store_id


@router.get("/analytics/dashboard", summary="老板经营驾驶舱")
def get_dashboard(request: Request, store_id: str | None = Query(default=None),
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": dashboard(db, sid, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/recovery-pool", summary="Recovery 客户池")
def get_recovery_pool(request: Request, store_id: str | None = Query(default=None),
                      tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": recovery_pool(db, sid, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.post("/analytics/recovery-pool/tasks", summary="由 Recovery 池生成今日任务（兼容入口：已转为统一机会流程）")
def create_recovery_tasks(request: Request, store_id: str | None = Query(default=None),
                          limit: int = Query(default=50),
                          tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    """兼容入口：不再直接创建旧式 Recovery Task，转为统一 Opportunity 流程（R-02）。"""
    from ...events.bus import emit
    from ...core.enums import ActorType
    from ...services.revos.opportunity import run_detection

    sid = _store_ok(tenant, store_id)
    result = run_detection(db, sid, org_id=tenant.organization_id, scenario="dormant_recovery")
    emit(db, "task.daily_generated", tenant.organization_id, "task", "pool_compat",
         store_id=sid, actor_type=ActorType.AI,
         payload={"converted_to_opportunity": True, "opportunities_created": result["created"]})
    db.commit()
    return {"data": {"converted_to_opportunity": True,
                     "note": "已转为统一 Opportunity 流程（R-02），不再直接创建旧式 Task",
                     "opportunities_created": result["created"]},
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/retention-funnel", summary="Retention 过程漏斗")
def get_funnel(request: Request, store_id: str | None = Query(default=None),
               days: int = Query(default=90),
               tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": retention_funnel(db, sid, days, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/retention/overdue", summary="超期复诊预警")
def get_overdue(request: Request, store_id: str | None = Query(default=None),
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": overdue_revisits(db, sid, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/retention/due-today", summary="今日应复诊")
def get_due_today(request: Request, store_id: str | None = Query(default=None),
                  tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": due_today_revisits(db, sid, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/quality", summary="数据质量评分")
def get_quality(request: Request, store_id: str | None = Query(default=None),
                tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    sid = _store_ok(tenant, store_id)
    return {"data": store_quality_report(db, sid, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/experiments/{experiment_id}/metrics", summary="实验增量指标")
def get_experiment_metrics(experiment_id: str, request: Request,
                           tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    from ...models import Experiment
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        raise ClinicOSError("NOT_FOUND", "实验不存在", status_code=404)
    tenant.ensure_scope(exp)
    result = experiment_metrics(db, experiment_id)
    if "error" in result:
        raise ClinicOSError("NOT_FOUND", result["error"], status_code=404)
    return {"data": result, "meta": {"request_id": request.state.request_id}}


@router.get("/analytics/experiments/summary", summary="全部实验指标汇总")
def get_experiments_summary(request: Request,
                            tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    return {"data": all_experiments_metrics(db, org_id=tenant.organization_id),
            "meta": {"request_id": request.state.request_id}}
