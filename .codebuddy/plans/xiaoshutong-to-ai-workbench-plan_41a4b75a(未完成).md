---
name: xiaoshutong-to-ai-workbench-plan
overview: 将 xiaoshutong 项目改造为仿匠厂的 AI 工作台桌面应用：删除知识库与邮件功能，保留注册登录与对话能力，新增左侧模块导航、技能市场、技能安装后生成任务入口、系统设置与版本更新。
design:
  architecture:
    framework: vue
    component: tdesign
  styleKeywords:
    - Apple HIG
    - 浅色桌面 UI
    - 左侧边栏导航
    - 卡片式任务列表
    - 蓝色主行动色
    - 柔和阴影
    - 圆角现代
    - 微交互动效
  fontSystem:
    fontFamily: PingFang SC
    heading:
      size: 18px
      weight: 600
    subheading:
      size: 14px
      weight: 500
    body:
      size: 13px
      weight: 400
  colorSystem:
    primary:
      - "#2563EB"
      - "#1D4ED8"
      - "#3B82F6"
    background:
      - "#F3F4F6"
      - "#FFFFFF"
      - "#E5E7EB"
    text:
      - "#1F2937"
      - "#4B5563"
      - "#9CA3AF"
    functional:
      - "#10B981"
      - "#EF4444"
      - "#F59E0B"
todos:
  - id: rename-brand
    content: 统一替换应用名称与标识为「匠厂 AI 工作台」
    status: pending
  - id: explore-deps
    content: 使用 [subagent:code-explorer] 扫描 KB/邮件 全库引用点
    status: pending
  - id: remove-kb-email
    content: 删除前后端 KB、邮件相关代码与数据库表
    status: pending
    dependencies:
      - explore-deps
  - id: add-skills-backend
    content: 实现技能清单、安装记录与按技能定制 Agent 接口
    status: pending
    dependencies:
      - remove-kb-email
  - id: refactor-frontend-layout
    content: 改造 App.vue 为左侧边栏，重设路由
    status: pending
    dependencies:
      - remove-kb-email
  - id: build-views
    content: 实现对话任务、技能市场、系统设置、占位页面
    status: pending
    dependencies:
      - refactor-frontend-layout
  - id: updater-desktop
    content: 配置 Tauri updater 与版本检查弹窗
    status: pending
    dependencies:
      - build-views
  - id: cleanup-verify
    content: 清理残留引用、运行冒烟测试并更新文档
    status: pending
    dependencies:
      - add-skills-backend
      - updater-desktop
---

## 项目概述
在现有 `xiaoshutong` 项目基础上改造为一个全新的 macOS 桌面 AI 助手应用，新名称建议为 **「匠厂 AI 工作台」**（英文/包名可同步为 `ai-workbench`）。应用定位为「本地 Agent 工作台」：保留注册登录与多轮对话能力，取消知识库与自动邮件功能，新增「技能市场」与「任务式对话」体验。

## 核心功能
1. **品牌/名称替换**：应用内名称、窗口标题、Tauri 包标识、README 等统一改为「匠厂 AI 工作台」。
2. **移除知识库能力**：删除前后端所有知识库相关代码（KB 注册/索引/检索/校准、RAG 工具、KB 配置表、.enc 上传加密、前端知识库页面）。
3. **移除自动邮件能力**：删除邮件路由、SMTP 发信工具、邮箱凭证表、前端邮件配置入口。
4. **保留注册登录**：JWT 双 token、用户表、会话表、鉴权中间件保持不变。
5. **保留对话核心**：WebSocket 流式聊天、消息持久化、ReAct Agent、长期记忆画像机制不变。
6. **匠厂风格 UI 改造**：改为左侧一级边栏导航，包含「对话任务、技能市场、数据管理、任务中心、定时任务、模型管理、频道管理、插件管理、更多、系统设置」。
7. **对话任务模块**：主区左侧为「新建任务 + 已安装技能的任务卡片」列表，右侧为聊天区；点击技能任务即进入该技能的专属对话。
8. **技能市场模块**：搜索框 + 分类标签 + 技能卡片列表；支持安装/卸载技能；技能数据本阶段随后端内置分发。
9. **系统设置-更新**：支持启动时检查远端 manifest，有新版本弹窗提示；设置页可手动检查、显示版本差异并跳转下载。
10. **占位模块**：其他边栏入口仅展示标题与空状态，具体页面本阶段不实现。



