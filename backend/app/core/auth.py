"""认证核心：PBKDF2 密码哈希 + HS256 JWT（标准库实现，无外部依赖）。"""
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

from ..config import get_settings


# ---------- 密码 ----------
def hash_password(password: str, iterations: int = 100_000) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iterations, salt_hex, hash_hex = stored.split("$")
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
        )
        return hmac.compare_digest(digest.hex(), hash_hex)
    except Exception:
        return False


# ---------- JWT ----------
def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def create_token(user_id: str, role: str, username: str, org_id: str | None = None) -> str:
    settings = get_settings()
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode("utf-8"))
    now = int(time.time())
    payload = _b64url(
        json.dumps(
            {
                "sub": user_id,
                "role": role,
                "username": username,
                "org": org_id,
                "iat": now,
                "exp": now + int(settings.token_ttl_hours * 3600),
                "jti": uuid.uuid4().hex,
            },
            ensure_ascii=False,
        ).encode("utf-8")
    )
    signing_input = f"{header}.{payload}"
    signature = hmac.new(
        settings.auth_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64url(signature)}"


class TokenError(Exception):
    pass


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
        signing_input = f"{header_b64}.{payload_b64}"
        expected = hmac.new(
            settings.auth_secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64url_decode(sig_b64), expected):
            raise TokenError("签名无效")
        payload = json.loads(_b64url_decode(payload_b64))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise TokenError("令牌已过期")
        return payload
    except TokenError:
        raise
    except Exception as exc:
        raise TokenError(f"令牌无效: {exc}")