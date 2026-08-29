"""执行反馈图片上传（员工完成任务时的反馈通道）。

安全（RevOS P0）：上传必须通过认证（服务端租户上下文），匿名不可上传。
"""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Request, UploadFile

from ...config import get_settings
from ...core.errors import ClinicOSError
from ...core.tenant import TenantContext, get_tenant

router = APIRouter(tags=["Upload"])

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
MAX_SIZE = 8 * 1024 * 1024  # 8MB


@router.post("/upload", summary="上传反馈图片（返回可访问 URL）")
async def upload_image(request: Request, file: UploadFile = File(...),
                       tenant: TenantContext = Depends(get_tenant)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ClinicOSError("INVALID_ARGUMENT", f"仅支持图片格式: {', '.join(ALLOWED_EXT)}")
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise ClinicOSError("INVALID_ARGUMENT", "图片不能超过 8MB")

    settings = get_settings()
    upload_root = Path(settings.upload_dir)
    upload_root.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{ext}"
    (upload_root / filename).write_bytes(content)

    return {
        "data": {"url": f"/uploads/{filename}", "filename": filename, "size": len(content)},
        "meta": {"request_id": request.state.request_id},
    }