## 技术栈
- 桌面壳：Tauri v2（Rust）
- 前端：Vue 3 + Vue Router + Pinia + Axios
- 后端：Python FastAPI + LangGraph（ReAct Agent）
- 存储：PostgreSQL（用户/会话/消息/技能安装）+ Redis（必填，协调与限流）
- 向量：保留 Chroma 用于长期记忆热存储（仅非知识库用途）

## 实现方案
### 后端
1. **清理 KB/邮件**
   - 删除 `api/routes_kb.py`、`api/routes_email.py` 并取消注册。
   - 删除 `core/kb_manager.py`、`core/kb_calibration.py`、`tools/rag_tool.py`、`tools/email_smtp_tool.py`、`tools/kb_crypto.py`。
   - 在 `infra/db.py`、`schema.sql` 中移除 `user_kb_config`、`calibration_tasks`、`user_email_creds` 表及相关迁移 SQL。
   - 清理 `main.py` WebSocket 入口中的 `kb_manager.set_tenant(user_id)` 调用与路由导入。

2. **新增技能系统**
   - 内置技能清单：`data/skills/manifest.json`（或 `skills/` 目录下的 YAML），包含技能 id、名称、slug、图标、分类、描述、版本、价格、系统提示词片段、可用工具白名单。
   - 数据库新增 `skills`（内置清单表，开发时预置）与 `installed_skills`（用户安装记录）表。
   - 新增 `api/routes_skills.py`：列表/分类/搜索、安装、卸载、我的已安装技能。
   - `conversations` 表新增 `skill_id` 字段，用于关联技能专属对话；默认通用任务 skill_id 为空。

3. **Agent 按技能定制**
   - `core/agent_runner.py` 的 `chat_stream` 增加可选 `skill_id` 参数。
   - 若 `skill_id` 有效，从 `installed_skills` + `skills` 读取该技能的「系统提示词片段」和「可用工具白名单」。
   - 将该片段追加到动态系统提示词；工具集合按白名单从全局工具集中过滤后传入 `create_react_agent`，实现不同技能调用不同能力。

4. **版本更新**
   - 新增 `api/routes_update.py`：返回当前后端打包版本（与 Tauri 版本保持一致），以及可选的远端 manifest 地址。
   - 远端 manifest 为静态 JSON（建议放在可访问 HTTPS URL），包含最新版本号、下载地址、release notes。
   - Tauri 端启用 `tauri-plugin-updater` 并配置 endpoints；通过 JS API `checkUpdate()` 触发检查，使用 Tauri dialog 或前端弹窗提示；设置页提供「自动检查更新」开关与手动检查按钮。

### 前端
1. **全局布局**：`App.vue` 改为左侧一级边栏 + 右侧主内容区结构，不再只是 `<router-view />`。
2. **路由改造**：删除 `/kb`、`/kb-list`；新增 `/tasks`（默认进入对话任务）、`/market`（技能市场）、`/settings`（系统设置）、`/placeholder/:key`（占位模块）。
3. **对话任务页**：`ChatView.vue` 改造为「任务列表 + 聊天区」两栏布局；左侧显示「新建任务」和已安装技能的任务卡片；点击后跳转到对应 `conversation_id`（按 skill 查找或自动创建）。
4. **技能市场页**：新增 `SkillMarketView.vue`，包含搜索框、分类标签、技能卡片（图标/名称/版本/描述/安装次数/价格/安装按钮）。
5. **设置页**：新增 `SettingsView.vue`，左侧二级设置菜单，主要实现「更新」面板（当前版本、可用更新、下载按钮、自动检查更新开关）。
6. **状态管理**：新增 `stores/skills.js` 管理技能列表、安装状态；`stores/auth.js` 与 `stores/chat.js` 保留并适配。

