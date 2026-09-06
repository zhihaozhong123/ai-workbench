"""
Agent 运行器：为每个请求构造隔离的 Agent 调用上下文。

隔离要点：
- 上下文来源：每轮完整上下文由调用方从业务消息表显式读取（get_context_messages）后传入，
  Agent 不读取也不写入共享 thread，因此并发不会共享或覆盖上下文。
- 长期记忆：通过注入的 RunnableConfig["configurable"]["user_id"] 传给记忆工具，
  即使 Agent 在异步线程池中执行工具，也能正确拿到当前用户 ID，不会串号。
- 并发：编译后的图只包含不可变的模型/工具定义，可被多个请求并发调用；单次运行状态
  只存在于该次 ainvoke/astream 的内存状态中，无共享状态。
"""
import os
import sys
import asyncio
import json
import re
from pathlib import Path
from typing import Any

# 让本模块能直接 import 顶层 agent / tools / memory
_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from langchain_core.messages import (
    HumanMessage,
    AIMessage,
    AIMessageChunk,
    ToolMessage,
    SystemMessage,
)

from core.agent import create_agent
from tools.calc_tool import calculator
from tools.time_tool import get_current_time
from tools.web_search import web_search
from tools.memory_tool import save_to_memory, recall_from_memory
from tools.local_tool import open_application, open_webpage, run_apple_script, find_local_files
import tools.local_tool as local_tool
from core.memory.long_term import init_long_term_memory
from skills.manifest import SkillError, load_manifest
from skills.runtime import run_skill_cli

from observability.logging_config import get_logger

log = get_logger(__name__)

from config import settings

# 连续重复工具调用达到该次数即判定为 loop_detected 并中断，避免 Agent 陷入无效死循环
MAX_REPEAT = 3


# ---------------- 工具集分类（按对话任务类型） ----------------
# 通用对话 = 全部内置工具；技能专属任务 = 通用子集 + 该技能自带的确定性 CLI 工具。
_COMMON_TOOLS = [
    web_search,
    calculator,
    get_current_time,
    save_to_memory,
    recall_from_memory,
]
_GENERAL_EXTRA_TOOLS = [
    open_application,
    open_webpage,
    run_apple_script,
    find_local_files,
]


def _get_tools():
    """通用对话默认工具集合（与历史行为一致：全部内置工具）。"""
    return list(_COMMON_TOOLS) + list(_GENERAL_EXTRA_TOOLS)


def _tool_key(tools) -> tuple:
    return tuple(sorted(t.name for t in tools))


_AGENT_CACHE: dict[tuple, Any] = {}


async def _get_agent(tools: list):
    """按「工具组合」缓存编译图：图不可变、可并发复用；技能工具不同 → 不同图。"""
    key = _tool_key(tools)
    agent = _AGENT_CACHE.get(key)
    if agent is None:
        init_long_term_memory()
        agent = create_agent(tools=tools)
        _AGENT_CACHE[key] = agent
    return agent


async def init_run_agent():
    """兼容入口：初始化通用对话 Agent（无 checkpointer）。"""
    return await _get_agent(_get_tools())


# ---------------- 技能任务上下文（XST-Skill 注入） ----------------
_skill_cli_tools: dict[str, dict] = {}   # slug -> {"version", "tool"}


def _skill_dir_path(slug: str) -> Path:
    return (Path(settings.skills_root) / slug).resolve()


