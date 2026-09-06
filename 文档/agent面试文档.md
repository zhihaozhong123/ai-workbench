# 小书童 Agent 实现 · 面试问答手册

> 面向 **AI Agent / 后端开发** 岗位的面试问答。本文聚焦「Agent 这一层」的实现，结合小书童项目真实代码，按「面试官可能怎么问 → 你怎么答」的形式展开。每个回答都尽量落到具体文件与实现细节，便于在面试中讲出有深度的东西，而不是泛泛而谈。
>
> 配套文档：架构与部署详见《面试文档-小书童项目介绍.md》；本文只讲 Agent 本体与周边（记忆 / RAG / 工具 / 并发 / 护栏）。

---

## 一、整体认知类

### Q1. 先整体介绍一下，你们这个 Agent 是怎么搭起来的？

**答：** 我们的 Agent 是一个「本地优先的桌面 AI 助手」，但后端是标准 Python（FastAPI + LangGraph），所以 Agent 这一层既能在本地跑，也能当无状态服务容器化部署。

Agent 的骨架用的是 **LangGraph 的 `create_react_agent`**，也就是经典的 ReAct（Reason → Act → Observe）循环：LLM 先判断「这个问题要不要调工具 / 调哪个工具 / 填什么参数」，工具返回结果后再次进入 LLM，如此循环，直到给出最终回答。推理模型用 DeepSeek（`deepseek-chat`），工具是普通 Python 函数通过 function calling 注册进去，目前有 12 个工具，覆盖 RAG 检索、联网、长期记忆读写、本机控制（开应用 / 开网页 / AppleScript / 找文件）、发邮件、计算、时间。

核心代码在 `core/agent.py`（构造 Agent + 动态提示词）和 `core/agent_runner.py`（运行器，封装流式 / 同步两种调用方式、记忆压缩、护栏）。

一句话：**LangGraph 把 ReAct 工程化，工具就是函数，记忆分短期（业务 messages 表 + 每轮回传）和长期（Chroma + PG）两层，整轮跑在一个 WebSocket 流里。**

---

### Q2. 为什么选 LangGraph，而不是自己手写一个 `while` 循环去调 LLM？

**答：** ReAct 本质上就是「LLM 决策 + 工具执行」的状态机，手写 `while` 循环也能跑通 demo，但项目要上生产，LangGraph 提供了几个手写很难低成本拿到的能力：

1. **图即状态机**：`StateGraph` 把状态、节点、边显式建模，比 `while` 循环好维护、好观测（能 trace 每一步）。
2. **循环保护**：`recursion_limit=12` 限制单轮工具调用深度；再叠加应用层的「连续 3 次重复工具调用即判定 loop_detected 中断」，避免 Agent 陷入无效死循环——这是手写循环最容易忽略的健壮性点。
3. **生态成熟**：和 LangChain 工具 / 消息类型无缝对接，新增能力就是加一个函数 + 改 prompt 工具清单。

> 说明：本项目线上对话**不使用** LangGraph checkpointer。短期记忆持久化由业务 `messages` 表负责，每轮上下文由 `get_context_messages` 从表读取后回传给 Agent。这样上下文只属于本次调用，天然避免并发覆盖，也省去 checkpointer 的运维。

> 面试追问可能问：为什么用 `create_react_agent` 预置图，不自己 `StateGraph`？——预置图覆盖了绝大多数对话场景，省代码；需要自定义分支时仍可在底层 API 上扩展。当前是「够用且规范」的选择。

---

## 二、ReAct 推理与工具调用

### Q3. 这套 ReAct 循环具体是怎么转起来的？一次「调工具」内部经历了什么？

**答：** 以流式接口为例，链路是：

1. `agent_runner.chat_stream` 拿到编译好的无状态 Agent（`init_run_agent()`），把本轮 `history + HumanMessage(用户消息)` 作为 `messages` 输入。
2. 调用 `agent.astream({"messages": ...}, config=..., stream_mode=["messages","values"])`。LangGraph 内部走 ReAct 预置图：
   - **Reason**：LLM 看当前 messages，决定直接回答，还是输出 `tool_calls`。
   - **Act**：框架把 `tool_calls` 路由到对应的 Python 工具函数执行（工具在 `asyncio.to_thread` 线程池里跑，不阻塞事件循环）。
   - **Observe**：工具的 `ToolMessage` 结果回到 messages，再次进入 LLM。
   - 循环直到 LLM 不再输出 tool_calls，给出最终 `AIMessage`。
