"""API 限流中间件（按客户端 IP，多实例安全）。

设计取舍：
- 用 ``@app.middleware("http")`` 形式而非 ``BaseHTTPMiddleware``，后者会缓冲 StreamingResponse
  的响应体，破坏 /api/chat/stream 的逐字推送（SSE）。本形式只在前置阶段判断，不消费流。
- 限流计数走 ``state_store.rate_allow``（统一抽象，多实例安全）：
    * 计数落在 Redis（INCR+EXPIRE 固定窗口），多个无状态副本共享同一份计数，
      限流在实例间一致，无需依赖前置层。
- 本中间件已多实例安全，无需任何前置层（如 Nginx/Caddy）。
- WebSocket 限流另见 main.py 中对 state_store.rate_allow 的调用，共用同一抽象。
- 注册/登录走更严的 auth 桶，防密码爆破、防刷 JWT。
"""
from fastapi import Request
from fastapi.responses import JSONResponse

from config import settings
from observability.logging_config import get_logger
from infra.state_store import rate_allow

log = get_logger(__name__)

_AUTH_PATHS = {"/api/register", "/api/login"}
# 健康检查 / 指标 / 文档 / 根路径 不限流
_SKIP_PATHS = {"/", "/healthz", "/readyz", "/metrics", "/metrics.json", "/docs", "/openapi.json", "/redoc"}

_WINDOW = 60  # 限流窗口 60 秒


def _client_ip(request: Request) -> str:
    """取真实客户端 IP：优先反向代理透传的 X-Forwarded-For / X-Real-IP，再退回直连 IP。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    real = request.headers.get("x-real-ip")
    if real:
        return real.strip()
    return request.client.host if request.client else "unknown"


async def rate_limit_middleware(request: Request, call_next):
    # CORS 预检 / 免限流路径直接放行，避免拦截 OPTIONS 导致跨域失败
    if request.method == "OPTIONS" or request.url.path in _SKIP_PATHS:
        return await call_next(request)

    ip = _client_ip(request)
    is_auth = request.url.path in _AUTH_PATHS
    limit = settings.rate_limit_auth_per_minute if is_auth else settings.rate_limit_per_minute
    key = f"{ip}:auth" if is_auth else f"{ip}:general"

    # 计数走 state_store.rate_allow：Redis 共享计数，多实例安全
    allowed = await rate_allow(key, limit, _WINDOW)
    if not allowed:
        log.warning("[限流] IP=%s path=%s 触发限流(%d/min)", ip, request.url.path, limit)
        return JSONResponse(
            status_code=429,
            content={"detail": "请求过于频繁，请稍后再试"},
        )
    return await call_next(request)
