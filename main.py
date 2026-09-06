"""智作台 (AI Workbench) API 入口 - 薄入口层，业务逻辑在 api/ core/ infra/ observability/ 模块中"""
import json
import uuid
import asyncio
from datetime import datetime, timezone

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select

from config import settings
from infra.db import User, Conversation, SessionLocal
from infra.security import decode_access_token
from infra.state_store import get_lock, rate_allow
from observability.logging_config import get_logger

# 导入各路由模块
from api.routes_auth import router as auth_router
from api.routes_conversation import router as conversation_router
from api.routes_chat import router as chat_router
from api.routes_messages import router as messages_router
from api.routes_skills import router as skills_router
from api.routes_update import router as update_router

# API 应用实例（由 api/app.py 创建）
from api.app import app

logger = get_logger(__name__)


# --------------------- 注册所有路由 ---------------------
app.include_router(auth_router)
app.include_router(conversation_router)
app.include_router(chat_router)
app.include_router(messages_router)
app.include_router(skills_router)
app.include_router(update_router)


# --------------------- WebSocket 聊天 ---------------------
@app.websocket("/ws/chat")
async def ws_chat(websocket: WebSocket):
    """WebSocket 聊天入口 —— 由于依赖 app 级生命周期与特定上下文，保留在 main.py"""
    import core.agent_runner as agent_runner
    from core.control_manager import subscribe_requests, publish_result

    await websocket.accept()

    token = websocket.query_params.get("token")
    if not token:
        await websocket.send_json({"type": "error", "message": "缺少 token 参数"})
        await websocket.close(code=1008)
        return

    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        await websocket.send_json({"type": "error", "message": "无效或过期的凭证"})
        await websocket.close(code=1008)
        return

    user_id = payload["sub"]

    async with SessionLocal() as db:
        _u = (await db.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
        display_name = ((_u.nickname or "") if _u else "").strip() \
            or (payload.get("username") or "").strip() or "用户"

        async def _send_local(msg):
            try:
                await websocket.send_json(msg)
            except Exception:
                pass

        sub_task = asyncio.create_task(subscribe_requests(user_id, _send_local))
        active_tasks = {}  # run_id -> {"task": Task, "thread_id": str}

        async def _run_chat(
            run_id: str,
            client_msg_id: str,
            content: str,
            mode: str,
            conv_id_inner: str,
            context_before_seq: int | None = None,
            skill_id: str = "",
        ):
            """为单条用户消息启动一次真正独立的 agent 运行。"""
            thread_id = f"{user_id}:{conv_id_inner}:run:{run_id}"
            lock = get_lock(f"run:{thread_id}")
            async with lock:
                loop_detected = False
                final_reply = ""
                try:
                    from infra import messages as msg_repo
                    async with SessionLocal() as udb:
                        await msg_repo.upsert_user_message(
                            udb, conv_id_inner, user_id, client_msg_id, content
                        )
                        await udb.commit()

                    # 每次运行只拿一份自己的数据库快照；Agent 不再读写共享 thread。
                    # context_before_seq 用于编辑历史消息时，只取该消息之前的上下文，
                    # 避免把编辑位置之后的后续消息带入重生成。
                    history = await agent_runner.get_context_messages(
                        user_id,
                        conv_id_inner,
                        exclude_message_id=client_msg_id,
                        before_seq=context_before_seq,
                    )
                    async for ev in agent_runner.chat_stream(
                        user_id, thread_id, content,
                        user_name=display_name, history=history, skill_id=skill_id,
                    ):
                        out = dict(ev)
                        out["run_id"] = run_id
                        await websocket.send_json(out)
                        if ev.get("type") == "final":
                            final_reply = ev.get("reply") or ""
                        if ev.get("type") == "loop_detected":
                            loop_detected = True
                    if not loop_detected:
                        async with SessionLocal() as pdb:
                            await msg_repo.upsert_user_message(
                                pdb, conv_id_inner, user_id, client_msg_id, content
                            )
                            # 编辑（方案 B）：user 消息已整体挪到会话底部，新 assistant 回复
                            # 直接追加到底部即可（与 user 消息相邻）。
                            # context_before_seq 仅用于限制 agent 上下文，不影响插入位置。
                            assistant_seq = None
                            assistant_id = await msg_repo.insert_assistant(
                                pdb,
                                conv_id_inner,
                                user_id,
                                parent_id=client_msg_id,
                                content=final_reply,
                                seq=assistant_seq,
                            )
                            await pdb.commit()
                        await websocket.send_json({
                            "type": "done",
                            "run_id": run_id,
                            "user_message_id": client_msg_id,
                            "assistant_message_id": assistant_id,
                        })
                        return
                    await websocket.send_json({"type": "done", "run_id": run_id})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("[WS] agent 运行异常 user_id=%s run_id=%s", user_id, run_id)
                    try:
                        await websocket.send_json({
                            "type": "error",
                            "message": "服务器开小差了，请稍后再试",
                            "run_id": run_id,
                        })
                    except Exception:
                        pass
                finally:
                    active_tasks.pop(run_id, None)

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    data = json.loads(raw)
                except Exception:
                    await websocket.send_json({"type": "error", "message": "消息需为 JSON 文本"})
                    continue

                t = data.get("type")
                if t == "message":
                    content = (data.get("content") or "").strip()
                    if not content:
                        await websocket.send_json({"type": "error", "message": "content 不能为空"})
                        continue

                    if not await rate_allow(f"ws:{user_id}", settings.rate_limit_per_minute, 60):
                        await websocket.send_json({"type": "error", "message": "消息过于频繁，请稍后再试"})
                        continue

                    conv_id = data.get("conversation_id") or None
                    mode = data.get("mode") or "send"
                    client_msg_id = data.get("client_msg_id") or str(uuid.uuid4())
                    run_id = data.get("run_id") or str(uuid.uuid4())
                    if conv_id:
                        conv = await _get_conversation(db, conv_id)
                        if not conv or conv.user_id != user_id:
                            await websocket.send_json({"type": "error", "message": "会话不存在或无权访问"})
                            continue
                        if conv.title == "新对话":
                            conv.title = content[:20]
                            await db.commit()
                        skill_id = conv.skill_id or ""   # 技能身份以会话行为准（防篡改上行）
                    else:
                        conv = Conversation(id=str(uuid.uuid4()), user_id=user_id, title=content[:20])
                        db.add(conv)
                        await db.commit()
                        await db.refresh(conv)
                        conv_id = conv.id
                        skill_id = ""

                    # 每条运行使用独立的 run_id/thread_id，消息 ID 只负责持久化与版本关联
                    thread_id = f"{user_id}:{conv_id}:run:{run_id}"

                    conv.updated_at = _utcnow()
                    await db.commit()

                    await websocket.send_json({
                        "type": "ready", "user_id": user_id,
                        "conversation_id": conv_id, "thread_id": thread_id,
                        "run_id": run_id, "client_msg_id": client_msg_id,
                    })

                    # 并发支持：不取消正在进行的其它运行，每个消息独立跑一个 task
                    context_before_seq = data.get("context_before_seq")
                    task = asyncio.create_task(
                        _run_chat(
                            run_id,
                            client_msg_id,
                            content,
                            mode,
                            conv_id,
                            context_before_seq=context_before_seq,
                            skill_id=skill_id,
                        )
                    )
                    active_tasks[run_id] = {"task": task, "thread_id": thread_id}

                elif t == "cancel":
                    rid = data.get("run_id") or data.get("client_msg_id") or None
                    if not rid and active_tasks:
                        # 未指定具体运行则取消最近一条
                        rid = next(reversed(active_tasks.keys()))
                    info = active_tasks.pop(rid, None) if rid else None
                    if info:
                        _task = info["task"]
                        if not _task.done():
                            _task.cancel()
                            try:
                                await _task
                            except asyncio.CancelledError:
                                pass
                    await websocket.send_json({"type": "done", "run_id": rid})

                elif t == "local_control_result":
                    await publish_result(user_id, data.get("request_id", ""), data.get("result", ""))

                elif t == "signature_report":
                    _handle_signature_report(user_id, data.get("status"))

                else:
                    await websocket.send_json({"type": "error", "message": "未知消息类型"})
        except WebSocketDisconnect:
            return
        except Exception:
            logger.exception("[WS] 聊天处理异常 user_id=%s", user_id)
            try:
                await websocket.send_json({"type": "error", "message": "服务器开小差了，请稍后再试"})
            except Exception:
                pass
        finally:
            sub_task.cancel()
            for _info in list(active_tasks.values()):
                _t = _info["task"]
                if not _t.done():
                    _t.cancel()


# --------------------- 辅助函数 ---------------------

def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_conversation(db, conv_id):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    return res.scalar_one_or_none()


def _handle_signature_report(user_id: str, status):
    if status == "developer_id":
        logger.info("[签名] 用户 %s 客户端已用 Developer ID 签名，本机控制 TCC 授权可用。", user_id)
    else:
        logger.warning(
            "[签名] ⚠️ 用户 %s 的客户端签名状态=%s（非 Developer ID）。\n"
            "   请为分发的 .app 配置 Apple Developer ID 代码签名并公证。", user_id, status,
        )


# ==================== 启动入口 ====================
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.backend_host, port=settings.backend_port, reload=False)
