# 小书童 API 接口文档

> 本文档基于原 README 第六点整理并补全，覆盖认证、会话、长期记忆、聊天、消息、知识库、邮箱发信、WebSocket 与 Agent 工具能力。所有接口均经认证鉴权保护。

## 1. 基础说明

- **基础地址**
  - 开发：`http://127.0.0.1:8000`
  - 生产：经 nginx 反代后的公网域名（如 `https://your-domain`）
- **鉴权**：除 `GET /`（健康检查）与 WebSocket 连接握手外，所有接口都要求在请求头携带：
  ```
  Authorization: Bearer <access_token>
  ```
  - `access_token` 有效期 **15 分钟**；`refresh_token` 有效期 **7 天**。
  - 获取方式：先用 `POST /api/login` 拿到 `access_token` / `refresh_token`；`access_token` 过期后用 `POST /api/refresh` 换发。
- **客户端标记（X-XST-Client）**：本服务原有一层「仅桌面客户端可访问」的校验（中间件要求请求头 `X-XST-Client`）。当前 `.env` 中 `XST_REQUIRE_CLIENT=false`，该层已关闭，**网页端 / Postman / `/docs` 均可直接调用**，无需携带该头。若上线想恢复限制，将 `.env` 中设为 `true` 重启即可（真正的防护始终是上面的 Bearer 鉴权，无账号者仍无法调用）。
- **通用错误码**
  - `400`：请求参数/格式不合法
  - `401`：未登录 / token 无效或过期
  - `404`：资源不存在或无权限访问
  - `409`：资源冲突（如账号已注册）
  - `500`：服务端内部错误

---

## 2. 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/register` | 注册账号，返回双 token |
| POST | `/api/login` | 登录，返回双 token |
| POST | `/api/refresh` | 用 refresh 换发新 access |
| POST | `/api/logout` | 注销，吊销当前 token |
| GET | `/api/me` | 获取当前用户信息 |

### 2.1 POST /api/register
注册新用户（邮箱或手机号 + 密码）。

**请求体**
```json
{
  "username": "user@example.com",   // 必填，邮箱或手机号（作为唯一登录 ID）
  "password": "123456",             // 必填，至少 6 位
  "nickname": "小明"                // 可选，昵称，可空
}
```

**返回值**
```json
{
  "access_token": "eyJ...",   // 访问令牌，15 分钟有效
  "refresh_token": "eyJ...",  // 刷新令牌，7 天有效
  "token_type": "bearer",     // 令牌类型
  "user_id": "uuid",          // 用户唯一 ID
  "username": "user@example.com"  // 归一化后的登录账号（邮箱转小写）
}
```

**可能错误**：`400` 密码少于 6 位；`409` 该邮箱/手机号已注册。

### 2.2 POST /api/login
账号登录，成功后返回双 token。

**请求体**
```json
{ "username": "user@example.com", "password": "123456" }
```

**返回值**：同 2.1 的 `TokenResponse`。

**可能错误**：`401` 邮箱/手机号或密码不正确。

### 2.3 POST /api/refresh
用未过期的 `refresh_token` 换发新的 `access_token`（旧 refresh 仍可持续使用）。

**请求体**
```json
{ "refresh_token": "eyJ..." }
```

**返回值**：同 `TokenResponse`（含新的 access_token 与原 refresh_token）。

**可能错误**：`401` refresh token 无效 / 已过期 / 已吊销（已 logout）。

### 2.4 POST /api/logout
注销当前会话：将当前 `access_token` 与指定的 `refresh_token` 加入黑名单，**立即失效**。

**请求体**
```json
{ "refresh_token": "eyJ..." }   // 可选；不传则只吊销当前 access
```

**返回值**
```json
{ "ok": true }
```

### 2.5 GET /api/me
获取当前登录用户的基本信息。

**请求头**：`Authorization: Bearer <access_token>`

**返回值**
```json
{
  "user_id": "uuid",
  "username": "user@example.com",
  "nickname": "小明",
  "created_at": "2026-07-28T10:00:00"   // 注册时间（ISO8601）
}
```

**可能错误**：`404` 用户不存在。

---

## 3. 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/conversations` | 新建一个会话 |
| GET | `/api/conversations` | 列出当前用户的所有会话 |
| GET | `/api/conversations/{conversation_id}/messages` | 恢复某会话的历史消息 |

所有接口需 `Authorization: Bearer <access_token>`。

### 3.1 POST /api/conversations
新建空白会话，用于后续聊天时携带 `conversation_id`。

**返回值**
```json
{
  "conversation_id": "uuid",                 // 会话唯一 ID
  "title": "新对话",                          // 会话标题
  "updated_at": "2026-07-28T10:00:00"        // 最后更新时间
}
```

