"""清空「长期记忆 / 向量」数据，配合 up_build.sh 的 RESET=1 使用。

RESET=1 表示「从 0 开始」的全新状态，本脚本负责清除非结构化数据：
- Chroma 热存储集合 long_term_memory_hot（长期记忆 · 语义向量）
- PostgreSQL 冷存储表 cold_memories（长期记忆 · 压缩归档）

结构化业务数据（用户 / 对话 / 技能安装记录）由 scripts/reset_db.py 负责。

best-effort：Chroma / PG 不可达时不抛异常，仅告警，避免阻断后续流程。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import chromadb
from config import settings
import logging

log = logging.getLogger(__name__)

# 与 core/memory/long_term.py 保持一致的热存储集合名
HOT_COLLECTION = "long_term_memory_hot"


async def _reset_long_term_hot() -> None:
    """删除并重建长期记忆热存储集合（default tenant 的 default database）。"""
    try:
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        try:
            client.delete_collection(name=HOT_COLLECTION)
            log.info("[RESET] 已删除 Chroma 热存储集合: %s", HOT_COLLECTION)
            print(f"[RESET] Chroma 热存储集合已删除: {HOT_COLLECTION}")
        except Exception as e:  # 集合不存在时 delete 会抛异常，忽略即可
            log.debug("[RESET] 删除 Chroma 热存储集合时（可能本就不存在）: %s", e)
        client.get_or_create_collection(
            name=HOT_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        log.info("[RESET] 已重建干净的 Chroma 热存储集合: %s", HOT_COLLECTION)
        print(f"[RESET] 已重建干净的 Chroma 热存储集合: {HOT_COLLECTION}")
    except Exception as e:  # noqa: BLE001 - best-effort
        log.warning("[RESET] 清空 Chroma 热存储失败（Chroma 可能未启动或不可达）：%s", e)
        print(f"[RESET][WARN] 清空 Chroma 热存储失败（可忽略，若 Chroma 未运行）：{e}")


async def _reset_cold_storage() -> None:
    """删除 PostgreSQL 冷存储表 cold_memories（后端启动时由 init_long_term_memory 自动重建）。"""
    try:
        from infra.db import engine
        from sqlalchemy import text

        async with engine.begin() as conn:
            await conn.execute(text("DROP TABLE IF EXISTS cold_memories;"))
        log.info("[RESET] 已清空 PostgreSQL 冷存储表: cold_memories")
        print("[RESET] PostgreSQL 冷存储表 cold_memories 已清空")
    except Exception as e:  # noqa: BLE001 - best-effort
        log.warning("[RESET] 清空 PostgreSQL 冷存储失败（PG 可能未运行）：%s", e)
        print(f"[RESET][WARN] 清空 PostgreSQL 冷存储失败（可忽略，若 PG 未运行）：{e}")
    finally:
        try:
            await engine.dispose()
        except Exception:
            pass


async def main() -> None:
    print("==> 清空长期记忆向量数据（RESET=1）")
    await _reset_long_term_hot()
    await _reset_cold_storage()


if __name__ == "__main__":
    asyncio.run(main())
