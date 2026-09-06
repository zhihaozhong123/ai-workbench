"""消息持久化仓库：messages 表是会话展示 / 编辑 / 版本 / 分页的权威来源。

设计要点：
- 编辑 user 消息（方案 B）：归档旧版本（is_current=False）、删除其当前 assistant 回复，
  并将该 user 消息的新版本整体移动到底部（seq = max_seq + 1），原位置之后的消息自然上移。
  重生成该消息的 assistant 回复时追加到底部，且由调用方通过 context_before_seq（取编辑前的
  原始 seq）控制上下文范围，避免引入编辑位置之后的后续消息。
- 每次对话运行前，agent 上下文由本表当前消息重建后传入，不依赖任何共享 thread 历史。
- 版本历史由后端保存，前端箭头切换只回显，无需 localStorage。
"""
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from sqlalchemy.orm import Session

from infra.db import Message

_utcnow = lambda: datetime.now(timezone.utc).replace(tzinfo=None)


async def _lock_conversation_seq(db, conversation_id: str):
    """锁定当前会话的序号分配；事务提交/回滚时自动释放，跨 worker 也有效。"""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"xiaoshutong:messages:{conversation_id}"},
    )


async def get_max_seq(db, conversation_id: str) -> int:
    await _lock_conversation_seq(db, conversation_id)
    res = await db.execute(
        select(func.coalesce(func.max(Message.seq), -1)).where(
            Message.conversation_id == conversation_id
        )
    )
    return res.scalar_one()


async def upsert_user_message(
    db, conversation_id: str, user_id: str, message_id: str, content: str, version: int = 1
) -> int:
    """插入或更新一条 user 消息（保持 message_id 稳定，支持版本演进）。返回 seq。"""
    res = await db.execute(select(Message).where(Message.message_id == message_id))
    rows = res.scalars().all()
    current = next((r for r in rows if r.is_current), None)
    if current is not None:
        current.content = content
        current.is_current = True
        current.updated_at = _utcnow()
        seq = current.seq
    else:
        seq = await get_max_seq(db, conversation_id) + 1
        current = Message(
            message_id=message_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=content,
            version=version,
            seq=seq,
            is_current=True,
        )
        db.add(current)
    await db.flush()
    return seq


async def insert_assistant(
    db,
    conversation_id: str,
    user_id: str,
    parent_id: str,
    content: str,
    seq: int | None = None,
) -> str:
    """删除该 user 消息下旧的 assistant 回复，插入最新的 assistant 回复。返回新 message_id。

    若传入 seq，则在该位置插入，并将 seq 大于等于该值的全部后续消息 seq + 1，
    用于编辑历史消息后把新回复插回原位置、保留下方消息的场景。
    """
    import uuid

    # 同一 parent 只保留最新一条 assistant 回复
    await db.execute(
        Message.__table__.delete().where(
            Message.parent_id == parent_id, Message.role == "assistant"
        )
    )
    if seq is None:
        seq = await get_max_seq(db, conversation_id) + 1
    else:
        # 为新 assistant 腾出位置：后续消息 seq + 1
        await db.execute(
            Message.__table__.update()
            .where(
                Message.conversation_id == conversation_id,
                Message.seq >= seq,
            )
            .values(seq=Message.seq + 1)
        )
    new_id = str(uuid.uuid4())
    db.add(
        Message(
            message_id=new_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role="assistant",
            content=content,
            version=1,
            seq=seq,
            parent_id=parent_id,
            is_current=True,
        )
    )
    await db.flush()
    return new_id


