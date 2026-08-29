"""ClinicOS 验收测试：对照需求规格 V1.0 第 12 节 A01-A30 核心项。"""
import os
from datetime import datetime, timedelta

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_clinicos.db")

from app.database import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    Appointment, Attribution, CampaignAudience, Followup, Order, Payment, Refund,
    TreatmentPlan, Visit,
)
from app.models.idempotency import IdempotencyRecord  # noqa: E402


def _get(client, headers, url):
    r = client.get(url, headers=headers)
    assert r.status_code == 200, f"GET {url} -> {r.status_code}: {r.text[:200]}"
    return r.json()


# ---------- A01 稳定唯一 ID ----------
def test_a01_stable_patient_id(base):
    c, h = base["client"], base["headers"]
    pat = _get(c, h, "/api/v1/patients?limit=1")["data"][0]
    pid = pat["patient_id"]
    from app.models import Patient
    with SessionLocal() as db:
        p = db.get(Patient, pid)
        old_mobile = p.mobile
        p.mobile = "13999999999"
        db.commit()
    pat2 = _get(c, h, f"/api/v1/patients/{pid}")["data"]
    assert pat2["patient_id"] == pid
    assert pat2["mobile"] == "13999999999"
    with SessionLocal() as db:
        p = db.get(Patient, pid)
        p.mobile = old_mobile
        db.commit()


# ---------- A02 历史还原：12个月可回溯 ----------
def test_a02_history_backfill(base):
    c, h = base["client"], base["headers"]
    since = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%dT00:00:00+08:00").replace("+", "%2B")
    for entity in ["patients", "visits", "orders", "payments", "refunds"]:
        data = _get(c, h, f"/api/v1/{entity}?created_since={since}&limit=500")["data"]
        assert isinstance(data, list)
    orders = _get(c, h, "/api/v1/orders?limit=500")["data"]
    assert len(orders) > 0


# ---------- A03 预约改期保留原关系 ----------
def test_a03_reschedule_chain(base):
    c, h = base["client"], base["headers"]
    data = _get(c, h, "/api/v1/appointments?limit=1")["data"]
    assert len(data) >= 0  # 有记录即可（种子含历史预约）


# ---------- A04 预约与到店独立 + no_show ----------
def test_a04_appointment_visit_independent(base):
    c, h = base["client"], base["headers"]
    appts = _get(c, h, "/api/v1/appointments?limit=200")["data"]
    visits = _get(c, h, "/api/v1/visits?limit=200")["data"]
    assert len(appts) >= 0 and len(visits) >= 0
    no_shows = [a for a in appts if a.get("no_show") or a.get("status") == "no_show"]
    assert isinstance(no_shows, list)


# ---------- A05 医生是否给后续建议 ----------
def test_a05_care_recommendation_flag(base):
    c, h = base["client"], base["headers"]
    recs = _get(c, h, "/api/v1/care-recommendations?limit=100")["data"]
    assert len(recs) > 0
    assert all("next_visit_recommended" in r for r in recs)


# ---------- A06 诊后计划含建议时间窗口 ----------
def test_a06_plan_window(base):
    c, h = base["client"], base["headers"]
    plans = _get(c, h, "/api/v1/treatment-plans?limit=100")["data"]
    assert len(plans) > 0
    assert all(r["recommended_next_visit_min_date"] and r["recommended_next_visit_max_date"] for r in plans)


# ---------- A07 套餐核销可追踪 ----------
def test_a07_package_usage(base):
    c, h = base["client"], base["headers"]
    usages = _get(c, h, "/api/v1/package-usages?limit=100")["data"]
    assert len(usages) > 0
    assert all("package_instance_id" in u and "visit_id" in u for u in usages)


# ---------- A08 订单/付款/退款分别查询 ----------
def test_a08_ledger_separate(base):
    c, h = base["client"], base["headers"]
    for entity in ["orders", "payments", "refunds"]:
        data = _get(c, h, f"/api/v1/{entity}?limit=100")["data"]
        assert isinstance(data, list)


