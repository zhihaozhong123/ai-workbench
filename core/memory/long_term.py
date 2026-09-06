"""
长期记忆 - ChromaDB 热存储 + PostgreSQL 冷存储 + 阿里云百炼 Embedding

说明:
- Embedding 由 embeddings.get_chroma_embed_fn() 提供 (qwen3.7-text-embedding)，
  与 RAG 知识库使用同一个百炼模型 / 端点。
- 数据库仅支持 PostgreSQL：冷库用 PG 普通表存储。

策略:
- 热存储 (ChromaDB): 向量化存储，语义检索 + 时间衰减重排序
- 冷存储 (PostgreSQL): 每 20 条热记录压缩为 1 条归档，BM25 词法检索（rank_bm25 + jieba 中文分词）
- 冷库淘汰: > 10000 条时从最旧开始删除
- 综合分: score = similarity × 0.9^(days_ago / 30)
"""
import threading
import uuid
from datetime import datetime, timezone

import chromadb
from infra.embeddings import get_chroma_embed_fn
from config import settings
from observability.logging_config import get_logger

log = get_logger(__name__)

# 冷存储后端：仅 PostgreSQL（已移除 SQLite 回退）。
# psycopg 同步连接需要去掉 SQLAlchemy 的 +asyncpg 方案标识，故转换为同步连接串。
_COLD_DB_URL = (getattr(settings, "database_url", "") or "").strip()
_COLD_DB_SYNC_URL = _COLD_DB_URL.replace("+asyncpg", "")
_PLACE = "%s"

# BM25 词法检索（冷存储替代原 SQL LIKE）：中文用 jieba 分词
try:
    import jieba
    from rank_bm25 import BM25Okapi
    _HAS_BM25 = True
except ImportError:
    BM25Okapi = None
    _HAS_BM25 = False

# ==================== 常量 ====================
HOT_MAX_PER_THREAD = 200          # 热存储单线程触发压缩的阈值
COMPRESS_BATCH_SIZE = 20          # 每 N 条热记录压缩为 1 条冷记录
COLD_MAX_RECORDS = 10000          # 冷库记录上限
SUMMARY_MAX_CHARS = 300           # 压缩时每条取前 N 字
TIME_DECAY_BASE = 0.9             # 时间衰减底数
TIME_DECAY_DAYS = 30              # 衰减半衰天数
HOT_QUERY_MULTIPLIER = 3          # 热检索放大倍数（先多取再重排）
COLD_SEARCH_TOP_N = 3             # 冷检索返回数


# ==================== 中文分词（BM25 依赖）====================
def _tokenize(text: str) -> list[str]:
    """中文分词：优先 jieba；缺失时退回字粒度（每个汉字当一个词），对中文仍可用。"""
    text = (text or "").lower()
    if _HAS_BM25:
        return [w for w in jieba.cut(text) if w.strip()]
    return [ch for ch in text if ch.strip()]


def _days_ago(created_at_iso: str, now: datetime) -> int:
    """计算记忆距今天数（解析失败按 365 天，使其时间权重最低）。"""
    try:
        return max(0, (now - datetime.fromisoformat(created_at_iso)).days)
    except Exception:
        return 365


# ==================== 全局状态 ====================
# 系统就绪标志（替代原单一共享集合指针）：Chroma / PG 任一不可达则保持 False，
# 所有读写操作降级为空/无操作（与原 hot_collection is None 语义一致）。
_ready = False

# 并发写保护：Chroma 持久化客户端对并发写不友好，用可重入锁串行化写入与后续压缩
_write_lock = threading.RLock()

# —— 存储层隔离 ——
#   * Chroma：每个 user_id 一个 tenant/database（mem_<uid>），向量层面强制隔离（双保险）；
#   * PostgreSQL 冷存储：[2026-07-26] 不再为每用户建 mem_<uid> 模式，改为单表
#     public.cold_memories + thread_id 行级隔离（用户要求 pg 库除 public 外不出现 mem_* 模式）。
#     所有冷存储读写均按 thread_id 过滤，功能不受影响；多副本后端共享同一张表。
_hot_clients: dict[str, "chromadb.HttpClient"] = {}
_hot_collections: dict[str, "chromadb.Collection"] = {}
_cold_schema_cache: set[str] = set()
_cold_schema_lock = threading.Lock()

