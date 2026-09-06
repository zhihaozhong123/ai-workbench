"""本机控制通道（服务端 ↔ 客户端执行层）。

后端 agent 需要操控用户本机时，不直接 subprocess，而是通过本模块把指令下发到
该用户的客户端（经 Redis pubsub 跨副本路由），客户端（Rust 执行层）在用户授权后
真正执行 open/osascript，再把结果回传，由 agent 继续流程。

通道复用聊天 WebSocket（/ws/chat），消息类型：
  server→client: {"type":"local_control","request_id","action","payload"}
  client→server: {"type":"local_control_result","request_id","result"}
  client→server: {"type":"signature_report","status"}  (status: developer_id/ad_hoc/unsigned)

多副本：请求经 Redis 发布到 control:req:{user_id}，所有持有该 user WS 的副本收到后
推给客户端；回传经 Redis 发布到 control:res:{user_id}，由持有对应 future 的副本唤醒。
"""
import asyncio
import json
import uuid

from infra.state_store import get_redis

log = __import__("logging").getLogger("control")

_REQ_CH = "control:req:{user_id}"
_RES_CH = "control:res:{user_id}"

_pending: dict[str, asyncio.Future] = {}


async def request_local_exec(user_id: str, action: str, payload: dict, timeout: int = 30) -> str:
    """请求该用户的客户端执行本机动作，返回结果字符串（含 ✅ 或 [ERROR]）。"""
    if not user_id:
        return "[ERROR] 未关联用户会话，无法下发本机控制指令。"
    request_id = uuid.uuid4().hex
    loop = asyncio.get_event_loop()
    future: asyncio.Future = loop.create_future()
    _pending[request_id] = future
    try:
        r = get_redis()
        msg = json.dumps({"request_id": request_id, "action": action, "payload": payload})
        await r.publish(_REQ_CH.format(user_id=user_id), msg)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return (
                f"[ERROR] 等待本机执行结果超时（{timeout}s）：客户端可能未连接、"
                f"未授权，或执行失败。请确认你正使用「智作台.app」且已授权相关权限。"
            )
    finally:
        _pending.pop(request_id, None)


async def publish_result(user_id: str, request_id: str, result: str):
    """客户端回传结果：经 Redis 发布，由持有 future 的副本唤醒。"""
    r = get_redis()
    await r.publish(
        _RES_CH.format(user_id=user_id),
        json.dumps({"request_id": request_id, "result": result}),
    )


async def subscribe_requests(user_id: str, send):
    """WS 层调用：订阅该用户的请求频道，收到后通过 send(dict) 推给客户端。"""
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(_REQ_CH.format(user_id=user_id))
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                payload = json.loads(msg["data"])
                await send({"type": "local_control", **payload})
            except Exception:
                continue
    finally:
        try:
            await pubsub.unsubscribe(_REQ_CH.format(user_id=user_id))
        except Exception:
            pass


async def _result_listener():
    """全局启动一次：订阅所有回传频道，唤醒对应 future（跨副本）。"""
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.psubscribe("control:res:*")
    try:
        async for msg in pubsub.listen():
            if msg.get("type") != "pmessage":
                continue
            try:
                data = json.loads(msg["data"])
                fut = _pending.get(data["request_id"])
                if fut and not fut.done():
                    fut.set_result(data.get("result", ""))
            except Exception:
                continue
    finally:
        try:
            await pubsub.punsubscribe("control:res:*")
        except Exception:
            pass


def start_control_listeners():
    """在应用 lifespan 启动一次全局回传监听器。"""
    loop = asyncio.get_event_loop()
    loop.create_task(_result_listener())