def _build_skill_cli_tool(manifest):
    """把技能的确定性 CLI 包装成 LangChain 工具（工具名 = skill_<slug>）。

    工具由模型在技能任务中按需调度；执行受 Redis 分布式信号量与超时保护
    （见 skills/runtime.py），失败返回结构化 [ERROR] 文本，Agent 不得编造成果。
    """
    from langchain_core.tools import tool as lc_tool

    tool_name = "skill_" + re.sub(r"[^a-zA-Z0-9]", "_", manifest.slug).strip("_")
    description = (
        f"执行技能「{manifest.name}」（slug={manifest.slug}）的确定性工具。\n"
        f"技能说明：{manifest.description or '（无）'}\n"
        "用法：传入该技能所需参数的 JSON 对象（参数含义见对话中的技能说明），"
        "返回技能执行结果的 JSON。\n"
        "技能是确定性子程序：必须依据返回结果如实回答用户，绝不编造成果；"
        "返回 [ERROR] 时应如实转告错误原因。"
    )

    @lc_tool(tool_name, description=description)
    async def _invoke(params: dict) -> str:
        result = await run_skill_cli(
            _skill_dir_path(manifest.slug), manifest, params or {}, user_id=_CURRENT_USER.get() or ""
        )
        if result.get("ok"):
            data = result.get("data")
            if data is None:
                return "（技能执行成功，无返回内容）"
            return json.dumps(data, ensure_ascii=False)[:4000]
        return f"[ERROR] {result.get('error', '技能执行失败')}"

    return _invoke


# contextvar 由 chat/chat_stream 在每次调用入口设置，供工具内取当前用户 ID
from contextvars import ContextVar  # noqa: E402
_CURRENT_USER: ContextVar[str] = ContextVar("skill_current_user", default="")


async def load_skill_context(user_id: str, slug: str) -> dict | None:
    """加载已安装技能的注入上下文（授权 → 磁盘清单 → CLI 工具）。

    返回 None 表示技能当前不可用（未安装 / status=failed / 磁盘清单损坏），
    由调用方决定兜底（不注入、按通用助手继续），保证爆炸半径仅限该技能。
    """
    if not slug:
        return None
    # 1) 授权与安装状态
    try:
        from infra.db import InstalledSkill, SessionLocal
        from sqlalchemy import select

        async with SessionLocal() as sdb:
            inst = (await sdb.execute(
                select(InstalledSkill).where(
                    InstalledSkill.user_id == user_id, InstalledSkill.slug == slug
                )
            )).scalar_one_or_none()
            if not inst or inst.status != "ok":
                log.info("[技能] %s 未安装或状态非 ok，跳过注入 (user=%s)", slug, user_id)
                return None
    except Exception as e:  # noqa: BLE001
        log.warning("[技能] 安装状态检查失败 slug=%s: %s", slug, e)
        return None

    # 2) 磁盘清单（manifest.json 权威；SKILL.md frontmatter 兜底；system_prompt_file 已合并）
    try:
        manifest = load_manifest(_skill_dir_path(slug))
    except (SkillError, OSError) as e:
        log.warning("[技能] 技能清单读取失败 slug=%s: %s", slug, e)
        return None

    # 3) CLI 工具（版本变化时重建，安装升级后自动生效）
    tool = None
    if manifest.has_cli:
        cached = _skill_cli_tools.get(slug)
        if cached and cached["version"] == manifest.version:
            tool = cached["tool"]
        else:
            tool = _build_skill_cli_tool(manifest)
            _skill_cli_tools[slug] = {"version": manifest.version, "tool": tool}

    return {
        "slug": manifest.slug,
        "name": manifest.name,
        "prompt": (
            f"你现在正在执行技能「{manifest.name}」{manifest.emoji}的专属任务。\n"
            f"{manifest.system_prompt}"
        ).strip(),
        "tool": tool,
    }


async def _prepare_run(user_id: str, skill_id: str, history, message: str):
    """组装本次运行的 (工具集, 输入消息, 是否技能任务)。

    技能任务：仅注入通用子集工具 + 该技能 CLI 工具，并把技能说明作为
    SystemMessage 置于上下文最前；通用任务保持原行为（全部内置工具）。
    """
    history = list(history or [])
    if not skill_id:
        return _get_tools(), history + [HumanMessage(content=message)], False

    tools = list(_COMMON_TOOLS)
    ctx = await load_skill_context(user_id, skill_id)
    msgs: list = []
    if ctx:
        if ctx.get("prompt"):
            msgs.append(SystemMessage(content=ctx["prompt"]))
        if ctx.get("tool"):
            tools.append(ctx["tool"])
    else:
        msgs.append(SystemMessage(
            content="当前技能暂时不可用（可能未安装、安装失败或本地文件缺失）。"
                    "请按通用助手方式回答用户，并提醒可到「技能市场」重新安装或稍后重试。"
        ))
    return tools, msgs + history + [HumanMessage(content=message)], True


