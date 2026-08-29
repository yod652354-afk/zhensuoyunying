"""持久 Job（R-07）：多实例安全执行。

- 唯一领取：UPDATE ... WHERE status='pending'（并发下只有一个 worker rowcount=1）；
- lease/heartbeat：超时后可被其他 worker 接管；
- 指数退避 + 最大重试 + 死信；
- 人工重放（requeue）保留审计；
- 进程重启后 pending/leased 超时任务继续执行。
"""
import logging
import threading
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...config import get_settings
from ...core.ids import new_id
from ...core.timeutil import utcnow
from ...database import SessionLocal
from ...models.outbox import Job

logger = logging.getLogger("clinicos.revos.jobs")

LEASE_SECONDS = 300          # 任务租约
BASE_BACKOFF_SECONDS = 10.0  # 退避基数
MAX_ATTEMPTS_DEFAULT = 5


def enqueue_job(
    db: Session,
    organization_id: str,
    job_type: str,
    payload: dict | None = None,
    store_id: str | None = None,
    max_attempts: int = MAX_ATTEMPTS_DEFAULT,
    run_at=None,
) -> Job:
    job = Job(
        job_id=new_id("job"),
        organization_id=organization_id,
        store_id=store_id,
        job_type=job_type,
        payload=payload or {},
        status="pending",
        attempt=0,
        max_attempts=max_attempts,
        next_run_at=run_at,
    )
    db.add(job)
    db.flush()
    return job