# 固定连共享 Chroma 服务（与 RAG 一致）：
# - _ef: 阿里云百炼 embedding 函数（客户端预计算后显式传入，保证向量空间一致）
# - _precompute_embeddings: 恒为 True（服务端不启用 embedding，避免服务端默认/配置
#   漂移导致向量空间不一致，与 RAG 的 ChromaVectorStore 做法一致）。
_ef = None
_precompute_embeddings = False


# ==================== Chroma 客户端工厂（存储层 tenant 隔离，与 RAG 一致）====================
def _make_chroma_client(user_id: str) -> "chromadb.HttpClient":
    """返回绑定到本用户 tenant/database 的 Chroma 客户端（长期记忆专用 database=mem_<user_id>）。

    与 RAG 知识库共用「Chroma 原生 tenant/database 隔离」思路：即使应用层过滤代码有 bug，
    直接连 Chroma 也只能看到本用户 tenant 下的集合，天然无法跨用户读取（双保险）。
    """
    host = settings.chroma_host
    port = settings.chroma_port
    database = f"mem_{user_id}"
    # ChromaDB Python client >=1.5 构造时会校验 tenant/database 是否存在，且不再暴露
    # create_tenant/create_database 普通方法。这里通过 REST API 先确保 tenant/database 存在，
    # 再用 tenant/database 构造 client（后续 collection API 不再接受这两个关键字）。
    try:
        import requests
        base = f"http://{host}:{port}/api/v2"
        requests.post(f"{base}/tenants", json={"name": user_id}, timeout=10)
        requests.post(f"{base}/tenants/{user_id}/databases", json={"name": database}, timeout=10)
    except Exception as e:
        log.warning("[Chroma] 预创建 tenant/database 失败（可能已存在或服务暂不可达）: %s", e)
    return chromadb.HttpClient(host=host, port=port, tenant=user_id, database=database)


def _hot_collection_for(user_id: str) -> "chromadb.Collection":
    """取得本用户（tenant）下的热记忆集合（按需创建并缓存）。"""
    if user_id in _hot_collections:
        return _hot_collections[user_id]
    col = _make_chroma_client(user_id).get_or_create_collection(
        name="long_term_memory_hot",
        metadata={"hnsw:space": "cosine"},
    )
    _hot_collections[user_id] = col
    return col


def is_ready() -> bool:
    """长期记忆系统是否就绪（Chroma/PG 可达且已初始化）。替代原 hot_collection is None 判空。"""
    return _ready


# ==================== 冷存储: 每租户 schema（PostgreSQL 存储层隔离）====================
def _cold_schema_for(user_id: str) -> str:
    """冷记忆统一落在 public 模式（单表 + thread_id 行级隔离），不再返回 mem_<uid> 模式名。

    [2026-07-26] 用户要求 pg 的 xiaoshutong 库除 public 外不出现任何 mem_* 模式，故此处恒返回
    "public"；真正的用户隔离由 public.cold_memories 表的 thread_id 列承担。
    """
    return "public"


def _ensure_cold_schema(user_id: str) -> str:
    """确保冷记忆表 public.cold_memories 存在（幂等；结果缓存避免重复 DDL 往返）。

    [2026-07-26] 改为单表 + thread_id 行级隔离，不再 CREATE SCHEMA mem_<uid>。所有用户共用
    public.cold_memories，读写按 thread_id 过滤；多副本后端共享同一张表。
    """
    schema = _cold_schema_for(user_id)  # 恒为 "public"
    if schema in _cold_schema_cache:
        return schema
    with _cold_schema_lock:
        if schema in _cold_schema_cache:
            return schema
        try:
            _cold_exec(
                """
                CREATE TABLE IF NOT EXISTS cold_memories (
                    id SERIAL PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source_count INTEGER DEFAULT 20,
                    created_at TEXT NOT NULL
                )
                """
            )
            _cold_exec("CREATE INDEX IF NOT EXISTS idx_cold_thread ON cold_memories(thread_id)")
            _cold_exec("CREATE INDEX IF NOT EXISTS idx_cold_created ON cold_memories(created_at)")
            log.info("[冷存储] 已就绪 表=public.cold_memories")
        except Exception as e:
            log.warning("[冷存储] 创建表失败: %s", e)
        _cold_schema_cache.add(schema)
    return schema


def _cold_ping():
    """测试冷存储连接可用性（仅连接，不建表）。"""
    _cold_query("SELECT 1")


