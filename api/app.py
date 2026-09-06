"""FastAPI 应用创建、生命周期管理与中间件"""
import os
import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from config import settings
from infra.db import init_db, engine
from infra.security import decode_access_token
import core.agent_runner as agent_runner
from core.control_manager import start_control_listeners
from api.routes_admin import router as admin_router
from observability.metrics import get_metrics, get_metrics_text, get_content_type
from observability.logging_config import setup_logging, get_logger
from observability.audit import log_audit
from observability.ratelimit import rate_limit_middleware
from infra.state_store import (
    get_lock, is_revoked, revoke_token, rate_allow, get_redis,
    init_semaphore_defaults,
)
from fastapi.responses import Response

setup_logging()
logger = get_logger(__name__)

# --------------------- App 创建 ---------------------
# Swagger 页面: /docs。默认开启。DOCS_ENABLED=false 关闭（生产防网页端探测）
_DOCS_ENABLED = os.getenv("DOCS_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")
app = FastAPI(
    title="智作台 API",
    version=settings.app_version,
    docs_url="/docs" if _DOCS_ENABLED else None,
    openapi_url="/openapi.json" if _DOCS_ENABLED else None,
    redoc_url=None,
)

# --------------------- 生命周期 ---------------------

async def _init_services():
    """启动阶段初始化所有核心服务"""
    await init_db()
    # 信号量动态上限 seed：仅当 Redis 中无值时写入 .env 默认值（保留运维热更后的值，重启不丢失）
    try:
        await init_semaphore_defaults()
    except Exception as e:
        logger.warning("[启动] 信号量默认上限 seed 失败（不影响启动，将用默认值）: %s", e)
    start_control_listeners()


async def _shutdown_services():
    """关闭阶段优雅停止所有服务"""
    await engine.dispose()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _init_services()
    yield
    await _shutdown_services()


app.router.lifespan_context = lifespan


# 运维接口（并发上限热更等），由 ADMIN_API_TOKEN 保护
app.include_router(admin_router)


# --------------------- 探针与根路由 ---------------------

@app.get("/")
async def root():
    return {"service": "ai-workbench-api", "docs": "/docs", "status": "ok"}


@app.get("/healthz")
async def healthz():
    from fastapi import HTTPException
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("[healthz] DB 不可用: %s", e)
        raise HTTPException(status_code=503, detail="service unavailable: db")
    return {"status": "ok", "version": settings.app_version}


@app.get("/readyz")
async def readyz():
    from fastapi import HTTPException
    from sqlalchemy import text
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as e:
        logger.error("[readyz] DB 不可用: %s", e)
        raise HTTPException(status_code=503, detail="not ready: db")
    r = get_redis()
    try:
        await r.ping()
    except Exception as e:
        logger.error("[readyz] Redis 不可用: %s", e)
        raise HTTPException(status_code=503, detail="not ready: redis")
    return {"status": "ready", "version": settings.app_version}


@app.get("/metrics")
async def metrics_endpoint():
    return Response(content=get_metrics_text(), media_type=get_content_type())

@app.get("/metrics.json")
async def metrics_json_endpoint():
    return get_metrics()

@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("[未捕获异常] %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "服务器开小差了，请稍后再试"})


# --------------------- 中间件注册 ---------------------

# CORS 配置
# 瘦客户端桌面 App 采用「反射请求 Origin」策略（见下方 cors_reflect 中间件），放行本机
# WebView 任意来源（tauri://localhost / http://localhost / http://127.0.0.1 等）。
# 原因：Tauri 不同版本打包后 WebView 的 Origin 不固定，固定白名单极易漏配，导致
# 注册/登录的 OPTIONS 预检被「Disallowed CORS origin」拦截、前端只拿到网络错误。
# 鉴权靠 Bearer Token（非 Cookie），即便反射任意来源也无跨站凭证泄露风险。

# App 客户端校验
XST_CLIENT_TOKEN = "xst-tv-7f3a"
# 是否强制要求 X-XST-Client 头（仅桌面客户端会带该头）。
# 默认不强制：网页端 / Postman 可直接调用 API（真正的防护是 Bearer 登录鉴权）。
# 上线若只想放行桌面客户端，可设环境变量 XST_REQUIRE_CLIENT=true 恢复此限制。
_FORCE_CLIENT = os.getenv("XST_REQUIRE_CLIENT", "").strip().lower() == "true"


@app.middleware("http")
async def require_app_client(request: Request, call_next):
    if (_FORCE_CLIENT
            and request.url.path.startswith("/api")
            and request.method != "OPTIONS"):
        if request.headers.get("X-XST-Client") != XST_CLIENT_TOKEN:
            return JSONResponse(
                status_code=403,
                content={"detail": "仅智作台桌面客户端可访问（网页端不可用）"},
            )
    return await call_next(request)


# 限流
app.middleware("http")(rate_limit_middleware)

# 审计
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    if not settings.audit_enabled:
        return await call_next(request)
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        user_id = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            p = decode_access_token(auth[7:])
            user_id = p.get("sub") if p else None
        # 审计 IP：经 nginx 反代时优先读 X-Forwarded-For（最左为原始客户端），
        # 直连后端时回退到 X-Real-IP / TCP 对端地址。避免只记到 nginx 内网地址（172.26.0.x）导致无法溯源。
        xff = request.headers.get("X-Forwarded-For", "").strip()
        ip = (xff.split(",")[0].strip()
              or request.headers.get("X-Real-IP", "").strip()
              or (request.client.host if request.client else ""))
        try:
            response = await call_next(request)
        except Exception:
            log_audit(user_id, f"{request.method} {request.url.path}", detail="error", ip=ip)
            raise
        if response.status_code >= 400:
            log_audit(user_id, f"{request.method} {request.url.path}",
                      detail=f"http_{response.status_code}", ip=ip)
        else:
            log_audit(user_id, f"{request.method} {request.url.path}", ip=ip)
        return response
    return await call_next(request)


# CORS 反射中间件（最外层，优先处理预检）
# 对任意来源的 OPTIONS 预检直接回 204 并放行；对实际请求回显其 Origin 并允许携带凭证。
# 放在所有中间件最外层，确保预检在落到具体路由/其它中间件前就被处理。
def _apply_cors(headers, origin):
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    else:
        headers["Access-Control-Allow-Origin"] = "*"
    headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    headers["Access-Control-Allow-Headers"] = (
        "Authorization, Content-Type, Accept, X-XST-Client, X-Requested-With"
    )
    headers["Access-Control-Expose-Headers"] = "*"
    headers["Vary"] = "Origin"


@app.middleware("http")
async def cors_reflect(request: Request, call_next):
    origin = request.headers.get("origin")
    if request.method == "OPTIONS":
        resp = Response(status_code=204)
        _apply_cors(resp.headers, origin)
        return resp
    response = await call_next(request)
    _apply_cors(response.headers, origin)
    return response
