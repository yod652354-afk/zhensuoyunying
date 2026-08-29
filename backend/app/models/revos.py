"""RevOS 领域模型（ClinicOS → RevOS 兼容升级，规格 02 / 03 / 总体规格 §7）。

主链路：
Customer → CustomerStateHistory → Opportunity → Decision → ExecutionPlan
→ Review → Action/Touch/Task → Outcome → Attribution → StrategyPerformance

约束：
- 不删除旧表旧数据；Task/Touch/Attribution 通过 nullable 外键兼容旧数据；
- 手机号等身份加密存储（encrypted_value），匹配用独立哈希（value_hash）；
- 学习快照只保存脱敏特征，不复制完整敏感内容。
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, Boolean, DateTime, Enum, Index, Integer, Numeric, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..core.enums import (
    ActionStatus, ActionType, DraftStatus, IdentityType, LifecycleState,
    MoneyState, MoneyType, OpportunityScenario, OpportunityStatus, OutcomeType,
    PlanStatus, PsychologyStrategy, ReviewDecision, ReviewType, RiskLevel,
    SessionStatus, StrategyCategory, StrategyStatus, ValueTier,
    WorkflowDefinitionStatus, WorkflowInstanceStatus,
)
from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin, TimestampMixin


class Customer(CommonMixin, Base):
    """RevOS 统一客户经营档案（诊所SaaS仍是事实主系统，本表为经营聚合视图）。"""

    __tablename__ = "customers"

    customer_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("customer"))
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # 当前经营状态（历史见 customer_state_history）
    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        Enum(LifecycleState, native_enum=False, length=16), nullable=False, default=LifecycleState.LEAD
    )
    money_state: Mapped[MoneyState] = mapped_column(
        Enum(MoneyState, native_enum=False, length=8), nullable=False, default=MoneyState.FUTURE
    )
    value_tier: Mapped[ValueTier] = mapped_column(
        Enum(ValueTier, native_enum=False, length=2), nullable=False, default=ValueTier.C
    )
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state_reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    state_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 合规基线（与 Patient 同步）
    consent_status: Mapped[str | None] = mapped_column(String(16), nullable=True, default="unknown")
    dnc: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    complaint_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contact_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 经营指标快照
    total_visits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_revenue: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    last_visit_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_touch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerIdentity(CommonMixin, Base):
    """有作用域、可变的客户身份（手机号不是永久主键）。"""

    __tablename__ = "customer_identities"

    __table_args__ = (
        # R-05：同一组织/类型/哈希/作用域只允许一个有效身份（valid_to 为空）
        Index("uq_customer_identities_active",
              "organization_id", "identity_type", "value_hash", "app_scope",
              unique=True,
              sqlite_where=text("valid_to IS NULL"),
              postgresql_where=text("valid_to IS NULL")),
    )

    identity_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("identity"))
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    identity_type: Mapped[IdentityType] = mapped_column(
        Enum(IdentityType, native_enum=False, length=24), nullable=False, index=True
    )
    encrypted_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # 加密存储（Fernet 等）
    value_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # 匹配哈希
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)  # wecom/wechat/other
    app_scope: Mapped[str | None] = mapped_column(String(128), nullable=True)  # corp_id/app_id 作用域
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CustomerStateHistory(CommonMixin, Base):
    """客户状态迁移历史（不可变，只追加）。"""

    __tablename__ = "customer_state_history"

    state_history_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("state"))
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    lifecycle_from: Mapped[str | None] = mapped_column(String(16), nullable=True)
    lifecycle_to: Mapped[LifecycleState] = mapped_column(
        Enum(LifecycleState, native_enum=False, length=16), nullable=False
    )
    money_from: Mapped[str | None] = mapped_column(String(8), nullable=True)
    money_to: Mapped[MoneyState] = mapped_column(
        Enum(MoneyState, native_enum=False, length=8), nullable=False
    )
    value_tier: Mapped[ValueTier] = mapped_column(
        Enum(ValueTier, native_enum=False, length=2), nullable=False, default=ValueTier.C
    )
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger_event_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    rule_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 脱敏上下文快照


class Opportunity(CommonMixin, Base):
    """统一经营机会（三种钱分类，不是客户唯一标签）。"""

    __tablename__ = "opportunities"

    __table_args__ = (
        # R-05：同客户同场景同时只允许一个活动机会（部分唯一索引；枚举列存 name 大写）
        Index("uq_opportunities_active_scenario", "organization_id", "customer_id", "scenario_type",
              unique=True,
              sqlite_where=text("lower(status) IN ('candidate','qualified','approved','executing')"),
              postgresql_where=text("lower(status) IN ('candidate','qualified','approved','executing')")),
    )

    opportunity_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("opportunity"))
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    money_type: Mapped[MoneyType] = mapped_column(
        Enum(MoneyType, native_enum=False, length=8), nullable=False, index=True
    )
    scenario_type: Mapped[OpportunityScenario] = mapped_column(
        Enum(OpportunityScenario, native_enum=False, length=32), nullable=False, index=True
    )
    lifecycle_state: Mapped[LifecycleState] = mapped_column(
        Enum(LifecycleState, native_enum=False, length=16), nullable=False, default=LifecycleState.LEAD
    )
    status: Mapped[OpportunityStatus] = mapped_column(
        Enum(OpportunityStatus, native_enum=False, length=16), nullable=False, default=OpportunityStatus.CANDIDATE, index=True
    )
    priority_score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    expected_revenue: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    probability: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    expected_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 产生机会时的最小化快照
    detector_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scoring_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    workflow_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    experiment_group: Mapped[str | None] = mapped_column(String(16), nullable=True)  # control/treatment_a/...
    owner_staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    suppressed_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    suppressed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    suppressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    won_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 影子机会不执行


class ContextSnapshot(TimestampMixin, Base):
    """决策时刻冻结的最小化上下文（学习记录完整性，规格总体 §15.1）。"""

    __tablename__ = "context_snapshots"

    snapshot_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("context_snapshot"))
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    opportunity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    money_state: Mapped[str | None] = mapped_column(String(8), nullable=True)
    value_tier: Mapped[str | None] = mapped_column(String(2), nullable=True)
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 脱敏特征
    rule_versions: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # detector/scoring/decision/workflow 版本


class Decision(CommonMixin, Base):
    """Next Best Action 决策记录（V1 规则决策）。"""

    __tablename__ = "decisions"

    decision_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("decision"))
    opportunity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    policy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 2-3 候选动作
    selected_action: Mapped[str] = mapped_column(String(32), nullable=False)  # 从系统允许动作中选择
    selected_channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    selected_timing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    psychology_strategy: Mapped[PsychologyStrategy | None] = mapped_column(
        Enum(PsychologyStrategy, native_enum=False, length=32), nullable=True
    )
    psychology_evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # evidence/confidence/sample/avoid
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    requires_human_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    stop_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    escalation_conditions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    shadow: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 影子决策不执行


class ExecutionPlan(CommonMixin, Base):
    """完整执行方案（人工审核对象：不只文案）。批准版本不可变。"""

    __tablename__ = "execution_plans"

    __table_args__ = (
        UniqueConstraint("opportunity_id", "plan_version", name="uq_execution_plans_opp_ver"),
    )

    execution_plan_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("execution_plan"))
    opportunity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    decision_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    plan_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    goal: Mapped[str | None] = mapped_column(String(256), nullable=True)
    steps: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 多步骤执行流程
    assigned_staff_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    timing: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_draft_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    offer_reference: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 优惠引用（只引用已配置权益）
    compliance_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    review_status: Mapped[PlanStatus] = mapped_column(
        Enum(PlanStatus, native_enum=False, length=24), nullable=False, default=PlanStatus.DRAFT
    )
    review_decision: Mapped[ReviewDecision] = mapped_column(
        Enum(ReviewDecision, native_enum=False, length=20), nullable=False, default=ReviewDecision.PENDING
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 批准版本不可变哈希
    expected_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    expected_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    experiment_group: Mapped[str | None] = mapped_column(String(16), nullable=True)
    workflow_instance_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")  # draft/executing/completed/aborted
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    immutable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # 批准后不可变


class ContentDraft(CommonMixin, Base):
    """AI/模板/人工生成的内容草稿（版本化，不覆盖旧版本）。"""

    __tablename__ = "content_drafts"

    __table_args__ = (
        UniqueConstraint("opportunity_id", "version", name="uq_content_drafts_opp_ver"),
    )

    content_draft_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("content_draft"))
    opportunity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    generation_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="ai")  # ai/template/manual
    model_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_template_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_template_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    strategy_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 脱敏输入快照
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    wecom_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    mini_program_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_flags: Mapped[list | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    generation_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[Decimal] = mapped_column(Numeric(10, 6), nullable=False, default=0)
    status: Mapped[DraftStatus] = mapped_column(
        Enum(DraftStatus, native_enum=False, length=16), nullable=False, default=DraftStatus.DRAFT
    )


class ContentReviewRecord(CommonMixin, Base):
    """内容/方案自动检查与人工审核记录（机器 + 人工；含哈希防篡改）。"""

    __tablename__ = "content_review_records"

    review_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("content_review_record"))
    content_draft_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    review_type: Mapped[ReviewType] = mapped_column(
        Enum(ReviewType, native_enum=False, length=8), nullable=False
    )
    decision: Mapped[ReviewDecision] = mapped_column(
        Enum(ReviewDecision, native_enum=False, length=20), nullable=False, default=ReviewDecision.PENDING
    )
    risk_level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, native_enum=False, length=8), nullable=False, default=RiskLevel.LOW
    )
    rule_results: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 自动规则详情
    reviewer_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class ActionRecord(CommonMixin, Base):
    """实际动作（建议 vs 实际分离；完整证据链）。"""

    __tablename__ = "actions"

    action_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("action"))
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    touch_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, native_enum=False, length=24), nullable=False
    )
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    strategy_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    context_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, native_enum=False, length=12), nullable=False, default=ActionStatus.COMPLETED
    )
    deviation: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 与系统建议的差异
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)  # R-05 幂等唯一
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    causation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Outcome(CommonMixin, Base):
    """统一业务结果（回复/预约/到店/支付/DNC/投诉…）。"""

    __tablename__ = "outcomes"

    __table_args__ = (
        UniqueConstraint("opportunity_id", "outcome_type", "source_event_id", name="uq_outcomes_opp_type_src"),
    )

    outcome_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("outcome"))
    opportunity_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    patient_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    outcome_type: Mapped[OutcomeType] = mapped_column(
        Enum(OutcomeType, native_enum=False, length=16), nullable=False, index=True
    )
    source_event_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fact_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)  # R-04 关联 BusinessFact
    is_organic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)  # R-01 对照组自然结果
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revenue_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=True)  # 交易金额 ≠ 增量收入
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class InteractionSession(CommonMixin, Base):
    """企微卡片 → 小程序的安全承接会话（只携带随机 ticket）。"""

    __tablename__ = "interaction_sessions"

    __table_args__ = (
        Index("uq_interaction_sessions_token_hash", "token_hash", unique=True),
    )

    session_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("interaction_session"))
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    touch_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    content_draft_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    customer_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)  # 不保存明文 ticket
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    first_opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bound_openid_identity_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    status: Mapped[SessionStatus] = mapped_column(
        Enum(SessionStatus, native_enum=False, length=8), nullable=False, default=SessionStatus.ISSUED
    )


class MpEvent(TimestampMixin, Base):
    """小程序行为回流（幂等：event_id 客户端生成唯一）。"""

    __tablename__ = "mp_events"

    mp_event_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("mp_event"))
    organization_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    store_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)  # 客户端 UUID
    interaction_session_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # page_view/cta_click/appointment_submit/coupon_receive/share
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    page_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)


class WorkflowDefinition(CommonMixin, Base):
    """工作流定义（数据库配置 + 代码 Handler，不散落在 service 条件分支）。"""

    __tablename__ = "workflow_definitions"

    workflow_definition_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("workflow_definition"))
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)  # trigger/steps/stop_conditions
    status: Mapped[WorkflowDefinitionStatus] = mapped_column(
        Enum(WorkflowDefinitionStatus, native_enum=False, length=8), nullable=False, default=WorkflowDefinitionStatus.DRAFT
    )


class WorkflowInstance(CommonMixin, Base):
    """工作流实例（一次机会一次实例）。"""

    __tablename__ = "workflow_instances"

    workflow_instance_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("workflow_instance"))
    workflow_definition_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    workflow_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    opportunity_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    execution_plan_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    status: Mapped[WorkflowInstanceStatus] = mapped_column(
        Enum(WorkflowInstanceStatus, native_enum=False, length=12), nullable=False, default=WorkflowInstanceStatus.RUNNING
    )
    current_step: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrategyVersion(CommonMixin, Base):
    """策略注册中心（不可变版本；draft→…→active→retired/rolled_back）。"""

    __tablename__ = "strategy_versions"

    __table_args__ = (
        UniqueConstraint("organization_id", "category", "code", "version", name="uq_strategy_versions_org_cat_code_ver"),
    )

    strategy_version_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("strategy_version"))
    category: Mapped[StrategyCategory] = mapped_column(
        Enum(StrategyCategory, native_enum=False, length=24), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, index=True)
    status: Mapped[StrategyStatus] = mapped_column(
        Enum(StrategyStatus, native_enum=False, length=20), nullable=False, default=StrategyStatus.DRAFT, index=True
    )
    definition: Mapped[dict] = mapped_column(JSON, nullable=False)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(40), nullable=True)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_record: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    rollback_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)


class StrategyPerformance(CommonMixin, Base):
    """策略效果（按客群/场景/渠道/版本汇总，增量指标 + 护栏指标）。"""

    __tablename__ = "strategy_performance"

    performance_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("strategy_performance"))
    strategy_version_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    strategy_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    category: Mapped[str | None] = mapped_column(String(24), nullable=True)
    money_type: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    scenario_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    lifecycle_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    value_tier: Mapped[str | None] = mapped_column(String(2), nullable=True)
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    timing: Mapped[str | None] = mapped_column(String(32), nullable=True)
    content_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    treatment_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    control_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 回复率/预约率/到店率/支付率/DNC/投诉/增量收入/ROI…
    directional_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)  # 小样本方向性标记
    data_quality: Mapped[str | None] = mapped_column(String(16), nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
