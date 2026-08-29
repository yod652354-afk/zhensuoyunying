"""服务端到服务端认证：X-API-Key（需求规格 5.1 认证项）。"""
from fastapi import Header, HTTPException

from ..config import get_settings

SCHEME = "ApiKey"


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
    if x_api_key is None:
        raise HTTPException(status_code=401, detail="缺少 X-API-Key 请求头")
    keys = get_settings().api_key_list
    if x_api_key not in keys:
        raise HTTPException(status_code=401, detail="API Key 无效")
    return x_api_key