3. `recursion_limit=12` 是硬上限；应用层还有「连续 3 次相同工具调用」的软中断（`agent_runner.py` 的 `loop_detected` 逻辑）。
4. `stream_mode=["messages","values"]` 让我们一边拿到逐 token 的 `AIMessageChunk`（用于「逐字输出」），一边在结束时拿到完整 `values.messages`（用于跑护栏、持久化）。

---

### Q4. 工具是怎么被 Agent 识别和调用的？讲讲 function calling 的细节。

**答：** 工具就是被 `@tool` 装饰的普通 Python 函数（如 `tools/rag_tool.py` 的 `search_knowledge_base`、`tools/local_tool.py` 的 `open_application`），LangChain 会自动把它转成 OpenAI 兼容的 function-calling schema（函数名 + 参数 JSON schema + 描述），发给 DeepSeek。

关键点：

- **模型自己决策**：是调工具还是直接答、调哪个、参数填什么，全部由 LLM 决定，比「关键词路由」更泛化。工具描述（docstring）写得好不好，直接影响调用准确率——所以我们给 `search_knowledge_base` 写了一段很长的 `description`，明确「只要问题和文档有关就必须先调我」。
- **工具无状态**：`_get_tools()` 返回的工具集合是模块级单例、不保存单次问答状态，可被并发复用。`user_id` 通过注入的 `RunnableConfig["configurable"]["user_id"]` 传入，即使工具在异步线程池执行也能拿到当前用户，不会串号。
- **真实副作用的安全**：开应用 / AppleScript / 发邮件是「真实动作」，所以前置 TCC 授权 + 工具层「谎报成功护栏」兜底。

---

### Q5. 你怎么防止 Agent 在「调工具」这一步陷入死循环或者重复劳动？

**答：** 两层防护：

1. **图级硬上限**：`recursion_limit=12`，单轮最多 12 次工具决策，到头强制停。
2. **应用层软检测**：`chat_stream` 里维护一个 `seen` 列表记录本轮触发过的工具名，当「最近连续 `MAX_REPEAT=3` 次都是同一个工具」时，判定 `loop_detected`，立刻 `break` 并推一条「检测到重复工具调用，已中断」的事件给前端，不再浪费 LLM / 工具配额。

这一点的价值在于：模型有时候会因为工具返回结果「不完美」而反复重试同一工具，硬上限能兜底，软检测能更早止损、提升体感。

---

## 三、记忆系统

### Q6. 你的 Agent 有「记忆」吗？短期记忆和长期记忆分别怎么做的？

**答：** 有两层，分工明确：

**短期记忆（会话内上下文）**：由业务 `messages` 表负责。实时对话走无 checkpointer 的并发 Agent（`init_run_agent`），每轮上下文由调用方从消息表 `get_context_messages` 显式读出来传入——这样上下文只属于本次调用，不写入共享 thread，天然避免并发覆盖。当前未做自动压缩，长会话的建议是在业务层对回传历史做截断/摘要，以防上下文无限膨胀。

**长期记忆（跨会话「懂用户」）**：双层设计，在 `core/memory/long_term.py`：
- **热存储**：ChromaDB 向量库，存最近的事实/偏好，语义检索；单线程满 `HOT_MAX_PER_THREAD=200` 条触发压缩。
- **冷存储**：PostgreSQL，满 20 条热记录压缩成 1 条摘要（`[压缩×N条]`），用 BM25（jieba 中文分词）做词法检索兜底。
- 检索时热、冷两路并行，按 `相似度 × 0.9^(days_ago/30)` 时间衰减合并重排取 top_k，越久的记忆权重越低。冷库 > 10000 条从最旧开始淘汰。

---

### Q7. 长期记忆为什么冷存储用 BM25 而不是再开一套向量库？

**答：** 几个现实理由：

- 冷记忆是「粗粒度兜底」，已经被截断成 300 字以内的短摘要，关键词命中即可，不追求精语义。
- BM25（jieba 中文分词）便宜、确定、可解释，且**避免了再维护一套向量索引**的运维成本。
- 旧方案用 `LIKE '%关键词%'` 有三个硬伤：前导通配符全表扫描、按空格切词对中文失效、无 IDF 排序差。改 BM25 后全部消除。
- 真正到百万级、含大量专名/编号、高并发时，才应该换统一混合检索引擎（Qdrant / Weaviate / Elasticsearch）。当前是「成本与复杂度最优」的中间态。

> 注意：这里「压缩 ≠ 加密」。压缩是有损的「截断 + 合并明文摘要」，原文删除不可恢复，但摘要仍可被 BM25 搜到，所以检索不需要也不存在「解压」。

---