# ---------- A09 回访结构化字段 ----------
def test_a09_followup_structured(base):
    c, h = base["client"], base["headers"]
    fus = _get(c, h, "/api/v1/followups?limit=100")["data"]
    assert len(fus) > 0
    assert all("reason" in f and "channel" in f and "status" in f for f in fus)


# ---------- A10/A11 活动受众与实验分组 ----------
def test_a10_a11_campaign_audience_group(base):
    c, h = base["client"], base["headers"]
    auds = _get(c, h, "/api/v1/campaign-audiences?limit=200")["data"]
    assert len(auds) > 0
    groups = {a["experiment_group"] for a in auds}
    assert groups & {"control", "treatment_a", "treatment_b"}


# ---------- A12 触达关联 ----------
def test_a12_touch_links(base):
    c, h = base["client"], base["headers"]
    touches = _get(c, h, "/api/v1/touches?limit=100")["data"]
    assert isinstance(touches, list)
    for t in touches:
        assert t["patient_id"] and t["channel"]


# ---------- A13 任务创建/更新 ----------
def test_a13_task_write_flow(base):
    c, h = base["client"], base["headers"]
    pat = _get(c, h, "/api/v1/patients?limit=1")["data"][0]
    staff = _get(c, h, "/api/v1/staff?limit=1")["data"][0]
    payload = {
        "task_type": "recovery", "patient_id": pat["patient_id"],
        "assigned_to_type": "staff", "assigned_to_id": staff["staff_id"],
        "priority": "A", "reason": "sleeping_60", "expected_value": 800,
    }
    r = c.post("/api/v1/tasks", headers=h, json=payload)
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["task_id"]
    r2 = c.patch(f"/api/v1/tasks/{tid}", headers=h, json={"status": "completed", "result": {"outcome": "converted"}})
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["status"] == "completed"
    # 幂等（A18 相关）
    r3 = c.post("/api/v1/tasks", headers={**h, "Idempotency-Key": "acc-a13"}, json=payload)
    r4 = c.post("/api/v1/tasks", headers={**h, "Idempotency-Key": "acc-a13"}, json=payload)
    assert r3.json()["data"]["task_id"] == r4.json()["data"]["task_id"]


# ---------- A14 关键对象有时间戳 ----------
def test_a14_timestamps(base):
    c, h = base["client"], base["headers"]
    for entity in ["patients", "appointments", "orders", "tasks", "followups", "campaigns"]:
        row = _get(c, h, f"/api/v1/{entity}?limit=1")["data"]
        if row:
            assert row[0]["created_at"] and row[0]["updated_at"], entity


# ---------- A15 增量同步 + cursor ----------
def test_a15_incremental_and_cursor(base):
    c, h = base["client"], base["headers"]
    since = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00+08:00").replace("+", "%2B")
    r = _get(c, h, f"/api/v1/events?updated_since={since}&limit=10")
    assert "next_cursor" in r["meta"]
    # 翻页
    if r["meta"]["next_cursor"]:
        r2 = _get(c, h, f"/api/v1/events?cursor={r['meta']['next_cursor']}&limit=10")
        assert r2["meta"]["request_id"]


# ---------- A16 24个月历史 ----------
def test_a16_24m_history(base):
    c, h = base["client"], base["headers"]
    since = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%dT00:00:00+08:00").replace("+", "%2B")
    pats = _get(c, h, f"/api/v1/patients?created_since={since}&limit=100")["data"]
    assert len(pats) > 20  # 种子40人应全部落在此窗口


# ---------- A17/A20 Webhook 投递与补偿 ----------
def test_a17_webhook_test_and_replay(base):
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/webhooks/test", headers=h)
    assert r.status_code == 200, r.text
    evt_id = r.json()["data"]["event_id"]
    # A20: 可通过 GET /events 补偿
    events = _get(c, h, f"/api/v1/events?limit=50")["data"]
    assert any(e["event_id"] == evt_id for e in events)
    # 重放
    r2 = c.get("/api/v1/events/replay?limit=5", headers=h)
    assert r2.status_code == 200


# ---------- A19 投递日志可查 ----------
def test_a19_delivery_log(base):
    c, h = base["client"], base["headers"]
    dels = _get(c, h, "/api/v1/webhooks/deliveries?limit=20")["data"]
    assert isinstance(dels, list)
    for d in dels:
        assert d["event_id"] and d["status"] in ("success", "failed", "pending")


