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

import logging

log = logging.getLogger(__name__)

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


# 明确属于「非公众号文章」的普通交付物（邮件/周报/PPT/代码等）。技能专属会话里若命中这些词，
# 说明用户要写的是别的东西而不是公众号文章——除非句中同时带有公众号写作语境词。
_NON_ARTICLE_DELIVERABLE_PATTERNS = (
    r"邮件", r"周报", r"日报", r"月报", r"周记", r"日记", r"检讨书", r"请假条",
    r"道歉信", r"感谢信", r"求职信", r"简历", r"招聘", r"合同", r"协议", r"发票",
    r"演讲稿", r"主持稿", r"新闻稿", r"通讯稿", r"会议纪要", r"发言稿",
    r"述职报告", r"汇报材料", r"工作方案", r"项目计划", r"操作手册", r"接口文档",
    r"代码", r"程序", r"bug",
    r"朋友圈", r"小红书", r"微博", r"抖音", r"快手", r"短视频",
    r"ppt", r"演示文稿", r"word", r"excel", r"表格",
)
# 公众号写作语境提示词：命中则大概率仍属「写公众号文章」（如「把这篇周报分析发成公众号文章」）。
_ARTICLE_CONTEXT_HINT_PATTERNS = (
    r"公众号", r"文章", r"微信", r"图文", r"正文", r"排版", r"草稿", r"发布",
    r"素材", r"群发", r"mp\.weixin", r"标题",
)


