"""R-07 Outbox / 持久 Job 测试。

- 业务事务回滚时 Outbox 不发布；
- 业务提交后事件最终发布；
- 两个 worker 不会同时执行同一 Job（唯一领取）；
- lease 超时可被其他 worker 接管；
- 达到重试上限进入死信；
- 人工重放保留审计；
- 进程重启任务不丢失（pending 状态持久化）。
"""
from datetime import timedelta

from app.core.ids import new_id
from app.core.timeutil import utcnow
from app.database import SessionLocal
from app.models import Event
from app.models.outbox import Job, OutboxMessage
from app.services.revos import jobs as svc_jobs
from app.services.revos import outbox as svc_outbox


def test_outbox_rollback_does_not_publish():
    """事务回滚 → Outbox 不发布。"""
    with SessionLocal() as db:
        svc_outbox.outbox_publish(db, "test.rollback", "org_test", "test", "obj1",
                                  payload={"x": 1})
        db.rollback()
        assert db.query(OutboxMessage).filter(OutboxMessage.object_id == "obj1").count() == 0


def test_outbox_commit_publishes():
    """事务提交 → Outbox 最终发布为 Event。"""
    with SessionLocal() as db:
        svc_outbox.outbox_publish(db, "test.commit", "org_test", "test", "obj2",
                                  payload={"x": 2})
        db.commit()
    n = svc_outbox.outbox_worker_poll()
    with SessionLocal() as db:
        msg = db.query(OutboxMessage).filter(OutboxMessage.object_id == "obj2").first()
        assert msg.status == "published"
        evt = db.query(Event).filter(Event.event_type == "test.commit").first()
        assert evt is not None


def test_job_unique_claim():
    """两个 worker 不会同时领取同一 Job。"""
    with SessionLocal() as db:
        job = svc_jobs.enqueue_job(db, "org_test", "test_job", payload={"n": 1})
        db.commit()
        job_id = job.job_id
    with SessionLocal() as db:
        j1 = svc_jobs.claim_job(db, "worker_A")
        assert j1 is not None and j1.job_id == job_id
    with SessionLocal() as db:
        j2 = svc_jobs.claim_job(db, "worker_B")  # 已被 A 领取
        assert j2 is None


def test_lease_expiry_takeover():
    """lease 超时可被其他 worker 接管。"""
    with SessionLocal() as db:
        job = svc_jobs.enqueue_job(db, "org_test", "test_lease")
        db.commit()
        job_id = job.job_id
    with SessionLocal() as db:
        svc_jobs.claim_job(db, "worker_A")
        j = db.get(Job, job_id)
        j.lease_until = utcnow() - timedelta(seconds=10)  # 模拟 lease 过期
        db.commit()
    with SessionLocal() as db:
        j2 = svc_jobs.claim_job(db, "worker_B")
        assert j2 is not None and j2.job_id == job_id


def test_job_dead_after_max_attempts():
    """达到最大重试次数进入死信。"""
    with SessionLocal() as db:
        job = svc_jobs.enqueue_job(db, "org_test", "test_dead", max_attempts=2)
        db.commit()
        job_id = job.job_id
    with SessionLocal() as db:
        j = svc_jobs.claim_job(db, "w")
        svc_jobs.fail_job(db, j, "w", "err1")
    with SessionLocal() as db:
        # 退避后 next_run_at 在未来；模拟时间到达后再次领取
        j = db.get(Job, job_id)
        j.next_run_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with SessionLocal() as db:
        j = svc_jobs.claim_job(db, "w")
        assert j is not None
        svc_jobs.fail_job(db, j, "w", "err2")
    with SessionLocal() as db:
        j = db.get(Job, job_id)
        assert j.status == "dead"
        assert j.last_error == "err2"
        # 人工重放
        svc_jobs.requeue_job(db, job_id, by="admin")
        db.refresh(j)
        assert j.status == "pending"
        assert j.requeued_by == "admin"


def test_job_persists_across_restart():
    """pending 任务持久化（模拟重启：新会话仍可读取/领取；后台 worker 可能已执行，均合法）。"""
    with SessionLocal() as db:
        job = svc_jobs.enqueue_job(db, "org_test", "test_persist")
        db.commit()
        job_id = job.job_id
    # 新会话（相当于进程重启后）
    with SessionLocal() as db:
        j = db.get(Job, job_id)
        assert j is not None, "任务必须持久化到数据库"
        assert j.status in ("pending", "leased", "done"), f"状态异常: {j.status}"
    # 若仍 pending，验证可被新 worker 领取
    with SessionLocal() as db:
        j = db.get(Job, job_id)
        if j.status == "pending":
            claimed = svc_jobs.claim_job(db, "new_worker")
            assert claimed is not None