### 3.2 GET /api/conversations
列出当前用户全部会话，按 `updated_at` 倒序（最近使用在前）。

**返回值**
```json
[
  { "conversation_id": "uuid", "title": "新对话", "updated_at": "..." },
  { "conversation_id": "uuid", "title": "..." , "updated_at": "..." }
]
```

### 3.3 GET /api/conversations/{conversation_id}/messages
恢复指定会话的历史消息（用于「继续对话」）。

**路径参数**：`conversation_id` —— 会话 ID。

**返回值**
```json
{
  "conversation_id": "uuid",
  "messages": [                            // 历史消息列表（按时间顺序）
    { "role": "user", "content": "..." },
    { "role": "assistant", "content": "..." }
  ]
}
```

**可能错误**：`404` 会话不存在或不属于当前用户。

---

## 4. 长期记忆查看

### 4.1 GET /api/memory/long_term
查看当前用户的长期记忆（经验积累）。注意：**热库（hot）存完整原文，可直接阅读**；冷库（cold）为压缩后的记忆。

**查询参数**
- `source`：`all`（默认）/ `hot` / `cold`，选择查看热库、冷库或全部。
- `limit`：返回条数上限，默认 `200`，范围 `1–1000`。

**返回值**
```json
{
  "user_id": "uuid",
  "source": "all",
  "hot": {
    "count": 12,
    "items": [
      { "id": "chroma-id", "created_at": "2026-07-28T10:00:00",
        "days_ago": 3, "content": "记忆原文..." }
    ]
  },
  "cold": {
    "count": 5,
    "items": [
      { "id": 1, "content": "压缩后的记忆...", "source_count": 2,
        "created_at": "2026-07-20T08:00:00" }
    ]
  }
}
```
- `hot.items[].content`：热记忆原文（可读）。
- `hot.items[].days_ago`：距今天数。
- `cold.items[].source_count`：该冷记忆由多少条热记忆合并压缩而来。

**可能错误**：`400` `source` 取值非法。

---

## 5. 聊天接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/chat` | 非流式（一次性返回，调试用） |
| POST | `/api/chat/stream` | SSE 流式（逐字返回，前端主用） |

### 5.1 POST /api/chat
同步、非流式聊天。发送消息后等待模型完整生成再一次性返回，主要用于调试。

**请求体**
```json
{
  "message": "你好",            // 必填，用户消息，最长 8000 字符
  "conversation_id": "uuid",    // 可选，不传则自动新建会话
  "client_msg_id": "uuid",      // 可选，前端生成的稳定消息 ID，用于版本/编辑跟踪
  "mode": "send"                // 可选，send（默认）/ regenerate（重新生成）
}
```

**返回值**
```json
{
  "conversation_id": "uuid",    // 本次会话 ID（新建或复用）
  "reply": "助手的完整回复",     // 模型最终回复文本
  "tool_calls": [               // 本次回答过程中调用的工具记录
    { "name": "web_search", "args": {...}, "result": "..." }
  ]
}
```

**可能错误**：`404` 指定会话不存在或无权访问。

### 5.2 POST /api/chat/stream
SSE（Server-Sent Events）流式聊天，前端主交互方式。响应 `Content-Type: text/event-stream`，每个事件以 `data: <json>\n\n` 推送，结束时发送 `data: [DONE]\n\n`。

**请求体**：同 5.1。

**返回值（事件流）**
```
data: {"type":"ready","user_id":"...","conversation_id":"...","thread_id":"..."}
data: {"type":"tool_call","name":"web_search","args":{...}}
data: {"type":"tool_result","error":false,"preview":"搜索结果摘要"}
data: {"type":"token","content":"你"}
data: {"type":"token","content":"好"}
data: {"type":"final","reply":"你好，有什么可以帮你？"}
data: [DONE]
```

事件类型含义：
- `ready`：连接就绪，携带 `user_id` / `conversation_id` / `thread_id`。
- `tool_call`：即将调用某工具，`name` 为工具名，`args` 为入参。
- `tool_result`：`error` 是否出错，`preview` 为结果预览。
- `token`：最终回复的逐字片段，累加即得完整回复。
- `clear_intermediate`：清掉「思考中」闪现的中间文字（客户端应清空临时展示）。
- `loop_detected`：检测到可能死循环，`message` 为提示。
- `final`：完整回复（`reply` 字段）。
- `done`：流结束。
- `error`：出错，`message` 为错误信息。

---

## 6. 消息管理

