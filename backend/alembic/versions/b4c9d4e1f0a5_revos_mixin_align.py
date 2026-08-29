"""RevOS 模型对齐 migration（R-08 副作用修复）。

revision = b4c9d4e1f0a5
down_revision = b3c9d4e1f0a4

背景：R-08 将模型统一改为继承 CommonMixin/TimestampMixin 后，模型比既有数据库表
多出 store_id/source_system/created_by_type/created_by_id/deleted_at 列。
本迁移用 batch 模式为缺失列补列（幂等：列已存在则跳过），
使 create_all 库与迁移库结构一致；SQLite/PostgreSQL 均兼容。
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "b4c9d4e1f0a5"
down_revision = "b3c9d4e1f0a4"
branch_labels = None
depends_on = None

# (列名, 列类型)
MIXIN_COLUMNS = {
    "store_id": sa.String(40),
    "source_system": sa.String(64),
    "created_by_type": sa.String(16),
    "created_by_id": sa.String(64),
    "deleted_at": sa.DateTime(timezone=True),
}


def _table_names(conn) -> list[str]:
    return sa_inspect(conn).get_table_names()


def upgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)
    for table in tables:
        existing = {c["name"] for c in sa_inspect(conn).get_columns(table)}
        to_add = {name: col for name, col in MIXIN_COLUMNS.items() if name not in existing}
        if not to_add:
            continue
        with op.batch_alter_table(table) as batch_op:
            for name, coltype in to_add.items():
                batch_op.add_column(sa.Column(name, coltype, nullable=True))
    # store_id 索引（租户过滤）
    conn2 = op.get_bind()
    for table in tables:
        if "store_id" in {c["name"] for c in sa_inspect(conn2).get_columns(table)}:
            try:
                op.create_index(f"ix_{table}_store_id", table, ["store_id"])
            except Exception:  # noqa: BLE001  已存在
                pass


def downgrade() -> None:
    conn = op.get_bind()
    tables = _table_names(conn)
    for table in tables:
        existing = {c["name"] for c in sa_inspect(conn).get_columns(table)}
        to_drop = [name for name in MIXIN_COLUMNS if name in existing]
        if not to_drop:
            continue
        # 先删引用被删列的索引（batch 重建表会复制索引，遗留列会失败）
        for idx in sa_inspect(conn).get_indexes(table):
            if set(idx["column_names"]) & set(to_drop):
                try:
                    op.drop_index(idx["name"], table_name=table)
                except Exception:  # noqa: BLE001
                    pass
        try:
            with op.batch_alter_table(table) as batch_op:
                for name in to_drop:
                    batch_op.drop_column(name)
        except Exception:  # noqa: BLE001  单表回滚失败不阻断整体回滚
            pass
