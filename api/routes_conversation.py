"""会话管理路由"""
import uuid
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from infra.db import Conversation, InstalledSkill, get_db
from infra import messages as msg_repo
from core.memory import long_term as lt
from api.deps import get_current_user

router = APIRouter(prefix="/api", tags=["会话"])


async def _get_conversation(db, conv_id):
    res = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    return res.scalar_one_or_none()


class ConversationIn(BaseModel):
    skill_id: str = ""   # '' = 新建通用对话；否则进入/复用该技能的专属任务会话


@router.post("/conversations")
async def create_conversation(
    body: ConversationIn | None = None,
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    """创建对话。

    - 通用（无 skill_id）：每次新建一条「新对话」；
    - 技能任务（skill_id 非空）：校验已安装后，复用该技能最近一次会话
      （避免同一技能任务产生成堆空会话）；没有则自动创建一条专属会话。
    """
    body = body or ConversationIn()
    user_id = user["sub"]
    skill_id = (body.skill_id or "").strip()
    created = False

    if skill_id:
        # 授权校验：仅已安装且状态 ok 的技能可开任务会话
        inst = (await db.execute(
            select(InstalledSkill).where(
                InstalledSkill.user_id == user_id, InstalledSkill.slug == skill_id
            )
        )).scalar_one_or_none()
        if not inst or inst.status != "ok":
            raise HTTPException(status_code=400, detail="该技能未安装或不可用，无法创建技能任务会话")
        existing = (await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id, Conversation.skill_id == skill_id)
            .order_by(Conversation.updated_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if existing:
            return {
                "conversation_id": existing.id,
                "title": existing.title,
                "skill_id": skill_id,
                "updated_at": existing.updated_at.isoformat(),
                "created": False,
            }
        conv = Conversation(
            id=str(uuid.uuid4()), user_id=user_id,
            title=inst.name or inst.slug, skill_id=skill_id,
        )
        db.add(conv)
        created = True
    else:
        conv = Conversation(id=str(uuid.uuid4()), user_id=user_id, title="新对话", skill_id="")
        db.add(conv)
        created = True
    await db.commit()
    await db.refresh(conv)
    return {
        "conversation_id": conv.id,
        "title": conv.title,
        "skill_id": skill_id,
        "updated_at": conv.updated_at.isoformat(),
        "created": created,
    }


@router.get("/conversations")
async def list_conversations(user=Depends(get_current_user), db=Depends(get_db)):
    res = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user["sub"])
        .order_by(Conversation.updated_at.desc())
    )
    convs = res.scalars().all()
    return [
        {
            "conversation_id": c.id,
            "title": c.title,
            "skill_id": c.skill_id or "",
            "updated_at": c.updated_at.isoformat(),
        }
        for c in convs
    ]


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages_endpoint(
    conversation_id: str, user=Depends(get_current_user), db=Depends(get_db)
):
    conv = await _get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["sub"]:
        raise HTTPException(404, "会话不存在或无权访问")
    rows = await msg_repo.get_all_current(db, conversation_id, user["sub"])
    messages = [
        {"role": r.role, "content": r.content}
        for r in rows
        if r.content
    ]
    return {"conversation_id": conversation_id, "messages": messages}


@router.get("/memory/long_term")
async def list_long_term_memory(
    source: str = "all",
    limit: int = 200,
    user=Depends(get_current_user),
):
    if source not in ("all", "hot", "cold"):
        raise HTTPException(status_code=400, detail="source 仅支持 all / hot / cold")
    limit = max(1, min(int(limit), 1000))
    user_id = user["sub"]
    result: dict = {"user_id": user_id, "source": source}
    if source in ("all", "hot"):
        result["hot"] = await asyncio.to_thread(lt.list_hot_memories, user_id, limit)
    if source in ("all", "cold"):
        result["cold"] = await asyncio.to_thread(lt.list_cold_memories, user_id, limit)
    return result