消息持久化在 `messages` 表，是会话展示、编辑、版本、分页的权威来源。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/messages` | 分页获取某会话当前版本消息 |
| POST | `/api/messages/edit` | 编辑某条用户消息（触发重新生成） |
| GET | `/api/messages/versions` | 获取某条用户消息的版本历史 |

### 6.1 GET /api/messages
分页获取会话消息（前端历史加载、箭头切换走此接口）。

**查询参数**
- `conversation_id`：必填，会话 ID。
- `limit`：返回条数，默认 `50`。
- `before_seq`：可选分页游标，取 `seq` 小于该值的消息（用于向上翻页）。

**返回值**
```json
{
  "conversation_id": "uuid",
  "messages": [
    {
      "message_id": "stable-id",   // 逻辑消息 ID（跨版本稳定不变）
      "role": "user",              // user / assistant
      "content": "消息内容",
      "version": 1,                // 当前版本号
      "seq": 10,                   // 序号（顺序）
      "versions": [                // 仅 user 消息有；该消息的版本历史
        { "version": 1, "content": "原内容", "reply": "对应助手回复" }
      ],
      "current_version": 0         // 当前激活版本在 versions 中的下标
    }
  ]
}
```

**可能错误**：`404` 会话不存在或无权访问。

### 6.2 POST /api/messages/edit
编辑某条用户消息内容（编辑后前端通常据此重新生成回复）。

**请求体**
```json
{
  "conversation_id": "uuid",
  "message_id": "stable-id",   // 被编辑 user 消息的逻辑 ID
  "content": "编辑后的新内容"
}
```

**返回值**：`{ "conversation_id": "...", "messages": [...] }`（返回编辑后该会话的最新消息列表，结构同 6.1）。

**可能错误**：`404` 消息不存在或不可编辑。

### 6.3 GET /api/messages/versions
获取某条用户消息的全部版本（用于箭头切换历史版本）。

**查询参数**：`conversation_id`、`message_id`。

**返回值**
```json
{
  "conversation_id": "uuid",
  "message_id": "stable-id",
  "versions": [
    { "version": 1, "content": "第一版内容", "reply": "对应回复" },
    { "version": 2, "content": "第二版内容", "reply": "对应回复" }
  ]
}
```

---

## 7. 知识库管理（多租户 / 零知识）

知识库按用户隔离（tenant）。零知识模式下，Chroma 只存向量 + 元数据，原文留在用户自己的目录，检索时按需回取。

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/kb/register` | 注册知识库（指定目录或文件列表） |
| POST | `/api/kb/upload` | 上传文档注册知识库（form-data） |
| GET | `/api/kb/supported_formats` | 支持的文档格式 |
| GET | `/api/kb/list` | 列出当前用户的知识库 |
| DELETE | `/api/kb/{kb_name}` | 删除知识库 |
| POST | `/api/kb/{kb_name}/rebuild` | 重建索引 |
| POST | `/api/kb/calibrate` | 触发在线校准（top-k/阈值寻优） |
| GET | `/api/kb/calibrate/{task_id}` | 查询校准任务状态 |

### 7.1 POST /api/kb/register
通过指定本地目录或文件列表注册知识库（BYOC 模式，零知识）。

**请求体**
```json
{
  "kb_name": "我的手册",          // 必填，知识库名称
  "doc_dir": "/Users/me/docs",     // 文档目录（与 doc_files 二选一）
  "doc_files": ["/a.pdf","/b.docx"], // 或直接指定文件列表（与 doc_dir 二选一）
  "description": "产品文档",        // 可选，描述
  "doc_name": "手册合集"            // 可选，文档展示名
}
```

**返回值**：`{ "ok": true, ...配置信息 }`（`kb_name` 等注册结果）。

**可能错误**：`400` 目录/文件不存在或无权限；达到每租户知识库数量上限。

### 7.2 POST /api/kb/upload
通过 HTTP 多文件上传方式注册知识库（form-data）。

**请求（multipart/form-data）**
- `files`：文档文件（至少一个，支持格式见 7.3）。
- `description` / `kb_name` / `doc_name`：可选文本字段。

**返回值**：`{ "ok": true, ...配置信息 }`。

**可能错误**：`400` 未提供文件 / 含不支持的格式。

### 7.3 GET /api/kb/supported_formats
返回系统支持的文档扩展名列表。

**返回值**
```json
{ "extensions": [".pdf", ".docx", ".txt", ".md", ...] }
```

### 7.4 GET /api/kb/list
列出当前用户全部知识库及其配置与就绪状态。

**返回值**
```json
{
  "kbs": [
    {
      "kb_name": "我的手册",
      "doc_name": "手册合集",
      "doc_dir": "/Users/me/docs",    // 内存模式时为空字符串
      "description": "产品文档",
      "available": true,              // 是否可检索（索引就绪）
      "status": "ready",              // building / ready / failed
      "error_message": "",            // 失败时的错误信息
      "calibrated": false,            // 是否已在线校准
      "chunk_size": 800,              // 切分大小
      "top_k": 8,                     // 召回条数
      "similarity_threshold": 0.3     // 相似度阈值
    }
  ]
}
```

