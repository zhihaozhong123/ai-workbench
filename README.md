# 智作台（AI Workbench）

**本地 macOS AI 技能工作台**：原生 `.app` 桌面应用（Tauri v2）+ 本地后端（FastAPI + LangGraph）。
它把「通用 Agent 对话」升级为「**Agent 工作台 + 技能市场**」：开发者写好技能并发布到
GitHub Release，用户一键安装后，就在「对话任务」里获得该技能的**专属 Agent**。

- 代码/数据都在你本机，存储依赖 PostgreSQL + Redis + Chroma。
- 仅支持 macOS（本期桌面端）。

## 核心能力

- **对话任务**：注册登录（JWT 双 token + 可吊销）、WebSocket 流式聊天、消息持久化、
  ReAct Agent（LangGraph）、长期记忆（向量热存储 + 词法冷存储）、多模型（DeepSeek 等）。
- **技能市场（GitHub Release 分发）**：配置化技能源 → 拉取 Releases → 市场搜索 / 分类 /
  技能卡片（图标 / 名称 / 版本 / 描述 / 安装次数）/ 安装 / 卸载 / 升级。
- **技能任务**：安装后「对话任务」左侧新增该技能任务入口；进入专属对话后，Agent 注入技能
  系统提示并挂载「技能 CLI 工具」（安全子进程、JSON in/out、超时、env 白名单），由主 Agent 调度。
- **系统设置**：账号信息、服务地址、自动检查更新开关、手动检查 / 下载新版本、关于。
- **版本更新**：远端更新 manifest（任意托管 JSON），启动自动检查弹窗 + 设置页手动检查下载。
- **本机控制（macOS）**：通用对话内置打开应用 / 网页 / AppleScript 自动化等本地控制工具。

> 本产品不含「知识库（KB/RAG）」与「自动邮件（SMTP）」功能——它们的代码、页面与数据表已随改造移除。

## 技术架构

```text
┌──────────────────────────────────────────────────────────┐
│  智作台.app（Tauri v2 原生窗口，macOS）                    │
│  ├─ 前端：Vue 3 + Vue Router + Pinia（WebView）           │
│  └─ 后端：Python FastAPI + LangGraph ReAct                │
│        ├─ Agent：通用工具 + 技能提示注入 + 技能 CLI 工具    │
│        ├─ 技能平台：catalog/installer/runtime             │
│        └─ 持久化：PostgreSQL + Redis + Chroma(记忆热存储)  │
└──────────────────────────────────────────────────────────┘
```

| 层 | 技术 |
|----|------|
| 桌面壳 | Tauri v2（Rust；窗口 + 本机执行 + 外部打开） |
| 前端 | Vue 3 + Vue Router + Pinia + Axios（浅色工作台 UI） |
| 后端 | Python FastAPI + LangGraph（ReAct）+ httpx |
| Agent 工具 | 联网搜索 / 打开网页 / 计算 / 时间 / 记忆 / 本地控制 / 技能 CLI |
| LLM | DeepSeek（OpenAI 兼容）；可选联网搜索凭据（SerpAPI） |
| 存储 | PostgreSQL（用户 / 会话 / 消息 / 技能注册表）；Redis（锁 / 信号量 / 限流 / 缓存 / 黑名单） |
| 向量 | Chroma（仅长期记忆热存储） |
| 技能分发 | GitHub Releases（公开仓匿名 API；可选 PAT `GITHUB_TOKEN`） |

## 快速开始（一键启停）

前置：本机运行 Docker Desktop。

```bash
./up.sh            # 启动全部：PostgreSQL + Redis + Chroma + 后端 + 前端（全 docker）
./up.sh app        # 同上，并额外以 Tauri dev 模式打开桌面 App（需本机 Rust 环境）
./up.sh --build    # 强制重建后端镜像（依赖变更后使用）
./down.sh          # 停止全部并【清空数据】（下次启动为全新状态）
./down.sh --keep-data  # 仅停止，保留数据
```

启动后的地址：

| 服务 | 地址 |
|------|------|
| 前端（网页） | http://127.0.0.1:5173 |
| 后端 API | http://127.0.0.1:8000（文档 /docs） |
| PostgreSQL | 127.0.0.1:15432 |
| Redis | 127.0.0.1:16379 |
| Chroma | 127.0.0.1:18001 |

