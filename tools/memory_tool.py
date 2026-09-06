"""
长期记忆工具 - 基于 ChromaDB 热存储 + PostgreSQL 冷存储 + 阿里云百炼 Embedding

提供两个 LangChain tool:
- save_to_memory: 保存经验到热存储
- recall_from_memory: 检索热+冷存储，语义相似度×时间衰减重排序
"""
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from core.memory import long_term as lt


def _resolve_user_id(config: RunnableConfig | None) -> str:
    """解析 user_id：从注入的 RunnableConfig 读取（多用户并发场景），
    确保不同用户的记忆不会串号。"""
    if config:
        uid = (config.get("configurable") or {}).get("user_id")
        if uid:
            return uid
    return "default"


@tool
def save_to_memory(content: str, config: RunnableConfig = None) -> str:
    """将重要信息保存到长期记忆中。适用场景：用户明确表达了偏好、习惯、个人信息、或重要事实。
    例如用户说'我是一名大学生'或'我的名字是小明'时，应该调用此工具保存。
    ⚠️ 仅保存用户自身的偏好/习惯/个人信息等；严禁保存知识库文档的原文或检索片段
    （知识库内容属于用户私有资料，一旦存入长期记忆会被注入系统提示词、每次对话都带上，造成泄漏）。
    参数 content: 需要记住的信息内容（不得包含任何知识库文档内容）。
    """
    if not lt.is_ready():
        return "[ERROR] 长期记忆系统未初始化。"

    user_id = _resolve_user_id(config)
    lt.save_hot_memory(content, user_id)
    return f"已保存到长期记忆: {content}"


@tool
def recall_from_memory(query: str, config: RunnableConfig = None) -> str:
    """从长期记忆中检索与当前对话相关的历史信息（包括热存储和冷存储）。
    在回复用户前，如果认为需要回顾历史偏好或事实，应调用此工具。
    参数 query: 检索关键词或问题。
    """
    if not lt.is_ready():
        return "[ERROR] 长期记忆系统未初始化。"

    user_id = _resolve_user_id(config)
    result = lt.recall_memories(query, user_id, top_k=5)
    # 截断过长内容，避免长期记忆累积过多时撑爆上下文 / 无谓烧 token
    if len(result) > 2000:
        result = result[:2000] + f"\n...(已截断，完整记忆共 {len(result)} 字)"
    return result
