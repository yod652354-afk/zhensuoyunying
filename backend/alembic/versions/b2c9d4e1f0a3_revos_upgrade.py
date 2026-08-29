"""RevOS 兼容升级：新增领域模型 + 既有表扩展（可升级/可回滚，SQLite/PostgreSQL 兼容）。

revision = b2c9d4e1f0a3
down_revision = a715f4a894bb

原则（开发指令 §4 / 规格 03 §19）：
- 旧表和旧数据不删除；
- Task/Touch/Attribution 新增列均为 nullable，兼容旧数据；
- upgrade/downgrade 均可执行；
- 不为学习快照复制完整敏感内容。
"""
import sqlalchemy as sa
from alembic import op

revision = "b2c9d4e1f0a3"
down_revision = "a715f4a894bb"
branch_labels = None
depends_on = None


def _new_tables() -> None:
    # ---------- 客户经营档案 ----------
    op.create_table(
        "customers",
        sa.Column("customer_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("display_name", sa.String(length=64), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=False),
        sa.Column("money_state", sa.String(length=8), nullable=False),
        sa.Column("value_tier", sa.String(length=2), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("state_reason_codes", sa.JSON(), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_status", sa.String(length=16), nullable=True),
        sa.Column("dnc", sa.Boolean(), nullable=False),
        sa.Column("complaint_flag", sa.Boolean(), nullable=False),
        sa.Column("contact_status", sa.String(length=16), nullable=True),
        sa.Column("total_visits", sa.Integer(), nullable=False),
        sa.Column("total_revenue", sa.Numeric(14, 2), nullable=False),
        sa.Column("last_visit_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_touch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_system", sa.String(length=64), nullable=True),
    )
    op.create_index("ix_customers_organization_id", "customers", ["organization_id"])
    op.create_index("ix_customers_store_id", "customers", ["store_id"])
    op.create_index("ix_customers_patient_id", "customers", ["patient_id"])

    # ---------- 客户身份（加密值 + 匹配哈希） ----------
    op.create_table(
        "customer_identities",
        sa.Column("identity_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("identity_type", sa.String(length=24), nullable=False),
        sa.Column("encrypted_value", sa.Text(), nullable=True),
        sa.Column("value_hash", sa.String(length=128), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("app_scope", sa.String(length=128), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_customer_identities_organization_id", "customer_identities", ["organization_id"])
    op.create_index("ix_customer_identities_customer_id", "customer_identities", ["customer_id"])
    op.create_index("ix_customer_identities_identity_type", "customer_identities", ["identity_type"])
    op.create_index("ix_customer_identities_value_hash", "customer_identities", ["value_hash"])

    # ---------- 客户状态历史 ----------
    op.create_table(
        "customer_state_history",
        sa.Column("state_history_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("lifecycle_from", sa.String(length=16), nullable=True),
        sa.Column("lifecycle_to", sa.String(length=16), nullable=False),
        sa.Column("money_from", sa.String(length=8), nullable=True),
        sa.Column("money_to", sa.String(length=8), nullable=False),
        sa.Column("value_tier", sa.String(length=2), nullable=False),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("trigger_event_id", sa.String(length=40), nullable=True),
        sa.Column("rule_version", sa.String(length=32), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_customer_state_history_organization_id", "customer_state_history", ["organization_id"])
    op.create_index("ix_customer_state_history_customer_id", "customer_state_history", ["customer_id"])
    op.create_index("ix_customer_state_history_patient_id", "customer_state_history", ["patient_id"])

    # ---------- Opportunity ----------
    op.create_table(
        "opportunities",
        sa.Column("opportunity_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("money_type", sa.String(length=8), nullable=False),
        sa.Column("scenario_type", sa.String(length=32), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("priority_score", sa.Numeric(5, 2), nullable=False),
        sa.Column("expected_revenue", sa.Numeric(12, 2), nullable=False),
        sa.Column("probability", sa.Numeric(5, 4), nullable=False),
        sa.Column("expected_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=True),
        sa.Column("context_snapshot", sa.JSON(), nullable=True),
        sa.Column("detector_version", sa.String(length=32), nullable=True),
        sa.Column("scoring_version", sa.String(length=32), nullable=True),
        sa.Column("workflow_code", sa.String(length=64), nullable=True),
        sa.Column("experiment_id", sa.String(length=40), nullable=True),
        sa.Column("experiment_group", sa.String(length=16), nullable=True),
        sa.Column("owner_staff_id", sa.String(length=40), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suppressed_reason", sa.String(length=256), nullable=True),
        sa.Column("suppressed_by", sa.String(length=40), nullable=True),
        sa.Column("suppressed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("won_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "customer_id", "patient_id", "scenario_type", "status", "expires_at", "experiment_id", "owner_staff_id"):
        op.create_index(f"ix_opportunities_{col}", "opportunities", [col])

    # ---------- 决策上下文快照 ----------
    op.create_table(
        "context_snapshots",
        sa.Column("snapshot_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=True),
        sa.Column("money_state", sa.String(length=8), nullable=True),
        sa.Column("value_tier", sa.String(length=2), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("rule_versions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_context_snapshots_opportunity_id", "context_snapshots", ["opportunity_id"])
    op.create_index("ix_context_snapshots_customer_id", "context_snapshots", ["customer_id"])

    # ---------- Decision ----------
    op.create_table(
        "decisions",
        sa.Column("decision_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=True),
        sa.Column("candidates", sa.JSON(), nullable=True),
        sa.Column("selected_action", sa.String(length=32), nullable=False),
        sa.Column("selected_channel", sa.String(length=24), nullable=True),
        sa.Column("selected_timing", sa.String(length=32), nullable=True),
        sa.Column("psychology_strategy", sa.String(length=32), nullable=True),
        sa.Column("psychology_evidence", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("requires_human_review", sa.Boolean(), nullable=False),
        sa.Column("stop_conditions", sa.JSON(), nullable=True),
        sa.Column("escalation_conditions", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("shadow", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decisions_organization_id", "decisions", ["organization_id"])
    op.create_index("ix_decisions_opportunity_id", "decisions", ["opportunity_id"])

    # ---------- ExecutionPlan ----------
    op.create_table(
        "execution_plans",
        sa.Column("execution_plan_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("decision_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("goal", sa.String(length=256), nullable=True),
        sa.Column("steps", sa.JSON(), nullable=True),
        sa.Column("assigned_staff_id", sa.String(length=40), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=True),
        sa.Column("timing", sa.String(length=64), nullable=True),
        sa.Column("content_draft_id", sa.String(length=40), nullable=True),
        sa.Column("offer_reference", sa.JSON(), nullable=True),
        sa.Column("compliance_result", sa.JSON(), nullable=True),
        sa.Column("review_status", sa.String(length=24), nullable=False),
        sa.Column("review_decision", sa.String(length=20), nullable=False),
        sa.Column("reviewed_by", sa.String(length=40), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("expected_value", sa.Numeric(12, 2), nullable=False),
        sa.Column("expected_cost", sa.Numeric(12, 2), nullable=False),
        sa.Column("experiment_id", sa.String(length=40), nullable=True),
        sa.Column("experiment_group", sa.String(length=16), nullable=True),
        sa.Column("workflow_instance_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("immutable", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "opportunity_id", "customer_id", "content_draft_id", "workflow_instance_id"):
        op.create_index(f"ix_execution_plans_{col}", "execution_plans", [col])

    # ---------- ContentDraft ----------
    op.create_table(
        "content_drafts",
        sa.Column("content_draft_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("execution_plan_id", sa.String(length=40), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("generation_mode", sa.String(length=16), nullable=False),
        sa.Column("model_provider", sa.String(length=64), nullable=True),
        sa.Column("model_name", sa.String(length=64), nullable=True),
        sa.Column("prompt_template_code", sa.String(length=64), nullable=True),
        sa.Column("prompt_template_version", sa.String(length=32), nullable=True),
        sa.Column("strategy_code", sa.String(length=32), nullable=True),
        sa.Column("input_snapshot", sa.JSON(), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=True),
        sa.Column("wecom_text", sa.Text(), nullable=True),
        sa.Column("image_url", sa.String(length=512), nullable=True),
        sa.Column("mini_program_config", sa.JSON(), nullable=True),
        sa.Column("risk_flags", sa.JSON(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("generation_latency_ms", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(10, 6), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_content_drafts_organization_id", "content_drafts", ["organization_id"])
    op.create_index("ix_content_drafts_opportunity_id", "content_drafts", ["opportunity_id"])
    op.create_index("ix_content_drafts_execution_plan_id", "content_drafts", ["execution_plan_id"])
    op.create_index("ix_content_drafts_content_hash", "content_drafts", ["content_hash"])

    # ---------- ContentReviewRecord ----------
    op.create_table(
        "content_review_records",
        sa.Column("review_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("content_draft_id", sa.String(length=40), nullable=True),
        sa.Column("execution_plan_id", sa.String(length=40), nullable=True),
        sa.Column("review_type", sa.String(length=8), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("risk_level", sa.String(length=8), nullable=False),
        sa.Column("rule_results", sa.JSON(), nullable=True),
        sa.Column("reviewer_id", sa.String(length=40), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_review_records_organization_id", "content_review_records", ["organization_id"])
    op.create_index("ix_content_review_records_content_draft_id", "content_review_records", ["content_draft_id"])
    op.create_index("ix_content_review_records_execution_plan_id", "content_review_records", ["execution_plan_id"])

    # ---------- Action ----------
    op.create_table(
        "actions",
        sa.Column("action_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=True),
        sa.Column("execution_plan_id", sa.String(length=40), nullable=True),
        sa.Column("task_id", sa.String(length=40), nullable=True),
        sa.Column("touch_id", sa.String(length=40), nullable=True),
        sa.Column("action_type", sa.String(length=24), nullable=False),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=True),
        sa.Column("strategy_code", sa.String(length=32), nullable=True),
        sa.Column("content_version", sa.String(length=32), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("context_snapshot", sa.JSON(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cost", sa.Numeric(10, 4), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("deviation", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "opportunity_id", "task_id", "touch_id", "correlation_id"):
        op.create_index(f"ix_actions_{col}", "actions", [col])

    # ---------- Outcome ----------
    op.create_table(
        "outcomes",
        sa.Column("outcome_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("execution_plan_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("outcome_type", sa.String(length=16), nullable=False),
        sa.Column("source_event_id", sa.String(length=40), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revenue_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "opportunity_id", "customer_id", "outcome_type", "occurred_at"):
        op.create_index(f"ix_outcomes_{col}", "outcomes", [col])

    # ---------- InteractionSession ----------
    op.create_table(
        "interaction_sessions",
        sa.Column("session_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=True),
        sa.Column("touch_id", sa.String(length=40), nullable=True),
        sa.Column("content_draft_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bound_openid_identity_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "customer_id", "token_hash", "expires_at"):
        op.create_index(f"ix_interaction_sessions_{col}", "interaction_sessions", [col])

    # ---------- MpEvent ----------
    op.create_table(
        "mp_events",
        sa.Column("mp_event_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=False, unique=True),
        sa.Column("interaction_session_id", sa.String(length=40), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("page_code", sa.String(length=64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mp_events_organization_id", "mp_events", ["organization_id"])
    op.create_index("ix_mp_events_interaction_session_id", "mp_events", ["interaction_session_id"])
    op.create_index("ix_mp_events_event_type", "mp_events", ["event_type"])

    # ---------- Workflow ----------
    op.create_table(
        "workflow_definitions",
        sa.Column("workflow_definition_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=True),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_workflow_definitions_organization_id", "workflow_definitions", ["organization_id"])
    op.create_index("ix_workflow_definitions_code", "workflow_definitions", ["code"])

    op.create_table(
        "workflow_instances",
        sa.Column("workflow_instance_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("workflow_definition_id", sa.String(length=40), nullable=False),
        sa.Column("workflow_code", sa.String(length=64), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=True),
        sa.Column("execution_plan_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("current_step", sa.String(length=64), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "opportunity_id", "execution_plan_id"):
        op.create_index(f"ix_workflow_instances_{col}", "workflow_instances", [col])

    # ---------- Strategy ----------
    op.create_table(
        "strategy_versions",
        sa.Column("strategy_version_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("category", sa.String(length=24), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner", sa.String(length=40), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("approval_record", sa.JSON(), nullable=True),
        sa.Column("rollback_version", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "category", "code", "version", "status"):
        op.create_index(f"ix_strategy_versions_{col}", "strategy_versions", [col])

    op.create_table(
        "strategy_performance",
        sa.Column("performance_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("strategy_version_id", sa.String(length=40), nullable=True),
        sa.Column("strategy_code", sa.String(length=64), nullable=True),
        sa.Column("category", sa.String(length=24), nullable=True),
        sa.Column("money_type", sa.String(length=8), nullable=True),
        sa.Column("scenario_type", sa.String(length=32), nullable=True),
        sa.Column("lifecycle_state", sa.String(length=16), nullable=True),
        sa.Column("value_tier", sa.String(length=2), nullable=True),
        sa.Column("channel", sa.String(length=24), nullable=True),
        sa.Column("timing", sa.String(length=32), nullable=True),
        sa.Column("content_version", sa.String(length=32), nullable=True),
        sa.Column("experiment_id", sa.String(length=40), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("treatment_size", sa.Integer(), nullable=False),
        sa.Column("control_size", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("directional_only", sa.Boolean(), nullable=False),
        sa.Column("data_quality", sa.String(length=16), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "strategy_code", "money_type", "scenario_type"):
        op.create_index(f"ix_strategy_performance_{col}", "strategy_performance", [col])


def _extend_existing_tables() -> None:
    # webhook_deliveries：租户隔离列（RevOS P0）+ 历史数据回填
    op.add_column("webhook_deliveries", sa.Column("organization_id", sa.String(length=40), nullable=True))
    op.create_index("ix_webhook_deliveries_organization_id", "webhook_deliveries", ["organization_id"])
    op.execute(
        "UPDATE webhook_deliveries SET organization_id = "
        "(SELECT e.organization_id FROM events e WHERE e.event_id = webhook_deliveries.event_id) "
        "WHERE organization_id IS NULL"
    )

    # tasks：企微执行扩展（全部 nullable）
    op.add_column("tasks", sa.Column("opportunity_id", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("execution_plan_id", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("content_draft_id", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("workflow_instance_id", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("action_id", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("channel_account_id", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("send_mode", sa.String(length=16), nullable=True))
    op.add_column("tasks", sa.Column("external_message_id", sa.String(length=128), nullable=True))
    op.add_column("tasks", sa.Column("send_status", sa.String(length=32), nullable=True))
    op.add_column("tasks", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.add_column("tasks", sa.Column("failure_message", sa.String(length=512), nullable=True))
    op.add_column("tasks", sa.Column("confirmed_by", sa.String(length=40), nullable=True))
    op.add_column("tasks", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("content_hash", sa.String(length=128), nullable=True))
    op.add_column("tasks", sa.Column("correlation_id", sa.String(length=64), nullable=True))
    for col in ("opportunity_id", "execution_plan_id", "content_draft_id", "workflow_instance_id", "action_id", "send_status", "correlation_id"):
        op.create_index(f"ix_tasks_{col}", "tasks", [col])

    # touches：企微执行扩展（全部 nullable）
    op.add_column("touches", sa.Column("opportunity_id", sa.String(length=40), nullable=True))
    op.add_column("touches", sa.Column("content_draft_id", sa.String(length=40), nullable=True))
    op.add_column("touches", sa.Column("channel_account_id", sa.String(length=64), nullable=True))
    op.add_column("touches", sa.Column("send_mode", sa.String(length=16), nullable=True))
    op.add_column("touches", sa.Column("external_message_id", sa.String(length=128), nullable=True))
    op.add_column("touches", sa.Column("send_status", sa.String(length=32), nullable=True))
    op.add_column("touches", sa.Column("failure_code", sa.String(length=64), nullable=True))
    op.add_column("touches", sa.Column("failure_message", sa.String(length=512), nullable=True))
    op.add_column("touches", sa.Column("confirmed_by", sa.String(length=40), nullable=True))
    op.add_column("touches", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("touches", sa.Column("content_hash", sa.String(length=128), nullable=True))
    op.add_column("touches", sa.Column("correlation_id", sa.String(length=64), nullable=True))
    for col in ("opportunity_id", "content_draft_id", "send_status", "correlation_id"):
        op.create_index(f"ix_touches_{col}", "touches", [col])

    # attributions：归因扩展（全部 nullable）
    op.add_column("attributions", sa.Column("opportunity_id", sa.String(length=40), nullable=True))
    op.add_column("attributions", sa.Column("outcome_id", sa.String(length=40), nullable=True))
    op.add_column("attributions", sa.Column("experiment_group", sa.String(length=16), nullable=True))
    op.add_column("attributions", sa.Column("attribution_window_days", sa.Integer(), nullable=True))
    op.add_column("attributions", sa.Column("attribution_version", sa.String(length=32), nullable=True))
    op.add_column("attributions", sa.Column("evidence_chain", sa.JSON(), nullable=True))
    op.add_column("attributions", sa.Column("data_quality", sa.String(length=16), nullable=True))
    op.create_index("ix_attributions_opportunity_id", "attributions", ["opportunity_id"])

    # events：事件规范扩展（全部 nullable）
    op.add_column("events", sa.Column("schema_version", sa.String(length=8), nullable=True))
    op.add_column("events", sa.Column("correlation_id", sa.String(length=64), nullable=True))
    op.add_column("events", sa.Column("causation_id", sa.String(length=64), nullable=True))
    op.create_index("ix_events_correlation_id", "events", ["correlation_id"])


def upgrade() -> None:
    _new_tables()
    _extend_existing_tables()


def downgrade() -> None:
    # 先删 RevOS 新增索引（batch 重建表时不会自动剔除引用被删列的索引），
    # 再删列/表；旧数据不受影响（仅移除 RevOS 新增结构）。
    _indexes = [
        ("webhook_deliveries", "ix_webhook_deliveries_organization_id"),
        ("events", "ix_events_correlation_id"),
        ("attributions", "ix_attributions_opportunity_id"),
        ("touches", "ix_touches_opportunity_id"), ("touches", "ix_touches_content_draft_id"),
        ("touches", "ix_touches_send_status"), ("touches", "ix_touches_correlation_id"),
        ("tasks", "ix_tasks_opportunity_id"), ("tasks", "ix_tasks_execution_plan_id"),
        ("tasks", "ix_tasks_content_draft_id"), ("tasks", "ix_tasks_workflow_instance_id"),
        ("tasks", "ix_tasks_action_id"), ("tasks", "ix_tasks_send_status"),
        ("tasks", "ix_tasks_correlation_id"),
    ]
    for table, idx in _indexes:
        try:
            op.drop_index(idx, table_name=table)
        except Exception:  # noqa: BLE001  索引可能已不存在
            pass

    for table, cols in [
        ("webhook_deliveries", ["organization_id"]),
        ("events", ["causation_id", "correlation_id", "schema_version"]),
        ("attributions", ["data_quality", "evidence_chain", "attribution_version", "attribution_window_days", "experiment_group", "outcome_id", "opportunity_id"]),
        ("touches", ["correlation_id", "content_hash", "confirmed_at", "confirmed_by", "failure_message", "failure_code", "send_status", "external_message_id", "send_mode", "channel_account_id", "content_draft_id", "opportunity_id"]),
        ("tasks", ["correlation_id", "content_hash", "confirmed_at", "confirmed_by", "failure_message", "failure_code", "send_status", "external_message_id", "send_mode", "channel_account_id", "action_id", "workflow_instance_id", "content_draft_id", "execution_plan_id", "opportunity_id"]),
    ]:
        with op.batch_alter_table(table) as batch_op:
            for col in cols:
                batch_op.drop_column(col)

    for table in [
        "strategy_performance", "strategy_versions", "workflow_instances",
        "workflow_definitions", "mp_events", "interaction_sessions", "outcomes",
        "actions", "content_review_records", "content_drafts", "execution_plans",
        "decisions", "context_snapshots", "opportunities", "customer_state_history",
        "customer_identities", "customers",
    ]:
        op.drop_table(table)