async def get_context_messages(
    user_id: str,
    conversation_id: str,
    exclude_message_id: str | None = None,
    before_seq: int | None = None,
) -> list:
    """从业务消息表读取一次性、稳定的本轮上下文。

    业务消息表是展示和上下文的唯一来源；返回的 LangChain 消息对象只属于当前
    调用，因此并发不会共享或覆盖上下文。

    Args:
        before_seq: 若指定，仅返回 seq <= before_seq 的消息。用于编辑历史消息后
            重新生成回复时，避免把编辑位置之后的后续消息带入上下文。
    """
    from infra import messages as msg_repo
    from sqlalchemy import text
    from infra.db import SessionLocal

    async with SessionLocal() as sdb:
        await sdb.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        rows = await msg_repo.get_all_current(sdb, conversation_id, user_id)
        context = []
        for r in rows:
            if not r.content:
                continue
            if before_seq is not None and r.seq > before_seq:
                continue
            if exclude_message_id and r.role == "user" and r.message_id == exclude_message_id:
                continue
            if r.role == "user":
                context.append(HumanMessage(content=r.content))
            else:
                context.append(AIMessage(content=r.content))
        await sdb.commit()
    return context


# ---------------- 本地操作「谎报成功」护栏 ----------------
# 涉及「真实操作」的强断言（打开应用 / 打开网页 / 自动化等）。
_LOCAL_OPEN_TOOLS = ("open_application", "open_webpage", "run_apple_script")
_LOCAL_OPEN_CLAIMS = (
    "已打开", "已激活", "已启动", "已经打开", "已经启动", "打开了",
    "已为你打开", "已帮你打开", "已在浏览器", "已在默认浏览器", "已跳转",
    "Safari 已", "浏览器已", "已操作", "已经操作", "操作好", "操作完成",
    "已搜索", "为你搜索", "帮你搜索",
)


def _tool_succeeded(turn_messages, tool_names) -> bool:
    """本轮消息里是否有指定工具的成功回执（含 ✅ 且非 [ERROR]/❌）。"""
    for m in turn_messages:
        if isinstance(m, ToolMessage) and getattr(m, "name", "") in tool_names:
            content = m.content if isinstance(m.content, str) else str(getattr(m, "content", ""))
            if content.startswith("[ERROR]") or "❌" in content:
                continue
            if "✅" in content:
                return True
    return False


def _guard_local_open_claim(reply: str, turn_messages) -> str:
    """若回复宣称已打开/操作了应用或网页，但本轮并无对应工具的成功回执 → 纠正为诚实提示。"""
    if not reply:
        return reply
    if any(kw in reply for kw in _LOCAL_OPEN_CLAIMS) and not _tool_succeeded(turn_messages, _LOCAL_OPEN_TOOLS):
        return (
            "⚠️ 抱歉，我刚才并没有真正打开对应的应用或网页——系统没有检测到打开类工具"
            "（open_application / open_webpage / run_apple_script）返回的成功回执，之前那句「已打开」是不准确的，"
            "我不会再谎报操作结果。\n\n"
            "请再对我说一次「打开 Safari 并搜索深圳今天天气」，我会立即真正调用工具去打开并搜索，"
            "并把工具返回的真实结果给你核对。"
        )
    return reply

async def chat(
    user_id: str, thread_id: str, message: str, user_name: str = "", history: list | None = None,
    skill_id: str = "",
) -> dict:
    local_tool.set_current_user(user_id)
    _CURRENT_USER.set(user_id)
    tools, input_messages, skill_mode = await _prepare_run(user_id, skill_id, history, message)
    agent = await _get_agent(tools)
    config = {
        "configurable": {
            "run_id": thread_id,
            "user_id": user_id,
            "user_name": user_name,
            "recursion_limit": 12,
        }
    }
    try:
        result = await asyncio.wait_for(
            agent.ainvoke({"messages": input_messages}, config=config),
            timeout=settings.chat_timeout_seconds,
        )
    except asyncio.TimeoutError:
        log.warning("[chat] 整体超时 user=%s run=%s (%.0fs)", user_id, thread_id, settings.chat_timeout_seconds)
        return {"reply": "抱歉，这次回复超时了，请稍后再试或换种问法。", "tool_calls": []}
    messages = result.get("messages", [])
    turn_messages = messages[len(history):]
    tool_calls = []
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                tool_calls.append({"name": tc.get("name"), "args": tc.get("args")})
    final = messages[-1] if messages else None
    reply = final.content if isinstance(final, AIMessage) else (getattr(final, "content", "") or "")
    if not skill_mode:
        reply = _guard_local_open_claim(reply, turn_messages)
    return {"reply": reply, "tool_calls": tool_calls}