### Q8. 「越聊越懂用户」是怎么实现的？用户画像为什么做成动态注入，而不是写死在 system prompt？

**答：** 在 `core/agent.py` 的 `dynamic_prompt` 回调里实现。每轮 LLM 调用前：

1. 从注入的 `config.configurable.user_id` 拿到当前用户，取本轮最后一条用户消息作为检索 query。
2. 调 `lt.recall_memories` 检索长期记忆，拼出「## 已知用户画像（来自长期记忆）」段落，追加到静态系统提示词后面。
3. 这个画像**只用于本次 LLM 调用，不持久化到对话历史**，所以不会污染对话历史、不会让历史越来越长。

为什么动态注入而非静态写死：

- 静态写进 system prompt 会让「越聊越长」的画像持续累积，污染短期记忆、烧 token。
- 动态注入既保证个性化，又随对话即时更新，且不串号（按 user_id 隔离）。
- 同轮内对 `(user_id, query)` 做轻量缓存（`_PROFILE_CACHE`，上限 256），避免 ReAct 循环里 LLM 被多次调用导致重复检索长期记忆。

---

### Q9. 记忆的隔离是怎么保证多用户不串号的？

**答：** 三层隔离：

- **热存储**：Chroma 按 `tenant/database = mem_<user_id>` 原生隔离，应用层过滤代码即使有 bug，直接连 Chroma 也只看得到本用户 tenant（双保险）。
- **冷存储**：PostgreSQL 单表 `public.cold_memories`，按 `thread_id`（= user_id）行级过滤；淘汰时必须带 `thread_id` 条件，否则会误删别人。
- **运行期**：`user_id` 从 `RunnableConfig["configurable"]["user_id"]` 透传，工具在异步线程池里执行也拿得到正确 ID；本地控制指令也用 `contextvars.ContextVar` 记录当前用户，路由到正确客户端。

---

## 四、RAG 与知识库

### Q10. 知识库检索是怎么做的？为什么用混合检索而不是纯向量？

**答：** 在 `tools/rag_tool.py`，检索走「向量召回 + BM25 关键词召回 → RRF 融合 → 可选 rerank → 阈值过滤」：

1. **向量召回**（语义）：LlamaIndex `VectorStoreIndex.as_retriever`，余弦相似度。
2. **BM25 召回**（词法）：jieba 分词，专治「按名字 / 订单号 / 专名找片段」这类向量语义不匹配但字面命中的查询。
3. **RRF 融合**（Reciprocal Rank Fusion，`_rrf` 方法）：两路排名按 `1/(k+rank+1)` 加权求和融合，无需训练权重，简单稳健，工业界主流做法。
4. 阈值过滤只作用于向量召回（`similarity_threshold`），BM25 命中永远保留，避免「字面命中但向量分低」被误杀。
5. 可选 rerank：RRF 候选前 N 个送百炼 text-rerank 精排（默认关闭灰度，由 `user_kb_config` 逐库开启），失败自动回退 RRF 不阻断。

**为什么不全用向量**：纯向量对专名 / 编号 / 代码召回差（"订单号 A2026" 容易 miss）；纯 BM25 不懂语义（"怎么退课" 命中不了 "课程取消流程"）。混合取两者之长。

---

### Q11. 你们强调「零知识」知识库，这个隐私设计具体怎么落地的？

**答：** 核心原则：**Chroma 里只存向量 + 定位 metadata，绝不持久化原文**（`store_text=False`）。

- 索引时把绝对路径改写为相对 `rel_path`，记录 `start_char_idx / end_char_idx` 字符偏移和 `text_hash`。
- 检索命中后，凭 `rel_path + 字符偏移`，从**用户自己的 doc_dir**（BYOC，程序只读不复制）实时解析取回原文片段，解析结果只存在本次查询内存里，不落运营方磁盘。
- 对用户上传模式（内存）：原文只在内存，Chroma 落**密文**（用 `kb_crypto` 加密），检索时解密。
- 对 pdf/docx 等二进制：索引时**不**把解析后文本存 metadata，检索时即时用同套解析器按偏移取回，做到「全格式零知识」。

价值：即便向量库被攻破，攻击者拿不到任何用户文档明文，只能看到向量和偏移——而偏移没有原文件也毫无意义（运营方无用户存储凭证）。

---

### Q12. 如果用户问「这本书主人公叫什么」「列出全部章节」，普通 top-k 召回会答不好，你们怎么处理这类边界？

**答：** 两个针对性优化：

