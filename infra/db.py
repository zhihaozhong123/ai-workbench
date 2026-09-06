import os
import asyncio
from datetime import datetime, timezone

from sqlalchemy import Column, String, Integer, DateTime, Boolean, Float, Text, UniqueConstraint, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base

from config import settings, _pg_url
from observability.logging_config import get_logger
log = get_logger(__name__)

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), unique=True, index=True, nullable=False)   # 内部唯一 ID (uuid)
    username = Column(String(64), unique=True, index=True, nullable=False)  # 登录用户名，全局唯一
    password_hash = Column(String(255), nullable=False)
    nickname = Column(String(64), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    is_active = Column(Boolean, default=True)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(String(36), primary_key=True)           # uuid
    user_id = Column(String(36), index=True, nullable=False)
    title = Column(String(200), default="新对话")
    skill_id = Column(String(100), nullable=False, default="")   # '' = 通用；否则为已安装技能 slug
    segment = Column(Integer, default=0)               # 当前分段序号（控制单 thread 消息量）
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Message(Base):
    """会话消息：展示 / 编辑 / 版本 / 分页的权威来源（项目不使用 checkpointer）。

    - message_id 在同一问题的所有编辑版本间保持不变；每次编辑 version 自增，
      旧版本置 is_current=False 归档（保留历史，供箭头切换回显）。
    - seq 为会话内展示顺序；编辑非最新消息时，截断 seq 之后的所有消息。
    - assistant 行的 parent_id 指向其所属 user 消息的 message_id。
    """
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True)
    message_id = Column(String(36), index=True, nullable=False)
    conversation_id = Column(String(36), index=True, nullable=False)
    user_id = Column(String(36), index=True, nullable=False)
    role = Column(String(16), nullable=False)             # user / assistant
    content = Column(Text)                                # 消息文本
    reply = Column(Text)                                  # user 行：本版本回复快照
    version = Column(Integer, default=1)
    seq = Column(Integer, nullable=False)
    parent_id = Column(String(36), index=True)
    is_current = Column(Boolean, default=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class SkillSource(Base):
    """技能源：GitHub 仓库（技能市场的数据上游）。"""
    __tablename__ = "skill_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    source_key = Column(String(255), unique=True, index=True, nullable=False)  # gh:owner/repo
    kind = Column(String(32), default="github")
    label = Column(String(120), default="")
    url = Column(String(512), default="")
    enabled = Column(Boolean, default=True)
    last_fetched_at = Column(DateTime)
    fetch_error = Column(String(512), default="")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Skill(Base):
    """技能市场快照：由技能源同步 GitHub Releases 生成（slug 全局唯一）。"""
    __tablename__ = "skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    slug = Column(String(100), unique=True, index=True, nullable=False)
    name = Column(String(120), nullable=False, default="")
    version = Column(String(32), nullable=False, default="")
    description = Column(Text, default="")
    author = Column(String(128), default="")
    emoji = Column(String(32), default="")
    category = Column(String(64), default="通用")
    homepage = Column(String(512), default="")
    has_cli = Column(Boolean, default=False)
    source_key = Column(String(255), nullable=False, default="")
    artifact_url = Column(String(1024), default="")
    release_url = Column(String(1024), default="")
    asset_size = Column(Integer, default=0)
    install_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class InstalledSkill(Base):
    """用户安装记录（含安装时快照；技能源下线后本地仍可用）。"""
    __tablename__ = "installed_skills"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(36), index=True, nullable=False)
    slug = Column(String(100), nullable=False)
    name = Column(String(120), default="")
    version = Column(String(32), default="")
    description = Column(Text, default="")
    emoji = Column(String(32), default="")
    category = Column(String(64), default="通用")
    source_key = Column(String(255), default="")
    status = Column(String(16), default="ok")
    error = Column(Text, default="")
    installed_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
    __table_args__ = (UniqueConstraint("user_id", "slug", name="uq_installed_user_slug"),)


