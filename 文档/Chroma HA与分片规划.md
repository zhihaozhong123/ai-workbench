# Chroma HA 与分片规划（运维侧总览）

> 适用场景：生产环境 Chroma 是当前最大单点 / 基数瓶颈，必须提前规划高可用与横向扩展。
> 本文是**规划总览**，把五条预案串成一张路线图；其中「自建分布式 HA」的落地步骤已在
> [`Chroma多副本部署方案.md`](./Chroma多副本部署方案.md) 详细展开，本文直接引用，不重复。
>
> 代码现状（2026-07-28 核实）：
> - `tools/rag_tool.py:128-144` 的 `make_chroma_client(tenant_id)` 只连单个 `CHROMA_HOST`/`CHROMA_PORT`，无分片、无故障转移。
> - `config.py:127-129` 只有 `chroma_host` / `chroma_port` 两个字段，无多端点/分片配置。
> - 租户隔离已就位：`make_chroma_client` 每个租户一个 tenant/database（每库 = 一个 Chroma collection）。
> - `config.py:97` `kb_max_per_tenant`、`:144` `kb_build_concurrency`（建索引并发闸门，扛 embedding 配额）、`:133` `embed_max_retries` 已存在。
> - `/metrics`、`/healthz`、`/readyz` 已可接 Prometheus。

---

## 0. 先说结论（必读）

应用层（backend 多副本 + Redis 协调）不会崩，但 **Chroma 是最大单点 / 基数瓶颈**。
开源单 Chroma 服务撑「数百 ~ 低千租户」无压力，**上万租户必须干预**。

五条预案按「成本从低到高、入侵性从小到大」排列，可叠加使用：

| # | 预案 | 类别 | 是否改代码 | 解决什么 |
|---|------|------|-----------|---------|
| ① | 监控集合基数 | 可观测 | 否（加指标/告警） | 提前暴露基数逼近上限的风险 |
| ② | Chroma Cloud 托管 | 运维切换 | 否（零改造） | 自动扩缩 + 高可用，省运维 |
| ③ | 自建分布式 HA（多实例+对象存储+Kafka） | 部署改动 | 否（仅改连接地址） | 消除单点，水平扩展读/写 |
| ④ | 按租户分片（hash 路由到多 Chroma） | **代码改造** | **是（改 `rag_tool.py`）** | 彻底消除单 Chroma 基数硬上限 |
| ⑤ | 配额统筹（QPS/容量 + 告警） | 可观测+配置 | 否（加规则） | embedding 配额与 Chroma QPS 统筹 |

> ②③⑤ 是运维/部署侧，不碰业务逻辑；**只有 ④ 需要改 `rag_tool.py` 的客户端选择逻辑**。
> ③④ 可组合：每个 shard 自身也可以是分布式 HA 集群。

---

## 1. 容量基线（什么时候该动手）

以「租户数 × 每租户库数」为第一指标（每库 = 1 个 Chroma collection）：

| 规模 | 风险 | 建议动作 |
|------|------|---------|
| < 数百租户 | 低 | 单 Chroma + 定时卷备份足够 |
| 数百 ~ 低千 | 中 | 上 ① 监控 + ⑤ 告警；评估 ②/③ |
| 低千 ~ 上万 | 高 | 必须 ③（HA）或 ②（Cloud），并开始规划 ④ |
| 上万以上 | 临界 | **必须 ④ 分片**，每个 shard 承载一个租户哈希区间 |

> 单 Chroma 的内存/索引压力主要来自 collection 总数与向量总量，而非租户数本身；
> 但租户数直接决定 collection 数（`租户数 × 每租户库数`），是基数瓶颈的最直观代理指标。

---

## 2. ① 监控集合基数（最先做，零成本）

目标：让「租户数 × 库数」成为 Prometheus 里的一条可告警曲线，而不是靠人肉感知。

### 2.1 暴露基数指标（backend 侧加一个 Gauge）

在现有 `/metrics` 暴露逻辑里加一组 Gauge（伪代码，落地时按 FastAPI 的 `prometheus_client` 接入）：

```python
from prometheus_client import Gauge

CHROMA_TENANT_COUNT = Gauge("chroma_tenant_count", "当前 Chroma tenant 数")
CHROMA_COLLECTION_COUNT = Gauge("chroma_collection_count", "当前 Chroma collection 总数")
CHROMA_COLLECTION_PER_TENANT = Gauge(
    "chroma_collection_per_tenant", "每租户 collection 数", ["tenant_id"]
)

# 定时（如每 60s）从 DB / Chroma 拉一次：
#   tenant 数  ← SELECT COUNT(DISTINCT user_id) FROM tenants（或 Chroma /api/v2/tenants）
#   collection 数 ← 逐 tenant 调 Chroma 列出 database 下的 collection 并累加
```

> 注：Chroma 开源版没有现成的「collection 总数」Prometheus 指标，需要 backend 主动统计后暴露。
> 统计频率不要太高频（列 collection 有开销），60s 一轮足够预警。

### 2.2 告警规则（加到 `prometheus.yml` 的 `alerting` 段）

