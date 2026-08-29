"""R-03 前端认证静态扫描测试。

- 前端源码与构建产物不包含 `dev-key-change-me`；
- 前端源码不引用 `clinicos_api_key` 或 X-API-Key 回退；
- 未登录不发送 X-API-Key（client.js 无该逻辑）。
"""
import re
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"

FORBIDDEN = ["dev-key-change-me", "clinicos_api_key", "'X-API-Key'"]


def _scan_dir(directory: Path) -> list[str]:
    if not directory.exists():
        return []
    hits = []
    for f in directory.rglob("*"):
        if f.suffix not in (".js", ".vue", ".html", ".css", ".mjs"):
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:  # noqa: BLE001
            continue
        for token in FORBIDDEN:
            if token in text:
                hits.append(f"{f.relative_to(directory.parent)}: {token}")
    return hits


def test_frontend_source_no_api_key():
    hits = _scan_dir(FRONTEND_SRC)
    assert not hits, f"前端源码包含 API Key 残留: {hits}"


def test_frontend_dist_no_api_key():
    """构建产物（若存在）不得包含默认密钥。"""
    hits = _scan_dir(FRONTEND_DIST)
    assert not hits, f"前端构建产物包含 API Key: {hits}"


def test_client_uses_only_jwt():
    client_js = FRONTEND_SRC / "api" / "client.js"
    text = client_js.read_text(encoding="utf-8")
    assert "clinicos_token" in text                        # 使用 JWT
    assert "config.headers['X-API-Key']" not in text       # 无 API Key 发送逻辑
    assert "config.headers[\"X-API-Key\"]" not in text
    assert "dev-key-change-me" not in text


def test_router_guards_unauthenticated():
    router_js = FRONTEND_SRC / "router" / "index.js"
    text = router_js.read_text(encoding="utf-8")
    assert "return '/login'" in text
    assert "clinicos_api_key" not in text