- **身份/名字类查询**（`_is_identity_query`）：识别到「谁/名字/叫什么/主人公」等，做查询扩展（补「我叫 / 我的名字 / 姓名 / 自称」），让 BM25 字面命中「我叫XX」、向量也被拉向自述句，避免「主人公是谁」检索不到「我叫钟俊皓」。
- **整篇/结构类查询**（`_is_full_doc_query`）：识别到「全部/目录/大纲/所有章节/全文概述」，不走 top-k，而是返回该库**全部片段**（用 60000 字符全局预算兜底，超预算截断最后一块并说明），否则会出现「27 章只列出 12 章」的截断问题。

---

### Q13. 如果 embedding 模型升级了，旧的向量还能用吗？

**答：** 不能混用，所以做了模型指纹防护。每个节点的 `metadata` 里写入 `emb_model`（来自 `_MODEL_TAG`，含模型标识），索引时 `text_hash` 也编入模型标识。重载知识库时检测：若样本节点的 `emb_model != 当前模型`，则**强制全量重建**索引；若一致则 `from_vector_store` 直接复用。这样避免「向量空间变了但旧向量还在用」导致召回质量静默下降。增量构建时也以 `text_hash` 为准复用未改动块的旧向量，省 embedding 配额。

---

## 五、本机控制（真实副作用）

### Q14. 你的 Agent 能「操控电脑」，这听起来风险很高，怎么实现的？

**答：** 采用**瘦客户端架构**，服务端不直接 `subprocess`：

- 后端 agent 需要操控本机时，经 `core/control_manager.py` 把指令（action + payload + request_id）通过 **Redis Pub/Sub** 下发到该用户的客户端频道 `control:req:{user_id}`。
- 客户端（Tauri/Rust 执行层）在用户授权（macOS TCC）后真正执行 `open` / `osascript`，再把结果回传 `control:res:{user_id}`。
- 服务端用 `asyncio.Future` 等待结果，超时（`request_local_exec` 默认 30s）就诚实返回「等待本机执行结果超时」，绝不假装成功。

选 Redis Pub/Sub 是因为**跨副本也能路由**：多后端副本下，请求发到对应用户 WS 所在的副本，回传经 `control:res:*` 模式订阅由持有 future 的副本唤醒。

---

### Q15. Agent 会「谎报」自己已经发了邮件 / 打开了应用吗？你们怎么防？

**答：** 会，这是 LLM 的常见幻觉——文本说「已发送」但实际工具没成功。我们做了**「谎报成功」护栏**（`agent_runner.py`）：

- `_guard_email_claim`：若回复含「已发送 / 发送成功」等强断言，但本轮 messages 里没有 `send_email_smtp` 的**成功回执**（即 ToolMessage 内容含 ✅ 且非 `成功 0/`、非 `[ERROR]`），就纠正成诚实提示：「我刚才并没有真正把这封邮件发出去……不会再谎报结果」。
- `_guard_local_open_claim`：同理，对「已打开 / 已激活 / 已操作」等本地操作断言，校验 `open_application / open_webpage / run_apple_script` 的成功回执，缺则纠正。

因为 Agent 有**真实副作用**（真发信、真操控电脑），这类护栏是生产必备，不能让模型「嘴上说做了」却没做、或做了却说没做。

---

## 六、流式与并发

### Q17. 你们聊天是走 HTTP 还是 WebSocket？为什么？

**答：** WebSocket（`/ws/chat`）。因为 Agent 有**双向交互**需求：

- 服务端逐 token 推（`agent.astream` + `stream_mode="messages"` 实现「逐字输出」），工具调用 / 工具结果也实时可见。
- 前端能上行发 `cancel` 取消运行、`local_control_result` 回传本机操作结果、甚至 `signature_report` 上报签名状态——HTTP 轮询做不到这种双向控制流。
- 长连接受 nginx `proxy_read_timeout 3600s` 保护，避免流式输出中途断连。

---

### Q18. 多个用户同时聊天，怎么保证并发安全、不互相干扰？

**答：** 几个维度：

1. **每消息独立 task**：`main.py` 收到 `message` 后用 `asyncio.create_task(_run_chat(...))` 启动独立运行，互不取消——同一用户连发多条也各跑各的。
2. **会话级串行锁**：同一段对话用 `get_lock(f"run:{thread_id}")` 分布式锁串行（`async with lock`），避免同一会话并发写乱序。
3. **上下文隔离**：`thread_id = "{user_id}:{conversation_id}:run:{run_id}"`，每次运行自带 `run_id`，上下文从业务消息表一次性快照读出来，不共享可变 thread 状态。
4. **应用层限流**：`rate_allow(f"ws:{user_id}", ...)` 走 Redis 滑动窗口，跨副本一致，防单用户刷屏。
5. **无状态 Agent**：`init_run_agent` 返回编译好的无状态图，单次运行状态只在该次 `astream` 的内存中，多副本 / 多线程安全。

