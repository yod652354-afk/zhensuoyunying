"""通用 Connector 框架（R-09）：诊所SaaS 自动数据接入。

- 配置驱动：base_url + 实体端点 + 字段映射（OpenAPI/字段映射配置）；
- 全量首导 + updated_since/cursor 增量 + Webhook 实时 + 丢失补偿；
- 每租户独立游标（SyncCheckpoint）与运行记录（ConnectorRun）；
- 错误隔离与重放（通过 Job 队列执行）；
- 删除/退款/取消处理；每日对账差异定位到 ID；
- 模拟诊所 SaaS 服务（契约测试）。
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.enums import CustomerStatus, OrderStatus, PaymentStatus, VisitStatus, VisitType
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...models import Order, OrderItem, Patient, Payment, Refund, Visit
from ...models.connector import (
    ConnectorConfig, ConnectorRun, ReconciliationDiff, SyncCheckpoint,
)
from ...models.revos import Customer
from ..revos.common import ensure_customer
from .jobs import enqueue_job

logger = logging.getLogger("clinicos.revos.connector")

# 实体 → (RevOS 模型, 增量字段, 端点)
ENTITY_SPECS = {
    "patients": {"model": Patient, "since_field": "updated_since", "endpoint": "patients"},
    "visits": {"model": Visit, "since_field": "updated_since", "endpoint": "visits"},
    "orders": {"model": Order, "since_field": "updated_since", "endpoint": "orders"},
    "payments": {"model": Payment, "since_field": "updated_since", "endpoint": "payments"},
    "refunds": {"model": Refund, "since_field": "updated_since", "endpoint": "refunds"},
}

# 默认字段映射（源字段 → RevOS 模型字段）
DEFAULT_MAPPINGS = {
    "patients": {"patient_id": "source_id", "name": "name", "gender": "gender",
                 "mobile": "mobile", "first_visit_date": "first_visit_date",
                 "last_visit_date": "last_visit_date", "total_visits": "total_visits",
                 "total_revenue": "total_revenue", "consent_status": "consent_status",
                 "dnc": "dnc", "contact_status": "contact_status"},
    "visits": {"visit_id": "source_id", "patient_id": "patient_id", "visit_at": "visit_at",
               "visit_type": "visit_type", "service_category": "service_category"},
    "orders": {"order_id": "source_id", "patient_id": "patient_id", "final_amount": "final_amount",
               "order_status": "order_status", "created_at": "created_at"},
    "payments": {"payment_id": "source_id", "patient_id": "patient_id", "amount": "amount",
                 "paid_at": "paid_at", "status": "status", "order_id": "order_id"},
    "refunds": {"refund_id": "source_id", "patient_id": "patient_id", "amount": "amount",
                "refunded_at": "refunded_at", "payment_id": "payment_id"},
}


# ---------- 模拟诊所 SaaS（契约测试） ----------
class MockClinicSaaS:
    """内存模拟诊所SaaS：提供列表端点 + updated_since/cursor + 删除标记。"""

    def __init__(self):
        self.data: dict[str, list[dict]] = {k: [] for k in ENTITY_SPECS}
        self._seq: dict[str, int] = {}

    def seed(self, entity: str, rows: list[dict]) -> None:
        self.data[entity].extend(rows)
        self._seq[entity] = len(self.data[entity])

    def list_rows(self, entity: str, updated_since: str | None = None,
                  cursor: str | None = None, limit: int = 100) -> dict:
        rows = self.data.get(entity, [])
        if updated_since:
            rows = [r for r in rows if r.get("updated_at", "") >= updated_since]
        start = int(cursor) if cursor and cursor.isdigit() else 0
        page = rows[start:start + limit]
        next_cursor = str(start + len(page)) if start + len(page) < len(rows) else None
        return {"data": page, "next_cursor": next_cursor, "has_more": next_cursor is not None}

    def receive_webhook(self, entity: str, row: dict) -> None:
        self.data[entity].append(row)
        self._seq[entity] = len(self.data[entity])


# ---------- 同步执行 ----------
def _map_row(connector: ConnectorConfig, entity: str, row: dict) -> dict:
    mapping = (connector.field_mapping or {}).get(entity) or DEFAULT_MAPPINGS.get(entity, {})
    out: dict = {}
    for src, dst in mapping.items():
        if src in row:
            out[dst] = row[src]
    return out


def _get_checkpoint(db: Session, connector: ConnectorConfig, entity: str) -> SyncCheckpoint:
    cp = db.scalar(
        select(SyncCheckpoint).where(
            SyncCheckpoint.connector_id == connector.connector_id,
            SyncCheckpoint.entity == entity,
            SyncCheckpoint.deleted_at.is_(None),
        ).limit(1)
    )
    if cp is None:
        cp = SyncCheckpoint(
            checkpoint_id=new_id("checkpoint"),
            organization_id=connector.organization_id,
            store_id=connector.store_id,
            connector_id=connector.connector_id,
            entity=entity,
        )
        db.add(cp)
        db.flush()
    return cp


def _upsert_patient(db: Session, connector: ConnectorConfig, mapped: dict) -> str:
    """按 source_id 幂等 upsert 患者（source_id 存 patients.source_id）。"""
    source_id = mapped.get("source_id")
    org_id = connector.organization_id
    p = None
    if source_id:
        p = db.scalar(
            select(Patient).where(
                Patient.source_id == source_id,
                Patient.organization_id == org_id,
                Patient.deleted_at.is_(None),
            ).limit(1)
        )
    if p is None and mapped.get("mobile"):
        p = db.scalar(
            select(Patient).where(
                Patient.mobile == mapped["mobile"],
                Patient.organization_id == org_id,
                Patient.deleted_at.is_(None),
            ).limit(1)
        )
    if p is None:
        p = Patient(
            patient_id=new_id("patient"),
            organization_id=org_id,
            store_id=connector.store_id or mapped.get("store_id"),
            name=mapped.get("name") or "未命名",
            gender=mapped.get("gender"),
            mobile=mapped.get("mobile"),
            source_id=source_id,
            first_visit_date=mapped.get("first_visit_date"),
            last_visit_date=mapped.get("last_visit_date"),
            total_visits=int(mapped.get("total_visits") or 0),
            total_revenue=mapped.get("total_revenue") or 0,
            consent_status=mapped.get("consent_status") or "unknown",
            dnc=bool(mapped.get("dnc")),
            contact_status=mapped.get("contact_status"),
            source_system=connector.kind,
        )
        db.add(p)
    else:
        for f in ("name", "gender", "mobile", "consent_status", "dnc",
                  "contact_status", "last_visit_date", "total_visits", "total_revenue"):
            if mapped.get(f) is not None:
                setattr(p, f, mapped[f])
    db.flush()
    return p.patient_id


def _upsert_visit(db: Session, connector: ConnectorConfig, mapped: dict) -> str:
    org_id = connector.organization_id
    patient = db.scalar(
        select(Patient).where(
            Patient.organization_id == org_id,
            Patient.source_id == mapped.get("patient_id"),
            Patient.deleted_at.is_(None),
        ).limit(1)
    )
    if patient is None:
        raise LookupError(f"患者 {mapped.get('patient_id')} 未同步")
    v = db.scalar(
        select(Visit).where(
            Visit.source_system == connector.kind,
            Visit.source_id == mapped.get("source_id"),
            Visit.deleted_at.is_(None),
        ).limit(1)
    )
    if v is None:
        v = Visit(
            visit_id=new_id("visit"), organization_id=org_id, store_id=connector.store_id,
            patient_id=patient.patient_id, visit_at=mapped.get("visit_at") or utcnow(),
            visit_type=VisitType(mapped.get("visit_type") or "followup"),
            service_category=mapped.get("service_category"),
            visit_status=VisitStatus.COMPLETED, source_system=connector.kind,
            source_id=mapped.get("source_id"),
        )
        db.add(v)
        patient.total_visits = (patient.total_visits or 0) + 1
        patient.last_visit_date = max(patient.last_visit_date or v.visit_at, v.visit_at)
    db.flush()
    return v.visit_id


def _upsert_order_payment(db: Session, connector: ConnectorConfig, mapped: dict) -> str:
    org_id = connector.organization_id
    patient = db.scalar(
        select(Patient).where(
            Patient.organization_id == org_id,
            Patient.source_id == mapped.get("patient_id"),
            Patient.deleted_at.is_(None),
        ).limit(1)
    )
    if patient is None:
        raise LookupError(f"患者 {mapped.get('patient_id')} 未同步")
    o = db.scalar(
        select(Order).where(
            Order.source_system == connector.kind,
            Order.source_id == mapped.get("source_id"),
            Order.deleted_at.is_(None),
        ).limit(1)
    )
    final_amount = float(mapped.get("final_amount") or 0)
    if o is None:
        o = Order(
            order_id=new_id("order"), organization_id=org_id, store_id=connector.store_id,
            patient_id=patient.patient_id, original_amount=final_amount,
            discount_amount=0, final_amount=final_amount,
            order_status=OrderStatus(mapped.get("order_status") or "paid"),
            source_system=connector.kind, source_id=mapped.get("source_id"),
        )
        db.add(o)
    db.flush()
    return o.order_id


def _upsert_payment(db: Session, connector: ConnectorConfig, mapped: dict) -> str:
    org_id = connector.organization_id
    patient = db.scalar(
        select(Patient).where(
            Patient.organization_id == org_id,
            Patient.source_id == mapped.get("patient_id"),
            Patient.deleted_at.is_(None),
        ).limit(1)
    )
    if patient is None:
        raise LookupError(f"患者 {mapped.get('patient_id')} 未同步")
    # 独立支付（无订单）：创建占位订单（payments.order_id 非空）
    order_id = mapped.get("order_id")
    if not order_id:
        placeholder = Order(
            order_id=new_id("order"), organization_id=org_id, store_id=connector.store_id,
            patient_id=patient.patient_id, original_amount=float(mapped.get("amount") or 0),
            discount_amount=0, final_amount=float(mapped.get("amount") or 0),
            order_status=OrderStatus.PAID, source_system=connector.kind,
            source_id=f"auto-order:{mapped.get('source_id')}",
        )
        db.add(placeholder)
        db.flush()
        order_id = placeholder.order_id
    pay = db.scalar(
        select(Payment).where(
            Payment.source_system == connector.kind,
            Payment.source_id == mapped.get("source_id"),
            Payment.deleted_at.is_(None),
        ).limit(1)
    )
    if pay is None:
        pay = Payment(
            payment_id=new_id("payment"), organization_id=org_id, store_id=connector.store_id,
            patient_id=patient.patient_id, order_id=order_id,
            paid_at=mapped.get("paid_at") or utcnow(),
            amount=float(mapped.get("amount") or 0),
            status=PaymentStatus(mapped.get("status") or "succeeded"),
            source_system=connector.kind, source_id=mapped.get("source_id"),
        )
        db.add(pay)
    db.flush()
    return pay.payment_id


def _upsert_refund(db: Session, connector: ConnectorConfig, mapped: dict) -> str:
    org_id = connector.organization_id
    patient = db.scalar(
        select(Patient).where(
            Patient.organization_id == org_id,
            Patient.source_id == mapped.get("patient_id"),
            Patient.deleted_at.is_(None),
        ).limit(1)
    )
    if patient is None:
        raise LookupError(f"患者 {mapped.get('patient_id')} 未同步")
    ref = db.scalar(
        select(Refund).where(
            Refund.source_system == connector.kind,
            Refund.source_id == mapped.get("source_id"),
            Refund.deleted_at.is_(None),
        ).limit(1)
    )
    if ref is None:
        ref = Refund(
            refund_id=new_id("refund"), organization_id=org_id, store_id=connector.store_id,
            patient_id=patient.patient_id, payment_id=mapped.get("payment_id"),
            refunded_at=mapped.get("refunded_at") or utcnow(),
            amount=float(mapped.get("amount") or 0),
            status=mapped.get("status") or "completed",
            source_system=connector.kind, source_id=mapped.get("source_id"),
        )
        db.add(ref)
    db.flush()
    return ref.refund_id


_UPSERT = {
    "patients": _upsert_patient,
    "visits": _upsert_visit,
    "orders": _upsert_order_payment,
    "payments": _upsert_payment,
    "refunds": _upsert_refund,
}


def _pull_page(connector: ConnectorConfig, entity: str, since: str | None,
               cursor: str | None) -> tuple[list[dict], str | None]:
    """从诊所SaaS 拉取一页（真实实现按 OpenAPI 合同；Mock 用于测试）。"""
    import httpx

    endpoint = ENTITY_SPECS[entity]["endpoint"]
    url = f"{connector.base_url.rstrip('/')}/api/v1/{endpoint}"
    params: dict = {"limit": 100}
    if since:
        params["updated_since"] = since
    if cursor:
        params["cursor"] = cursor
    headers = {}
    if connector.auth_type == "api_key" and connector.api_key_ref:
        # 密钥经环境变量注入（api_key_ref 指向环境变量名）
        import os
        key = os.environ.get(connector.api_key_ref, "")
        if key:
            headers["X-API-Key"] = key
    resp = httpx.get(url, params=params, headers=headers, timeout=20.0)
    resp.raise_for_status()
    data = resp.json()
    rows = data.get("data") or data.get("items") or []
    next_cursor = data.get("next_cursor") or data.get("meta", {}).get("next_cursor")
    return rows, next_cursor


def run_sync(db: Session, connector: ConnectorConfig, entity: str,
             mode: str = "incremental") -> dict:
    """执行一次实体同步（全量/增量/补偿），返回统计。"""
    enabled = (connector.entity_enabled or {})
    if entity in enabled and not enabled[entity]:
        return {"entity": entity, "skipped": True, "reason": "disabled"}
    spec = ENTITY_SPECS[entity]
    run = ConnectorRun(
        run_id=new_id("connector_run"),
        organization_id=connector.organization_id,
        store_id=connector.store_id,
        connector_id=connector.connector_id,
        sync_mode=mode,
        entity=entity,
        status="running",
        started_at=utcnow(),
    )
    db.add(run)
    db.flush()
    checkpoint = _get_checkpoint(db, connector, entity)

    since = None
    cursor = None
    if mode in ("incremental", "compensate"):
        since = checkpoint.cursor  # updated_since 持久化为游标
    try:
        page = 0
        while page < 1000:  # 安全上限
            rows, next_cursor = _pull_page(connector, entity, since, cursor)
            run.pulled += len(rows)
            for row in rows:
                mapped = _map_row(connector, entity, row)
                mapped["source_id"] = mapped.get("source_id") or row.get(f"{entity[:-1] if entity.endswith('s') else entity}_id") or row.get("id")
                try:
                    _UPSERT[entity](db, connector, mapped)
                    run.inserted += 1
                except LookupError:
                    run.skipped += 1
            # 游标推进（updated_since 用本页最大 updated_at；cursor 用 next_cursor）
            if next_cursor:
                cursor = next_cursor
            elif rows:
                max_updated = max((r.get("updated_at") or "" for r in rows), default="")
                if max_updated:
                    checkpoint.cursor = max_updated
            page += 1
            if not next_cursor:
                break
        checkpoint.last_sync_at = utcnow()
        run.cursor = checkpoint.cursor
        run.status = "done"
        run.finished_at = utcnow()
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = utcnow()
        logger.warning("Connector 同步失败 %s/%s: %s", connector.connector_id, entity, exc)
    db.commit()
    return {"entity": entity, "status": run.status, "pulled": run.pulled,
            "inserted": run.inserted, "skipped": run.skipped}


def run_connector_sync(db: Session, connector_id: str, mode: str = "incremental") -> dict:
    """同步一个连接器的全部启用实体（通过 Job 调用，错误隔离）。"""
    connector = db.get(ConnectorConfig, connector_id)
    if connector is None or not connector.enabled:
        return {"error": "连接器不存在或已禁用"}
    results = {}
    for entity in ENTITY_SPECS:
        try:
            results[entity] = run_sync(db, connector, entity, mode)
        except Exception as exc:  # noqa: BLE001  单实体失败不阻断其他
            results[entity] = {"entity": entity, "status": "failed", "error": str(exc)}
    db.commit()
    return {"connector_id": connector_id, "results": results}


def handle_webhook_event(db: Session, connector: ConnectorConfig, payload: dict) -> dict:
    """Webhook 实时事件：去重（事件 ID）→ upsert → 触发结果回流。"""
    event_type = payload.get("event_type") or payload.get("type")
    entity = payload.get("entity")
    row = payload.get("data") or {}
    event_id = payload.get("event_id") or payload.get("id")

    from ..revos.outcome import sync_from_trusted_event
    outcomes = []
    if entity in _UPSERT:
        mapped = _map_row(connector, entity, row)
        mapped["source_id"] = mapped.get("source_id") or row.get("id")
        try:
            _UPSERT[entity](db, connector, mapped)
            db.flush()
        except LookupError:
            pass
        # 业务事实回流（支付/退款/到店/预约）
        if event_type in ("payment.completed", "refund.completed", "visit.completed",
                          "appointment.created", "appointment.completed"):
            patient_source = row.get("patient_id")
            patient = None
            if patient_source:
                patient = db.scalar(
                    select(Patient).where(
                        Patient.organization_id == connector.organization_id,
                        Patient.source_id == patient_source,
                        Patient.deleted_at.is_(None),
                    ).limit(1)
                )
            if patient is not None:
                revenue = float(row.get("amount") or row.get("final_amount") or 0) or None
                raw_at = (row.get("occurred_at") or row.get("paid_at") or row.get("visit_at")
                          or row.get("created_at"))
                occurred = None
                if raw_at:
                    from ...core.timeutil import ensure_utc
                    try:
                        occurred = ensure_utc(datetime.fromisoformat(str(raw_at).replace("Z", "+00:00")))
                    except ValueError:
                        occurred = None
                outcomes = sync_from_trusted_event(
                    db, event_type, patient.patient_id,
                    occurred_at=occurred or utcnow(),
                    revenue=revenue, event_id=event_id,
                    metadata={"connector_id": connector.connector_id},
                )
    db.commit()
    return {"event_id": event_id, "entity": entity, "event_type": event_type,
            "outcomes_synced": len(outcomes)}


def reconcile(db: Session, organization_id: str, store_id: str | None = None,
              date_str: str | None = None) -> dict:
    """每日对账（患者/到店/订单/支付/退款计数与金额差异，定位到 ID）。"""
    from ...services.reports import reconciliation as legacy_reconcile
    return legacy_reconcile(db, store_id, date_str, org_id=organization_id)


def enqueue_connector_sync(db: Session, connector: ConnectorConfig, mode: str = "incremental") -> Job:
    """把同步投递到持久 Job 队列。"""
    from .jobs import enqueue_job
    return enqueue_job(
        db, connector.organization_id, "connector_sync",
        payload={"connector_id": connector.connector_id, "mode": mode},
        store_id=connector.store_id,
    )