### 桌面壳
1. 修改 `src-tauri/tauri.conf.json`：`productName`、`identifier`、`version`、`title` 更新为「匠厂 AI 工作台」；在 `plugins` 中配置 updater endpoints。
2. 修改 `src-tauri/Cargo.toml`：启用 `tauri-plugin-updater`。
3. 修改 `src-tauri/src/lib.rs`：暴露 `check_update`、`download_update` 等 Tauri Command；启动时可选自动检查更新。

## 架构设计
```
┌─────────────────────────────────────────────────────────┐
│  匠厂 AI 工作台.app (Tauri + Vue3)                        │
│  ├─ 左侧边栏导航（对话任务/技能市场/系统设置/占位模块）    │
│  ├─ 技能市场 → 安装技能 → 写入 installed_skills          │
│  ├─ 对话任务 → 按 skill 加载对应系统提示+工具            │
│  └─ 系统设置 → 版本检查 → manifest / Tauri updater       │
├─────────────────────────────────────────────────────────┤
│  FastAPI 后端                                             │
│  ├─ 保留：注册/登录/会话/消息/WebSocket/Agent/长期记忆    │
│  ├─ 新增：技能清单/安装/卸载/Agent 按技能定制            │
│  └─ 删除：KB 路由/邮件路由/RAG 工具/邮箱工具               │
└─────────────────────────────────────────────────────────┘
```

## 目录结构

```text
xiaoshutong_jc/
├── frontend/src/
│   ├── App.vue                         # [MODIFY] 改为左侧边栏全局布局
│   ├── router/index.js                 # [MODIFY] 替换路由表
│   ├── views/
│   │   ├── ChatView.vue                # [MODIFY] 对话任务模块（任务列表+聊天）
│   │   ├── SkillMarketView.vue         # [NEW] 技能市场
│   │   ├── SettingsView.vue            # [NEW] 系统设置（含更新）
│   │   └── PlaceholderView.vue         # [NEW] 占位模块
│   ├── components/
│   │   ├── AppSidebar.vue              # [NEW] 左侧一级边栏
│   │   ├── SkillCard.vue               # [NEW] 技能卡片
│   │   └── TaskCard.vue                # [NEW] 任务入口卡片
│   ├── stores/
│   │   └── skills.js                   # [NEW] 技能状态
│   └── api/
│       ├── skills.js                   # [NEW] 技能市场 API
│       └── update.js                   # [NEW] 版本更新 API
├── api/
│   ├── routes_skills.py                # [NEW] 技能相关接口
│   ├── routes_update.py                # [NEW] 版本信息接口
│   ├── routes_kb.py                    # [DELETE] 删除
│   └── routes_email.py                 # [DELETE] 删除
├── core/
│   ├── agent_runner.py                 # [MODIFY] 支持 skill_id 注入
│   ├── kb_manager.py                   # [DELETE] 删除
│   └── kb_calibration.py               # [DELETE] 删除
├── tools/
│   ├── rag_tool.py                     # [DELETE] 删除
│   ├── email_smtp_tool.py              # [DELETE] 删除
│   └── kb_crypto.py                    # [DELETE] 删除
├── infra/
│   ├── db.py                           # [MODIFY] 移除 KB/邮件模型，新增 skills/installed_skills
│   └── schema.sql                      # [MODIFY] 同上
├── data/skills/manifest.json           # [NEW] 内置技能清单
├── src-tauri/
│   ├── tauri.conf.json                 # [MODIFY] 应用名、版本、updater 配置
│   ├── Cargo.toml                      # [MODIFY] 启用 updater plugin
│   └── src/lib.rs                      # [MODIFY] 增加更新检查命令
└── README.md                           # [MODIFY] 品牌与功能说明更新
```

## 关键代码结构

### 1. Agent 按技能定制的函数签名
```python
async def chat_stream(
    user_id: str,
    thread_id: str,
    message: str,
    user_name: str = "",
    history: list | None = None,
    skill_id: str | None = None,   # 新增
) -> AsyncIterator[dict]:
```

