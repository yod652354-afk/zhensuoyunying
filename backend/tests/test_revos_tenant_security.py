"""RevOS 租户安全测试（审计报告 P0：list/detail/write/analytics/files 全部强制 scope）。

用例：
- 组织 A 无法读取组织 B 客户（list/detail）；
- 组织 A 无法写入组织 B 数据；
- 员工 JWT 强制 store scope；
- 生产模式拒绝默认开发密钥；
- 匿名请求被拒绝。
"""
import pytest
from fastapi.testclient import TestClient

from app.core.auth import create_token
from app.core.ids import new_id
from app.database import SessionLocal
from app.main import app
from app.models import Organization, Patient, Store, User
from app.core.enums import PersonStatus


def _make_org(name: str):
    from datetime import date
    with SessionLocal() as db:
        org = Organization(organization_id=new_id("organization"), name=name,
                           created_by_type="test")
        db.add(org)
        db.flush()
        store = Store(store_id=new_id("store"), organization_id=org.organization_id,
                      store_name=f"{name}门店", region="test", open_date=date(2026, 1, 1),
                      created_by_type="test")
        db.add(store)
        db.flush()
        org_id = org.organization_id
        store_id = store.store_id
        db.commit()
    return org_id, store_id


def _make_user(org_id: str, store_id: str | None, role: str) -> str:
    with SessionLocal() as db:
        user = User(user_id=new_id("user"), organization_id=org_id, store_id=store_id,
                    username=new_id("u"), password_hash="x", name="u", role=role,
                    status=PersonStatus.ACTIVE, created_by_type="test")
        db.add(user)
        db.flush()
        uid = user.user_id
        db.commit()
    return uid


def _make_patient(org_id: str, store_id: str) -> str:
    with SessionLocal() as db:
        p = Patient(patient_id=new_id("patient"), organization_id=org_id, store_id=store_id,
                    name="租户B客户", created_by_type="test")
        db.add(p)
        db.flush()
        pid = p.patient_id
        db.commit()
    return pid


@pytest.fixture(scope="module")
def second_tenant():
    """组织 B（boss 用户 + 1 患者 + 1 门店）。"""
    org_id, store_id = _make_org("组织B")
    uid = _make_user(org_id, None, "boss")
    pid = _make_patient(org_id, store_id)
    token = create_token(uid, "boss", "boss_b", org_id)
    return {"org_id": org_id, "store_id": store_id, "patient_id": pid,
            "headers": {"Authorization": f"Bearer {token}"}}


def test_anonymous_rejected(client):
    r = client.get("/api/v1/patients?limit=5")
    assert r.status_code == 401
    r2 = client.post("/api/v1/tasks", json={})
    assert r2.status_code == 401


def test_cross_tenant_list_rejected(base, second_tenant):
    """组织 B 的 boss 列患者：只能看到自己组织的数据。"""
    c = base["client"]
    r = c.get("/api/v1/patients?limit=500", headers=second_tenant["headers"])
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data) >= 1
    for p in data:
        assert p["organization_id"] == second_tenant["org_id"]


def test_cross_tenant_detail_rejected(base, second_tenant):
    """组织 B 无法读取组织 A 的患者详情。"""
    c = base["client"]
    # 取组织 A 的一个患者
    a_patients = c.get("/api/v1/patients?limit=1", headers=base["headers"]).json()["data"]
    assert a_patients
    pid = a_patients[0]["patient_id"]
    r = c.get(f"/api/v1/patients/{pid}", headers=second_tenant["headers"])
    assert r.status_code in (403, 404)
    # 组织 B 读取自己的患者 OK
    ok = c.get(f"/api/v1/patients/{second_tenant['patient_id']}", headers=second_tenant["headers"])
    assert ok.status_code == 200


def test_cross_tenant_write_rejected(base, second_tenant):
    """组织 B 不能给组织 A 的患者创建任务（禁止扩大 scope）。"""
    c = base["client"]
    a_patients = c.get("/api/v1/patients?limit=1", headers=base["headers"]).json()["data"]
    pid = a_patients[0]["patient_id"]
    r = c.post("/api/v1/tasks", headers=second_tenant["headers"], json={
        "task_type": "followup", "patient_id": pid,
        "assigned_to_type": "staff", "assigned_to_id": "staff_x",
    })
    assert r.status_code == 403


def test_staff_forced_store_scope(base):
    """员工 JWT 强制 store scope：只能看到自己门店的数据。"""
    with SessionLocal() as db:
        from app.models import Store as StoreModel
        store = db.query(StoreModel).first()
        staff_user = User(user_id=new_id("user"), organization_id=store.organization_id,
                          store_id=store.store_id, username=new_id("u2"), password_hash="x",
                          name="员工", role="staff", status=PersonStatus.ACTIVE, created_by_type="test")
        db.add(staff_user)
        db.flush()
        uid, sid = staff_user.user_id, store.store_id
        db.commit()
    headers = {"Authorization": f"Bearer {create_token(uid, 'staff', 'staff', None)}"}
    c = base["client"]
    r = c.get("/api/v1/patients?limit=500", headers=headers)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data, "员工应能看到本门店患者"
    for p in data:
        assert p["store_id"] == sid


def test_production_rejects_default_secrets(monkeypatch):
    """生产模式启动门禁：默认开发密钥必须被拒绝。"""
    from app.core.tenant import assert_production_secrets
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("API_KEYS", "dev-key-change-me")
    monkeypatch.setenv("AUTH_SECRET", "dev-auth-secret-change-me")
    monkeypatch.setenv("WEBHOOK_SECRET", "dev-webhook-secret-change-me")
    monkeypatch.setenv("API_KEY_ORG_MAP", "{}")
    from app.config import get_settings
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        assert_production_secrets()
    get_settings.cache_clear()
    monkeypatch.setenv("ENVIRONMENT", "development")


def test_opportunity_cross_tenant(base, second_tenant):
    """RevOS 机会池同样强制租户隔离。"""
    c = base["client"]
    r = c.get("/api/v1/opportunities", headers=second_tenant["headers"])
    assert r.status_code == 200
    # 新组织暂无机会
    assert r.json()["data"] == []
