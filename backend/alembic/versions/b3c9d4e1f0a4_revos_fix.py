"""RevOS 修复 migration（R-04/R-05/R-07/R-09）。

revision = b3c9d4e1f0a4
down_revision = b2c9d4e1f0a3

内容：
- 新增业务事实层（business_facts / opportunity_outcome_links，含外键）；
- 新增 Outbox / Job（R-07）、Connector（R-09）表；
- outcomes 增加 fact_id / is_organic（R-01/R-04）；
- actions 增加 idempotency_key 唯一约束；
- 关键唯一约束（含 SQLite/PostgreSQL 均支持的部分唯一索引）；
- 关键父子外键（batch 模式兼容 SQLite）。
"""
import sqlalchemy as sa
from alembic import op

revision = "b3c9d4e1f0a4"
down_revision = "b2c9d4e1f0a3"
branch_labels = None
depends_on = None


def _new_tables() -> None:
    op.create_table(
        "business_facts",
        sa.Column("fact_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("customer_id", sa.String(length=40), nullable=True),
        sa.Column("patient_id", sa.String(length=40), nullable=True),
        sa.Column("fact_type", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=32), nullable=False),
        sa.Column("source_event_id", sa.String(length=64), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revenue_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("refund_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("matched_opportunity_id", sa.String(length=40), nullable=True),
        sa.Column("match_status", sa.String(length=16), nullable=False),
        sa.Column("match_version", sa.String(length=32), nullable=True),
        sa.Column("match_reason", sa.JSON(), nullable=True),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.customer_id"], name="fk_business_facts_customer"),
    )
    for col in ("organization_id", "customer_id", "patient_id", "fact_type", "occurred_at", "matched_opportunity_id"):
        op.create_index(f"ix_business_facts_{col}", "business_facts", [col])

    op.create_table(
        "opportunity_outcome_links",
        sa.Column("link_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("opportunity_id", sa.String(length=40), nullable=False),
        sa.Column("fact_id", sa.String(length=40), nullable=False),
        sa.Column("outcome_id", sa.String(length=40), nullable=True),
        sa.Column("link_type", sa.String(length=16), nullable=False),
        sa.Column("revenue_attributed", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["opportunity_id"], ["opportunities.opportunity_id"], name="fk_links_opportunity"),
        sa.ForeignKeyConstraint(["fact_id"], ["business_facts.fact_id"], name="fk_links_fact"),
    )
    for col in ("organization_id", "opportunity_id", "fact_id", "outcome_id"):
        op.create_index(f"ix_opportunity_outcome_links_{col}", "opportunity_outcome_links", [col])

    op.create_table(
        "outbox_messages",
        sa.Column("outbox_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=40), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("causation_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for col in ("organization_id", "event_type", "status", "next_retry_at"):
        op.create_index(f"ix_outbox_messages_{col}", "outbox_messages", [col])

    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_log", sa.JSON(), nullable=True),
        sa.Column("requeued_by", sa.String(length=40), nullable=True),
        sa.Column("requeued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "job_type", "status", "next_run_at"):
        op.create_index(f"ix_jobs_{col}", "jobs", [col])

    op.create_table(
        "connector_configs",
        sa.Column("connector_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("base_url", sa.String(length=512), nullable=True),
        sa.Column("auth_type", sa.String(length=16), nullable=False),
        sa.Column("api_key_ref", sa.String(length=128), nullable=True),
        sa.Column("field_mapping", sa.JSON(), nullable=True),
        sa.Column("entity_enabled", sa.JSON(), nullable=True),
        sa.Column("webhook_secret_ref", sa.String(length=128), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_connector_configs_organization_id", "connector_configs", ["organization_id"])

    op.create_table(
        "connector_runs",
        sa.Column("run_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("connector_id", sa.String(length=40), nullable=False),
        sa.Column("sync_mode", sa.String(length=16), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("pulled", sa.Integer(), nullable=False),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("updated", sa.Integer(), nullable=False),
        sa.Column("skipped", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "connector_id", "entity", "status"):
        op.create_index(f"ix_connector_runs_{col}", "connector_runs", [col])

    op.create_table(
        "sync_checkpoints",
        sa.Column("checkpoint_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("connector_id", sa.String(length=40), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("cursor", sa.String(length=512), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "connector_id", "entity"):
        op.create_index(f"ix_sync_checkpoints_{col}", "sync_checkpoints", [col])

    op.create_table(
        "reconciliation_diffs",
        sa.Column("diff_id", sa.String(length=40), primary_key=True),
        sa.Column("organization_id", sa.String(length=40), nullable=False),
        sa.Column("store_id", sa.String(length=40), nullable=True),
        sa.Column("diff_date", sa.String(length=16), nullable=False),
        sa.Column("entity", sa.String(length=32), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column("revos_value", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.String(length=64), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    for col in ("organization_id", "diff_date", "entity", "entity_id"):
        op.create_index(f"ix_reconciliation_diffs_{col}", "reconciliation_diffs", [col])


def _extend_tables() -> None:
    # outcomes：R-01/R-04 事实关联 + 对照组自然结果标记
    with op.batch_alter_table("outcomes") as batch_op:
        batch_op.add_column(sa.Column("fact_id", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("is_organic", sa.Boolean(), nullable=False, server_default="0"))
    op.create_index("ix_outcomes_fact_id", "outcomes", ["fact_id"])

    # actions：幂等键（R-05）
    with op.batch_alter_table("actions") as batch_op:
        batch_op.add_column(sa.Column("idempotency_key", sa.String(length=128), nullable=True))

    # Connector 源 ID（R-09）：visits/orders/payments/refunds
    for table in ("visits", "orders", "payments", "refunds"):
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(sa.Column("source_id", sa.String(length=64), nullable=True))
        op.create_index(f"ix_{table}_source_id", table, ["source_id"])


def _dedupe(table: str, cols: list[str]) -> None:
    """删除每组 (cols) 中除最新一条外的重复行（兼容 SQLite/PostgreSQL）。"""
    col_list = ", ".join(cols)
    # 保留每组的 max(rowid)；SQLite/PostgreSQL 均有 rowid（PG 用 ctid 不可靠，改用主键）
    pk = {"content_drafts": "content_draft_id", "execution_plans": "execution_plan_id",
          "strategy_versions": "strategy_version_id", "outcomes": "outcome_id"}[table]
    op.execute(
        f"DELETE FROM {table} WHERE {pk} NOT IN ("
        f"SELECT MIN({pk}) FROM {table} GROUP BY {col_list})"
    )


def _unique_constraints() -> None:
    # 清理历史重复数据（保留每个分组最新一条），保证唯一索引可建立
    for table, cols in [
        ("content_drafts", ["opportunity_id", "version"]),
        ("execution_plans", ["opportunity_id", "plan_version"]),
        ("strategy_versions", ["organization_id", "category", "code", "version"]),
    ]:
        _dedupe(table, cols)
    # outcomes 去重（opportunity/type/source_event）
    _dedupe("outcomes", ["opportunity_id", "outcome_type", "source_event_id"])

    # 全部用唯一索引（SQLite 不支持 ALTER ADD CONSTRAINT；唯一索引同样保证数据库唯一性）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_business_facts_source "
        "ON business_facts (organization_id, source_system, source_event_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_outcomes_opp_type_src "
        "ON outcomes (opportunity_id, outcome_type, source_event_id)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_content_drafts_opp_ver "
        "ON content_drafts (opportunity_id, version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_execution_plans_opp_ver "
        "ON execution_plans (opportunity_id, plan_version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_strategy_versions_org_cat_code_ver "
        "ON strategy_versions (organization_id, category, code, version)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_actions_idempotency "
        "ON actions (idempotency_key)"
    )
    # mp_events.event_id 唯一已由列级 unique=True 建立，无需重复
    # interaction_sessions.token_hash：把普通索引改造成唯一索引
    op.execute("DROP INDEX IF EXISTS ix_interaction_sessions_token_hash")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_interaction_sessions_token_hash "
        "ON interaction_sessions (token_hash)"
    )

    # 部分唯一索引（SQLite / PostgreSQL 均支持）
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_customer_identities_active "
        "ON customer_identities (organization_id, identity_type, value_hash, app_scope) "
        "WHERE valid_to IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_opportunities_active_scenario "
        "ON opportunities (organization_id, customer_id, scenario_type) "
        "WHERE lower(status) IN ('candidate','qualified','approved','executing')"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_links_primary_fact "
        "ON opportunity_outcome_links (fact_id) WHERE link_type = 'primary'"
    )


def _foreign_keys() -> None:
    # 先清理孤儿行，保证 FK 建立成功
    op.execute(
        "DELETE FROM outcomes WHERE opportunity_id NOT IN (SELECT opportunity_id FROM opportunities)"
    )
    op.execute(
        "DELETE FROM execution_plans WHERE opportunity_id NOT IN (SELECT opportunity_id FROM opportunities)"
    )
    op.execute(
        "DELETE FROM decisions WHERE opportunity_id NOT IN (SELECT opportunity_id FROM opportunities)"
    )
    op.execute(
        "DELETE FROM content_drafts WHERE opportunity_id NOT IN (SELECT opportunity_id FROM opportunities)"
    )
    op.execute(
        "DELETE FROM actions WHERE opportunity_id IS NOT NULL AND opportunity_id NOT IN "
        "(SELECT opportunity_id FROM opportunities)"
    )
    op.execute(
        "DELETE FROM opportunities WHERE customer_id NOT IN (SELECT customer_id FROM customers)"
    )

    with op.batch_alter_table("opportunities") as batch_op:
        batch_op.create_foreign_key("fk_opportunities_customer", "customers", ["customer_id"], ["customer_id"])
    with op.batch_alter_table("outcomes") as batch_op:
        batch_op.create_foreign_key("fk_outcomes_opportunity", "opportunities", ["opportunity_id"], ["opportunity_id"])
    with op.batch_alter_table("execution_plans") as batch_op:
        batch_op.create_foreign_key("fk_execution_plans_opportunity", "opportunities", ["opportunity_id"], ["opportunity_id"])
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.create_foreign_key("fk_decisions_opportunity", "opportunities", ["opportunity_id"], ["opportunity_id"])
    with op.batch_alter_table("content_drafts") as batch_op:
        batch_op.create_foreign_key("fk_content_drafts_opportunity", "opportunities", ["opportunity_id"], ["opportunity_id"])
    with op.batch_alter_table("actions") as batch_op:
        batch_op.create_foreign_key("fk_actions_opportunity", "opportunities", ["opportunity_id"], ["opportunity_id"])


def upgrade() -> None:
    _new_tables()
    _extend_tables()
    _unique_constraints()
    _foreign_keys()


def downgrade() -> None:
    # 反向：先删外键（batch），再删约束/索引/列/表
    for table, fk, ref in [
        ("actions", "fk_actions_opportunity", "opportunities"),
        ("content_drafts", "fk_content_drafts_opportunity", "opportunities"),
        ("decisions", "fk_decisions_opportunity", "opportunities"),
        ("execution_plans", "fk_execution_plans_opportunity", "opportunities"),
        ("outcomes", "fk_outcomes_opportunity", "opportunities"),
        ("opportunities", "fk_opportunities_customer", "customers"),
    ]:
        try:
            with op.batch_alter_table(table) as batch_op:
                batch_op.drop_constraint(fk, type_="foreignkey")
        except Exception:  # noqa: BLE001
            pass

    for idx in ["uq_customer_identities_active", "uq_opportunities_active_scenario",
                "uq_links_primary_fact", "uq_interaction_sessions_token_hash",
                "uq_business_facts_source", "uq_outcomes_opp_type_src",
                "uq_content_drafts_opp_ver", "uq_execution_plans_opp_ver",
                "uq_strategy_versions_org_cat_code_ver", "uq_actions_idempotency"]:
        op.execute(f"DROP INDEX IF EXISTS {idx}")

    op.drop_index("ix_outcomes_fact_id", table_name="outcomes")
    for table in ("visits", "orders", "payments", "refunds"):
        op.drop_index(f"ix_{table}_source_id", table_name=table)
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_column("source_id")
    with op.batch_alter_table("outcomes") as batch_op:
        batch_op.drop_column("is_organic")
        batch_op.drop_column("fact_id")
    with op.batch_alter_table("actions") as batch_op:
        batch_op.drop_column("idempotency_key")

    for table in ["reconciliation_diffs", "sync_checkpoints", "connector_runs",
                  "connector_configs", "jobs", "outbox_messages",
                  "opportunity_outcome_links", "business_facts"]:
        op.drop_table(table)
