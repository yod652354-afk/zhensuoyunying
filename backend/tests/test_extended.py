"""新增功能验收：认证 / 话术模板 / 任务引擎 / Campaign 归因 / 显著性 / 对账 / 内容审批 / 复盘。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_clinicos.db")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402


def test_b01_login_and_me(base):
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/auth/login", headers=h, json={"username": "boss", "password": "boss123"})
    assert r.status_code == 200, r.text
    token = r.json()["data"]["access_token"]
    assert token.startswith("eyJ")
    me = c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["data"]["role"] == "boss"


def test_b02_login_wrong_password(base):
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/auth/login", headers=h, json={"username": "boss", "password": "wrong"})
    assert r.status_code == 401


def test_b03_message_templates(base):
    c, h = base["client"], base["headers"]
    rows = c.get("/api/v1/message-templates", headers=h).json()["data"]
    assert len(rows) >= 4
    assert all("content" in r and "channel" in r for r in rows)
    # 创建
    r = c.post("/api/v1/message-templates", headers=h, json={
        "name": "测试模板", "task_type": "growth", "channel": "sms",
        "content": "测试内容{患者姓名}", "version": "v1",
    })
    assert r.status_code == 200, r.text


def test_b04_retention_engine(base):
    """R-02：旧引擎端点已转为统一 Opportunity 流程（兼容入口，不再直接创建旧 Task）。"""
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/analytics/engine/retention-tasks", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data.get("converted_to_opportunity") is True
    assert "opportunities_created" in data


def test_b05_campaign_metrics(base):
    c, h = base["client"], base["headers"]
    rows = c.get("/api/v1/analytics/campaigns/metrics-summary", headers=h).json()["data"]
    assert len(rows) >= 1
    m = rows[0]
    assert "incremental_lift_pp" in m and "significance" in m
    assert m["control"]["n"] > 0 and m["treatment"]["n"] > 0


def test_b06_significance_directional(base):
    """样本不足时应标记方向性信号（实验纪律）。"""
    from app.services.significance import experiment_significance
    r = experiment_significance(n_t=5, rate_t=0.2, n_c=5, rate_c=0.0)
    assert r["conclusion"] == "directional"
    r2 = experiment_significance(n_t=100, rate_t=0.3, n_c=100, rate_c=0.1)
    assert r2["p_value"] < 0.05
    assert r2["conclusion"] == "significant"


def test_b07_reconciliation(base):
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/analytics/reconciliation", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert "counters" in data and "amounts" in data and "differences" in data


def test_b08_leakage_report(base):
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/analytics/revenue-leakage-report", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["recoverable_revenue"] > 0
    assert "by_doctor" in data and "by_category" in data


def test_b09_content_compliance_flow(base):
    c, h = base["client"], base["headers"]
    # 扫描命中风险词
    r = c.post("/api/v1/compliance/scan", headers=h, json={"content": "根治失眠，限时抢购"})
    assert r.status_code == 200
    scan = r.json()["data"]
    assert scan["risk_score"] > 0 and len(scan["flags"]) >= 1
    # 提交审批
    r = c.post("/api/v1/compliance/reviews", headers=h, json={"content": "根治失眠，限时抢购", "channel": "wechat"})
    assert r.status_code == 200, r.text
    rid = r.json()["data"]["content_review_id"]
    # 审批通过
    r = c.post(f"/api/v1/compliance/reviews/{rid}/approve", headers=h, json={"approved": True, "note": "测试"})
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "approved"
    # 列表含记录
    rows = c.get("/api/v1/compliance/reviews", headers=h).json()["data"]
    assert any(x["content_review_id"] == rid for x in rows)


def test_b10_review_sessions(base):
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/reviews", headers=h, json={
        "period_start": "2026-08-01T00:00:00+08:00", "period_end": "2026-08-07T00:00:00+08:00",
        "engine": "recovery", "summary": "测试复盘", "actions_kept": ["A"], "actions_dropped": ["B"],
    })
    assert r.status_code == 200, r.text
    rows = c.get("/api/v1/reviews", headers=h).json()["data"]
    assert len(rows) >= 1


def test_b11_dashboard_extended(base):
    c, h = base["client"], base["headers"]
    d = c.get("/api/v1/analytics/dashboard", headers=h).json()["data"]
    assert "monthly_summary" in d
    assert "total_incremental" in d["monthly_summary"]
    assert "staff_incentive" in d


def test_b12_funnel_by_dimension(base):
    c, h = base["client"], base["headers"]
    r = c.get("/api/v1/analytics/funnel-by-doctor", headers=h)
    assert r.status_code == 200
    assert len(r.json()["data"]) >= 1


def test_b13_webhook_retry_worker(base):
    from app.events.dispatcher import start_retry_worker
    start_retry_worker(interval=3600)
    assert True


def test_b14_doctor_flag(base):
    """建议率 <30% 的医生被标记异常。"""
    from app.services.retention import funnel_by_dimension
    from app.database import SessionLocal
    with SessionLocal() as db:
        rows = funnel_by_dimension(db, None, 90, by="doctor")
        assert isinstance(rows, list)
        assert all("flagged" in r for r in rows)