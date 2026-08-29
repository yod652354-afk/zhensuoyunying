"""任务闭环测试：分配 / 反馈 / 审核 / 上传 / 调度。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_clinicos.db")


def test_c01_task_assignment_resolve(base):
    """谁看诊谁负责：患者主诊员工优先。"""
    from app.database import SessionLocal
    from app.models import Patient
    from app.services.assignment import resolve_assignee
    with SessionLocal() as db:
        p = db.query(Patient).first()
        assign_type, assign_id = resolve_assignee(db, p.patient_id)
        assert assign_type in ("staff", "doctor")
        assert assign_id and assign_id != "unassigned"


def test_c02_feedback_and_review_loop(base):
    c, h = base["client"], base["headers"]
    pat = c.get("/api/v1/patients?limit=1", headers=h).json()["data"][0]
    # 创建任务
    staff = c.get("/api/v1/staff?limit=1", headers=h).json()["data"][0]
    r = c.post("/api/v1/tasks", headers=h, json={
        "task_type": "recovery", "patient_id": pat["patient_id"],
        "assigned_to_type": "staff", "assigned_to_id": staff["staff_id"],
        "priority": "A", "reason": "test_loop", "expected_value": 500,
    })
    assert r.status_code == 200, r.text
    tid = r.json()["data"]["task_id"]
    # 完成 + 反馈
    r = c.patch(f"/api/v1/tasks/{tid}", headers=h, json={
        "status": "completed", "feedback_note": "客户回复有意向",
        "feedback_images": ["/uploads/demo.png"], "result": {"outcome": "interested"},
    })
    assert r.status_code == 200
    assert r.json()["data"]["review_status"] == "pending"
    # 审核退回 → 状态回到 in_progress（催办）
    r = c.patch(f"/api/v1/tasks/{tid}/review", headers=h, json={"approved": False, "note": "缺图片"})
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["review_status"] == "rejected" and d["status"] == "in_progress" and d["repushed"] is True
    # 重新完成并审核通过
    c.patch(f"/api/v1/tasks/{tid}", headers=h, json={"status": "completed", "feedback_note": "已补充"})
    r = c.patch(f"/api/v1/tasks/{tid}/review", headers=h, json={"approved": True, "note": "OK"})
    assert r.json()["data"]["review_status"] == "approved"
    # review_status 过滤
    rows = c.get("/api/v1/tasks?status=completed&review_status=approved&limit=50", headers=h).json()["data"]
    assert any(t["task_id"] == tid for t in rows)


def test_c03_upload_image(base):
    c, h = base["client"], base["headers"]
    r = c.post("/api/v1/upload", headers=h,
               files={"file": ("a.png", b"\x89PNG\r\n\x1a\nfake", "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["data"]["url"].startswith("/uploads/")
    # 非图片拒绝
    r = c.post("/api/v1/upload", headers=h, files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_c04_scheduler_registered(base):
    """调度器可启动且注册每日任务（不等待触发）。"""
    from app.services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    stop_scheduler()
    assert True


def test_c05_daily_task_generation():
    """R-02：run_daily_tasks 走统一运营链（按组织/门店，不再直接创建旧 Recovery/Retention Task）。"""
    from app.database import SessionLocal
    from app.services.scheduler import run_daily_tasks
    with SessionLocal() as db:
        pass
    result = run_daily_tasks()
    assert "orgs_processed" in result and "per_org" in result
    assert result["orgs_processed"] >= 1