def claim_job(db: Session, worker_id: str) -> Job | None:
    """原子领取一个到期任务（多实例唯一：UPDATE 条件含 status）。"""
    now = utcnow()
    # 候选：pending 到期 或 lease 超时（可接管）
    candidate = db.scalar(
        select(Job).where(
            Job.status.in_(["pending", "leased"]),
            Job.deleted_at.is_(None),
            (Job.next_run_at.is_(None)) | (Job.next_run_at <= now),
            (Job.lease_until.is_(None)) | (Job.lease_until < now),
        ).order_by(Job.created_at.asc()).limit(1)
    )
    if candidate is None:
        return None
    # 唯一领取：仅当仍为候选状态时更新（并发下仅一个 worker 成功）
    # synchronize_session=False：避免 ORM 对 naive/aware 时间戳的 Python 求值
    from sqlalchemy import update
    result = db.execute(
        update(Job)
        .where(
            Job.job_id == candidate.job_id,
            Job.status.in_(["pending", "leased"]),
            (Job.next_run_at.is_(None)) | (Job.next_run_at <= now),
            (Job.lease_until.is_(None)) | (Job.lease_until < now),
        )
        .values(status="leased", lease_until=now + timedelta(seconds=LEASE_SECONDS),
                started_at=now, heartbeat_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        return None
    db.commit()
    db.refresh(candidate)
    candidate.run_log = list(candidate.run_log or []) + [{
        "worker": worker_id, "at": now.isoformat(), "action": "claim",
    }]
    db.commit()
    return candidate


def heartbeat(db: Session, job_id: str, worker_id: str) -> None:
    job = db.get(Job, job_id)
    if job is None or job.status != "leased":
        return
    job.heartbeat_at = utcnow()
    job.lease_until = utcnow() + timedelta(seconds=LEASE_SECONDS)
    db.commit()


def finish_job(db: Session, job: Job, worker_id: str, result: dict | None = None) -> None:
    job.status = "done"
    job.finished_at = utcnow()
    job.lease_until = None
    job.last_error = None
    job.run_log = list(job.run_log or []) + [{
        "worker": worker_id, "at": utcnow().isoformat(), "action": "done", "result": result,
    }]
    db.commit()


def fail_job(db: Session, job: Job, worker_id: str, error: str) -> None:
    """失败：指数退避重试；超过最大次数进入死信。"""
    now = utcnow()
    job.attempt += 1
    job.last_error = error[:2000]
    job.last_error_at = now
    job.lease_until = None
    job.run_log = list(job.run_log or []) + [{
        "worker": worker_id, "at": now.isoformat(), "action": "fail", "error": error[:500],
    }]
    if job.attempt >= job.max_attempts:
        job.status = "dead"
        job.finished_at = now
    else:
        job.status = "pending"
        job.next_run_at = now + timedelta(seconds=BASE_BACKOFF_SECONDS * (2 ** (job.attempt - 1)))
    db.commit()


def requeue_job(db: Session, job_id: str, by: str | None = None) -> Job | None:
    """人工重放（死信/失败任务重新入队，保留审计）。"""
    job = db.get(Job, job_id)
    if job is None:
        return None
    if job.status in ("dead", "failed", "done"):
        job.status = "pending"
        job.attempt = 0
        job.next_run_at = None
        job.last_error = None
        job.lease_until = None
        job.requeued_by = by
        job.requeued_at = utcnow()
        job.run_log = list(job.run_log or []) + [{
            "by": by, "at": utcnow().isoformat(), "action": "requeue",
        }]
        db.commit()
    return job


def list_jobs(db: Session, tenant, status: str | None = None, job_type: str | None = None,
              limit: int = 100) -> list[Job]:
    query = select(Job).where(Job.deleted_at.is_(None))
    query = tenant.scope_query(query, Job)
    if status:
        query = query.where(Job.status == status)
    if job_type:
        query = query.where(Job.job_type == job_type)
    return db.scalars(query.order_by(Job.created_at.desc()).limit(min(limit, 500))).all()


# ---------- 后台 worker ----------
def _job_loop(stop_event, interval: int = 5) -> None:
    settings = get_settings()
    worker_id = f"worker_{id(threading.current_thread()):x}"
    while True:
        try:
            with SessionLocal() as db:
                job = claim_job(db, worker_id)
                if job is None:
                    continue
                try:
                    result = _run_job(db, job)
                    finish_job(db, job, worker_id, result)
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    with SessionLocal() as db2:
                        j2 = db2.get(Job, job.job_id)
                        if j2 is not None and j2.status == "leased":
                            fail_job(db2, j2, worker_id, str(exc))
                    logger.exception("Job 执行失败 %s", job.job_id)
        except Exception:  # noqa: BLE001
            pass
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval)


def _run_job(db: Session, job: Job) -> dict | None:
    """按 job_type 分发（注册式，可扩展）。"""
    from .opportunity import expire_opportunities, run_detection
    from .customer_state import ensure_all_customers, recompute_all
    from .attribution import experiment_metrics

    if job.job_type == "daily_ops":
        org_id = job.organization_id
        store_id = job.store_id
        created = ensure_all_customers(db, org_id=org_id, store_id=store_id)
        transitions = recompute_all(db, store_id=store_id, org_id=org_id)
        detection = run_detection(db, store_id=store_id, org_id=org_id)
        expired = expire_opportunities(db)
        db.commit()
        return {"customers_created": created, "state_transitions": transitions,
                "opportunities_created": detection["created"],
                "opportunities_expired": expired}
    if job.job_type.startswith("experiment_calc:"):
        exp_id = job.job_type.split(":", 1)[1]
        metrics = experiment_metrics(db, exp_id)
        db.commit()
        return {"calculated": True, "experiment_id": exp_id}
    db.commit()
    return {"ok": True}


_job_worker = None
_job_stop = None


def start_job_worker(interval: int = 5) -> None:
    global _job_worker, _job_stop
    if _job_worker is not None and _job_worker.is_alive():
        return
    _job_stop = threading.Event()
    _job_worker = threading.Thread(
        target=_job_loop, args=(_job_stop, interval), daemon=True,
        name="revos-job-worker",
    )
    _job_worker.start()


def stop_job_worker() -> None:
    global _job_stop
    if _job_stop is not None:
        _job_stop.set()