# ==================== 初始化 ====================
def init_long_term_memory():
    """初始化长期记忆系统：存储层 tenant 隔离（Chroma tenant/database + PG 每租户 schema）。"""
    global _ef, _precompute_embeddings, _ready
    try:
        _ef = get_chroma_embed_fn()
        # 客户端预计算 embedding 并显式传入（服务端不启用 embedding，避免向量空间漂移）
        _precompute_embeddings = True

        # 连通性检查：Chroma 不可达则整体不就绪（与原行为一致，运维能立刻发现）
        chromadb.HttpClient(
            host=settings.chroma_host, port=settings.chroma_port
        ).heartbeat()
        # 冷存储连通性
        _cold_ping()

        # 一次性迁移旧版共享存储 → 各租户隔离
        _migrate_legacy_to_tenant_isolation()

        _ready = True
        log.info("长期记忆已就绪 | 隔离: Chroma tenant=<uid>/database=mem_<uid> + PG public.cold_memories(thread_id 隔离)")
    except Exception as e:
        log.error("[长期记忆] 初始化失败（Chroma/PG 不可达？）: %s", e)
        _ready = False
    return _ready


def _cold_conn():
    """返回冷存储连接（PostgreSQL 同步连接）。"""
    import psycopg
    return psycopg.connect(_COLD_DB_SYNC_URL)


def _cold_exec(sql: str, params: tuple = ()):
    with _cold_conn() as conn:
        conn.execute(sql, params)
        conn.commit()


def _cold_query(sql: str, params: tuple = ()):
    with _cold_conn() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()


# ==================== 旧版 → 租户隔离 一次性迁移 ====================
def _migrate_legacy_to_tenant_isolation():
    """把旧版「共享 Chroma 集合 + 共享 PG 表」里的记忆，按 thread_id 迁移到各用户租户。

    幂等：迁移完成后旧 Chroma 集合会被删除、旧 PG 表会被改名备份，重复启动不再迁移。
    任何子步骤失败仅告警，不阻断启动（不影响新数据写入）。
    """
    try:
        _migrate_legacy_chroma()
    except Exception as e:
        log.warning("[迁移] Chroma 迁移异常: %s", e)
    try:
        _migrate_legacy_cold()
    except Exception as e:
        log.warning("[迁移] 冷存储迁移异常: %s", e)


def _migrate_legacy_chroma():
    """迁移旧版共享 Chroma 集合 long_term_memory_hot（default tenant）到各租户。

    使用 upsert 写入目标集合，保证重复启动幂等（不会因重复 id 报错 / 产生重复数据）。
    """
    try:
        legacy = chromadb.HttpClient(
            host=settings.chroma_host, port=settings.chroma_port
        ).get_or_create_collection(
            name="long_term_memory_hot", metadata={"hnsw:space": "cosine"}
        )
    except Exception as e:
        log.warning("[迁移] 旧 Chroma 集合访问失败: %s", e)
        return

    seen = 0
    offset = 0
    BATCH = 1000
    while True:
        try:
            data = legacy.get(
                include=["embeddings", "documents", "metadatas"],
                limit=BATCH, offset=offset,
            )
        except Exception as e:
            log.warning("[迁移] 读取旧 Chroma 失败: %s", e)
            break
        ids = data.get("ids") or []
        if not ids:
            break
        groups: dict[str, dict] = {}
        for i, _id in enumerate(ids):
            meta = data["metadatas"][i] or {}
            uid = meta.get("thread_id") or "default"
            g = groups.setdefault(uid, {"ids": [], "emb": [], "docs": [], "metas": []})
            g["ids"].append(_id)
            g["emb"].append(data["embeddings"][i])
            g["docs"].append(data["documents"][i])
            g["metas"].append(meta)
        for uid, g in groups.items():
            try:
                # upsert：重复启动时已存在的 id 会被覆盖而非报错（幂等）
                _hot_collection_for(uid).upsert(
                    ids=g["ids"], embeddings=g["emb"],
                    documents=g["docs"], metadatas=g["metas"],
                )
                seen += len(g["ids"])
            except Exception as e:
                log.error("[迁移] 写入 tenant=%s 失败: %s", uid, e)
        if len(ids) < BATCH:
            break
        offset += BATCH

    if seen:
        try:
            legacy.delete()
            log.info("[迁移] 已将 %d 条热记忆迁移到各租户 Chroma，并删除旧共享集合", seen)
        except Exception as e:
            log.warning("[迁移] 删除旧 Chroma 集合失败（可手动删除 long_term_memory_hot）: %s", e)


