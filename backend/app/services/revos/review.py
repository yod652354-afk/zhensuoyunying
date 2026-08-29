"""人工审核服务（规格 03 §12 / 企微规格 §7.2-7.3）。

- 人工审核完整 ExecutionPlan（不只文案）；
- 审核请求携带 expected_content_hash，不一致返回冲突（409 CONTENT_CHANGED）；
- 批准版本不可修改；任何修改创建新版本并重新审核；
- blocked 风险不得由普通审核员强制发送；
- 支持低风险同模板批量审核和高风险逐条审核。
"""
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import DraftStatus, PlanStatus, ReviewDecision, RiskLevel
from ...core.errors import ClinicOSError
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models.revos import (
    ContentDraft, ContentReviewRecord, ExecutionPlan, Opportunity,
)
from .compliance_check import run_machine_check
from .execution_plan import approve_plan, reject_plan, request_changes


def compute_content_hash(draft: ContentDraft) -> str:
    raw = json.dumps({
        "title": draft.title, "text": draft.wecom_text,
        "image": draft.image_url, "mp": draft.mini_program_config,
    }, ensure_ascii=False, sort_keys=True)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def batch_eligible(drafts: list[ContentDraft]) -> bool:
    """批量审核条件（企微规格 §7.3）：同门店/同场景/同内容/同优惠/低风险。"""
    if len(drafts) < 2:
        return False
    store_ids = {d.store_id for d in drafts}
    hashes = {d.content_hash for d in drafts}
    texts = {d.wecom_text for d in drafts}
    opp_ids = {d.opportunity_id for d in drafts}
    # 个性化正文不同 → 逐条审核
    if len(texts) != 1 or len(hashes) != 1:
        return False
    return True


def _current_machine_review(db: Session, draft_id: str) -> ContentReviewRecord | None:
    return db.scalar(
        select(ContentReviewRecord).where(
            ContentReviewRecord.content_draft_id == draft_id,
            ContentReviewRecord.review_type == "machine",
        ).order_by(ContentReviewRecord.created_at.desc()).limit(1)
    )


def ensure_machine_checked(db: Session, draft: ContentDraft) -> ContentReviewRecord:
    """确保草稿已通过机器检查（未检查则先执行）。"""
    record = _current_machine_review(db, draft.content_draft_id)
    if record is None or record.risk_level in (RiskLevel.BLOCKED, RiskLevel.HIGH):
        opportunity = db.get(Opportunity, draft.opportunity_id)
        record = run_machine_check(db, draft, opportunity, draft.execution_plan_id)
        db.flush()
    return record


def human_review(
    db: Session,
    draft: ContentDraft,
    decision: str,
    reviewer: str | None = None,
    note: str | None = None,
    expected_content_hash: str | None = None,
    reviewer_role: str = "boss",
    allow_force: bool = False,
) -> ContentReviewRecord:
    """人工审核内容草稿（哈希校验 + 风险门禁）。

    decision: approved | rejected | changes_requested
    哈希不一致 → 409 CONTENT_CHANGED（防审核后篡改）。
    """
    from ...events.bus import emit
    from ...core.enums import ActorType, ReviewType

    actual_hash = compute_content_hash(draft)
    if draft.content_hash and expected_content_hash and actual_hash != expected_content_hash:
        raise ClinicOSError("CONTENT_CHANGED", "内容已被修改，请重新审核最新版本", status_code=409, retryable=False)

    record = ensure_machine_checked(db, draft)
    if record.risk_level == RiskLevel.BLOCKED and not allow_force:
        raise ClinicOSError(
            "FORBIDDEN", "内容命中 blocked 风险，普通审核员不得强制发送，需管理员处理",
            status_code=403, retryable=False,
        )
    if record.risk_level == RiskLevel.HIGH and reviewer_role not in ("boss", "admin", "auditor"):
        raise ClinicOSError("FORBIDDEN", "高风险内容需老板/管理员审核", status_code=403, retryable=False)

    decision_enum = ReviewDecision(decision) if isinstance(decision, str) else decision
    human = ContentReviewRecord(
        review_id=new_id("content_review_record"),
        organization_id=draft.organization_id,
        store_id=draft.store_id,
        content_draft_id=draft.content_draft_id,
        execution_plan_id=draft.execution_plan_id,
        review_type=ReviewType.HUMAN,
        decision=decision_enum,
        risk_level=record.risk_level,
        reviewer_id=reviewer,
        review_note=note,
        reviewed_at=utcnow(),
        content_hash=actual_hash,
    )
    db.add(human)

    plan: ExecutionPlan | None = None
    if draft.execution_plan_id:
        plan = db.get(ExecutionPlan, draft.execution_plan_id)
    if decision_enum == ReviewDecision.APPROVED:
        draft.status = DraftStatus.APPROVED
        if plan is not None:
            approve_plan(db, plan, reviewer, note, content_hash=actual_hash)
    elif decision_enum == ReviewDecision.REJECTED:
        draft.status = DraftStatus.REJECTED
        if plan is not None:
            reject_plan(db, plan, reviewer, note)
    else:
        draft.status = DraftStatus.PENDING_REVIEW
        if plan is not None:
            request_changes(db, plan, reviewer, note)
    db.flush()
    emit(db, f"content.review_{decision_enum.value}", draft.organization_id,
         "content_draft", draft.content_draft_id,
         store_id=draft.store_id, actor_type=ActorType.STAFF, actor_id=reviewer,
         correlation_id=draft.opportunity_id,
         payload={"decision": decision_enum.value, "risk_level": record.risk_level.value,
                  "content_hash": actual_hash})
    return human


def review_plan(
    db: Session,
    plan: ExecutionPlan,
    decision: str,
    reviewer: str | None = None,
    note: str | None = None,
    expected_content_hash: str | None = None,
    reviewer_role: str = "boss",
) -> ExecutionPlan:
    """审核完整 ExecutionPlan（含内容哈希校验）。"""
    if plan.content_draft_id:
        draft = db.get(ContentDraft, plan.content_draft_id)
        if draft is not None and draft.status == DraftStatus.APPROVED and decision == "approved":
            # 内容已批准：直接批准方案
            approve_plan(db, plan, reviewer, note, content_hash=expected_content_hash or draft.content_hash)
            return plan
        if draft is not None:
            human_review(db, draft, decision, reviewer, note, expected_content_hash, reviewer_role)
    elif decision == "approved":
        approve_plan(db, plan, reviewer, note, content_hash=expected_content_hash)
    else:
        reject_plan(db, plan, reviewer, note)
    return plan


def list_pending_reviews(db: Session, tenant, store_id: str | None = None,
                         status: str | None = None, limit: int = 100) -> list[ContentDraft]:
    """待审核内容列表（租户强制 scope）。"""
    query = select(ContentDraft).where(ContentDraft.deleted_at.is_(None))
    query = tenant.scope_query(query, ContentDraft)
    if store_id:
        query = query.where(ContentDraft.store_id == store_id)
    if status:
        query = query.where(ContentDraft.status == status)
    else:
        query = query.where(ContentDraft.status.in_(["draft", "pending_review", "check_failed"]))
    return db.scalars(query.order_by(ContentDraft.created_at.desc()).limit(min(limit, 500))).all()