def get_engine():
    # 仅 PostgreSQL（asyncpg 驱动，连接池复用，支撑多实例/高并发）。
    # settings.database_url 由 config 按 DB_HOST/PORT/NAME(+可选 USER/PASSWORD) 拼装。
    url = settings.database_url.strip()
    return create_async_engine(
        url,
        echo=False,
        pool_pre_ping=True,
        pool_size=20,       # 常驻连接数（按 worker 数 × 并发调整）
        max_overflow=10,    # 高峰可临时超出的连接数
        pool_timeout=30,    # 取不到连接时等待上限（秒），超时即报错而非无限阻塞
    )


engine = get_engine()
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    """FastAPI 依赖：提供请求级异步数据库会话"""
    async with SessionLocal() as session:
        yield session


def _core_tables() -> set:
    """应用自身拥有的业务表（schema.sql 负责创建；不含 langgraph / 记忆模块运行时自建的表）。

    包含技能平台三表：老库升级时若缺失这些表，会触发 schema.sql 全量重跑，
    其中的 CREATE TABLE IF NOT EXISTS 会幂等补齐新增表、跳过已存在的表。
    """
    return {"users", "conversations", "messages", "skills", "skill_sources", "installed_skills"}


async def _tables_exist() -> bool:
    """判断核心业务表是否都已存在（已建好则无需重复建表）。"""
    try:
        async with engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            )
            existing = {r[0] for r in rows}
        return _core_tables().issubset(existing)
    except Exception as e:
        log.warning("[DB] 检查已存在表失败，将尝试建表: %s", e)
        return False


def _run_schema_sql():
    """读取并执行 schema.sql（CREATE TABLE IF NOT EXISTS，幂等、可重复执行）。

    表定义集中在项目根 schema.sql（类似 MySQL 的 .sql 建表文件），
    启动时直接执行，已存在的表会自动跳过，绝不重复建表。
    多副本并发启动时，psycopg 可能报 UniqueViolation（序列/索引冲突），
    此处捕获并忽略，由外层的锁 + 二次检查确保安全。
    """
    # schema.sql 位于项目根目录；本文件在 infra/ 子目录下，需向上一级才能找到。
    # 兼容多种部署位置，依次尝试候选路径，命中第一个存在的文件（避免文件位置
    # 变动导致 FileNotFoundError → 启动建表失败 → 容器崩溃 → 永久 unhealthy）。
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(here, "schema.sql"),                       # db.py 与 schema.sql 同目录（旧结构）
        os.path.join(os.path.dirname(here), "schema.sql"),     # 项目根（db.py 在 infra/ 下，当前结构）
        os.path.join(os.getcwd(), "schema.sql"),               # 工作目录即项目根
    ]
    sql_path = next((p for p in candidates if os.path.exists(p)), None)
    if not sql_path:
        raise FileNotFoundError(f"找不到 schema.sql，已尝试路径：{candidates}")
    with open(sql_path, "r", encoding="utf-8") as f:
        sql = f.read()
    # 仅 PostgreSQL：用同步驱动执行 DDL（去掉 +asyncpg 标识，复用 psycopg）
    sync_url = settings.database_url.replace("+asyncpg", "")
    import psycopg
    conn = psycopg.connect(sync_url, autocommit=True)
    try:
        for stmt in sql.split(";"):
            stmt = stmt.strip()
            if stmt:
                try:
                    conn.execute(stmt)
                except psycopg.errors.UniqueViolation:
                    # 多副本同时启动时可能并发执行 DDL，序列/索引冲突正常，
                    # 表已由另一个副本建好，继续执行下一条即可。
                    pass
    finally:
        conn.close()


