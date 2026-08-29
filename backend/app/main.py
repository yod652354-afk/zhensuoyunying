"""ClinicOS 后端入口。

启动：cd backend，执行 .venv\\Scripts\\python -m uvicorn app.main:app --reload --port 8000
文档：http://127.0.0.1:8000/docs （OpenAPI 3.1）
"""
import logging
import warnings
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .api.deps import request_id_middleware
from .api.v1 import analytics, auth, imports, operations, read, templates, uploads, webhooks, write
from .config import get_settings
from .core.errors import register_error_handlers
from .database import Base, SessionLocal, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("clinicos")

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 生产模式安全门禁：拒绝默认开发密钥（RevOS P0）
    from .core.tenant import assert_production_secrets
    assert_production_secrets()

    # 建表（生产建议改用 Alembic 迁移）
    import app.models  # noqa: F401  确保所有模型注册
    Base.metadata.create_all(bind=engine)
    if settings.seed_demo_data:
        with SessionLocal() as db:
            from .seed import run as seed_run
            seed_run(db)
    # 启动 Webhook 持久化重试 worker 与每日自动任务调度
    from .events.dispatcher import start_retry_worker, stop_retry_worker
    from .services.scheduler import start_scheduler, stop_scheduler
    start_retry_worker(interval=60)
    start_scheduler()
    # RevOS：Outbox 发布 worker + 持久 Job worker（R-07）
    from .services.revos.outbox import start_outbox_worker, stop_outbox_worker
    from .services.revos.jobs import start_job_worker, stop_job_worker
    start_outbox_worker(interval=10)
    start_job_worker(interval=5)
    logger.info("ClinicOS 启动完成：%s（Webhook 重试 worker + 每日任务调度 + RevOS Outbox/Job worker 已启动）", settings.database_url)
    yield
    stop_retry_worker()
    stop_scheduler()
    stop_outbox_worker()
    stop_job_worker()


app = FastAPI(
    title=settings.app_name,
    description="诊所 SaaS 经营决策与执行系统 — 数据底座 + REST API + Webhook/Event（需求规格 V1.0）",
    version="1.0.0",
    openapi_version="3.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.middleware("http")(request_id_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_error_handlers(app)

prefix = settings.api_v1_prefix
app.include_router(webhooks.router, prefix=prefix)
app.include_router(read.router, prefix=prefix)
app.include_router(write.router, prefix=prefix)
app.include_router(analytics.router, prefix=prefix)
app.include_router(imports.router, prefix=prefix)
app.include_router(auth.router, prefix=prefix)
app.include_router(operations.router, prefix=prefix)
app.include_router(templates.router, prefix=prefix)
app.include_router(uploads.router, prefix=prefix)
# RevOS 领域 API（机会/决策/方案/审核/企微/小程序/归因/策略）
from .api.v1 import revos
app.include_router(revos.router, prefix=prefix)


# 反馈图片静态目录
from fastapi.staticfiles import StaticFiles
from pathlib import Path
_upload_dir = Path(settings.upload_dir)
_upload_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(_upload_dir)), name="uploads")


@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "app": settings.app_name, "version": "1.0.0"}


@app.get("/", include_in_schema=False)
def root():
    return {"app": settings.app_name, "docs": "/docs", "health": "/health"}