"""
Agent 核心 - 使用 LangGraph create_react_agent 创建 ReAct 智能体

系统提示词已拆分到同目录 prompts/ 下的 4 个 Markdown 文档：
- AGENTS.md : 身份 + 行为准则（主指令文件）
- SOUL.md   : 灵魂 / 性格 / 语气
- USER.md   : 用户画像模板（静态说明；真实画像运行时动态注入）
- TOOLS.md  : 工具与核心能力清单

运行时由 load_static_prompt() 按固定顺序拼装为「静态系统提示词」；
再由 dynamic_prompt() 在每轮对话前，按当前用户 user_id 从长期记忆检索画像，
以「## 已知用户画像」段落动态追加到系统提示词——做到"越聊越懂你"，
且不写入短期记忆历史，不污染对话记录。
"""
import asyncio
import pathlib

from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent

from core.memory import long_term as lt
from config import settings
from observability.logging_config import get_logger

log = get_logger(__name__)

# ==================== 静态系统提示词（来自 prompts/*.md） ====================
_PROMPT_DIR = pathlib.Path(__file__).parent / "prompts"
# 拼装顺序：身份/准则 → 灵魂/性格 → 用户画像说明 → 工具清单
_PROMPT_FILES = ("AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md")


def load_static_prompt() -> str:
    """从 prompts/ 目录按固定顺序读取并拼装静态系统提示词。"""
    parts = []
    for name in _PROMPT_FILES:
        p = _PROMPT_DIR / name
        if p.exists():
            text = p.read_text(encoding="utf-8").strip()
            if text:
                parts.append(text)
    return "\n\n".join(parts)


STATIC_SYSTEM_PROMPT = load_static_prompt()

# 兼容旧引用：仍暴露 SYSTEM_PROMPT（等于静态部分，不含动态画像）
SYSTEM_PROMPT = STATIC_SYSTEM_PROMPT


# ==================== 动态用户画像注入 ====================
# 轻量缓存：同一轮 ReAct 循环内 LLM 会被多次调用（工具调用后再进 LLM），
# 而"最后一条用户消息(query)"在一轮内保持不变，故按 (user_id, query) 缓存检索结果，
# 避免一轮对话内重复检索长期记忆。缓存超过上限时清空，防止无限增长。
_PROFILE_CACHE: dict[tuple[str, str], str] = {}
_PROFILE_CACHE_MAX = 256


def _extract_last_user_text(messages) -> str:
    """取最后一条 HumanMessage 的纯文本，作为记忆检索的 query。"""
    for m in reversed(list(messages)):
        if isinstance(m, HumanMessage):
            c = m.content
            if isinstance(c, str):
                return c.strip()
            if isinstance(c, list):
                parts = [b.get("text", "") if isinstance(b, dict) else str(b) for b in c]
                return "\n".join(p for p in parts if p).strip()
    return ""


def _recall_profile(user_id: str, query: str) -> str:
    """按 user_id + query 检索长期记忆画像（带轻量缓存）。返回可注入的画像文本，或空串。"""
    if not user_id or not query or not lt.is_ready():
        return ""
    key = (user_id, query)
    if key in _PROFILE_CACHE:
        return _PROFILE_CACHE[key]

    profile = ""
    try:
        result = lt.recall_memories(query, user_id, top_k=5)
        # recall_memories 未命中时返回固定文案，此处过滤掉
        if result and "没有找到相关信息" not in result:
            profile = result
    except Exception as e:
        log.warning("[用户画像注入] 检索失败: %s", e)
        profile = ""

    if len(_PROFILE_CACHE) >= _PROFILE_CACHE_MAX:
        _PROFILE_CACHE.clear()
    _PROFILE_CACHE[key] = profile
    return profile


async def dynamic_prompt(state, config: RunnableConfig):
    """LangGraph prompt 回调：在静态系统提示词后动态追加「已知用户画像」。

    - user_id 从注入的 config.configurable.user_id 读取（多用户并发安全）。
    - query 取本轮最后一条用户消息；检索在线程池执行，避免阻塞事件循环。
    - 返回值仅用于本次 LLM 调用，不参与短期记忆历史的持久化，故不污染对话记录。
    """
    messages = state["messages"] if isinstance(state, dict) else getattr(state, "messages", [])
    parts = [STATIC_SYSTEM_PROMPT]

    user_id = ""
    user_name = ""
    if config:
        cfg = config.get("configurable") or {}
        user_id = cfg.get("user_id") or ""
        user_name = cfg.get("user_name") or ""

    # 当前用户名称：默认用登录昵称/账号称呼，除非用户明确要求改用其他名字
    if user_name:
        parts.append(
            "## 当前用户名称\n"
            f"当前登录用户的名字是「{user_name}」。\n"
            "请默认用这个名字来称呼、指代用户（例如以「{user_name}，……」开头，"
            "或在回答中自然地提到这个名字）。\n"
            "除非用户在对话中**明确**要求你用别的名字称呼他（例如「叫我 XX 就好」「以后请叫我 XX」），"
            "否则不要更改对他的称呼，也不要自行编造或猜测其他名字。"
        )

    if user_id:
        query = _extract_last_user_text(messages)
        profile = await asyncio.to_thread(_recall_profile, user_id, query)
        if profile:
            parts.append(
                "## 已知用户画像（来自长期记忆）\n"
                "以下是关于当前用户的既有信息，请在回答时**自然融入**、体现"
                "\"懂用户\"，但切勿生硬复述或让用户觉得被监视：\n\n"
                f"{profile}"
            )

    system_text = "\n\n".join(parts)
    return [SystemMessage(content=system_text)] + list(messages)


def create_llm(temperature: float = 0.7, max_tokens: int = 2048, streaming: bool = False):
    """创建 DeepSeek LLM 实例（可复用）。

    streaming=True 时底层走 SSE 流式，配合 agent.astream(stream_mode="messages")
    可逐 token 返回，从而实现前端「逐字输出」效果。
    """
    return ChatOpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        max_retries=3,   # API 抖动/网络异常时自动重试，避免模型输出中途断裂
        timeout=settings.llm_request_timeout,  # 单次请求超时，避免 LLM 卡死占满连接
        streaming=streaming,
    )


def create_agent(tools: list = None):
    """创建智作台 ReAct Agent（无 checkpointer）。

    项目不依赖 LangGraph checkpointer 做短期记忆：每轮完整上下文由调用方从业务
    消息表显式读取后传入，Agent 不读取也不写入共享 thread。编译后的图只包含
    不可变的模型/工具定义，可并发复用。

    Args:
        tools: 工具列表

    Returns:
        编译好的 LangGraph Agent
    """
    llm = create_llm(streaming=True)

    if tools is None:
        tools = []

    agent = create_react_agent(
        model=llm,
        tools=tools,
        prompt=dynamic_prompt,   # 动态系统提示词：静态文档 + 运行时用户画像
    )

    return agent