def _run_migrations():
    """对已存在的表执行幂等增量迁移（ADD COLUMN IF NOT EXISTS）。

    仅补列、不改已有结构：schema.sql 负责新库建表，本函数负责老库升级。
    多次执行安全（IF NOT EXISTS 幂等）。新增业务列时在此追加 ALTER 语句即可。
    """
    stmts: list[str] = [
        # 老库升级：conversations 增加技能任务标识列（默认 '' = 通用对话）
        "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS skill_id VARCHAR(100) DEFAULT '';",
        # 新列就绪后再建技能对话查询索引（幂等；新库列随 CREATE 建好，此处重复执行无副作用）
        "CREATE INDEX IF NOT EXISTS ix_conversations_skill_id ON conversations(user_id, skill_id);",
    ]
    sync_url = settings.database_url.replace("+asyncpg", "")
    import psycopg
    conn = psycopg.connect(sync_url, autocommit=True)
    try:
        for stmt in stmts:
            try:
                conn.execute(stmt)
            except Exception as e:
                # 单条失败不阻断其余；记录后继续（如列已存在外的其它瞬时错误）。
                log.warning("[DB迁移] 执行失败（可下次启动重试）: %s | %s", stmt, e)
    finally:
        conn.close()


# 单实例本地场景用进程内锁串行化建表即可（无需 Redis 协调）。
_build_lock = asyncio.Lock()


async def init_db():
    """启动时自动建库 + 建表（无需手动建库 / 跑迁移）。

    流程：
    1. 目标库不存在则自动创建（连接 postgres 维护库；本地阶段免手动建库）；
    2. 先判断核心业务表是否已存在：
       - 都已存在 → 直接跳过，**绝不重复建表**，启动零成本；
       - 未建好 → 在锁内执行项目根 schema.sql（CREATE TABLE IF NOT EXISTS，幂等）：
         * 表定义集中在 schema.sql，与应用代码（db.py 模型）保持一致；
         * 放在线程里跑，避免与 FastAPI 已运行的事件循环冲突。
    """
    await _ensure_database_exists()
    if await _tables_exist():
        log.info("[DB] 核心表已存在，跳过自动建表")
    else:
        async with _build_lock:
            # 二次检查：持锁后若已建好，则无需重复
            if await _tables_exist():
                pass
            else:
                try:
                    await asyncio.to_thread(_run_schema_sql)
                    log.info("[DB] 表结构已就绪（schema.sql 已应用）")
                except Exception as e:
                    log.error("[DB] 自动建表失败：%s", e)
                    raise
    # 增量迁移：对已存在表补加新列（幂等 ADD COLUMN IF NOT EXISTS），
    # 兼容「老库升级」——schema.sql 的 CREATE TABLE IF NOT EXISTS 不会给已有表加列。
    try:
        await asyncio.to_thread(_run_migrations)
    except Exception as e:
        # 迁移失败非致命：仅影响新功能，不阻断整体启动。
        log.error("[DB] 增量迁移失败（非致命，不影响其余功能）：%s", e)


async def _ensure_database_exists():
    """目标库不存在时自动创建（连接 postgres 维护库）。

    仅用于本地/测试阶段免去手动建库；生产建议由 DBA 预先建库，删除本调用亦可。
    无密码（trust）或留空账号（asyncpg 回退到 OS 用户）都能工作。
    """
    target = settings.db_name
    admin_url = _pg_url(settings.db_host, settings.db_port, "postgres",
                        settings.db_user, settings.db_password)
    admin_engine = create_async_engine(admin_url, pool_pre_ping=True)
    try:
        async with admin_engine.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target})
            if not exists:
                # CREATE DATABASE 不能在事务内执行，需 AUTOCOMMIT。
                # 上面 scalar() 已 autobegin 事务，必须先 rollback 才能改 isolation_level。
                await conn.rollback()
                autocommit_conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
                await autocommit_conn.execute(text(f'CREATE DATABASE "{target}"'))
                log.info("[DB] 已自动创建数据库 %s", target)
    except Exception as e:
        log.warning("[DB] 自动建库跳过（如已存在或无权限创建）：%s", e)
    finally:
        await admin_engine.dispose()



