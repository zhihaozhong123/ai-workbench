-- 智作台 (AI Workbench) 数据库表结构（PostgreSQL）
-- 启动时由 db.init_db() 执行：CREATE TABLE IF NOT EXISTS 幂等，重复执行安全。
-- 列定义与 db.py 中的 SQLAlchemy 模型保持一致。
-- checkpoint_* / cold_memories 等表由 langgraph / 记忆模块在运行时自建，不在此维护。
-- skills / skill_sources / installed_skills 表由 skills 模块初始化时创建，不在此维护。

CREATE TABLE IF NOT EXISTS users (
    id            SERIAL       PRIMARY KEY,
    user_id       VARCHAR(36)  NOT NULL,
    username      VARCHAR(64)  NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    nickname      VARCHAR(64)  DEFAULT '',
    created_at    TIMESTAMP,
    is_active     BOOLEAN       DEFAULT TRUE
);
CREATE INDEX IF NOT EXISTS ix_users_user_id ON users(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users(username);

CREATE TABLE IF NOT EXISTS conversations (
    id         VARCHAR(36) PRIMARY KEY,
    user_id    VARCHAR(36) NOT NULL,
    title      VARCHAR(200) DEFAULT '新对话',
    skill_id   VARCHAR(100) DEFAULT '',    -- '' = 通用对话；否则为该技能专属任务（已安装技能 slug）
    segment    INTEGER      DEFAULT 0,
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);
-- 注：ix_conversations_skill_id 在 infra/db.py _run_migrations 中创建（老库需先 ALTER
-- 补列再建索引；新库在 schema.sql 的 CREATE 已含 skill_id 列，由迁移幂等补建即可）。

-- 消息表：会话展示 / 编辑 / 版本 / 分页的权威来源（由 messages 仓库维护，
-- 项目不使用 LangGraph checkpointer。编辑非最新消息会截断后续并新增版本）。
CREATE TABLE IF NOT EXISTS messages (
    id              SERIAL       PRIMARY KEY,
    message_id      VARCHAR(36)  NOT NULL,   -- 逻辑消息 ID：同一问题的所有版本共享
    conversation_id VARCHAR(36)  NOT NULL,
    user_id         VARCHAR(36)  NOT NULL,
    role            VARCHAR(16)  NOT NULL,   -- user / assistant
    content         TEXT,                    -- 消息文本
    reply           TEXT,                    -- user 行：本版本对应 assistant 回复快照（用于版本切换回显）
    version         INTEGER      DEFAULT 1,   -- 同一 message_id 内的版本号，编辑自增
    seq             INTEGER      NOT NULL,   -- 会话内展示顺序（0 起）
    parent_id       VARCHAR(36),             -- assistant 行：所属 user 消息的 message_id
    is_current      BOOLEAN       DEFAULT TRUE, -- 仅当前版本为 true，旧版本归档保留
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS ix_messages_message_id ON messages(message_id);

-- 技能平台（XST-Skill）：
-- skills = 技能市场快照（由各 skill_sources 同步 GitHub Releases 而来，slug 全局唯一）；
-- skill_sources = 技能源（GitHub 仓库），市场数据唯一上游；
-- installed_skills = 用户安装记录（安装的是某时点的快照，源删除后仍可运行已装版本）。

CREATE TABLE IF NOT EXISTS skill_sources (
    id              SERIAL        PRIMARY KEY,
    source_key      VARCHAR(255)  NOT NULL,          -- gh:owner/repo（唯一标识）
    kind            VARCHAR(32)   DEFAULT 'github',
    label           VARCHAR(120)  DEFAULT '',
    url             VARCHAR(512)  DEFAULT '',
    enabled         BOOLEAN       DEFAULT TRUE,
    last_fetched_at TIMESTAMP,
    fetch_error     VARCHAR(512)  DEFAULT '',
    created_at      TIMESTAMP,
    updated_at      TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_skill_sources_key ON skill_sources(source_key);

CREATE TABLE IF NOT EXISTS skills (
    id            SERIAL        PRIMARY KEY,
    slug          VARCHAR(100)  NOT NULL,            -- 技能唯一 slug（同 slug 多源时以最近同步的为准）
    name          VARCHAR(120)  NOT NULL DEFAULT '',
    version       VARCHAR(32)   NOT NULL DEFAULT '',
    description   TEXT          DEFAULT '',
    author        VARCHAR(128)  DEFAULT '',
    emoji         VARCHAR(32)   DEFAULT '',
    category      VARCHAR(64)   DEFAULT '通用',
    homepage      VARCHAR(512)  DEFAULT '',
    has_cli       BOOLEAN       DEFAULT FALSE,
    source_key    VARCHAR(255)  NOT NULL DEFAULT '',
    artifact_url  VARCHAR(1024) DEFAULT '',          -- 最新 .xskill 下载地址
    release_url   VARCHAR(1024) DEFAULT '',
    asset_size    INTEGER       DEFAULT 0,
    install_count INTEGER       DEFAULT 0,
    created_at    TIMESTAMP,
    updated_at    TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_skills_slug ON skills(slug);
CREATE INDEX IF NOT EXISTS ix_skills_category ON skills(category);
CREATE INDEX IF NOT EXISTS ix_skills_source ON skills(source_key);

CREATE TABLE IF NOT EXISTS installed_skills (
    id           SERIAL        PRIMARY KEY,
    user_id      VARCHAR(36)   NOT NULL,
    slug         VARCHAR(100)  NOT NULL,
    name         VARCHAR(120)  DEFAULT '',
    version      VARCHAR(32)   DEFAULT '',
    description  TEXT          DEFAULT '',
    emoji        VARCHAR(32)   DEFAULT '',
    category     VARCHAR(64)   DEFAULT '通用',
    source_key   VARCHAR(255)  DEFAULT '',
    status       VARCHAR(16)   DEFAULT 'ok',         -- ok / failed（安装/执行失败时标记，便于用户重试）
    error        TEXT          DEFAULT '',
    installed_at TIMESTAMP,
    updated_at   TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS ix_installed_skills_user_slug ON installed_skills(user_id, slug);
CREATE INDEX IF NOT EXISTS ix_installed_skills_user ON installed_skills(user_id);