---

### Q19. 你们后端能横向扩容吗？Agent 这层怎么配合？

**答：** 能，关键是**状态全外置**。Agent 运行需要的协调态（锁、信号量、队列、缓存失效、token 黑名单、限流）全部走 Redis（`infra/state_store.py`），业务代码完全不感知后端是几副本。

所以对 Agent 而言：
- 向量 / 记忆外置到 Chroma / PostgreSQL，多副本共享。
- 本机控制用 Redis Pub/Sub 跨副本路由（Q14）。
- 编译好的 Agent 图是无状态的，加副本即扩容，**代码零分叉**。

一个关键约束：**同一容器严禁 `--workers N>1`**，横向扩展靠「多副本」而非「多 worker」，因为进程内仍有少量状态（失效监听任务、回传 future 池），多 worker 会不一致。

---

## 七、健壮性工程

### Q20. 整轮 Agent 调用如果卡死（LLM 或工具挂住），怎么兜底？

**答：** 多层兜底：

- **整体超时**：`chat_stream` 用 `asyncio.timeout(settings.chat_timeout_seconds)`（默认 120s）包裹整轮（含多轮工具调用 / 压缩），到点强制中断返回兜底提示，防止卡死的连接一直占着 worker 导致雪崩。
- **LLM 重试**：`ChatOpenAI(max_retries=3, timeout=...)`，API 抖动自动重试，避免输出中途断裂。
- **Embedding / Rerank 退避**：批量 embedding 调用指数退避重试（`_embed_with_retry`），扛百炼 429 限流。
- **用户存储读取超时**：NFS/网络盘不可达时，用线程池 + 超时包裹读取（`_read_file_text`），超时返回 None，调用方诚实返回「无法取回原文」而非阻塞 worker。

---

### Q21. 你们在做并发压测 / 生产排障时，怎么判断瓶颈在哪？

**答：** 靠完整的可观测栈（docker-compose 内置）：Prometheus 抓 `/metrics`、redis/pg/chroma exporter 暴露连接数 / 命中率 / 延迟、Loki+Promtail 集中多副本 JSON 日志、Grafana 看板 + 告警。核心看 P95 延迟（尤其 `/ws/`）、活跃 builder / 校准任务数、PG 连接池占用、Redis / Chroma 存活与延迟。而且日志 / 指标里**不含密钥、token、用户 PII**（脱敏已就位）。

---

## 八、开放题

### Q22. 如果让你重做 / 优化这个 Agent，你会改哪？

**答：**（候选可结合自身理解，给几个方向，体现思考深度）

- **规划能力**：当前是 ReAct 单层循环，复杂任务（多步、有依赖）可以引入 `plan-and-execute` 或 LangGraph 的 `create_agent` 多 agent 协作，先做计划再执行，减少无效工具调用。
- **工具选择更可控**：function calling 全靠模型决策，高准确场景可以加一层「工具路由 + 参数校验 / 修正」，或对工具描述做在线评测迭代。
- **记忆再升级**：长期记忆目前是「热向量 + 冷 BM25」中间态，量到百万级后应当换统一混合检索引擎；画像注入也可加入「遗忘 / 纠错」机制（用户改了偏好要能覆盖旧记忆）。
- **评测闭环**：目前 RAG 的 `top_k` / 阈值靠 `kb_calibration` 自动校准，但 Agent 整体（工具调用准确率、死循环率）缺少自动化评测集，补上 eval 才算真正生产化。

---

### Q23. 用一句话总结你在 Agent 上的核心设计取舍（收尾用）

**答：** 小书童 Agent 的核心取舍是——**用 LangGraph 把 ReAct 推理工程化、用「无状态 Agent + 状态全外置」做成可水平扩展、用混合 RAG + 动态画像把「检索 / 记忆」做扎实、再用「谎报护栏 + 超时」守住「有真实副作用」的底线**。每个点都不是炫技，而是为「能真操控本机、又能稳定上生产的本地 Agent」这一具体目标服务。

---

> **使用建议**：面试时不必逐字背诵，把每个回答的「为什么」讲清楚（对比了什么方案、踩过什么坑、生产上要解决什么问题）比背实现细节更重要。遇到追问，用代码里的真实设计（如 `recursion_limit`、`_guard_email_claim`、RRF、`store_text=False`）做佐证即可。
