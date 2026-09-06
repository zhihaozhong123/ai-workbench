"""
阿里云百炼 Embedding - 统一配置与工厂

复用百炼 OpenAI 兼容接口调用 qwen3.7-text-embedding。
RAG (LlamaIndex) 与长期记忆 (ChromaDB) 共用同一个百炼模型 / 端点。

- RAG 使用 LlamaIndex 官方适配器 OpenAIEmbedding
- 长期记忆使用 ChromaDB 官方适配器 OpenAIEmbeddingFunction
  与 autogen-09 的写法完全一致，无需手写适配类。
"""
from config import settings

from chromadb.utils import embedding_functions
from llama_index.embeddings.openai import OpenAIEmbedding
from llama_index.llms.openai import OpenAI


def _model() -> str:
    return settings.aliyun_embedding_model


def embedding_model_name() -> str:
    """当前生效的 embedding 模型名（供向量指纹编入模型标识，模型升级后旧向量不再被复用）。"""
    return _model()


def _api_key() -> str:
    return settings.aliyun_embedding_api_key


def _base_url() -> str:
    return settings.aliyun_embedding_base_url


def get_llama_embed_model() -> OpenAIEmbedding:
    """供 RAG (LlamaIndex Settings.embed_model) 使用。

    LlamaIndex 的 OpenAIEmbedding 对 model 有 OpenAI 官方模型枚举白名单校验，
    百炼 qwen3.7-text-embedding 不在其中。这里不传 model（用其库内默认值过校验），
    改用 model_name 指定真实百炼模型（base.py:310-312 中 model_name 会覆盖 engine）。
    """
    return OpenAIEmbedding(
        model_name=_model(),   # 真实生效的百炼模型名（qwen3.7-text-embedding）
        api_key=_api_key(),
        api_base=_base_url(),
        # 百炼/DeepSeek embedding 接口限制单次批量 ≤ 20 条；留余量设 16，
        # 避免长文档（如数万字的 docx）切分后节点数过多触发 400。
        embed_batch_size=16,
    )


def get_chroma_embed_fn():
    """供长期记忆 (ChromaDB embedding_function) 使用，与 autogen-09 同一写法"""
    return embedding_functions.OpenAIEmbeddingFunction(
        api_key=_api_key(),
        api_base=_base_url(),
        model_name=_model(),
    )


def get_llama_llm() -> OpenAI:
    """供 LlamaIndex Settings.llm 使用（指向 DeepSeek，OpenAI 兼容）。

    关键：绝不使用 MockLLM。若 DeepSeek 配置异常（key/model/网络），
    调用时直接报错并如实返回，而非静默降级为 Mock 返回假数据。
    llm(DeepSeek) 与 embed_model(百炼) 是两套独立凭据，故即便 embedding 未配置，
    llm 也应无条件可用。
    """
    return OpenAI(
        model=settings.deepseek_model,
        api_key=settings.deepseek_api_key,
        api_base=settings.deepseek_base_url,
        timeout=settings.llm_request_timeout,
        max_tokens=2048,
    )