不用 nginx、Prometheus/Loki/Grafana 等运维组件——本项目只保留纯净的前后端与三个数据服务。

## 关键环境变量（根目录 `.env`）

| 变量 | 默认 | 说明 |
|------|------|------|
| `ENV` / `JWT_SECRET` | dev | `production` 时强制强随机 JWT 密钥 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` | 127.0.0.1 / 5432 / xiaoshutong | PostgreSQL |
| `REDIS_URL` | 必填 | Redis（多实例协调：锁 / 信号量 / 限流 / 黑名单） |
| `CHROMA_HOST` / `CHROMA_PORT` | 127.0.0.1 / 18001 | 长期记忆向量库（共享 Chroma 服务，固定连接） |
| `DEEPSEEK_API_KEY` | - | LLM 密钥 |
| `SERPAPI_API_KEY` | - | 可选：联网搜索工具凭据（也可作为技能的 `env_whitelist` 透传） |
| `GITHUB_TOKEN` | - | 可选：GitHub PAT，提升技能市场配额 / 访问私有源 |
| `SKILL_SOURCES` | - | 默认技能源 JSON（`gh:owner/repo` 列表），不填则从市场 UI 添加 |

> 密钥管理：`.env` 已 gitignore，不会进入版本库。

## 技能平台

- **技能包契约 XST-Skill v1**：仓库根 `manifest.json` 为权威元数据；缺失时兼容回退读取
  `SKILL.md` frontmatter，因此 skill-template 仓库可零改动接入。
- **内置技能（本地包）**：技能源码位于 `data/skills/<slug>/`，`scripts/register_skill.py` 登记到市场
  （source_key=local）；卸载只移除用户安装记录，技能代码与市场快照不删除。
- **安装安全**：manifest 严格校验 → 防 zip-slip 安全解压到 `data/skills/<slug>/` → 写注册表；
  单个技能失败只影响它自己，不影响平台。
- **Agent 落地**：`conversations.skill_id` 标识专属会话；`agent_runner` 动态注入技能提示与
  `skill_<slug>` 工具（子进程执行，JSON in/out、超时、env 白名单、Redis 分布式信号量限流）。

内置技能示例：`data/skills/wechat-article-publish/`。

## 项目结构（要点）

```text
main.py / config.py / schema.sql     # 入口、配置、DDL
up.sh / down.sh                      # 一键启动 / 停止清空（全 docker 编排）
Dockerfile                           # 后端镜像（python:3.14-slim + uv）
api/                                 # routes_auth / conversation / chat / messages / skills
core/agent_runner.py                 # Agent 编排：通用工具 + 技能注入（skill_id）
skills/                              # 技能平台：manifest(契约)/catalog(市场)/installer(安装)/runtime(执行)
infra/                               # db(SQLAlchemy)/state_store(Redis 原语)/messages/security/schemas/embeddings
tools/                               # web_search / memory / calc / time / local(本机控制)
scripts/                             # register_skill / reset_db / reset_chroma
data/                                # 运行时数据：skills 安装目录
frontend/                            # Vue3：ChatView / SkillMarketView / SettingsView
src-tauri/                           # Tauri 壳（窗口、本机执行）
```

## 安全

- JWT 双 token 可吊销（Redis 黑名单跨实例）、HTTP/WS 限流、bcrypt 密码哈希；
- 技能子进程：超时、env 白名单、仅透传声明变量、敏感凭据不进日志；
- 锁 / 信号量 / 限流 / 缓存失效 / 注销黑名单全部走 Redis（`state_store.py`）。

## FAQ

- **窗口提示「连接未就绪」**：后端未启动或端口不对（默认 8000）。
- **市场一直空 / 拉不到 Release**：先在「技能市场 → 管理技能源」添加含 `.xskill` 资产的公开仓库；
  匿名 GitHub API 有 60 次/时配额，平台已做 TTL 缓存与重试。
- **技能任务没有工具**：技能需在 `manifest.json` 声明 `runtime.entry` 才会被包装为可执行工具；
  纯提示词技能只有系统提示；声明 `permissions: ["local_control"]` 的本地控制类技能会额外注入
  `open_webpage / run_apple_script` 等本机控制工具。