### 2. 技能数据模型（SQLAlchemy）
```python
class Skill(Base):
    __tablename__ = "skills"
    id = Column(String(36), primary_key=True)
    name = Column(String(64), nullable=False)
    slug = Column(String(64), unique=True, nullable=False)
    icon = Column(String(255))
    category = Column(String(64))
    description = Column(Text)
    version = Column(String(32))
    system_prompt = Column(Text)       # 追加到 Agent 系统提示词
    tools_allowed = Column(Text)       # JSON 数组，工具白名单
    price_info = Column(String(255))
    install_count = Column(Integer, default=0)


class InstalledSkill(Base):
    __tablename__ = "installed_skills"
    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), index=True, nullable=False)
    skill_id = Column(String(36), nullable=False)
    installed_at = Column(TIMESTAMP)
```

### 3. WebSocket 消息扩展字段
前端发送消息时增加 `skill_id` 字段；后端 `_run_chat` 透传给 `agent_runner.chat_stream`。



## 设计架构
采用 **Vue 3 + Tauri v2** 原生桌面应用架构，引入 **tdesign-vue-next** 组件库统一按钮、开关、输入框、卡片、弹窗等控件，保证桌面端视觉一致性与开发效率。整体风格参考「匠厂 App」：浅灰背景、左侧深色/浅色边栏、蓝色主行动色、卡片式内容区、圆角与柔和阴影。

## 页面规划

### 1. 全局布局（App.vue）
- 左侧固定 64px/180px 可折叠边栏，顶部显示品牌图标与名称。
- 边栏一级菜单：对话任务、技能市场、数据管理、任务中心、定时任务、模型管理、频道管理、插件管理、更多、系统设置。
- 选中项高亮蓝色背景 + 白色图标，hover 有轻微背景过渡。
- 底部显示「匠厂 AI 工作台」版本号徽标。
- 右侧主内容区随路由切换。

### 2. 对话任务模块（ChatView.vue）
- 左侧二级面板：顶部搜索框 + 新建任务按钮。
- 列表首项为「新建任务」卡片（蓝色高亮），点击创建通用对话。
- 已安装技能按任务卡片展示：图标、技能名称、slug、状态角标。
- 右侧聊天区：顶部显示当前任务标题，中间消息流（保留现有对话气泡/重试/编辑/版本切换），底部输入框与模型选择器（DeepSeek）。
- 空态：未选择任务时显示引导文字。

### 3. 技能市场模块（SkillMarketView.vue）
- 顶部标题 + 副标题「浏览和安装匠厂专属 AI 技能」。
- 搜索框（按名称/slug/ID 搜索）+ 蓝色「搜索」按钮。
- 分类标签栏：全部、标准版、定制版，以及多行分类 pills（今日头条、供应商管理、内容创作、客服、营销获客等）。
- 技能卡片：左侧圆角图标，右侧名称/版本/价格/描述/安装次数，右侧「安装」按钮（已安装显示「打开」/「卸载」）。
- 点击卡片进入详情浮层或跳转详情页（本阶段可在卡片展开简介）。

### 4. 系统设置模块（SettingsView.vue）
- 左侧二级设置菜单：用户信息、存储管理、通用、网关、代理、开发者、更新、关于。
- 右侧内容区：
  - 「更新」面板：当前版本号、可用更新版本卡片、下载更新按钮、自动检查更新开关、自动更新开关。
  - 其余菜单为占位页面，显示模块名称与「即将上线」提示。

### 5. 占位模块（PlaceholderView.vue）
- 对应「数据管理、任务中心、定时任务、模型管理、频道管理、插件管理、更多」。
- 页面中央显示大图标 + 标题 + 「功能开发中」提示。

## 响应式与交互
- 桌面窗口默认 1100×800，最小 800×600；侧边栏可折叠（设置/通用里控制）。
- 卡片 hover 轻微上浮 + 阴影加深。
- 按钮/开关使用 tdesign 组件，保证焦点态与键盘可访问。
- 更新弹窗使用 tdesign Dialog，标题「发现新版本」，内容展示版本号与更新日志，按钮「立即下载」/「稍后提醒」。

## Agent 扩展
- **SubAgent: code-explorer**
  - **用途**：在清理 KB/邮件相关代码前，扫描全仓库中对这些模块的导入与调用点，确保删除后无残留引用。
  - **预期结果**：输出所有引用 `kb_manager`、`kb_calibration`、`rag_tool`、`email_smtp_tool`、`routes_kb`、`routes_email`、`UserKBConfig`、`UserEmailCred` 的文件位置，为清理阶段提供待改清单。
