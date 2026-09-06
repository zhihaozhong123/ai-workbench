"""消息持久化 / 编辑 / 版本 / 分页 API。

messages 表是会话展示、编辑、版本、分页的权威来源；前端历史加载、编辑截断、
箭头切换全部走后端，不再依赖前端 localStorage 缓存。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sqlalchemy import select

from infra.db import Conversation, get_db
from infra import messages as msg_repo
from api.deps import get_current_user

router = APIRouter(prefix="/api", tags=["消息"])


class EditMessageRequest(BaseModel):
    conversation_id: str
    message_id: str          # 被编辑 user 消息的逻辑 ID（稳定，跨版本不变）
    content: str             # 编辑后的新内容


async def _check_conv(db, conversation_id: str, user: dict) -> Conversation:
    # db 是 AsyncSession（infra.db.get_db），其 execute 为 async，必须 await；
    # 否则返回的是 coroutine，再链式调 .scalar_one_or_none() 会 AttributeError
    # → 接口 500 → 前端 .catch 仅关编辑框、不触发重新生成，表现为「Send 没反应」。
    res = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = res.scalar_one_or_none()
    if not conv or conv.user_id != user["sub"]:
        raise HTTPException(404, "会话不存在或无权访问")
    return conv


@router.get("/messages")
async def list_messages(
    conversation_id: str,
    limit: int = 50,
    before_seq: int | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    conv = await _check_conv(db, conversation_id, user)
    msgs = await msg_repo.page_messages(db, conversation_id, user["sub"], before_seq, limit)
    return {"conversation_id": conversation_id, "messages": msgs}


@router.post("/messages/edit")
async def edit_message(req: EditMessageRequest, user=Depends(get_current_user), db=Depends(get_db)):
    await _check_conv(db, req.conversation_id, user)
    try:
        await msg_repo.edit_user_message(db, req.conversation_id, user["sub"], req.message_id, req.content)
    except ValueError:
        raise HTTPException(404, "消息不存在或不可编辑")
    msgs = await msg_repo.page_messages(db, req.conversation_id, user["sub"])
    return {"conversation_id": req.conversation_id, "messages": msgs}


@router.get("/messages/versions")
async def get_versions(
    conversation_id: str,
    message_id: str,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _check_conv(db, conversation_id, user)
    vers = await msg_repo.get_versions(db, conversation_id, user["sub"], message_id)
    return {"conversation_id": conversation_id, "message_id": message_id, "versions": vers}