def _migrate_legacy_cold():
    """[2026-07-26] 不再需要：冷记忆现已原生落在 public.cold_memories（单表 + thread_id 隔离），

    不存在旧版「共享表 → 每用户 mem_* 模式」的拆分动作。保持为空操作，避免误建 mem_* 模式、
    或把 public.cold_memories 改名备份导致线上表失效。
    """
    return

# ==================== 热存储: 写入 ====================
def save_hot_memory(content: str, thread_id: str) -> str:
    """保存一条记忆到 ChromaDB 热存储（本用户 tenant），并触发压缩/淘汰检查"""
    if not _ready:
        return ""

    memory_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # 并发保护：Chroma 持久化客户端对并发写不友好，用可重入锁串行化写入与后续压缩
    with _write_lock:
        col = _hot_collection_for(thread_id)
        if _precompute_embeddings and _ef is not None:
            # http 模式：显式传入预计算向量（服务端不跑 embedding）
            col.add(
                ids=[memory_id],
                embeddings=_ef([content]),
                documents=[content],
                metadatas=[{"thread_id": thread_id, "created_at": now}],
            )
        else:
            col.add(
                ids=[memory_id],
                documents=[content],
                metadatas=[{"thread_id": thread_id, "created_at": now}],
            )
        # 写入后触发维护（压缩/淘汰），与读取隔离
        _check_and_compress(thread_id)

    return memory_id


# ==================== 检索: 热 + 冷，综合分重排序 ====================
def recall_memories(query: str, thread_id: str, top_k: int = 5) -> str:
    """
    检索长期记忆：
    1. 热存储: ChromaDB 语义检索 → 相似度 × 时间衰减 → 综合分
    2. 冷存储: PostgreSQL 关键词匹配 → 匹配分 × 时间衰减
    3. 合并重排序，返回 top_k
    """
    if not _ready:
        return "长期记忆系统未初始化。"

    all_results: list[dict] = []

    # --- 1. 热存储检索 ---
    all_results.extend(_search_hot(query, thread_id, top_k))

    # --- 2. 冷存储检索 ---
    all_results.extend(_search_cold(query, thread_id))

    # --- 3. 综合分重排序 ---
    all_results.sort(key=lambda x: x["score"], reverse=True)
    top_results = all_results[:top_k]

    if not top_results:
        return "长期记忆中没有找到相关信息。"

    lines = ["📌 长期记忆 (按相关性排序):"]
    for i, r in enumerate(top_results, 1):
        days_str = f"{r['days_ago']}天前" if r['days_ago'] > 0 else "今天"
        lines.append(f"  {i}. [{r['source']} | 分:{r['score']:.3f} | {days_str}] {r['content']}")
    return "\n".join(lines)


def _search_hot(query: str, thread_id: str, top_k: int) -> list[dict]:
    """ChromaDB 热存储检索（本用户 tenant），应用时间衰减"""
    results = []
    try:
        col = _hot_collection_for(thread_id)
        if _precompute_embeddings and _ef is not None:
            # http 模式：显式传入 query 向量
            raw = col.query(
                query_embeddings=_ef([query]),
                n_results=top_k * HOT_QUERY_MULTIPLIER,
                include=["documents", "metadatas", "distances"],
            )
        else:
            raw = col.query(
                query_texts=[query],
                n_results=top_k * HOT_QUERY_MULTIPLIER,
                include=["documents", "metadatas", "distances"],
            )
        if not raw or not raw["ids"] or not raw["ids"][0]:
            return results

        now = datetime.now(timezone.utc)
        for i in range(len(raw["ids"][0])):
            meta = raw["metadatas"][0][i]
            if meta.get("thread_id") != thread_id:
                continue

            # 余弦距离 → 相似度
            distance = raw["distances"][0][i]
            similarity = max(0.0, 1.0 - distance)

            # 时间衰减
            try:
                created_at = datetime.fromisoformat(meta["created_at"])
                days_ago = max(0, (now - created_at).days)
            except Exception:
                days_ago = 0
            time_weight = TIME_DECAY_BASE ** (days_ago / TIME_DECAY_DAYS)

            score = similarity * time_weight
            results.append({
                "content": raw["documents"][0][i],
                "score": round(score, 4),
                "source": "热存储",
            "days_ago": days_ago,
        })
    except Exception as e:
        log.warning("[热存储检索] %s", e)
    return results


