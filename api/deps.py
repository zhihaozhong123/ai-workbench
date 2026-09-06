"""鉴权依赖与 DB 查询辅助"""
import uuid
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select

from infra.db import User, get_db
from infra.security import decode_access_token, create_access_token, create_refresh_token
from infra.state_store import is_revoked

bearer = HTTPBearer()


async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> dict:
    payload = decode_access_token(creds.credentials)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="无效或过期的凭证")
    if await is_revoked(payload.get("jti")):
        raise HTTPException(status_code=401, detail="凭证已失效，请重新登录")
    return payload


def issue_tokens(user_id: str, username: str, refresh_token: str | None = None):
    return {
        "access_token": create_access_token(user_id, username),
        "refresh_token": refresh_token or create_refresh_token(user_id, username),
        "token_type": "bearer",
        "user_id": user_id,
        "username": username,
    }


async def get_user_by_username(db, username):
    res = await db.execute(select(User).where(User.username == username))
    return res.scalar_one_or_none()
