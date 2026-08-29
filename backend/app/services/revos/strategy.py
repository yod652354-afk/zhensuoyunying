"""Strategy Registry / Learning Engine（规格 03 §16 / 总体规格 §15）。

- 版本化 detector / scoring / decision / workflow / psychology / prompt / model /
  content / channel / timing；
- 状态机：draft → offline_validated → shadow → experiment → limited_release →
  active → retired/rolled_back；
- 影子模式：只输出建议，不创建 Task/Touch/优惠/任何外部动作；
- A/B/Holdout、小流量放量、护栏（DNC/投诉/成本）、自动暂停与回滚；
- 未经批准不得自动修改合规和生产策略；
- 样本不足只标记方向性信号。
"""
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...core.enums import StrategyCategory, StrategyStatus
from ...core.errors import ClinicOSError
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models.revos import StrategyPerformance, StrategyVersion

# 状态流转白名单
ALLOWED_TRANSITIONS: dict[str, list[str]] = {
    StrategyStatus.DRAFT.value: [StrategyStatus.OFFLINE_VALIDATED.value],
    StrategyStatus.OFFLINE_VALIDATED.value: [StrategyStatus.SHADOW.value, StrategyStatus.RETIRED.value],
    StrategyStatus.SHADOW.value: [StrategyStatus.EXPERIMENT.value, StrategyStatus.RETIRED.value],
    StrategyStatus.EXPERIMENT.value: [StrategyStatus.LIMITED_RELEASE.value, StrategyStatus.ROLLED_BACK.value],
    StrategyStatus.LIMITED_RELEASE.value: [StrategyStatus.ACTIVE.value, StrategyStatus.ROLLED_BACK.value],
    StrategyStatus.ACTIVE.value: [StrategyStatus.RETIRED.value, StrategyStatus.ROLLED_BACK.value],
}

# 硬性护栏：不可自动修改的策略类别（合规规则）
GUARDED_CATEGORIES = {StrategyCategory.DETECTOR_RULE.value, StrategyCategory.DECISION_POLICY.value,
                      StrategyCategory.CHANNEL_POLICY.value}


