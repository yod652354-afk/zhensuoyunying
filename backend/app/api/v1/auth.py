"""认证 API：注册（API Key 保护）/ 登录 / 当前用户。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.tenant import TenantContext, get_tenant
from ...database import get_db
from ...models import User
from ...services.auth import authenticate, get_current_user, issue_token, register_user

router = APIRouter(tags=["Auth"])


class RegisterBody(BaseModel):
    username: str
    password: str
    name: str
    role: str = "staff"          # boss/staff/admin
    store_id: str | None = None
    staff_id: str | None = None


class LoginBody(BaseModel):
    username: str
    password: str


@router.post("/auth/register", summary="创建账号（服务端，需 API Key）")
def register(body: RegisterBody, request: Request,
             tenant: TenantContext = Depends(get_tenant), db: Session = Depends(get_db)):
    if body.role not in ("boss", "staff", "admin"):
        raise HTTPException(status_code=400, detail="role 必须是 boss/staff/admin")
    user = register_user(db, body.username, body.password, body.name, body.role,
                         organization_id=tenant.organization_id,
                         store_id=body.store_id, staff_id=body.staff_id)
    return {"data": {"user_id": user.user_id, "username": user.username, "role": user.role},
            "meta": {"request_id": request.state.request_id}}


@router.post("/auth/login", summary="登录（返回 JWT）")
def login(body: LoginBody, request: Request, db: Session = Depends(get_db)):
    user = authenticate(db, body.username, body.password)
    return {
        "data": {
            "access_token": issue_token(user),
            "token_type": "bearer",
            "user": {"user_id": user.user_id, "username": user.username,
                     "name": user.name, "role": user.role, "store_id": user.store_id},
        },
        "meta": {"request_id": request.state.request_id},
    }


@router.get("/auth/me", summary="当前用户")
def me(user: User = Depends(get_current_user), request: Request = None):
    return {"data": {"user_id": user.user_id, "username": user.username, "name": user.name,
                     "role": user.role, "store_id": user.store_id},
            "meta": {"request_id": request.state.request_id if request else None}}