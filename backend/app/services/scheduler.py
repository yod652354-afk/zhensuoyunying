"""每日自动任务调度：按配置时间定时生成 Recovery + Retention 任务（APScheduler）。

配置（.env）：TASK_SCHEDULE_ENABLED / TASK_SCHEDULE_HOUR / TASK_SCHEDULE_MINUTE
每次运行记录 task.daily_generated 事件，可在事件流/投递日志中审计。
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from ..config import get_settings
from ..core.enums import ActorType
from ..database import SessionLocal
from ..events.bus import emit

logger = logging.getLogger("clinicos.scheduler")

_scheduler: BackgroundScheduler | None = None


def run_daily_tasks() -> dict:
    """每日自动运营链（R-02：统一 Opportunity→仲裁→方案→待审核，禁止旧 Task 绕过）。

    数据同步/补偿 → Customer State 重算 → Detectors → 机会去重/过期 → 仲裁 →
    Decision → ExecutionPlan 候选 → AI 内容与自动检查 → 待人工审核。
    每个组织/门店分别运行；单租户失败不阻断其他租户。
    """
    settings = get_settings()
    result: dict = {"orgs_processed": 0, "stores_processed": 0, "per_org": {}}
    with SessionLocal() as db:
        from ..models import Organization, Store

        orgs = db.scalars(
            select(Organization).where(Organization.deleted_at.is_(None))
            .order_by(Organization.created_at.asc())
        ).all()
        for org in orgs:
            stores = db.scalars(
                select(Store).where(
                    Store.organization_id == org.organization_id,
                    Store.deleted_at.is_(None),
                )
            ).all()
            store_ids = [s.store_id for s in stores] or [None]
            org_result: dict = {"stores": {}}
            for sid in store_ids:
                try:
                    org_result["stores"][sid or "all"] = _run_org_ops(db, org.organization_id, sid)
                    result["stores_processed"] += 1
                except Exception as exc:  # noqa: BLE001  单租户失败不阻断
                    org_result["stores"][sid or "all"] = {"error": f"{type(exc).__name__}: {exc}"}
                    logger.exception("[调度] 组织 %s 门店 %s 运营链失败", org.organization_id, sid)
            result["per_org"][org.organization_id] = org_result
            result["orgs_processed"] += 1

        try:
            from ..models import Organization as _Org
            first = db.scalar(select(_Org).limit(1))
            if first:
                emit(
                    db, "task.daily_generated", first.organization_id, "task", "daily",
                    payload={"orgs_processed": result["orgs_processed"],
                             "stores_processed": result["stores_processed"]},
                    actor_type=ActorType.SYSTEM,
                )
        except Exception:  # noqa: BLE001
            pass
        db.commit()
    logger.info("[调度] 每日运营链完成: %s", result)
    return result


def _run_org_ops(db: Session, org_id: str, store_id: str | None) -> dict:
    """单组织单门店运营链（R-02）。"""
    from .revos import customer_state as revos_state
    from .revos import decision as revos_decision
    from .revos import execution_plan as revos_plan
    from .revos import opportunity as revos_opportunity
    from .revos import arbitration as revos_arbitration
    from .revos import content_provider as revos_content
    from .revos import compliance_check as revos_compliance
    from .revos.opportunity import expire_opportunities

    out: dict = {"customers_created": 0, "state_transitions": 0,
                 "opportunities": 0, "plans_pending_review": 0}

    # 1) 客户档案与状态重算
    out["customers_created"] = revos_state.ensure_all_customers(db, org_id=org_id, store_id=store_id)
    out["state_transitions"] = revos_state.recompute_all(db, store_id=store_id, org_id=org_id)

    # 2) 机会检测（三种钱 Detectors）
    detection = revos_opportunity.run_detection(db, store_id=store_id, org_id=org_id)
    out["opportunities"] = detection["created"]
    out["opportunities_expired"] = expire_opportunities(db)

    # 3) 为候选机会生成待审核 ExecutionPlan（对照组跳过；只生成不审核）
    plans_created = 0
    opps = revos_opportunity.list_opportunities(
        db, _TenantScope(org_id, store_id),
        status="candidate", limit=50,
    )
    for opp in opps:
        try:
            if opp.experiment_group == "control":
                continue  # 对照组不生成内容/方案
            # 仲裁（同客户多机会 → 主机会）
            arbitration = revos_arbitration.arbitrate_customer(db, opp.customer_id)
            if arbitration.primary is None or arbitration.primary.opportunity_id != opp.opportunity_id:
                continue  # 非主机会延后/抑制
            # 决策 → 方案 → 内容 → 机器检查 → 待人工审核
            output = revos_decision.decide(db, opp)
            if not output.execute:
                continue
            decision = revos_decision.persist_decision(db, opp, output)
            plan = revos_plan.create_plan(db, opp, decision)
            draft = revos_content.generate_content(db, opp, plan.execution_plan_id, actor="scheduler")
            revos_compliance.run_machine_check(db, draft, opp, plan.execution_plan_id)
            revos_plan.set_machine_checked(db, plan, {"source": "daily_ops"})
            revos_plan.submit_for_review(db, plan)
            plans_created += 1
        except Exception:  # noqa: BLE001  单机会失败不影响其他
            logger.exception("[调度] 机会 %s 方案生成失败", opp.opportunity_id)
    out["plans_pending_review"] = plans_created
    db.commit()
    return out


class _TenantScope:
    """调度内部租户作用域（无 HTTP 请求）。"""

    def __init__(self, org_id: str, store_id: str | None):
        self.organization_id = org_id
        self.store_id = store_id
        self.force_store_scope = bool(store_id)

    def scope_query(self, query, model):
        query = query.where(model.organization_id == self.organization_id)
        if self.force_store_scope and self.store_id:
            query = query.where(model.store_id == self.store_id)
        return query

    def ensure_scope(self, entity):
        if getattr(entity, "organization_id", None) != self.organization_id:
            from ..core.errors import ClinicOSError
            raise ClinicOSError("FORBIDDEN", "无权访问其他组织数据", status_code=403, retryable=False)
        if self.force_store_scope and self.store_id:
            store = getattr(entity, "store_id", None)
            if store is not None and store != self.store_id:
                from ..core.errors import ClinicOSError
                raise ClinicOSError("FORBIDDEN", "无权访问其他门店数据", status_code=403, retryable=False)

    def require_role(self, *roles):
        pass


def start_scheduler() -> None:
    """应用启动时调用：注册每日 cron 任务。"""
    global _scheduler
    settings = get_settings()
    if not settings.task_schedule_enabled:
        logger.info("[调度] 每日自动任务未启用（TASK_SCHEDULE_ENABLED=false）")
        return
    if _scheduler is not None:
        return
    _scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    _scheduler.add_job(
        run_daily_tasks,
        CronTrigger(hour=settings.task_schedule_hour,
                    minute=settings.task_schedule_minute,
                    timezone="Asia/Shanghai"),
        id="clinicos_daily_tasks",
        name="每日经营任务生成",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("[调度] 每日任务已注册：%02d:%02d（Recovery 上限 %d 条）",
                settings.task_schedule_hour, settings.task_schedule_minute,
                settings.task_daily_recovery_limit)


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None