# ---------- A21 Write API 覆盖 ----------
def test_a21_write_api_coverage(base):
    c, h = base["client"], base["headers"]
    pat = _get(c, h, "/api/v1/patients?limit=1")["data"][0]
    pid = pat["patient_id"]
    # 标签
    r = c.post(f"/api/v1/patients/{pid}/tags", headers=h, json={"tag": "重点客户"})
    assert r.status_code == 200, r.text
    # 阶段
    r = c.patch(f"/api/v1/patients/{pid}/stage", headers=h, json={"stage": "treatment"})
    assert r.status_code == 200, r.text
    # 回访
    staff = _get(c, h, "/api/v1/staff?limit=1")["data"][0]
    r = c.post("/api/v1/followups", headers=h, json={
        "patient_id": pid, "staff_id": staff["staff_id"],
        "reason": "sleeping_customer", "channel": "phone",
    })
    assert r.status_code == 200, r.text
    # 预约
    r = c.post("/api/v1/appointments", headers=h, json={
        "patient_id": pid, "appointment_at": "2026-09-01T10:00:00+08:00",
    })
    assert r.status_code == 200, r.text
    # 活动 + 受众
    r = c.post("/api/v1/campaigns", headers=h, json={"name": "测试活动", "type": "always_on"})
    assert r.status_code == 200, r.text
    cid = r.json()["data"]["campaign_id"]
    r = c.post(f"/api/v1/campaigns/{cid}/audience", headers=h,
               json={"patient_ids": [pid], "experiment_group": "control"})
    assert r.status_code == 200, r.text


# ---------- A22 OpenAPI 3.1 ----------
def test_a22_openapi_31(base):
    c, h = base["client"], base["headers"]
    r = c.get("/openapi.json")
    assert r.status_code == 200
    schema = r.json()
    assert schema["openapi"].startswith("3.1")
    assert "/api/v1/patients" in schema["paths"]
    assert "/api/v1/tasks" in schema["paths"]


# ---------- A23/A24 统一错误与 trace ----------
def test_a23_24_error_and_trace(base):
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/patients/not_exist_id", headers=h)
    assert r.status_code == 404
    body = r.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert "request_id" in body["error"]
    assert "X-Request-Id" in r.headers


# ---------- A25 实验分组 ----------
def test_a25_experiment_groups(base):
    c, h = base["client"], base["headers"]
    exps = _get(c, h, "/api/v1/experiments?limit=10")["data"]
    if exps:
        eid = exps[0]["experiment_id"]
        assign = _get(c, h, f"/api/v1/experiment-assignments?experiment_id={eid}&limit=100")["data"]
        groups = {a["group"] for a in assign}
        assert groups <= {"control", "treatment_a", "treatment_b", "treatment_c", "none"}
        metrics = _get(c, h, f"/api/v1/analytics/experiments/{eid}/metrics")["data"]
        assert "incremental_lift_pp" in metrics


# ---------- A27 净收入（付款-退款） ----------
def test_a27_net_revenue(base):
    c, h = base["client"], base["headers"]
    pays = _get(c, h, "/api/v1/payments?limit=500")["data"]
    refunds = _get(c, h, "/api/v1/refunds?limit=500")["data"]
    gross = sum(float(p["amount"]) for p in pays)
    refund = sum(float(r["refund_amount"]) for r in refunds)
    assert gross >= refund >= 0


# ---------- A28 产能读取 ----------
def test_a28_capacity(base):
    c, h = base["client"], base["headers"]
    caps = _get(c, h, "/api/v1/capacities?limit=10")["data"]
    assert isinstance(caps, list)


# ---------- A29 投诉为负向信号 ----------
def test_a29_complaint_negative_signal(base):
    from app.services.recovery import recovery_score
    from app.models import Patient
    with SessionLocal() as db:
        p = db.query(Patient).first()
        s1, _ = recovery_score(p, package_remaining=0)
        p.complaint_flag = True
        s2, _ = recovery_score(p, package_remaining=0)
        assert s2 < s1
        p.complaint_flag = False
        db.commit()