"""运维接口：并发上限热更（无需重启）。

保护：请求头 ``X-Admin-Token`` 必须匹配 ``settings.admin_api_token``（来自环境变量
ADMIN_API_TOKEN）。该变量留空时，所有运维接口返回 503（禁用），避免误暴露。

并发上限实际存于 Redis（semcfg:<name>），由本接口 / 技能执行限流退避共用，
对所有无状态副本即时生效。
"""
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from config import settings
from infra.state_store import (
    SEMAPHORE_NAMES, SEMAPHORE_DEFAULTS,
    get_semaphore_limit, set_semaphore_limit,
)

router = APIRouter(prefix="/api/admin", tags=["运维"])

# 并发上限硬顶：防误设过大打爆技能/模型配额
_MAX_LIMIT = 64


def _check(token: str | None):
    expected = settings.admin_api_token.strip()
    if not expected:
        raise HTTPException(status_code=503, detail="未配置 ADMIN_API_TOKEN，运维接口不可用")
    if not token or token != expected:
        raise HTTPException(status_code=403, detail="无效的管理员令牌")


class ConcurrencySet(BaseModel):
    name: str
    value: int


@router.get("/concurrency")
async def get_concurrency(x_admin_token: str | None = Header(None, alias="X-Admin-Token")):
    """查看当前各信号量生效并发上限（已含运维热更后的值）。"""
    _check(x_admin_token)
    out = {}
    for name in SEMAPHORE_NAMES:
        out[name] = await get_semaphore_limit(name)
    return out


@router.post("/concurrency")
async def set_concurrency(req: ConcurrencySet,
                          x_admin_token: str | None = Header(None, alias="X-Admin-Token")):
    """热更某个信号量的并发上限（1~64），无需重启，立即对所有副本生效。

    可选 name：skills_run（技能 CLI 子进程全局并发上限）。
    """
    _check(x_admin_token)
    if req.name not in SEMAPHORE_NAMES:
        raise HTTPException(
            status_code=400,
            detail=f"未知信号量名：{req.name}（可选：{', '.join(SEMAPHORE_NAMES)}）",
        )
    if req.value < 1 or req.value > _MAX_LIMIT:
        raise HTTPException(status_code=400, detail=f"并发上限需在 1~{_MAX_LIMIT} 之间")
    await set_semaphore_limit(req.name, req.value)
    return {"ok": True, "name": req.name, "value": req.value}


@router.post("/concurrency/reset")
async def reset_concurrency(x_admin_token: str | None = Header(None, alias="X-Admin-Token")):
    """将所有信号量并发上限重置回 .env 默认值（强制，忽略运维热更值）。"""
    _check(x_admin_token)
    for name, val in SEMAPHORE_DEFAULTS.items():
        await set_semaphore_limit(name, val)
    out = {}
    for name in SEMAPHORE_NAMES:
        out[name] = await get_semaphore_limit(name)
    return {"ok": True, "defaults": out}
