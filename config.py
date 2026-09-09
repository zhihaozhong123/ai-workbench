import os

from dotenv import load_dotenv

# 1. 代码设置 `load_dotenv(override=False)` 的含义是什么？
load_dotenv(override=False)

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# 项目根目录（config.py 位于项目根）：用于推导默认数据目录（技能安装目录等）。
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))


def _pg_url(host: str, port: int, name: str, user: str, password: str) -> str:
    """拼 PostgreSQL asyncpg DSN。user/password 任一为空则省略（测试阶段无密码登录）。"""
    auth = ""
    if user:
        auth = user
        if password:
            auth += ":" + password
        auth += "@"
    return f"postgresql+asyncpg://{auth}{host}:{port}/{name}"


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ===== JWT（双 token：短期 access + 长期 refresh）=====
    jwt_secret: str
    jwt_algorithm: str
    access_token_expire_minutes: int
    refresh_token_expire_hours: int

    # ===== 运行环境 =====
    # dev（本地）/ production（独立部署，会强制强随机 JWT_SECRET 并关闭 /docs）
    env: str

    # ===== 日志 =====
    log_level: str
    # json（生产，便于 Loki/ELK/Vector 采集）/ text（dev，便于调试）
    log_format: str

    # ===== 本地服务（仅本机 127.0.0.1，不对外暴露）=====
    backend_host: str
    backend_port: int

    # ===== CORS 额外允许的跨域来源（逗号分隔，留空=仅本机前端）=====
    extra_cors_origins: str

    # ===== 存储 =====

    # ===== 主关系数据库（PostgreSQL）=====
    # DB_HOST / DB_PORT / DB_NAME 必填；DB_USER / DB_PASSWORD 为【预留、可选】：
    # 测试阶段留空即可（本地 PG 配 trust 无密码登录）；以后生产再在 .env 填这两项。
    # 最终 DSN 由下方 database_url 属性按上述字段自动拼装，代码其它处仍读 settings.database_url。
    # 长期记忆的【向量】仍在 Chroma（共享 Chroma 服务），不在此列。
    # 注：pgvector 是 PostgreSQL 的扩展，本阶段向量检索仍由 Chroma 承担，故这里无需 pgvector。
    db_host: str
    db_port: int
    db_name: str
    db_user: str = ""          # 预留：测试阶段可留空（asyncpg 回退到 OS 用户）
    db_password: str = ""      # 预留：同上

    @property
    def database_url(self) -> str:
        """拼装 PostgreSQL asyncpg DSN；user/password 为空时省略（无密码登录）。"""
        return _pg_url(self.db_host, self.db_port, self.db_name,
                       self.db_user, self.db_password)

    # ===== 对话分段 =====
    # 单段(thread)消息上限，超过自动开新段（保留最近窗口）；
    # 跨段连续性由「按 user_id 隔离的长期记忆」保证，避免上下文无限膨胀。
    segment_max_messages: int

    # ===== 超时（秒）=====
    # 单次 LLM / embedding HTTP 请求超时；底层 httpx 超过即断开并重试。
    llm_request_timeout: float
    # 单轮对话（含多轮工具调用 / 压缩）整体超时；到点强制中断并返回兜底提示，
    # 防止某个卡死的 LLM/工具把 worker 连接一直占着导致雪崩。
    chat_timeout_seconds: float

    # ===== 限流（每 IP 每分钟）=====
    rate_limit_per_minute: int              # 普通接口
    rate_limit_auth_per_minute: int         # 注册/登录接口（更严，防爆破）

    # ===== 多实例共享协调（Redis，必填）=====
    # 锁 / 技能执行信号量 / 缓存失效广播 / 刷新黑名单 / 频率限制
    # 全部走 Redis，支持多实例水平扩展。现已不再支持「进程内降级」模式，必须配置。
    redis_url: str

    # ===== 技能平台（XST-Skill）=====
    # 技能安装根目录：默认 <项目根>/data/skills。
    # 技能 CLI 子进程并发由全局信号量 skills_run 控制（上限 skill_exec_max_concurrency）。
    skills_root: str = ""
    skill_exec_max_concurrency: int = 4   # 全局技能 CLI 子进程并发上限
    # 提高默认技能 CLI 调用超时到 180s（3 分钟），与业务需求 1~3 分钟相匹配。
    skill_exec_timeout_seconds: float = 180.0  # 单个技能 CLI 调用超时上限（防失控技能占满 worker）

    # ===== LLM（DeepSeek）=====
    deepseek_api_key: str
    deepseek_model: str
    deepseek_base_url: str

    # ===== Embedding（阿里云百炼，RAG 与长期记忆共用）=====
    aliyun_embedding_api_key: str
    aliyun_embedding_model: str
    aliyun_embedding_base_url: str

    # ===== Chroma 向量库（长期记忆热存储；固定连共享 Chroma 服务）=====
    chroma_host: str
    chroma_port: int

    # ===== 运维接口保护（并发上限热更等）=====
    # 设置后，运维接口需带请求头 X-Admin-Token 匹配才放行；留空则运维接口返回 503 禁用。
    admin_api_token: str = ""

    # ===== GitHub 技能源 =====
    # 技能市场从 GitHub Releases 拉取。公开仓库可用匿名 API（免 token，配额 60 次/时/IP，
    # 已配合 Redis TTL 缓存规避）；配置 GH_TOKEN 可提升配额 / 访问私有仓库。
    github_token: str = ""
    # 技能源自动重同步间隔（秒）：打开市场/任务页超过该间隔未同步则触发后台刷新
    skill_catalog_ttl_seconds: int = 600

    # ===== 应用版本与远端更新（智作台桌面端）=====
    # app_version 与 src-tauri/tauri.conf.json、src-tauri/Cargo.toml 中的 version 保持一致；
    # 前端 / 设置页展示用的版本号（frontend/src/config.js APP_VERSION）也应同步。
    app_version: str = "0.1.0"
    # 远端更新 manifest JSON（含 version/notes/download_url 等）。留空 = 未接入更新服务，
    # /api/update/check 返回 501，前端呈现「暂未接入远端更新服务」。
    update_manifest_url: str = ""

    # ===== 可选工具凭证（留空 = 对应工具不可用）=====
    serpapi_api_key: str               # 联网搜索（web_search 工具）

    @model_validator(mode="after")
    def _enforce_production_safety(self):
        # 推导技能安装根目录（默认 <项目根>/data/skills）
        if not self.skills_root.strip():
            object.__setattr__(
                self, "skills_root", os.path.join(_PROJECT_ROOT, "data", "skills")
            )
        try:
            os.makedirs(self.skills_root, exist_ok=True)
        except OSError:  # 只读环境等场景下不阻断启动，实际安装时再报
            pass
        # PostgreSQL 是唯一数据库后端；DB_HOST / DB_NAME 必须配置。
        if not self.db_host.strip() or not self.db_name.strip():
            raise ValueError(
                "必须配置 PostgreSQL：请在 .env 设置 "
                "DB_HOST / DB_PORT / DB_NAME（DB_USER / DB_PASSWORD 可留空）。"
            )
        # REDIS_URL 必填：所有多实例协调原语。
        if not self.redis_url or not self.redis_url.strip():
            raise ValueError(
                "REDIS_URL 为必填项。"
                "请在 .env 配置 REDIS_URL=redis://host:6379/0 后再启动。"
            )
        # 显式 env=production → 视为生产约束，禁止弱密钥
        is_production = self.env.strip().lower() == "production"
        if is_production and self.jwt_secret == "dev-secret-change-me":
            raise ValueError(
                "生产环境禁止使用默认 JWT 密钥（dev-secret-change-me）。"
                "请在 .env 配置强随机 JWT_SECRET（例如 `openssl rand -hex 32`）后再启动，"
                "否则任何人都能伪造登录 token。"
            )
        return self


settings = Settings()