```yaml
groups:
  - name: chroma-cardinality
    rules:
      - alert: ChromaTenantCountHigh
        expr: chroma_tenant_count > 800          # 按容量基线调整阈值
        for: 10m
        labels: { severity: warning }
        annotations:
          summary: "Chroma 租户数逼近单实例上限 ({{ $value }})"
      - alert: ChromaCollectionCountCritical
        expr: chroma_collection_count > 5000
        for: 10m
        labels: { severity: critical }
        annotations:
          summary: "Chroma collection 总数临界，需启动分片预案"
```

---

## 3. ② Chroma Cloud（最省力，零改造）

- 注册 Chroma Cloud，拿到 endpoint + key。
- 把 `config.py` 的 `chroma_host` 指向云 endpoint、`chroma_port` 改为对应端口（或 https）。
- **代码零改动**：`make_chroma_client` 的 `HttpClient(host, port, ...)` 逻辑不变，tenant/database 隔离照旧。
- 代价：数据出域 + 按量付费。适合不想运维 Kafka/对象存储、且能接受数据上云的团队。
- 详见 [`Chroma多副本部署方案.md`](./Chroma多副本部署方案.md) 第 11 节「方案 Y」。

---

## 4. ③ 自建分布式 HA（多实例 + 对象存储 + Kafka）

消除单点、水平扩展读写的完整步骤（准备工作、compose 拆分、backend 改连接、迁移、备份、成本、坑）已写入
[`Chroma多副本部署方案.md`](./Chroma多副本部署方案.md)，核心要点：

- 单 `chroma` 服务 → 拆成 `chroma-frontend` + `chroma-coordinator` + `chroma-worker × N`。
- 共享后端：对象存储（OSS / MinIO）+ Kafka 消息队列（Chroma 分布式**必须**用 Kafka）。
- backend 仅改 `CHROMA_HOST=chroma-frontend`，`make_chroma_client` 逻辑不动。
- 租户隔离（tenant/database/collection 三级）不变。

> 注意：③ 解决「单点」和「读写扩展」，但**单个分布式集群的 collection 基数仍有上限**（受 coordinator / 对象存储元数据压力约束）。
> 要彻底突破基数硬上限，必须叠加 ④ 分片。

---

## 5. ④ 按租户分片（唯一要改代码的硬手段）

当单 Chroma（无论是否分布式 HA）的 collection 基数逼近上限时，按 `hash(tenant_id)` 把租户路由到不同 Chroma 实例。

### 5.1 设计

- 引入「分片端点列表」配置：`CHROMA_SHARDS = "host1:8000,host2:8000,host3:8000"`（逗号分隔）。
- 路由函数：`idx = hash(tenant_id) % len(shards)` → 选对应 host:port。
- **确定性**：同一 tenant 永远落到同一 shard，建索引与查询自然对齐，无需额外路由表。
- 与 ③ 兼容：每个 shard 可以本身就是一个分布式 HA 集群（endpoint 指向 shard 的 frontend）。
- 租户隔离不变：`make_chroma_client` 仍按 `tenant/database` 构造 client，只是 host/port 来自分片路由。

### 5.2 配置项（加到 `config.py`，紧挨现有 `chroma_host/port`）

```python
# ===== Chroma 分片（按租户 hash 路由到多实例）=====
# 留空（默认）= 不分片，仍用下方 chroma_host/chroma_port 单实例（兼容现状）。
# 非空 = "host1:port1,host2:port2,..."，make_chroma_client 按 hash(tenant_id) 取模路由。
chroma_shards: str = ""
# 单实例兜底端点（chroma_shards 为空时使用）
chroma_host: str
chroma_port: int
```

### 5.3 客户端工厂改造（`tools/rag_tool.py` 的 `make_chroma_client`）

改造后同时保持「单实例兼容」与「分片路由」：

```python
def _resolve_chroma_endpoint(tenant_id: str):
    """返回 (host, port)。chroma_shards 非空时按 hash 分片；否则用单实例配置。"""
    shards = [s.strip() for s in (settings.chroma_shards or "").split(",") if s.strip()]
    if not shards:
        return settings.chroma_host, settings.chroma_port
    pick = shards[hash(tenant_id) % len(shards)]
    host, _, port = pick.partition(":")
    return host, int(port or settings.chroma_port)


def make_chroma_client(tenant_id: str):
    """返回绑定到本租户 tenant/database 的 Chroma 客户端（支持按租户分片）。"""
    host, port = _resolve_chroma_endpoint(tenant_id)   # ← 改这一行，原写死 settings.chroma_host/port
    database = f"kb_{tenant_id}"
    try:
        import requests
        base = f"http://{host}:{port}/api/v2"
        requests.post(f"{base}/tenants", json={"name": tenant_id}, timeout=10)
        requests.post(f"{base}/tenants/{tenant_id}/databases", json={"name": database}, timeout=10)
    except Exception as e:
        log.warning("[Chroma] 预创建 tenant/database 失败（可能已存在或服务暂不可达）: %s", e)
    return chromadb.HttpClient(host=host, port=port, tenant=tenant_id, database=database)
```

