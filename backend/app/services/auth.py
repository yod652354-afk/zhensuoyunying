"""用户认证服务。"""
from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.auth import TokenError, create_token, decode_token, hash_password, verify_password
from ..core.enums import PersonStatus
from ..core.ids import new_id
from ..database import get_db
from ..models import Organization, User


def register_user(
    db: Session,
    username: str,
    password: str,
    name: str,
    role: str = "staff",
    organization_id: str | None = None,
    store_id: str | None = None,
    staff_id: str | None = None,
) -> User:
    if db.scalar(select(User).where(User.username == username)):
        raise HTTPException(status_code=409, detail="用户名已存在")
    org = db.scalar(select(Organization).limit(1))
    org_id = organization_id or (org.organization_id if org else None)
    user = User(
        user_id=new_id("user"),
        organization_id=org_id or "",
        store_id=store_id,
        username=username,
        password_hash=hash_password(password),
        name=name,
        role=role,
        staff_id=staff_id,
        created_by_type="system",
    )
    db.add(user)
    db.commit()
    return user


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username, User.deleted_at.is_(None)))
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if user.status != PersonStatus.ACTIVE:
        raise HTTPException(status_code=403, detail="账号已停用")
    return user


def issue_token(user: User) -> str:
    return create_token(user.user_id, user.role, user.username, user.organization_id)


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="缺少 Bearer Token")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    user = db.get(User, payload.get("sub"))
    if user is None or user.deleted_at or user.status != PersonStatus.ACTIVE:
        raise HTTPException(status_code=401, detail="用户不存在或已停用")
    return user


def require_role(*roles: str):
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail=f"需要角色: {'/'.join(roles)}")
        return user
    return checker