"""清空 PostgreSQL 全部数据表（业务表 + LangGraph checkpoint 表）。

用于「从 0 开始」的重置：删掉所有账号、技能安装记录、对话记录，以及 Agent 的
对话状态（LangGraph checkpoint 表，存于 checkpoints / checkpoint_blobs /
checkpoint_writes / checkpoint_migrations）。保留表结构（由 schema.sql 维护，
后端启动会自动 ensure 就绪）。

注意：
- 长期记忆（Chroma 热存储 + PostgreSQL 冷存储 cold_memories）由
  scripts/reset_chroma.py 负责，配合 up_build.sh 的 RESET=1 一起调用；
- checkpoint_migrations 是 LangGraph 迁移记录元数据，清空后下一次后端启动会
  自动重新执行迁移建表（幂等），不影响功能；
- 镜像 db.py 的连接方式（同 DSN / 同凭证回退逻辑），避免再写一份连接串；
- best-effort：PG 不可达时不抛异常退出，仅告警，避免阻断后端启动。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

from infra.db import engine
from observability.logging_config import get_logger

log = get_logger(__name__)

# 业务表 + LangGraph checkpoint 表（Agent 对话状态）。checkpoint_blobs /
# checkpoint_writes 通过外键关联 checkpoints，TRUNCATE ... CASCADE 会一并级联清空。
_TABLES = [
    "conversations",
    "users",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
    "checkpoint_migrations",
]


async def main() -> None:
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text(f"TRUNCATE TABLE {', '.join(_TABLES)} RESTART IDENTITY CASCADE;")
            )
        log.info("[RESET] 已清空 PostgreSQL 业务表: %s", ", ".join(_TABLES))
        print(f"[RESET] PostgreSQL 业务表已清空: {', '.join(_TABLES)}")
        # 校验：再次查询各表行数，确认确实清空。
        # 防止「连错库」导致 TRUNCATE 看似成功、实际没清到 docker 库（表现为选项 1 清数据无效）。
        async with engine.connect() as conn:
            for t in _TABLES:
                n = await conn.scalar(text(f"SELECT count(*) FROM {t}"))
                if n:
                    log.warning("[RESET] 表 %s 仍有 %s 行，清空可能未生效（请检查 DB 连接是否指向 docker 库）", t, n)
                    print(f"[RESET][WARN] 表 {t} 仍有 {n} 行，清空可能未生效（请检查 .env 的 DB_HOST/DB_PORT/DB_USER 是否指向 docker 库）")
    except Exception as e:  # noqa: BLE001 - best-effort，绝不让重置阻断启动
        log.warning("[RESET] 清空 PostgreSQL 失败（PG 可能未启动或不可达）：%s", e)
        print(f"[RESET][WARN] 清空 PostgreSQL 失败（可忽略，若 PG 未运行）：{e}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