### 5.4 迁移注意（分片是「重分布」，不是「加副本」）

- 分片后，某租户的数据只存在于它命中的 shard；**改 `chroma_shards` 列表会重算 hash，租户可能换 shard**。
- 安全变更原则：
  - **加 shard（扩容）**：用一致性哈希或「按 tenant_id 前缀灰度」避免大面积搬迁；简单做法是新租户走新分片、存量租户保持原 shard（需一张 `tenant→shard` 映射表兜底）。
  - **减 shard / 调整顺序**：必须先按 tenant 把 collection 导出，再导入新 shard（Chroma 无官方一键跨实例迁移，需写脚本：逐 tenant 逐库 `get_collection` 取出向量+metadata，写入目标 shard）。
- 因为本项目是「零知识」设计（向量可重建，原文在 `doc_dir`），最稳妥的做法是：**对受影响租户触发知识库重建**（`POST /api/kb/{kb_name}/rebuild`），而非手动搬向量。
- 回滚：分片配置出错时，把 `chroma_shards` 清空即回退到单实例（前提是原单实例数据还在）。

### 5.5 与 ① 监控的配合

分片后，① 的基数指标要**按 shard 分别统计**（每个 shard 一个 `chroma_collection_count{shard="host2:8000"}` 标签），
告警阈值按单 shard 容量设定，而非全局总和。

---

## 6. ⑤ 配额统筹（QPS / 容量 + 告警）

Chroma 自身没有独立的 QPS 限流；真正的压力闸门在「建索引」侧：

- `config.py:144` `kb_build_concurrency`：跨租户并行建索引上限，间接控制写入 Chroma 的速率，避免打爆 embedding 配额（阿里云百炼有 QPS 限制，已有 `embed_max_retries` 退避）。
- 分片 / 多副本后，建索引并发应**按 shard 数摊薄**（每 shard 的 `kb_build_concurrency` 上限 = 全局 / shard 数），否则单 shard 仍会被写爆。

告警补充（加进 `prometheus.yml`，与 ① 同组）：

```yaml
      - alert: ChromaDown
        expr: probe_success{job="chroma"} == 0
        for: 1m
        labels: { severity: critical }
        annotations:
          summary: "Chroma 不可达（单点/分片副本挂了）"
      - alert: ChromaHighLatency
        expr: probe_duration_seconds{job="chroma"} > 1.5
        for: 5m
        labels: { severity: warning }
        annotations:
          summary: "Chroma 探活延迟过高，可能过载"
```

> 用 blackbox exporter 探 `chroma` 的 `/healthz` 或 `/readyz`（已在服务里就位）；
> 分片后对每个 shard endpoint 各配一个 `probe_success` 实例。
> 详见 [`Chroma多副本部署方案.md`](./Chroma多副本部署方案.md) 第 10 节第 8 条。

---

## 7. 落地路线图（建议优先级）

```
阶段 0（现在就能做，零成本）
  ├─ ① 暴露基数指标 + 告警规则        → Prometheus 能看见风险
  └─ ⑤ Chroma 探活告警               → 单点挂了立刻知道

阶段 1（单实例开始吃紧 / 想消除单点）
  ├─ ③ 自建分布式 HA  或  ② Chroma Cloud   → 消除单点，读写可扩展
  └─ ⑤ 把 kb_build_concurrency 按副本/分片摊薄

阶段 2（上万租户 / 基数临界）
  └─ ④ 按租户分片（改 rag_tool.py）
        ├─ 加 chroma_shards 配置 + _resolve_chroma_endpoint 路由
        ├─ 受影响租户按 tenant 触发知识库重建
        └─ ① 的基数指标按 shard 分别统计
```

> 优先级：**④ > ③ > ①/⑤**。④ 是解决基数硬上限的唯一手段；③ 解决单点；
> ①/⑤ 是「让风险可见」，成本最低、应最先落地。

---

## 8. 规划检查清单

- [ ] ① 在 `/metrics` 增加 `chroma_tenant_count` / `chroma_collection_count` Gauge
- [ ] ① 加 `ChromaTenantCountHigh` / `ChromaCollectionCountCritical` 告警规则
- [ ] ⑤ 加 `ChromaDown` / `ChromaHighLatency`（blackbox 探 `/healthz`）
- [ ] ②/③ 决策：上 Chroma Cloud 还是自建分布式 HA（见 `Chroma多副本部署方案.md`）
- [ ] ③ 若自建：按该文档完成对象存储 + Kafka + frontend/coordinator/worker 拆分
- [ ] ④ `config.py` 加 `chroma_shards` 字段（默认空，兼容单实例）
- [ ] ④ `rag_tool.py` 的 `make_chroma_client` 改用 `_resolve_chroma_endpoint` 路由
- [ ] ④ 分片扩容用一致性哈希 / `tenant→shard` 映射，避免大面积搬迁
- [ ] ④ 受影响租户触发知识库重建（零知识设计，可重建不丢知识）
- [ ] ④ ① 的基数指标按 `shard` 标签分别统计与告警
- [ ] ⑤ `kb_build_concurrency` 按 shard/副本数摊薄，统筹 embedding 配额
