"""Redis 共享协调后端（启用无状态多实例水平扩展）。

所有协调原语（分布式锁 / 全局信号量 / 刷新黑名单 / 频率限制）统一走 Redis，
多个无状态实例共享同一份协调状态（需配合 Chroma server + PostgreSQL）。

``REDIS_URL`` 为必填配置（见 config.py 强校验），未配置会在启动时直接报错，
不再支持进程内降级模式。
"""
import time
import json
import uuid
import asyncio

from config import settings
from observability.logging_config import get_logger

log = get_logger(__name__)

_redis = None
_redis_url = settings.redis_url.strip()
_queue = None


def get_redis():
    """返回 ``redis.asyncio.Redis``（懒加载）。未配置 REDIS_URL 时直接抛错。"""
    global _redis
    if not _redis_url:
        raise RuntimeError(
            "REDIS_URL 未配置：现在为必填项，请在 .env 设置 "
            "REDIS_URL=redis://host:6379/0 后再启动"
        )
    if _redis is None:
        try:
            import redis.asyncio as aioredis
        except ImportError:
            raise RuntimeError(
                "已配置 REDIS_URL 但未安装 redis 库：请 `uv add redis` 后重试"
            )
        _redis = aioredis.from_url(
            _redis_url, decode_responses=True, health_check_interval=30
        )
    return _redis


# ============================ 分布式锁 ============================
class RedisLock:
    """基于 Redis ``SET NX`` 的分布式锁：acquire 自旋重试 + 自动过期（防持有者崩溃死锁）。"""

    def __init__(self, redis, name: str, ttl: int = 120):
        self.redis = redis
        self.name = f"lock:{name}"
        self.ttl = ttl
        self.token = uuid.uuid4().hex

    async def __aenter__(self):
        delay = 0.05
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.ttl * 3
        while True:
            ok = await self.redis.set(self.name, self.token, nx=True, px=self.ttl * 1000)
            if ok:
                return self
            if loop.time() > deadline:
                raise TimeoutError(f"获取分布式锁超时: {self.name}")
            await asyncio.sleep(min(delay, 0.5))
            delay = min(delay * 1.5, 1.0)

    async def __aexit__(self, *exc):
        # 仅当仍持有（token 匹配）时才删，避免误删他人锁（Lua 原子操作）
        await self.redis.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] "
            "then return redis.call('del', KEYS[1]) else return 0 end",
            1, self.name, self.token,
        )


def get_lock(name: str, ttl: int = 120):
    """返回按 name 区分的分布式锁（跨实例串行化）。"""
    return RedisLock(get_redis(), name, ttl)


# ============================ 全局信号量 ============================
# 信号量「当前生效上限」存于 Redis（semcfg:<name>），支持运维热更（无需重启）。
# 各信号量名与默认上限（来自 .env / settings），供启动 seed 与运维接口共用。
SEMAPHORE_NAMES = ("skills_run",)
SEMAPHORE_DEFAULTS = {
    "skills_run": settings.skill_exec_max_concurrency,
}


def _semcfg_key(name: str) -> str:
    return f"semcfg:{name}"


