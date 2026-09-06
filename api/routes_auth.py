"""认证路由：注册 / 登录 / 刷新 / 注销 / 个人信息"""
import uuid
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from infra.db import User, get_db
from infra.security import (
    hash_password, verify_password,
    decode_access_token, decode_refresh_token,
)
from infra.schemas import (
    RegisterRequest, LoginRequest, TokenResponse, RefreshRequest, LogoutRequest,
    normalize_account,
)
from infra.state_store import is_revoked, revoke_token
from api.deps import get_current_user, issue_tokens, get_user_by_username

router = APIRouter(prefix="/api", tags=["认证"])

bearer = HTTPBearer()


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest, db=Depends(get_db)):
    account = normalize_account(req.username)
    if len(req.password) < 6:
        raise HTTPException(400, "密码至少 6 位")
    existing = await get_user_by_username(db, account)
    if existing:
        raise HTTPException(409, "该邮箱/手机号已被注册")
    user = User(
        user_id=str(uuid.uuid4()),
        username=account,
        password_hash=hash_password(req.password),
        nickname=req.nickname or "",
    )
    db.add(user)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise HTTPException(409, "该邮箱/手机号已被注册")
    await db.refresh(user)
    return TokenResponse(**issue_tokens(user.user_id, user.username))


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db=Depends(get_db)):
    account = normalize_account(req.username)
    user = await get_user_by_username(db, account)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "邮箱/手机号或密码不正确")
    return TokenResponse(**issue_tokens(user.user_id, user.username))


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    payload = decode_refresh_token(req.refresh_token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="refresh token 无效或已过期")
    if await is_revoked(payload.get("jti")):
        raise HTTPException(status_code=401, detail="refresh token 已失效，请重新登录")
    return TokenResponse(**issue_tokens(payload["sub"], payload["username"], req.refresh_token))


@router.post("/logout")
async def logout(
    req: LogoutRequest,
    creds: HTTPAuthorizationCredentials = Depends(bearer),
):
    """注销：吊销当前 access 与 refresh，立即失效。"""
    acc = decode_access_token(creds.credentials)
    if acc and acc.get("jti"):
        await revoke_token(acc["jti"], acc.get("exp", 0))
    if req.refresh_token:
        ref = decode_refresh_token(req.refresh_token)
        if ref and ref.get("jti"):
            await revoke_token(ref["jti"], ref.get("exp", 0))
    return {"ok": True}


@router.get("/me")
async def me(user=Depends(get_current_user), db=Depends(get_db)):
    res = await db.execute(select(User).where(User.user_id == user["sub"]))
    u = res.scalar_one_or_none()
    if not u:
        raise HTTPException(404, "用户不存在")
    return {
        "user_id": u.user_id,
        "username": u.username,
        "nickname": u.nickname,
        "created_at": u.created_at.isoformat(),
    }