def _search_cold(query: str, thread_id: str) -> list[dict]:
    """PostgreSQL 冷存储检索（BM25 词法相关性 + 时间衰减）。

    相比原 SQL LIKE 子串计数，BM25 具备：
    - IDF：常见词（"的/我"）降权、罕见词（专名/编号）升权；
    - 词频饱和 + 文档长度归一：长文本不会被"命中词多"虚高；
    - 中文 jieba 分词：原 LIKE 按空格切词，对中文几乎失效。
    最终分 = BM25归一化分(∈[0,1]) × 时间衰减，与热存储量纲对齐，便于合并重排。
    若 BM25 依赖未安装，自动退回原 LIKE 实现，保证可用。
    """
    results = []
    try:
        # 1. 取该线程全部冷记忆作为 BM25 语料（驱动无关，按列索引访问）
        schema = _ensure_cold_schema(thread_id)
        rows = _cold_query(
            f"SELECT id, content, created_at FROM {schema}.cold_memories WHERE thread_id = " + _PLACE,
            (thread_id,),
        )
        if not rows:
            return results

        docs = [{"id": r[0], "content": r[1], "created_at": r[2]} for r in rows]
        corpus = [_tokenize(d["content"]) for d in docs]
        now = datetime.now(timezone.utc)

        if _HAS_BM25:
            # 2. BM25 打分
            bm25 = BM25Okapi(corpus)
            raw_scores = bm25.get_scores(_tokenize(query))
            max_s = max(raw_scores) if raw_scores else 0.0
            for d, s in zip(docs, raw_scores):
                if s <= 0:
                    continue
                norm = s / (max_s + 1e-9)          # 归一化到 [0,1]
                days_ago = _days_ago(d["created_at"], now)
                time_weight = TIME_DECAY_BASE ** (days_ago / TIME_DECAY_DAYS)
                results.append({
                    "content": d["content"],
                    "score": round(norm * time_weight, 4),
                    "source": "冷存储",
                    "days_ago": days_ago,
                })
        else:
            # 兜底：原 LIKE 实现（依赖缺失时）
            keywords = query.split()
            if not keywords:
                return results
            for d in docs:
                content_lower = d["content"].lower()
                match_count = sum(1 for kw in keywords if kw.lower() in content_lower)
                if match_count == 0:
                    continue
                keyword_score = 0.2 + 0.6 * (match_count / len(keywords))
                days_ago = _days_ago(d["created_at"], now)
                time_weight = TIME_DECAY_BASE ** (days_ago / TIME_DECAY_DAYS)
                results.append({
                    "content": d["content"],
                    "score": round(keyword_score * time_weight, 4),
                    "source": "冷存储",
                    "days_ago": days_ago,
                })

        # 冷存储只取 top N（recall_memories 会再与热存储合并后按总分取 top_k）
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:COLD_SEARCH_TOP_N]
    except Exception as e:
        log.warning("[冷存储检索] %s", e)
    return results


# ==================== 维护: 压缩 & 淘汰 ====================
def _check_and_compress(thread_id: str):
    """检查热存储是否需要压缩（本用户 tenant）"""
    try:
        col = _hot_collection_for(thread_id)
        result = col.get(
            where={"thread_id": thread_id},
            include=["metadatas"],
            limit=HOT_MAX_PER_THREAD + 100,
        )
        count = len(result["ids"]) if result and result["ids"] else 0
    except Exception:
        return

    if count >= HOT_MAX_PER_THREAD:
        _compress_hot_to_cold(thread_id)
        _prune_cold_storage(thread_id)


