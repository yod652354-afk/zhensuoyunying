"""通用 Connector（R-09）：诊所SaaS 数据接入配置 / 运行游标 / 对账差异。

Connector 是 RevOS 内部适配层：消费既有 Read API、Webhook/Event 与增量同步合同，
把前端字段映射为 RevOS 标准经营事件；每租户独立游标，错误隔离与重放。
"""
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..core.ids import new_id
from ..database import Base
from .base import CommonMixin


class ConnectorConfig(CommonMixin, Base):
    """数据源连接配置（服务端到服务端，密钥经环境变量注入）。"""

    __tablename__ = "connector_configs"

    connector_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("connector"))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="clinicos_saas")  # clinicos_saas/his/crm/csv
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    auth_type: Mapped[str] = mapped_column(String(16), nullable=False, default="api_key")  # api_key/bearer/none
    api_key_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)  # 引用环境变量名，不存密钥明文
    field_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # 源字段 → RevOS 字段
    entity_enabled: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # {"patients": true, "orders": true, ...}
    webhook_secret_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ConnectorRun(CommonMixin, Base):
    """单次/持续同步运行状态（租户独立游标、错误、统计）。"""

    __tablename__ = "connector_runs"

    run_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("connector_run"))
    connector_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    sync_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="incremental")  # full/incremental/compensate
    entity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)  # patients/visits/orders/payments/refunds
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)  # updated_since/cursor
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="running", index=True)  # running/done/failed
    pulled: Mapped[int] = mapped_column(nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(nullable=False, default=0)
    updated: Mapped[int] = mapped_column(nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SyncCheckpoint(CommonMixin, Base):
    """每租户每实体的增量同步游标（updated_since + cursor 持久化）。"""

    __tablename__ = "sync_checkpoints"

    checkpoint_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("checkpoint"))
    connector_id: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ReconciliationDiff(CommonMixin, Base):
    """每日对账差异（定位到 ID：患者/到店/订单/支付/退款）。"""

    __tablename__ = "reconciliation_diffs"

    diff_id: Mapped[str] = mapped_column(String(40), primary_key=True, default=lambda: new_id("diff"))
    diff_date: Mapped[str] = mapped_column(String(16), nullable=False, index=True)  # YYYY-MM-DD
    entity: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    revos_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)  # 差异定位到 ID
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")  # open/resolved/ignored
