"""数据导入（需求规格 8 数据质量 / 7 历史回溯）：CSV 批量导入 + 质量校验。

安全（RevOS P0）：导入组织固定为服务端租户上下文，客户端不可指定其他组织。
"""
import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from sqlalchemy.orm import Session

from ...core.enums import CustomerStatus, OrderStatus, PaymentStatus, VisitStatus, VisitType
from ...core.errors import ClinicOSError
from ...core.ids import new_id
from ...core.tenant import TenantContext, get_tenant
from ...core.timeutil import ensure_utc
from ...database import get_db
from ...models import Order, OrderItem, Patient, Payment, Visit

router = APIRouter(tags=["Import"])


def _parse_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return ensure_utc(datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
    except ValueError:
        return None


def _validate_store(db, tenant: TenantContext, store_id: str | None) -> None:
    """客户端传入门店必须属于当前租户（禁止扩大权限）。"""
    if store_id:
        from ...models import Store
        s = db.get(Store, store_id)
        if s is None or s.organization_id != tenant.organization_id:
            raise ClinicOSError("FORBIDDEN", "无权导入到其他组织的门店", status_code=403, retryable=False)


@router.post("/import/patients", summary="批量导入患者（CSV）")
async def import_patients(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Form(default=""),
    store_id: str = Form(default=""),
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    content = await file.read()
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    organization_id = tenant.organization_id  # 服务端权威，忽略客户端传入
    _validate_store(db, tenant, store_id)
    imported = 0
    errors = []
    for idx, row in enumerate(reader, start=2):
        try:
            if not row.get("name"):
                errors.append(f"第{idx}行缺 name，跳过")
                continue
            p = Patient(
                patient_id=new_id("patient"),
                organization_id=organization_id,
                store_id=store_id or row.get("store_id"),
                name=row["name"],
                gender=row.get("gender") or None,
                mobile=row.get("mobile") or None,
                source_id=row.get("source_id") or None,
                first_visit_date=_parse_dt(row.get("first_visit_date") or ""),
                last_visit_date=_parse_dt(row.get("last_visit_date") or ""),
                total_visits=int(row.get("total_visits") or 0),
                total_revenue=float(row.get("total_revenue") or 0),
                customer_status=CustomerStatus.NEW,
                contact_status=row.get("contact_status") or None,
                consent_status=row.get("consent_status") or "unknown",
                dnc=(row.get("dnc") or "").lower() in ("1", "true", "yes"),
                source_system="csv_import",
            )
            db.add(p)
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第{idx}行失败: {exc}")
    db.commit()
    return {"data": {"imported": imported, "errors": errors[:20], "total_errors": len(errors)},
            "meta": {"request_id": request.state.request_id}}


@router.post("/import/visits", summary="批量导入到店记录（CSV）")
async def import_visits(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Form(default=""),
    store_id: str = Form(default=""),
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    from ...models import Patient
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))
    organization_id = tenant.organization_id
    _validate_store(db, tenant, store_id)
    imported = 0
    errors = []
    for idx, row in enumerate(reader, start=2):
        try:
            patient = db.query(Patient).filter(Patient.patient_id == row.get("patient_id")).first()
            if patient is None:
                errors.append(f"第{idx}行 patient_id 不存在，跳过")
                continue
            if patient.organization_id != tenant.organization_id:
                errors.append(f"第{idx}行患者属于其他组织，跳过")
                continue
            visit_at = _parse_dt(row.get("visit_at") or "")
            if visit_at is None:
                errors.append(f"第{idx}行 visit_at 无效，跳过")
                continue
            v = Visit(
                visit_id=new_id("visit"),
                organization_id=organization_id,
                store_id=store_id or patient.store_id,
                patient_id=patient.patient_id,
                doctor_id=row.get("doctor_id") or "unknown",
                visit_at=visit_at,
                visit_type=VisitType(row.get("visit_type") or "followup"),
                service_category=row.get("service_category") or None,
                first_visit_flag=(row.get("first_visit_flag") or "").lower() in ("1", "true", "yes"),
                visit_status=VisitStatus.COMPLETED,
                source_system="csv_import",
            )
            db.add(v)
            if patient.first_visit_date is None or v.visit_at < patient.first_visit_date:
                patient.first_visit_date = v.visit_at
            if patient.last_visit_date is None or v.visit_at > patient.last_visit_date:
                patient.last_visit_date = v.visit_at
            patient.total_visits = (patient.total_visits or 0) + 1
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第{idx}行失败: {exc}")
    db.commit()
    return {"data": {"imported": imported, "errors": errors[:20], "total_errors": len(errors)},
            "meta": {"request_id": request.state.request_id}}


@router.post("/import/orders", summary="批量导入订单（CSV）")
async def import_orders(
    request: Request,
    file: UploadFile = File(...),
    organization_id: str = Form(default=""),
    store_id: str = Form(default=""),
    tenant: TenantContext = Depends(get_tenant),
    db: Session = Depends(get_db),
):
    from ...models import Patient
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")))
    organization_id = tenant.organization_id
    _validate_store(db, tenant, store_id)
    imported = 0
    errors = []
    for idx, row in enumerate(reader, start=2):
        try:
            patient = db.query(Patient).filter(Patient.patient_id == row.get("patient_id")).first()
            if patient is None:
                errors.append(f"第{idx}行 patient_id 不存在，跳过")
                continue
            if patient.organization_id != tenant.organization_id:
                errors.append(f"第{idx}行患者属于其他组织，跳过")
                continue
            final_amount = float(row.get("final_amount") or 0)
            o = Order(
                order_id=new_id("order"),
                organization_id=organization_id,
                store_id=store_id or patient.store_id,
                patient_id=patient.patient_id,
                original_amount=float(row.get("original_amount") or final_amount),
                discount_amount=float(row.get("discount_amount") or 0),
                final_amount=final_amount,
                order_status=OrderStatus.PAID,
                source_system="csv_import",
            )
            db.add(o)
            oi = OrderItem(
                order_item_id=new_id("order_item"),
                organization_id=organization_id,
                store_id=store_id or patient.store_id,
                order_id=o.order_id,
                patient_id=patient.patient_id,
                service_id=row.get("service_id") or None,
                quantity=1,
                unit_price=final_amount,
                line_final_amount=final_amount,
                source_system="csv_import",
            )
            db.add(oi)
            pay_at = _parse_dt(row.get("paid_at") or "") or o.created_at
            db.add(Payment(
                payment_id=new_id("payment"),
                organization_id=organization_id,
                store_id=store_id or patient.store_id,
                order_id=o.order_id,
                patient_id=patient.patient_id,
                paid_at=pay_at,
                amount=final_amount,
                status=PaymentStatus.SUCCEEDED,
                source_system="csv_import",
            ))
            patient.total_revenue = float(patient.total_revenue or 0) + final_amount
            imported += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(f"第{idx}行失败: {exc}")
    db.commit()
    return {"data": {"imported": imported, "errors": errors[:20], "total_errors": len(errors)},
            "meta": {"request_id": request.state.request_id}}