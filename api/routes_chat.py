"""聊天路由（HTTP SSE 流式）"""
import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from infra.db import Conversation, SessionLocal, get_db
from infra.schemas import ChatRequest, ChatResponse
import core.agent_runner as agent_runner
from observability.logging_config import get_logger
from api.deps import get_current_user

router = APIRouter(prefix="/api", tags=["聊天"])
logger = get_logger(__name__)


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get_conversation(db, conv_id):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    return res.scalar_one_or_none()


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if req.conversation_id:
        conv = await _get_conversation(db, req.conversation_id)
        if not conv or conv.user_id != user["sub"]:
            raise HTTPException(404, "会话不存在或无权访问")
    else:
        conv = Conversation(id=str(uuid.uuid4()), user_id=user["sub"], title=req.message[:20])
        db.add(conv)
        await db.commit()

    client_msg_id = req.client_msg_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    from infra import messages as msg_repo
    async with SessionLocal() as udb:
        await msg_repo.upsert_user_message(udb, conv.id, user["sub"], client_msg_id, req.message)
        await udb.commit()

    # 只把本次运行开始时的业务快照显式传入无状态 Agent
    history = await agent_runner.get_context_messages(user["sub"], conv.id, client_msg_id)
    thread_id = f"{user['sub']}:{conv.id}:run:{run_id}"
    result = await agent_runner.chat(
        user["sub"], thread_id, req.message, history=history,
        skill_id=conv.skill_id or "",
    )

    # 持久化 assistant 回复
    try:
        from infra import messages as msg_repo
        async with SessionLocal() as pdb:
            await msg_repo.upsert_user_message(pdb, conv.id, user["sub"], client_msg_id, req.message)
            await msg_repo.insert_assistant(pdb, conv.id, user["sub"], parent_id=client_msg_id, content=result["reply"])
            await pdb.commit()
    except Exception:
        logger.exception("[HTTP] 持久化消息失败")

    conv.updated_at = _utcnow()
    await db.commit()
    return ChatResponse(
        conversation_id=conv.id, reply=result["reply"], tool_calls=result["tool_calls"]
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest, user=Depends(get_current_user), db=Depends(get_db)):
    if req.conversation_id:
        conv = await _get_conversation(db, req.conversation_id)
        if not conv or conv.user_id != user["sub"]:
            raise HTTPException(404, "会话不存在或无权访问")
    else:
        conv = Conversation(id=str(uuid.uuid4()), user_id=user["sub"], title=req.message[:20])
        db.add(conv)
        await db.commit()

    client_msg_id = req.client_msg_id or str(uuid.uuid4())
    run_id = str(uuid.uuid4())
    thread_id = f"{user['sub']}:{conv.id}:run:{run_id}"
    from infra import messages as msg_repo
    async with SessionLocal() as udb:
        await msg_repo.upsert_user_message(udb, conv.id, user["sub"], client_msg_id, req.message)
        await udb.commit()

    history = await agent_runner.get_context_messages(user["sub"], conv.id, client_msg_id)
    conv.updated_at = _utcnow()
    await db.commit()

    async def event_gen():
        final_reply = ""
        try:
            async for ev in agent_runner.chat_stream(
                user["sub"], thread_id, req.message, history=history,
                skill_id=conv.skill_id or "",
            ):
                if ev.get("type") == "final":
                    final_reply = ev.get("reply") or ""
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            try:
                async with SessionLocal() as pdb:
                    await msg_repo.upsert_user_message(pdb, conv.id, user["sub"], client_msg_id, req.message)
                    await msg_repo.insert_assistant(pdb, conv.id, user["sub"], parent_id=client_msg_id, content=final_reply)
                    await pdb.commit()
            except Exception:
                logger.exception("[HTTP] 持久化消息失败")
        finally:
            yield "data: [DONE]\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


class SignatureReportRequest(BaseModel):
    status: str


@router.post("/client/signature")
async def client_signature_report(req: SignatureReportRequest, user=Depends(get_current_user)):
    if req.status == "developer_id":
        logger.info("[签名] 用户 %s 客户端已用 Developer ID 签名。", user["sub"])
    else:
        logger.warning(
            "[签名] ⚠️ 用户 %s 的客户端签名状态=%s（非 Developer ID）。", user["sub"], req.status,
        )
    return {"ok": True}