def _chunk_content_text(content) -> str:
    """把 AIMessageChunk 的 content（str / list[block]）统一成纯文本增量（用空串拼接）。"""
    if not content:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                parts.append(c.get("text", ""))
            else:
                parts.append(str(c))
        return "".join(parts)
    return str(content)


async def chat_stream(
    user_id: str, thread_id: str, message: str, user_name: str = "", history: list | None = None,
    skill_id: str = "",
):
    """流式运行一个完全自包含的 Agent；每个调用拥有自己的内存状态。"""
    local_tool.set_current_user(user_id)
    _CURRENT_USER.set(user_id)
    tools, input_messages, skill_mode = await _prepare_run(user_id, skill_id, history, message)
    agent = await _get_agent(tools)
    config = {
        "configurable": {
            "run_id": thread_id,
            "user_id": user_id,
            "user_name": user_name,
            "recursion_limit": 12,
        }
    }
    n_before = len(input_messages)

    seen = []
    open_tool_names = set()
    loop_detected = False
    last_msg_id = None
    current_is_tool = False
    final_state_messages = []

    try:
        async with asyncio.timeout(settings.chat_timeout_seconds):
            async for mode, payload in agent.astream(
                {"messages": input_messages},
                config=config,
                stream_mode=["messages", "values"],
            ):
                if mode == "values":
                    final_state_messages = payload.get("messages", [])
                    continue

                chunk, _meta = payload
                if not isinstance(chunk, AIMessageChunk):
                    continue

                cid = getattr(chunk, "id", None)
                if cid is not None and cid != last_msg_id:
                    last_msg_id = cid
                    current_is_tool = False

                tcs = getattr(chunk, "tool_call_chunks", None) or []
                if tcs:
                    if not current_is_tool:
                        current_is_tool = True
                        yield {"type": "clear_intermediate"}
                    for tc in tcs:
                        name = tc.get("name")
                        if name and name not in open_tool_names:
                            open_tool_names.add(name)
                            yield {"type": "tool_call", "name": name, "args": {}}
                            seen.append(name)
                            if len(seen) >= MAX_REPEAT and all(s == seen[-1] for s in seen[-MAX_REPEAT:]):
                                loop_detected = True
                                yield {"type": "loop_detected", "message": "检测到重复工具调用，已中断以避免无效循环"}
                                break
                    if loop_detected:
                        break
                    continue

                if not current_is_tool:
                    text = _chunk_content_text(chunk.content)
                    if text:
                        yield {"type": "token", "content": text}

            if loop_detected:
                yield {"type": "final", "reply": ""}
                return

            msgs = final_state_messages
            for m in msgs[n_before:]:
                if isinstance(m, ToolMessage):
                    content = m.content if isinstance(m.content, str) else str(m.content)
                    preview = content[:200] + ("..." if len(content) > 200 else "")
                    yield {"type": "tool_result", "error": content.startswith("[ERROR]"), "preview": preview}

            final = msgs[-1] if msgs else None
            reply = final.content if isinstance(final, AIMessage) else (getattr(final, "content", "") or "")
            if not skill_mode:
                reply = _guard_local_open_claim(reply, msgs[n_before:])
            yield {"type": "final", "reply": reply}
    except asyncio.TimeoutError:
        log.warning("[chat_stream] 整体超时 user=%s run=%s (%.0fs)", user_id, thread_id, settings.chat_timeout_seconds)
        yield {"type": "timeout", "message": "回复超时，请稍后再试或换种问法"}
        return