### 7.5 DELETE /api/kb/{kb_name}
删除指定知识库（含向量与配置）。

**路径参数**：`kb_name` —— 知识库名称。

**返回值**：`{ "ok": true, ... }`。

### 7.6 POST /api/kb/{kb_name}/rebuild
对指定知识库重新构建索引（例如源文档更新后）。

**返回值**：`{ "ok": true, ... }`。

### 7.7 POST /api/kb/calibrate
触发指定知识库的在线校准（自动寻优 top-k / 相似度阈值等）。

**请求体**：`{ "kb_name": "我的手册" }`

**返回值**：`{ "ok": true, "task_id": "uuid", ... }`。

### 7.8 GET /api/kb/calibrate/{task_id}
查询校准任务进度与结果。

**路径参数**：`task_id` —— 校准任务 ID（来自 7.7 返回）。

**返回值**：校准任务状态对象（含进度、阶段、最优参数等）。

**可能错误**：`404` 任务不存在或不属于当前用户。

---

## 8. 邮箱发信（163 SMTP）

用于配置 163 邮箱 SMTP 授权码，使 Agent 能发信。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/email/status` | 查询发信凭证是否已配置 |
| POST | `/api/email/credential` | 保存/更新发信凭证 |
| DELETE | `/api/email/credential` | 删除发信凭证 |

### 8.1 GET /api/email/status
**返回值**
```json
{ "configured": true, "email": "user@163.com" }   // configured=false 时无 email 字段
```

### 8.2 POST /api/email/credential
保存或更新 163 SMTP 发信凭证（授权码加密存储）。

**请求体**
```json
{
  "email": "user@163.com",     // 必填，有效邮箱
  "auth_code": "abcd-efgh-ijkl-mnop"  // 必填，163 授权码（16 位，非登录密码）
}
```

**返回值**
```json
{ "ok": true, "message": "邮箱发信凭证已保存（user@163.com）" }
```

**可能错误**：`400` 邮箱无效 / 授权码格式不正确。

### 8.3 DELETE /api/email/credential
删除已配置的发信凭证。

**返回值**：`{ "ok": true, "message": "邮箱发信凭证已删除" }`

**可能错误**：`404` 尚未配置凭证。

---

## 9. WebSocket 实时交互

WebSocket 是桌面客户端的主要交互通道（与 `POST /api/chat/stream` 推送的事件类型一致）。

- **连接地址**：`ws://127.0.0.1:8000/ws/chat?token=<JWT>`（生产替换为对应域名；`token` 为 access_token）
- **客户端 → 服务端**（JSON）：
  ```json
  { "type": "message", "content": "你好", "conversation_id": "可选" }
  ```
- **服务端 → 客户端**（逐事件 JSON，字段含义同 5.2）：
  - `{"type":"ready","user_id":...,"conversation_id":...,"thread_id":...}`
  - `{"type":"tool_call","name":...,"args":...}`
  - `{"type":"tool_result","error":bool,"preview":...}`
  - `{"type":"token","content":...}`（回复逐字）
  - `{"type":"clear_intermediate"}`（清掉临时思考文字）
  - `{"type":"loop_detected","message":...}`
  - `{"type":"final","reply":...}` / `{"type":"done"}` / `{"type":"error","message":...}`

---

## 10. Agent 工具能力清单

Agent 可调用的工具，也是它「能做什么」的边界：

| 工具 | 作用 |
|------|------|
| `search_knowledge_base` | 本地知识库向量检索（RAG） |
| `web_search` | 联网搜索（SerpAPI） |
| `open_application` | 打开本机应用（macOS） |
| `open_webpage` | 用默认浏览器打开网址（macOS） |
| `run_apple_script` | 执行 AppleScript 自动化（macOS） |
| `send_email_smtp` | 163 SMTP 发信（纯文本 + 附件） |
| `check_email_ready` | 发信前自检凭证是否就绪 |
| `calculator` | 数学计算 |
| `get_current_time` | 查询当前时间 |
| `save_to_memory` / `recall_from_memory` | 长期记忆存取 |

---

## 附：调用示例（curl）

```bash
# 1. 登录拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"user@example.com","password":"123456"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. 查看长期记忆
curl http://127.0.0.1:8000/api/memory/long_term?source=all&limit=50 \
  -H "Authorization: Bearer $TOKEN"

# 3. 列出知识库
curl http://127.0.0.1:8000/api/kb/list -H "Authorization: Bearer $TOKEN"
```

> 当前 `.env` 中 `XST_REQUIRE_CLIENT=false`，以上请求无需携带 `X-XST-Client` 头即可成功（见第 1 节说明）。