def _compress_hot_to_cold(thread_id: str):
    """将热存储中最旧的 COMPRESS_BATCH_SIZE 条压缩为 1 条，移至冷存储（本用户 tenant）"""
    try:
        col = _hot_collection_for(thread_id)
        result = col.get(
            where={"thread_id": thread_id},
            include=["documents", "metadatas"],
            limit=HOT_MAX_PER_THREAD + 100,
        )
        if not result or not result["ids"]:
            return

        # 按创建时间排序
        items = list(zip(result["ids"], result["documents"], result["metadatas"]))
        items.sort(key=lambda x: x[2].get("created_at", ""))

        batch = items[:COMPRESS_BATCH_SIZE]
        if len(batch) == 0:
            return

        # 每条取前 SUMMARY_MAX_CHARS 字，拼接压缩
        parts = [doc[:SUMMARY_MAX_CHARS] for _, doc, _ in batch]
        compressed = " | ".join(parts)
        compressed = f"[压缩×{len(batch)}条] {compressed}"

        # 写入冷存储（本用户 tenant schema）
        now = datetime.now(timezone.utc).isoformat()
        schema = _ensure_cold_schema(thread_id)
        _cold_exec(
            f"INSERT INTO {schema}.cold_memories (thread_id, content, source_count, created_at) "
            f"VALUES (" + _PLACE + ", " + _PLACE + ", " + _PLACE + ", " + _PLACE + ")",
            (thread_id, compressed, len(batch), now),
        )

        # 从热存储删除
        batch_ids = [item[0] for item in batch]
        col.delete(ids=batch_ids)

        log.info("[记忆压缩] %d条热记忆 → 1条冷记录", len(batch))

    except Exception as e:
        log.warning("[压缩异常] %s", e)


def _prune_cold_storage(thread_id: str):
    """本用户冷存储 > COLD_MAX_RECORDS 时，从最旧开始删除（按 thread_id 隔离，只删本用户）。

    [2026-07-26] public.cold_memories 现为多用户共享表，必须按 thread_id 过滤，否则会误删其他
    用户的冷记忆。
    """
    try:
        schema = _ensure_cold_schema(thread_id)
        rows = _cold_query(
            f"SELECT COUNT(*) FROM {schema}.cold_memories WHERE thread_id = " + _PLACE, (thread_id,)
        )
        count = rows[0][0] if rows else 0
        if count > COLD_MAX_RECORDS:
            overflow = count - COLD_MAX_RECORDS
            _cold_exec(
                f"DELETE FROM {schema}.cold_memories WHERE thread_id = " + _PLACE +
                f" AND id IN (SELECT id FROM {schema}.cold_memories WHERE thread_id = " + _PLACE +
                f" ORDER BY created_at ASC LIMIT " + _PLACE + ")",
                (thread_id, thread_id, overflow),
            )
            log.info("[冷库淘汰] tenant=%s 超限 %d 条，已从最旧开始删除", thread_id, overflow)
    except Exception as e:
        log.warning("[冷库淘汰异常] %s", e)


# ==================== 只读查看（调试/运维接口用）====================
def list_hot_memories(thread_id: str, limit: int = 200) -> dict:
    """只读列出某 thread（=user_id）的全部热记忆，按创建时间倒序。供查看接口调用。

    仅做 SELECT，绝不触发压缩/淘汰；系统未就绪时返回空。
    """
    if not _ready:
        return {"count": 0, "items": []}
    items = []
    try:
        col = _hot_collection_for(thread_id)
        res = col.get(
            where={"thread_id": thread_id},
            include=["documents", "metadatas"],
            limit=limit,
        )
        if not res or not res.get("ids"):
            return {"count": 0, "items": []}
        now = datetime.now(timezone.utc)
        for i in range(len(res["ids"])):
            meta = res["metadatas"][i]
            created = meta.get("created_at", "")
            try:
                days_ago = max(0, (now - datetime.fromisoformat(created)).days)
            except Exception:
                days_ago = None
            items.append({
                "id": res["ids"][i],
                "created_at": created,
                "days_ago": days_ago,
                "content": res["documents"][i],
            })
        items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    except Exception as e:
        log.warning("[热记忆查看] %s", e)
    return {"count": len(items), "items": items}


def list_cold_memories(thread_id: str, limit: int = 200) -> dict:
    """只读列出某 thread（=user_id）的全部冷记忆，按创建时间倒序。供查看接口调用。

    仅做 SELECT，绝不修改数据；冷库不可用时返回空。
    """
    items = []
    try:
        schema = _ensure_cold_schema(thread_id)
        rows = _cold_query(
            f"SELECT id, content, source_count, created_at FROM {schema}.cold_memories "
            "WHERE thread_id = " + _PLACE + " ORDER BY created_at DESC LIMIT " + _PLACE,
            (thread_id, limit),
        )
        items = [
            {"id": r[0], "content": r[1], "source_count": r[2], "created_at": r[3]}
            for r in rows
        ]
    except Exception as e:
        log.warning("[冷记忆查看] %s", e)
    return {"count": len(items), "items": items}