def _hash_definition(definition: dict) -> str:
    raw = json.dumps(definition, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def register_strategy(
    db: Session,
    category: str,
    code: str,
    definition: dict,
    owner: str | None = None,
    change_reason: str | None = None,
    organization_id: str | None = None,
) -> StrategyVersion:
    """注册策略新版本（version 自动递增；definition 不可变哈希）。"""
    last = db.scalar(
        select(StrategyVersion).where(
            StrategyVersion.category == category,
            StrategyVersion.code == code,
        ).order_by(StrategyVersion.version.desc()).limit(1)
    )
    version = (last.version + 1) if last else 1
    sv = StrategyVersion(
        strategy_version_id=new_id("strategy_version"),
        organization_id=organization_id or "",
        category=category,
        code=code,
        version=version,
        status=StrategyStatus.DRAFT,
        definition=definition,
        owner=owner,
        change_reason=change_reason,
        content_hash=_hash_definition(definition),
        rollback_version=last.version if last else None,
    )
    db.add(sv)
    db.commit()
    return sv


def transition(db: Session, strategy_version_id: str, target: str,
               approver: str | None = None, reason: str | None = None) -> StrategyVersion:
    """状态流转（自动暂停/回滚场景由护栏调用，其他流转需人工批准）。"""
    sv = db.get(StrategyVersion, strategy_version_id)
    if sv is None:
        raise ClinicOSError("NOT_FOUND", "策略版本不存在", status_code=404)
    allowed = ALLOWED_TRANSITIONS.get(sv.status.value, [])
    if target not in allowed:
        raise ClinicOSError("INVALID_STATE", f"不允许从 {sv.status.value} 流转到 {target}",
                            status_code=409, retryable=False)
    if sv.category in GUARDED_CATEGORIES and target in (
        StrategyStatus.ACTIVE.value, StrategyStatus.LIMITED_RELEASE.value):
        # 合规/决策/渠道策略进入生产前必须人工批准
        if not approver:
            raise ClinicOSError("FORBIDDEN", "受护栏保护策略的生产发布必须人工批准",
                                status_code=403, retryable=False)
        sv.approval_record = {"approver": approver, "at": utcnow().isoformat(), "reason": reason}
    from ...events.bus import emit
    from ...core.enums import ActorType
    emit(db, f"strategy.{target}", sv.organization_id, "strategy_version", sv.strategy_version_id,
         actor_type=ActorType.STAFF if approver else ActorType.AI, actor_id=approver,
         correlation_id=sv.strategy_version_id,
         payload={"category": sv.category, "code": sv.code, "version": sv.version,
                  "from": sv.status.value, "to": target})
    sv.status = StrategyStatus(target)  # 显式转枚举，避免内存中残留原始字符串
    if target == StrategyStatus.ACTIVE.value:
        sv.effective_from = utcnow()
    db.commit()
    return sv


def rollback(db: Session, strategy_version_id: str, reason: str,
             actor: str | None = None) -> StrategyVersion | None:
    """回滚：当前版本置为 rolled_back；恢复 rollback_version 为 active（若有）。"""
    sv = db.get(StrategyVersion, strategy_version_id)
    if sv is None:
        return None
    sv.status = StrategyStatus.ROLLED_BACK
    sv.change_reason = f"回滚: {reason}"
    db.commit()
    from ...events.bus import emit
    from ...core.enums import ActorType
    emit(db, "strategy.rolled_back", sv.organization_id, "strategy_version", sv.strategy_version_id,
         actor_type=ActorType.STAFF if actor else ActorType.AI, actor_id=actor,
         correlation_id=sv.strategy_version_id,
         payload={"category": sv.category, "code": sv.code, "version": sv.version, "reason": reason})
    db.commit()
    if sv.rollback_version:
        previous = db.scalar(
            select(StrategyVersion).where(
                StrategyVersion.category == sv.category,
                StrategyVersion.code == sv.code,
                StrategyVersion.version == sv.rollback_version,
            ).limit(1)
        )
        if previous and previous.status != StrategyStatus.ACTIVE:
            previous.status = StrategyStatus.ACTIVE
            previous.effective_from = utcnow()
            db.commit()
    return sv


def pause(db: Session, strategy_version_id: str, reason: str, actor: str | None = None) -> StrategyVersion:
    """自动暂停（护栏触发：DNC/投诉超过阈值等）。"""
    return transition(db, strategy_version_id, StrategyStatus.RETIRED.value,
                      approver=actor, reason=f"自动暂停: {reason}")


def active_versions(db: Session, category: str | None = None,
                    code: str | None = None) -> list[StrategyVersion]:
    query = select(StrategyVersion).where(
        StrategyVersion.status == StrategyStatus.ACTIVE.value
    )
    if category:
        query = query.where(StrategyVersion.category == category)
    if code:
        query = query.where(StrategyVersion.code == code)
    return db.scalars(query).all()


def record_performance(db: Session, performance: StrategyPerformance) -> None:
    db.add(performance)
    db.commit()


def evaluate_guardrails(db: Session, strategy_code: str | None = None,
                        window_days: int = 30) -> list[dict]:
    """护栏评估：DNC/投诉超阈值 → 自动暂停建议（需人工执行或批准）。"""
    from datetime import timedelta

    since = utcnow() - timedelta(days=window_days)
    query = select(StrategyPerformance).where(StrategyPerformance.created_at >= since)
    if strategy_code:
        query = query.where(StrategyPerformance.strategy_code == strategy_code)
    rows = db.scalars(query).all()
    alerts: list[dict] = []
    for perf in rows:
        metrics = perf.metrics or {}
        dnc = metrics.get("dnc_treatment", 0)
        complaint = metrics.get("complaint_treatment", 0)
        sample = perf.sample_size or 0
        if sample >= 10 and (dnc / sample > 0.05 or complaint / sample > 0.02):
            alerts.append({
                "performance_id": perf.performance_id,
                "strategy_code": perf.strategy_code,
                "sample_size": sample,
                "dnc": dnc, "complaint": complaint,
                "alert": "DNC/投诉超阈值，建议暂停或回滚",
                "auto_paused": False,  # 自动建议；生产策略需人工批准
            })
    return alerts


def list_versions(db: Session, tenant, category: str | None = None,
                  code: str | None = None, status: str | None = None,
                  limit: int = 100) -> list[StrategyVersion]:
    query = select(StrategyVersion)
    query = tenant.scope_query(query, StrategyVersion)
    if category:
        query = query.where(StrategyVersion.category == category)
    if code:
        query = query.where(StrategyVersion.code == code)
    if status:
        query = query.where(StrategyVersion.status == status)
    return db.scalars(query.order_by(StrategyVersion.created_at.desc()).limit(min(limit, 500))).all()