class RedisSemaphore:
    """基于 Redis 原子 incr/decr 的分布式计数信号量（跨实例共享同一闸门）。

    典型用法：
      - ``async with get_semaphore(name, n):``（技能 CLI 子进程执行用）
    acquire 在 Redis 计数达到上限时自旋等待，不占用本地事件循环。

    **动态上限（层 1 运行时可调）**：生效并发上限从 Redis ``semcfg:<cfg_key>`` 实时读取；
    该键不存在时回退到构造时的 ``default``（来自 .env）。运维接口 / worker 限流退避
    都通过修改 ``semcfg:<cfg_key>`` 来调整全局闸门，立即对所有实例生效。

    ``ttl``（秒）：持有者崩溃时计数键的自动过期时间。每次成功 acquire 后刷新 ttl，
    若所有持有者都崩溃（不再有 acquire/refresh），键过期后计数归零，自愈防永久占满。
    默认 None 表示不设过期（建索引等短任务场景）。

    ``cfg_key``：动态上限所读的配置键名。默认取 ``name``；需要让多个信号量共享同一
    上限时应显式传入统一的 cfg_key。
    """

    def __init__(self, redis, name: str, default: int, ttl: int | None = None,
                 cfg_key: str | None = None):
        self.redis = redis
        self.name = f"sem:{name}"
        self.cfg_key = _semcfg_key(cfg_key or name)
        self.default = default
        self.ttl = ttl

    async def acquire(self):
        delay = 0.1
        while True:
            cur = await self.redis.eval(
                # 实时读取动态上限：键不存在则用 default 兜底；达到上限则 incr 后立即 decr 并返回 -1（等待）
                "local limit = tonumber(redis.call('get', KEYS[2]));"
                "if limit == nil then limit = tonumber(ARGV[1]) end;"
                "local cur = redis.call('incr', KEYS[1]);"
                "if cur > limit then redis.call('decr', KEYS[1]); return -1 end;"
                "return cur",
                2, self.name, self.cfg_key, self.default,
            )
            if cur != -1:
                if self.ttl:
                    await self.redis.expire(self.name, self.ttl)
                return
            await asyncio.sleep(min(delay, 1.0))
            delay = min(delay * 1.5, 1.0)

    async def release(self):
        try:
            # 计数减一；归零时删除键，保持 Redis 干净
            await self.redis.eval(
                "local cur = redis.call('decr', KEYS[1]);"
                "if cur <= 0 then redis.call('del', KEYS[1]) end;"
                "return cur",
                1, self.name,
            )
        except Exception:
            pass

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, *exc):
        await self.release()


def get_semaphore(name: str, default: int, ttl: int | None = None,
                  cfg_key: str | None = None):
    return RedisSemaphore(get_redis(), name, default, ttl, cfg_key)


# ---- 动态上限的读写（层 1：运维热更 / 层 2：限流退避共用）----
async def get_semaphore_limit(name: str, default: int | None = None) -> int:
    r = get_redis()
    v = await r.get(_semcfg_key(name))
    if v is None:
        return int(default) if default is not None else SEMAPHORE_DEFAULTS.get(name, 1)
    try:
        return int(v)
    except (TypeError, ValueError):
        return int(default) if default is not None else SEMAPHORE_DEFAULTS.get(name, 1)


async def set_semaphore_limit(name: str, value: int):
    """写生效并发上限（运维热更 / worker 限流退避下调）。下限 1，防误设为 0 卡死。"""
    v = max(1, int(value))
    await get_redis().set(_semcfg_key(name), v)


async def init_semaphore_defaults():
    """启动时仅当键不存在才写入默认上限（setnx）。

    保留运维/限流退避已改过的值，重启不丢失；若从未改过，则从 .env 取默认值初始化。
    """
    r = get_redis()
    for name, val in SEMAPHORE_DEFAULTS.items():
        await r.setnx(_semcfg_key(name), int(val))


# ============================ 刷新黑名单（注销即时失效） ============================
async def revoke_token(jti: str, exp_ts: float):
    """吊销一个 token（填黑名单）。exp_ts 用于 Redis 自动过期清理。"""
    if not jti:
        return
    r = get_redis()
    ttl = max(1, int(exp_ts - time.time()))
    await r.set(f"bl:{jti}", "1", ex=ttl)


async def is_revoked(jti: str | None) -> bool:
    if not jti:
        return False
    r = get_redis()
    return await r.exists(f"bl:{jti}") == 1


# ============================ 频率限制（WebSocket 应用层） ============================
async def rate_allow(key: str, limit: int, window: int) -> bool:
    """滑动窗口限流：window 秒内最多 limit 次。计数落在 Redis（INCR+EXPIRE），
    多个无状态副本共享同一份计数，限流在实例间一致。返回是否放行。"""
    r = get_redis()
    cnt = await r.incr(f"ratelimit:{key}")
    if cnt == 1:
        await r.expire(f"ratelimit:{key}", window)
    return cnt <= limit
