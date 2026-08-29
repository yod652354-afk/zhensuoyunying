"""客户状态机与三种钱迁移测试（规格 03 §5-6 / 数据门禁）。

- 状态变更保留历史（不可变追加）；
- 三种钱判断返回 reason_codes 与规则版本；
- 客户手机号变化不改变稳定 ID（Customer/Patient 分离）；
- 旧 Patient 数据仍可读取（兼容）。
"""
from datetime import datetime, timedelta

from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Patient
from app.models.revos import Customer, CustomerStateHistory
from app.services.revos import customer_state as svc


def _mk_patient(db, **kw):
    p = Patient(
        patient_id=new_id("patient"), organization_id=kw.get("organization_id", "org_test"),
        store_id=kw.get("store_id"), name=kw.get("name", "测试客户"),
        mobile=kw.get("mobile"), total_visits=kw.get("total_visits", 0),
        total_revenue=kw.get("total_revenue", 0),
        last_visit_date=kw.get("last_visit_date"),
        first_visit_date=kw.get("first_visit_date"),
        consent_status=kw.get("consent_status", "granted"),
        dnc=kw.get("dnc", False), complaint_flag=kw.get("complaint_flag", False),
        created_by_type="test",
    )
    db.add(p)
    db.flush()
    return p


def test_state_history_appended_on_change():
    with SessionLocal() as db:
        p = _mk_patient(db, total_visits=0, last_visit_date=None)
        customer = svc.ensure_customer(db, p.patient_id)
        db.commit()

        h1 = svc.recompute(db, customer.customer_id, trigger_event_id="evt_1")
        db.commit()
        assert h1 is not None, "首次重算应产生初始迁移"
        assert h1.lifecycle_to.value == "lead"
        assert h1.money_to.value == "future"
        assert h1.rule_version

        # 客户到店 → 状态迁移
        p.total_visits = 5
        p.last_visit_date = utcnow() - timedelta(days=5)
        db.commit()
        h2 = svc.recompute(db, customer.customer_id, trigger_event_id="evt_2")
        db.commit()
        assert h2 is not None
        assert h2.lifecycle_to.value in ("active", "in_service", "booked")
        assert h2.lifecycle_from == "lead"

        # 再次重算（无变化）不追加
        h3 = svc.recompute(db, customer.customer_id)
        db.commit()
        assert h3 is None

        # 历史完整保留（首次记录 from 可为初始默认值）
        rows = db.query(CustomerStateHistory).filter(
            CustomerStateHistory.customer_id == customer.customer_id
        ).order_by(CustomerStateHistory.effective_from.asc()).all()
        assert len(rows) >= 2
        assert rows[-1].lifecycle_from != rows[-1].lifecycle_to.value or rows[-1].lifecycle_from == "lead"


def test_three_money_reason_codes():
    with SessionLocal() as db:
        # 沉睡客户 → past money
        p = _mk_patient(db, total_visits=6, total_revenue=3000,
                        last_visit_date=utcnow() - timedelta(days=120))
        customer = svc.ensure_customer(db, p.patient_id)
        db.commit()
        svc.recompute(db, customer.customer_id)
        db.commit()
        db.refresh(customer)
        assert customer.money_state.value == "past"
        assert customer.state_reason_codes
        assert any("DORMANT" in c or "LIFECYCLE" in c for c in (customer.state_reason_codes or []))


def test_mobile_change_keeps_stable_id():
    """手机号变化不改变稳定 customer_id。"""
    with SessionLocal() as db:
        p = _mk_patient(db, total_visits=2, last_visit_date=utcnow() - timedelta(days=10),
                        mobile="13800000001")
        customer = svc.ensure_customer(db, p.patient_id)
        cid = customer.customer_id
        db.commit()
        svc.recompute(db, cid)  # 触发身份同步（mobile → CustomerIdentity）
        db.commit()
        # 手机号变更
        p.mobile = "13900000002"
        db.commit()
        customer2 = svc.ensure_customer(db, p.patient_id)
        assert customer2.customer_id == cid
        # 身份同步含历史（valid_to 归档旧身份）
        from app.models.revos import CustomerIdentity
        identities = db.query(CustomerIdentity).filter(
            CustomerIdentity.customer_id == cid).all()
        assert len(identities) >= 1


def test_old_patient_data_still_readable(base):
    """旧 Patient 数据仍可通过既有 API 读取（兼容性）。"""
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/patients?limit=5", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) > 0


def test_daily_recompute_all():
    with SessionLocal() as db:
        p = _mk_patient(db, total_visits=0, last_visit_date=None)
        svc.ensure_customer(db, p.patient_id)
        db.commit()
        transitions = svc.recompute_all(db, org_id="org_test")
        assert transitions >= 1