def _is_article_intent(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    patterns = [
        r"写一篇",
        r"帮我写",
        r"标题为",
        r"写一篇关于",
        r"写一篇以",
        r"发公众号",
        r"发到公众号",
        r"发布到公众号",
        r"发到微信",
        r"发公众号",
        r"生成一篇公众号",
        r"公众号文章",
        r"写篇文章",
    ]
    has_write_signal = False
    for p in patterns:
        if re.search(p, t, flags=re.I):
            has_write_signal = True
            break
    if not has_write_signal and not re.search(
        r"write (an |a )?article|wechat|public account", t, flags=re.I
    ):
        return False
    # 命中明确「非公众号交付物」且没有公众号语境 → 普通聊天（邮件/周报/PPT/简历等），
    # 交给普通 agent 分支回答，不被公众号写作流程抢占。
    if not any(re.search(p, t, flags=re.I) for p in _ARTICLE_CONTEXT_HINT_PATTERNS):
        if any(re.search(p, t, flags=re.I) for p in _NON_ARTICLE_DELIVERABLE_PATTERNS):
            return False
    return True


def _extract_title(text: str) -> str | None:
    if not text:
        return None
    t = text.strip()

    candidates = [
        r"(?:标题|题目|主题)(?:[:：\s]|为|是)*([^，,。！？\n]{2,120})",
        r"(?:标题|题目|主题)\s*(?:为|是)\s*([^，,。！？\n]{2,120})",
        r"写(?:一篇|篇)?(?:关于|以)?\s*([^，,。！？\n]{2,120})",
        r"帮我写(?:一篇|篇)?(?:关于|以)?\s*([^，,。！？\n]{2,120})",
    ]
    for pat in candidates:
        m = re.search(pat, t, flags=re.I)
        if m:
            value = m.group(1).strip()
            if value and value not in {"文章", "公众号", "公众号文章", "文章标题"}:
                return value

    m = re.search(r"(?:主题|方向)\s*为\s*([^，,。！？\n]{2,120})", t, flags=re.I)
    if m:
        value = m.group(1).strip()
        if value:
            return value
    return None


def _extract_wordcount(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(\d+\s*[-至–~~]\s*\d+\s*字|\d+\s*字)", text)
    if m:
        return m.group(0)
    m2 = re.search(r"(\d{2,4})\s*字", text)
    if m2:
        return m2.group(1) + "字"
    return None


# 用户「明确认可并让我开始」的确认词表（需求：回复 执行/开始/正确/对/做吧 等才启动自动化）。
# 强确认词：即便句中带否定修饰也视为确认（如「不要改，直接执行」）；
# 弱确认词：需整句无否定/更正/礼貌收尾成分才算确认（避免「可以吗」「先别，再想想」「好的谢谢」误触发）。
_STRONG_CONFIRM_WORDS = (
    "执行", "开始吧", "开始做", "确认", "做吧", "动手吧", "开干", "就这么办", "就这么做",
    "confirm", "start", "go", "yes", "sure",
)
_WEAK_CONFIRM_WORDS = (
    "对", "可以", "行", "正确", "没问题", "就这样", "是的", "没错", "那就这样", "好的",
    "好", "嗯", "ok", "okay",
)
_NEGATION_WORDS = (
    "不", "别", "不要", "先别", "先不", "暂", "等等", "稍等", "再想想", "待定", "再说",
    "谢谢", "但是", "不过", "还要", "再改", "改成", "吗",
)
_CONFIRM_CACHE: dict[str, bool] = {}


def _is_confirmed_text(text: str) -> bool:
    if not text:
        return False
    if text in _CONFIRM_CACHE:
        return _CONFIRM_CACHE[text]
    t = text.strip()
    res = False
    if re.search(r"(?:%s)" % "|".join(_STRONG_CONFIRM_WORDS), t, flags=re.I):
        res = True
    elif not re.search(r"(?:%s)" % "|".join(_NEGATION_WORDS), t, flags=re.I):
        res = bool(re.search(r"(?:%s)" % "|".join(_WEAK_CONFIRM_WORDS), t, flags=re.I))
    if len(_CONFIRM_CACHE) >= 512:
        _CONFIRM_CACHE.clear()
    _CONFIRM_CACHE[text] = res
    return res


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
        # Fail-safe: only allow the deterministic skill CLI to run when caller explicitly sets confirmed=True
        # This prevents accidental execution when the conversation hasn't received user's explicit confirmation.
        try:
            if not params or not params.get("confirmed"):
                return "[ERROR] 未经确认，拒绝执行自动化操作。请先确认写作要素并回复“确认”。"
        except Exception:
            return "[ERROR] 参数校验失败，拒绝执行自动化操作。"
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
        # 技能声明 local_control 权限时，技能任务额外注入本机控制工具
        # （open_webpage / run_apple_script 等），供浏览器自动化类技能使用。
        "local_control": "local_control" in (manifest.permissions or []),
    }


async def _prepare_run(user_id: str, skill_id: str, history, message: str):
    """组装本次运行的 (工具集, 输入消息, 是否技能执行模式)。

    技能专属会话采用「普通对话 → 需求澄清 → 确认执行」三态分流：

    1) 普通对话：历史与当前消息都不含「写公众号文章」意图时，与普通 agent 一样正常聊天
       —— 不注入技能系统提示，也不启用浏览器自动化 / 技能 CLI 工具（需求 1、2）；
    2) 需求澄清：处于写作语境、但用户尚未明确确认最终方案时，注入技能手册（AGENT.md），
       由 Agent 引导澄清 标题/主题、目标字数、排版（四套模板选一）、正文载体（Markdown/HTML），
       并把理解到的完整方案总结给用户确认；本阶段不注入浏览器自动化工具，物理上杜绝误执行；
    3) 确认执行：写作语境 + 已明确标题/主题 + 用户本轮以确认词（执行/开始/对/做吧/可以/没问题…）认可
       → 注入完整技能上下文（含 local_control 浏览器自动化与技能 CLI），由 Agent 开始执行。
    """
    history = list(history or [])
    # 会话未绑定技能 → 按通用助手行为
    if not skill_id:
        return _get_tools(), history + [HumanMessage(content=message)], False

    # 把历史与当前消息合并，支持用户分多轮提供信息、以及“仅回复确认词”的语境判断
    def _concat_history_text(hist, current_msg: str) -> str:
        parts = []
        for h in hist or []:
            try:
                c = getattr(h, "content", None)
                if c:
                    parts.append(str(c))
                else:
                    parts.append(str(h))
            except Exception:
                parts.append(str(h))
        if current_msg:
            parts.append(current_msg)
        return "\n".join(parts)

    combined = _concat_history_text(history, message)

    # 1) 无写作意图（历史 + 当前均不涉及）→ 普通聊天，等同通用 agent
    if not _is_article_intent(combined):
        return _get_tools(), history + [HumanMessage(content=message)], False

    # 写作语境：标题/主题、是否本轮明确确认（只认本轮确认词，避免回溯历史误判）
    title = (_extract_title(combined) or "").strip()
    confirmed = _is_confirmed_text(message)

    # 2) 加载技能手册（磁盘 manifest/AGENT.md 实时读取；失败按普通助手兜底）
    ctx = await load_skill_context(user_id, skill_id)
    if not ctx:
        return _get_tools(), history + [HumanMessage(content=message)], False

    # 3) 确认执行模式：标题/主题明确 + 用户本轮确认
    if title and confirmed:
        tools = list(_COMMON_TOOLS)
        msgs: list = []
        if ctx.get("prompt"):
            msgs.append(SystemMessage(content=ctx["prompt"]))
        if ctx.get("tool"):
            tools.append(ctx["tool"])
        if ctx.get("local_control"):
            tools.extend(list(_GENERAL_EXTRA_TOOLS))
        wordcount = _extract_wordcount(combined)
        if re.search(r"markdown|\bmd\b", combined, flags=re.I):
            detected_format = "Markdown"
        elif re.search(r"\bhtml\b", combined, flags=re.I):
            detected_format = "HTML"
        else:
            detected_format = ""
        params = {
            "title": title,
            "format": detected_format or "Markdown",
            "wordcount": wordcount or "",
            "confirmed": True,
        }
        msgs.append(SystemMessage(content=(
            "用户已确认开始执行。请以 ReAct 方式推进整段流程：先思考本步应调用哪个工具、预期读到什么回执，"
            "再调用工具；**每一步都以工具的真实回执为准决定下一步**，绝不跳过步骤，也绝不编造"
            "“已打开/已输入/已保存”等结果。\n"
            "开始前若需要回顾该用户的公众号偏好（惯用排版模板 / 字数 / 公众号账号 / 写作风格），"
            "可先调用 recall_from_memory 取用（本系统每轮也自动注入了该用户的画像，直接采用即可），"
            "让正文与排版贴合其偏好；正文主题若涉及需核实的最新资料且用户允许联网，可用 web_search，"
            "用户没要求时直接按已确认方案写作。\n"
            "先回复用户一句「好的，现在就马上开始做。」，"
            "然后立即按手册「执行流程」推进（打开公众号平台 → 核对登录态 → 新建图文 → 填标题 → 写正文 → 存草稿），"
            "每完成一步先读回/核对结果再进入下一步，执行过程中遵循手册全部硬性规则"
            "（标题 ≤64 字、正文绝不进标题框、只点保存草稿、未登录停下等用户扫码等）。\n"
            "提示：若你此前已给用户拟出候选标题而用户没有特别指定，直接默认采用你的首选推荐标题，"
            "无需再就标题二次征求意见。\n"
            "若你决定调用技能确定性工具 skill_wechat_article_publish，必须以 JSON 参数传入以下内容，"
            "且 confirmed 必须为 true（可按对话最新共识调整其中字段）：\n"
            + json.dumps(params, ensure_ascii=False)
        )))
        return tools, msgs + history + [HumanMessage(content=message)], True

    # 4) 澄清模式：写作语境但尚未到执行门（缺标题 / 未确认 / 用户还在补充信息）
    gaps = []
    if not title:
        gaps.append("文章标题（若未定，可先给主题/方向，由你来拟定候选标题）")
    if not _extract_wordcount(combined):
        gaps.append("目标字数")
    stage_note = ""
    if gaps:
        stage_note = "当前对话中还缺少：" + "、".join(gaps) + "，请优先补全。\n"
    stage_prompt = (
        "你现在处于「公众号写作需求澄清」环节：尚未执行任何浏览器操作，本环节未启用浏览器自动化与"
        "技能 CLI 工具（open_webpage / run_apple_script / skill_wechat_article_publish 均不可用），"
        "因此不要宣称能打开网页、也不要调用不存在的工具；除此之外，你的思考与其它工具能力完全正常——\n"
        "像平时一样先思考、再行动、后开口（ReAct）：需要核实写作主题涉及的最新事实/资料时可调用 "
        "web_search 查证后再拟候选标题或大纲；需要回顾该用户的历史公众号偏好（惯用排版 / 字数 / 账号 / 写作风格）"
        "时可调用 recall_from_memory（每轮系统也已自动注入该用户画像，优先直接采用）；需要计算/时间时用 "
        "calculator / get_current_time。\n"
        "请按上方技能手册行事：\n"
        "1) 用户当前消息若不是「写公众号文章」业务（例如闲聊、身份/能力询问、查询、周报邮件 PPT 等其它任务）\n"
        "   → 与普通智作台 agent 完全一致地自然回答即可，不套技能话术、不追问写作要素；\n"
        "2) 若是写公众号文章 → 逐项与用户澄清：\n"
        "   ① 标题：用户已给则采用；只给了方向/主题则你主动拟定候选标题（可给 2～3 个供其选择或直接推荐一个）；\n"
        "   ② 目标字数：问清或按语境建议一个明确的字数/区间；\n"
        "   ③ 排版：从技能手册给出的四套排版模板中推荐一套并请用户选择（或直接按文章语境选定一套并说明）；\n"
        "   ④ 正文载体：Markdown 或 HTML（默认 Markdown）。\n"
        f"{stage_note}"
        "记忆协作：当用户明确表达**可复用的公众号偏好**（例如「以后都用 C 模板」「我一般写 1500 字」"
        "「固定发在 XX 公众号」「我喜欢这种风格」）→ 主动调用 save_to_memory 保存。记忆按当前登录用户"
        "（多租户）自动隔离，安全可靠不会与其它用户串号；仅为本次文章做的临时选择（如本次排版用 A）不必保存。\n"
        "每当用户补充信息或提出更正，都要用自然、简短的语言重述你对这篇完整写作方案的理解"
        "（标题 / 字数 / 排版 / 载体格式），并请用户确认；只有用户明确回复“执行 / 开始 / 对 / 可以 / 做吧 / 没问题”等确认词，"
        "才能进入执行。用户更正时不要不耐烦，反复核对直到一致。"
    )
    msgs: list = []
    if ctx.get("prompt"):
        msgs.append(SystemMessage(content=ctx["prompt"]))
    msgs.append(SystemMessage(content=stage_prompt))
    tools = list(_COMMON_TOOLS)
    return tools, msgs + history + [HumanMessage(content=message)], False


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
            "recursion_limit": 30,
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
            "recursion_limit": 30,
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