async def edit_user_message(
    db, conversation_id: str, user_id: str, message_id: str, new_content: str
) -> int:
    """编辑一条 user 消息（方案 B）：整段「user + 其 assistant 回复」移动到底部。

    - 归档旧版本（is_current=False），并把旧 assistant 回复文本快照到 reply 供版本切换回显；
    - 删除该 user 消息下当前的 assistant 回复（旧位置清空，稍后重新生成到底部）；
    - 把该 user 消息的新版本插到会话最底部（seq = 当前最大 seq + 1），
      原位置之后的消息因此自然上移。

    返回新的版本号。前端用返回的完整消息列表重排，重生成时把新 assistant 回复追加到底部。
    """
    res = await db.execute(select(Message).where(Message.message_id == message_id))
    rows = res.scalars().all()
    current = next((r for r in rows if r.is_current), None)
    if current is None or current.role != "user":
        raise ValueError("message not found")

    # 捕获当前 assistant 回复（本版本的答案快照，供箭头切换回显）
    res2 = await db.execute(
        select(Message).where(
            Message.parent_id == message_id,
            Message.is_current == True,  # noqa: E712
            Message.role == "assistant",
        )
    )
    old_assistant = res2.scalars().first()
    old_reply = old_assistant.content if old_assistant else ""

    # 旧版本归档
    current.is_current = False
    current.reply = old_reply
    current.updated_at = _utcnow()

    # 删除该 user 消息下当前的 assistant 回复：旧位置需要清空，稍后重新生成到底部
    await db.execute(
        Message.__table__.delete().where(
            Message.parent_id == message_id, Message.role == "assistant"
        )
    )

    # 新版本：整体移动到底部（seq = 当前最大 seq + 1），原位置之后的消息自然上移
    new_seq = await get_max_seq(db, conversation_id) + 1
    new_version = current.version + 1
    db.add(
        Message(
            message_id=message_id,
            conversation_id=conversation_id,
            user_id=user_id,
            role="user",
            content=new_content,
            version=new_version,
            seq=new_seq,
            is_current=True,
            reply=None,
        )
    )

    await db.commit()
    return new_version


async def get_all_current(db, conversation_id: str, user_id: str | None = None):
    """返回当前版本（is_current=True）消息，按 seq 升序。"""
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.is_current == True,  # noqa: E712
    )
    if user_id is not None:
        stmt = stmt.where(Message.user_id == user_id)
    stmt = stmt.order_by(Message.seq.asc())
    res = await db.execute(stmt)
    return list(res.scalars().all())


async def page_messages(
    db, conversation_id: str, user_id: str, before_seq: int | None = None, limit: int = 50
) -> list[dict]:
    """分页返回当前版本消息（含 user 消息的版本历史），用于前端回显。

    返回 seq 升序的最新 limit 条（before_seq 给定时取 seq < before_seq 的部分）。
    """
    stmt = select(Message).where(
        Message.conversation_id == conversation_id,
        Message.is_current == True,  # noqa: E712
    )
    if before_seq is not None:
        stmt = stmt.where(Message.seq < before_seq)
    stmt = stmt.order_by(Message.seq.desc()).limit(limit)
    res = await db.execute(stmt)
    rows = list(reversed(res.scalars().all()))  # 转回 seq 升序

    out = []
    for r in rows:
        item = {
            "message_id": r.message_id,
            "role": r.role,
            "content": r.content or "",
            "version": r.version,
            "seq": r.seq,
            "versions": None,
            "current_version": 0,
        }
        if r.role == "user":
            # 防御性过滤：明确只查 user 角色的版本历史，避免任何 message_id 异常
            # （理论上不应撞 id）混入 assistant 行导致 versions 数组被污染、长度错乱、
            # 切换版本时 assistant 回复错位。
            vres = await db.execute(
                select(Message)
                .where(
                    Message.message_id == r.message_id,
                    Message.role == "user",
                )
                .order_by(Message.version.asc())
            )
            vers = vres.scalars().all()
            item["versions"] = [
                {"version": v.version, "content": v.content or "", "reply": v.reply or ""}
                for v in vers
            ]
            item["current_version"] = next(
                (i for i, v in enumerate(vers) if v.is_current), len(vers) - 1
            )
        out.append(item)
    return out


async def get_versions(db, conversation_id: str, user_id: str, message_id: str) -> list[dict]:
    """返回某条 user 消息的全部版本（用于箭头切换）。"""
    res = await db.execute(
        select(Message)
        .where(Message.message_id == message_id)
        .order_by(Message.version.asc())
    )
    vers = res.scalars().all()
    return [
        {"version": v.version, "content": v.content or "", "reply": v.reply or ""}
        for v in vers
    ]
