# Chroma 多副本（分布式高可用）部署方案

> 适用场景：当前 `docker-compose.yml` 里的 `chroma` 是单副本 standalone 模式，数据落在本地卷 `chroma_data:/data`。
> 本文档记录「改为多副本 / 高可用」的完整步骤、付费项与易踩的坑，**日后照做即可**。
>
> 参考现状（2026-07-28）：
> - `docker-compose.yml` 第 129-150 行：`chroma` 服务，镜像 `chromadb/chroma:1.5.9`，挂载 `chroma_data:/data`，单实例。
> - `docker-compose.yml` 第 40-41 行：`backend` 通过 `CHROMA_HOST=chroma`、`CHROMA_PORT=8000` 连接。
> - `scripts/reset_chroma.py`：清空向量/长期记忆/知识库；`up_build.sh` 的 `RESET=1` 会调用它 + `reset_db.py`。
> - 设计要点：Chroma 只存 **embedding + metadata（零知识）**，原文在用户 `doc_dir`，故向量可重建。

---

## 0. 先说结论（必读）

**Chroma 的开源镜像默认跑 standalone（单节点），不是加个 `replicas: 3` 就能多副本的。**

直接在 compose 里给单个 `chroma` 服务加 `deploy.replicas: N` 并挂同一个 `chroma_data` 卷，会**数据错乱/损坏**——多个节点之间没有协调，谁写谁读互相不知道。

真正的 Chroma 多副本 = **分布式部署**，必须补齐三块基础设施：

| 组件 | 作用 | 是否必须 |
|------|------|---------|
| 对象存储（OSS / MinIO / S3） | 替代本地 `/data`，所有节点共享同一份向量数据 | ✅ 必须 |
| 消息队列 Kafka | 协调 frontend/coordinator/worker 之间的写入广播 | ✅ 必须 |
| Chroma 三角色：frontend + coordinator + N×worker | frontend 对外提供 HTTP（backend 连它）；coordinator 管元数据路由；worker 真正存/查 | ✅ 必须（替代现在的单镜像） |

你项目里 **backend 已经多副本**（Redis 外置、共享 PG），但 **chroma 这层是单点**。要 chroma 也多副本，只能走上面这套分布式架构。

---

## 1. 架构总览

```
                         ┌─────────────────────────────────────┐
   backend 多副本  ─────▶ │  chroma-frontend (:8000, 对外 HTTP)  │
   (CHROMA_HOST=          │       ↓ gRPC                        │
    chroma-frontend)      │  chroma-coordinator (:50051, 路由)   │
                         │       ↓ gRPC                          │
                         │  chroma-worker × N (:50051)          │
                         └───────┬──────────────┬───────────────┘
                                 │              │
                          ┌──────▼─────┐  ┌─────▼─────┐
                          │ 对象存储    │  │  Kafka     │
                          │ OSS/MinIO  │  │ (广播写入)  │
                          └────────────┘  └────────────┘
```

- **backend 改动极小**：仅把 `CHROMA_HOST` 从 `chroma` 改为 `chroma-frontend`（连 frontend 的 8000 端口）。worker 的负载均衡由 coordinator 内部完成，后端无感知。
- **真正的「多副本」是 `chroma-worker` 的 `replicas`**，coordinator / frontend 也可按需加副本（frontend 前面可再挂 nginx 负载）。

---

## 2. 前置决策（动手前先定）

做之前先回答两个问题，文档后续步骤会用到：

1. **对象存储用哪个？**
   - 阿里云 OSS（S3 兼容 endpoint，**付费**，见第 6 节）；或
   - 本地起 **MinIO**（免费，自托管，适合先试 / 内网）。
2. **现有数据能否接受「重建索引」？**
   - 本项目是零知识设计，Chroma 只存向量+metadata，原文在 `doc_dir`。因此**重建 = 重新算 embedding 写入新存储，不会丢知识**，只是有重算耗时（几十万级向量可能几十分钟到数小时）。长期记忆有 PG 冷库（`cold_memories`）兜底。
   - 若必须零停机迁移，需另写导出/导入脚本（Chroma 分布式版暂无官方一键迁移工具，见第 7 节风险）。**建议接受重建，简单可靠。**

---

## 3. 步骤一：准备对象存储

### 方案 A：阿里云 OSS（生产推荐，付费）
1. 控制台创建 Bucket，例如 `xiaoshutong-chroma`，地域选离服务近的。
2. 创建 RAM 子账号 AccessKey（**不要用主账号**），只授权该 Bucket 的读写。
3. 记录：
   - `BUCKET_NAME=xiaoshutong-chroma`
   - `OSS_ENDPOINT=https://oss-cn-xxx.aliyuncs.com`（S3 兼容，注意用带 region 的 endpoint）
   - `OSS_ACCESS_KEY=...`
   - `OSS_SECRET_KEY=...`
   - `OSS_REGION=cn-xxx`
4. 在 Bucket 里**预先建好目录/前缀**（Chroma 会自动按 tenant 分桶，但建议先建好 bucket）。

### 方案 B：本地 MinIO（免费，先试）
在 `docker-compose.yml` 新增 `minio` 服务：

```yaml
  minio:
    image: minio/minio:RELEASE.2024-xx
    command: server /data --console-address ":9001"
    environment:
      - MINIO_ROOT_USER=minioadmin
      - MINIO_ROOT_PASSWORD=minioadmin123
    ports:
      - "19000:9000"   # S3 API
      - "19001:9001"   # 控制台
    volumes:
      - minio_data:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped

  # 初始化 bucket（首次用，可跑一次后移除）
  minio-init:
    image: minio/mc:latest
    depends_on: [minio]
    entrypoint: >
      sh -c "mc alias set m http://minio:9000 minioadmin minioadmin123 &&
             mc mb -p m/xiaoshutong-chroma || true"
```

记：`OSS_ENDPOINT=http://minio:9000`、`OSS_ACCESS_KEY=minioadmin`、`OSS_SECRET_KEY=minioadmin123`。

---

## 4. 步骤二：准备 Kafka（付费/免费视部署方式）

Chroma 分布式**必须用 Kafka** 做写入广播，目前没有其它消息队列后端可选。

```yaml
  kafka:
    image: bitnami/kafka:3.7
    environment:
      - KAFKA_CFG_NODE_ID=1
      - KAFKA_CFG_PROCESS_ROLES=broker,controller
      - KAFKA_CFG_CONTROLLER_QUORUM_VOTERS=1@kafka:9093
      - KAFKA_CFG_LISTENERS=PLAINTEXT://:9092,CONTROLLER://:9093
      - KAFKA_CFG_ADVERTISED_LISTENERS=PLAINTEXT://kafka:9092
      - KAFKA_CFG_LISTENER_SECURITY_PROTOCOL_MAP=CONTROLLER:PLAINTEXT,PLAINTEXT:PLAINTEXT
      - KAFKA_CFG_CONTROLLER_LISTENER_NAMES=CONTROLLER
      - ALLOW_PLAINTEXT_LISTENER=yes
      - KAFKA_CFG_AUTO_CREATE_TOPICS_ENABLE=true
    ports:
      - "9092:9092"
    volumes:
      - kafka_data:/bitnami/kafka
    healthcheck:
      test: ["CMD-SHELL", "kafka-topics.sh --bootstrap-server localhost:9092 --list || exit 1"]
      interval: 15s
      timeout: 10s
      retries: 10
    restart: unless-stopped
```

> 生产建议至少 3 broker 的 Kafka 集群（跨可用区），但那是另一个运维话题。单 broker Kafka 只能保证 chroma 多副本**可用性**，不能保证 Kafka 自身高可用。

---

## 5. 步骤三：拆分 chroma 服务（核心改动）

把原 `docker-compose.yml` 第 129-150 行的单个 `chroma` 服务**替换为** frontend + coordinator + worker。删掉旧的 `chroma` 服务和 `chroma_data` 卷（数据将落在对象存储，本地卷不再需要）。

```yaml
  # ============ Chroma 分布式：frontend（对外 HTTP，backend 连这个）============
  chroma-frontend:
    image: chromadb/chroma:1.5.9
    command: ["chroma", "run", "--type", "frontend", "--host", "0.0.0.0", "--port", "8000"]
    environment:
      - CHROMA_SERVER_HOST=0.0.0.0
      - CHROMA_SERVER_PORT=8000
      - CHROMA_SERVER_ENDPOINT=chroma-coordinator:50051   # 内部 gRPC 指向 coordinator
      # 对象存储（以下变量名以 1.5.9 官方文档为准，部署前务必核对！）
      - CHROMA_OBJECT_STORE_TENANT_ID=test_tenant
      - CHROMA_OBJECT_STORE_BUCKET_NAME=xiaoshutong-chroma
      - CHROMA_OBJECT_STORE_TYPE=s3
      - CHROMA_OBJECT_STORE_ENDPOINT=${OSS_ENDPOINT}
      - CHROMA_OBJECT_STORE_ACCESS_KEY=${OSS_ACCESS_KEY}
      - CHROMA_OBJECT_STORE_SECRET_KEY=${OSS_SECRET_KEY}
      - CHROMA_OBJECT_STORE_REGION=${OSS_REGION:-}
      # Kafka 消息服务
      - CHROMA_MESSAGE_SERVICE_IMPLEMENTATION=kafka
      - CHROMA_MESSAGE_SERVICE_HOST=kafka
      - CHROMA_MESSAGE_SERVICE_PORT=9092
    ports:
      - "18001:8000"
    depends_on:
      kafka: { condition: service_healthy }
      # minio / oss 不可探活，靠 chroma 自身重试
    healthcheck:
      test: ["CMD-SHELL", "grep -Eq ':1F40[[:space:]]+[^[:space:]]+[[:space:]]+0A' /proc/net/tcp /proc/net/tcp6"]
      interval: 10s
      timeout: 5s
      retries: 10
    restart: unless-stopped

  # ============ Chroma 分布式：coordinator（路由元数据）============
  chroma-coordinator:
    image: chromadb/chroma:1.5.9
    command: ["chroma", "run", "--type", "coordinator", "--host", "0.0.0.0", "--port", "50051"]
    environment:
      - CHROMA_SERVER_ENDPOINT=chroma-coordinator:50051
      - CHROMA_OBJECT_STORE_TENANT_ID=test_tenant
      - CHROMA_OBJECT_STORE_BUCKET_NAME=xiaoshutong-chroma
      - CHROMA_OBJECT_STORE_TYPE=s3
      - CHROMA_OBJECT_STORE_ENDPOINT=${OSS_ENDPOINT}
      - CHROMA_OBJECT_STORE_ACCESS_KEY=${OSS_ACCESS_KEY}
      - CHROMA_OBJECT_STORE_SECRET_KEY=${OSS_SECRET_KEY}
      - CHROMA_OBJECT_STORE_REGION=${OSS_REGION:-}
      - CHROMA_MESSAGE_SERVICE_IMPLEMENTATION=kafka
      - CHROMA_MESSAGE_SERVICE_HOST=kafka
      - CHROMA_MESSAGE_SERVICE_PORT=9092
    depends_on:
      kafka: { condition: service_healthy }
    restart: unless-stopped

  # ============ Chroma 分布式：worker（真正的多副本在这里）============
  chroma-worker:
    image: chromadb/chroma:1.5.9
    command: ["chroma", "run", "--type", "worker", "--host", "0.0.0.0", "--port", "50051"]
    environment:
      - CHROMA_SERVER_ENDPOINT=chroma-coordinator:50051
      - CHROMA_OBJECT_STORE_TENANT_ID=test_tenant
      - CHROMA_OBJECT_STORE_BUCKET_NAME=xiaoshutong-chroma
      - CHROMA_OBJECT_STORE_TYPE=s3
      - CHROMA_OBJECT_STORE_ENDPOINT=${OSS_ENDPOINT}
      - CHROMA_OBJECT_STORE_ACCESS_KEY=${OSS_ACCESS_KEY}
      - CHROMA_OBJECT_STORE_SECRET_KEY=${OSS_SECRET_KEY}
      - CHROMA_OBJECT_STORE_REGION=${OSS_REGION:-}
      - CHROMA_MESSAGE_SERVICE_IMPLEMENTATION=kafka
      - CHROMA_MESSAGE_SERVICE_HOST=kafka
      - CHROMA_MESSAGE_SERVICE_PORT=9092
    depends_on:
      chroma-coordinator: { condition: service_started }
      kafka: { condition: service_healthy }
    deploy:
      replicas: 2          # ← 这里才是真正的「多副本」，按需加到 3/5
      resources:
        limits:
          cpus: "1.0"
          memory: 2G
    restart: unless-stopped
```

> ⚠️ **环境变量名以你部署时 Chroma 1.5.9 官方文档为准**。分布式相关的 env 名在不同版本间可能调整，部署前用 `docker run --rm chromadb/chroma:1.5.9 chroma run --help` 或官方 docs 核对一遍（尤其 `CHROMA_OBJECT_STORE_*` 与 `CHROMA_MESSAGE_SERVICE_*` 前缀）。

---

## 6. 步骤四：改 backend 连接地址

只需改 `docker-compose.yml` 里 `backend` 服务的环境变量（第 40 行附近）：

```diff
-      - CHROMA_HOST=chroma
+      - CHROMA_HOST=chroma-frontend
       - CHROMA_PORT=8000
```

`config.py` 的 `settings.chroma_host` 和 `tools/rag_tool.py` 的 `HttpClient(host, port)` **逻辑不用动**，它们读的就是这两个变量。

> 若哪天 frontend 也要多副本，可在前面再挂一层 nginx 负载（参考现有 `nginx` 服务写法），backend 的 `CHROMA_HOST` 指向那层 nginx 即可。

---

## 7. 步骤五：数据迁移（本地卷 → 对象存储）

**原 `chroma_data` 卷里的向量不会自动搬到对象存储**，旧数据只能丢弃、重新构建。这是设计使然，按下面做：

1. **停掉旧的 standalone chroma**（已在上一步被删除/替换）。
2. 确保对象存储 bucket、Kafka 已就绪，分布式 chroma 三个角色都 `healthy`。
3. 启动 backend 后，对**每个知识库**触发重建索引：
   - 调接口 `POST /api/kb/{kb_name}/rebuild`（见 `api/routes_kb.py`），或在管理端点「重新构建」。
   - 或用 `up_build.sh` 的 `RESET=1` 清空后，让 backend 启动时的 `init_long_term_memory` / KB 自动建索引流程重建（源文档在 `doc_dir` 即可）。
4. **长期记忆**：热库在 Chroma（重建后空），冷库在 PG `cold_memories`（保留，启动自动重建热层），无需额外操作。
5. 验证：访问 `http://localhost:8000/api/memory/long_term?source=all&limit=200` 看是否有数据回流；随便问一个知识库问题验证检索正常。

> 重建期间系统**可降级运行**（新写入会自动进新存储；只是旧知识暂时查不到，直到该库重建完）。因此不必停机，可逐个库平滑重建。

---

## 8. 步骤六：调整备份策略

旧方案 `chroma-backup` 每 6h 对 `chroma_data` 卷做 tar 快照（compose 第 220-234 行）。改为对象存储后：

- **本地卷快照不再有意义**（数据在 OSS/MinIO），可移除 `chroma-backup` 服务和 `chroma_backups` 卷。
- **新备份对象变为对象存储**：
  - 阿里云 OSS：开启**跨地域复制 + 版本控制**，或定期 `ossutil cp` 到异地/低频存储。
  - MinIO：用 `mc mirror` 同步到另一个 bucket / 另一台机器。
- Kafka 数据一般不备份（只存消息流，chroma 消费后状态在对象存储），但建议开启 topic  retention 留几天便于排障。

---

## 9. 付费与成本细节（重点）

| 资源 | 是否付费 | 说明 |
|------|---------|------|
| **阿里云 OSS** | ✅ 付费 | 按存储量（GB/月）+ 请求次数 + 外网流量计费。向量数据通常不大（百万级向量约几 GB），但 embedding 写入/查询请求多，请求费可能被忽略。建议：标准存储 + 生命周期转低频/归档。 |
| **Kafka** | ✅ 视部署 | 自托管（bitnami/kafka 镜像）免费，但占机器 CPU/内存；上云用阿里云 Kafka/MSE 则按实例规格+流量付费，且 Kafka 要高可用需 ≥3 broker，成本翻倍。 |
| **额外 chroma worker 副本** | ✅ 间接 | 每个 worker 吃 1~2G 内存（见上面 limits），副本越多机器成本越高。 |
| **MinIO** | ❌ 免费 | 自托管，吃本地磁盘；但要自己保证磁盘可靠（RAID/备份），否则对象存储本身又成单点。 |
| **Chroma Cloud（替代方案）** | ✅ 付费 | 官方托管分布式，连 endpoint 即可，省掉 Kafka/MinIO 运维，按用量计费。最省力但数据出域。 |

> 成本量级参考：中小知识库（千万向量以内）OSS 月费通常几元~几十元；Kafka 上云才是大头。若机器资源紧张，**先用 MinIO + 单 broker Kafka 试通**，确认架构无误再上云付费。

---

## 10. 其它必须考虑的坑（细节清单）

1. **版本一致性**：frontend / coordinator / worker **必须用同一个 chroma 版本**（本文统一 `1.5.9`），混版本会不兼容。升级时整体一起升。
2. **env 变量名核对**：见第 5 节警告，部署前务必核对官方文档，避免变量名变更导致静默落到本地盘。
3. **对象存储 endpoint 网络连通性**：compose 内服务通过服务名访问（MinIO 用 `http://minio:9000`）；上云 OSS 需保证容器能出公网或走内网 endpoint（同 region 内网免费、更快）。
4. **Kafka 先于 chroma 就绪**：上面 `depends_on` 已加 `service_healthy`；若 Kafka 慢，chroma 启动失败会 `restart: unless-stopped` 自动重试，一般无碍。
5. **单 broker Kafka 自身是单点**：它挂了，chroma 写入会阻塞/报错，但已写入对象存储的数据不丢。要 Kafka 也高可用需 3 broker 集群（跨机器/可用区）。
6. **worker 副本数 ≠ 性能线性提升**：worker 间通过 coordinator 协调，副本多了 coordinator 压力大；一般 2~3 个 worker 足够，瓶颈多在 embedding 调用（阿里云 embedding API 有 QPS 限制）。
7. **迁移期间避免并发重建冲突**：多个库同时 rebuild 会打爆 embedding API，建议错峰或限流（项目已有 Redis 信号量做建索引节流，留意 `KB_MAX_PER_TENANT` 等配置）。
8. **监控**：chroma 无官方 Prometheus exporter（见 `prometheus.yml` 注释），可用 blackbox 探活 frontend 的 8000，或接入业务层心跳。分布式后建议额外盯 Kafka 消费堆积、对象存储错误率。
9. **回滚预案**：若分布式部署出问题，回退简单——把 frontend/coordinator/worker 三服务删掉，恢复原来的单个 `chroma` 服务 + `chroma_data` 卷（旧卷若没删就还在）。**所以迁移前先备份 `chroma_data` 卷**（停服后 `docker compose cp` 或依赖原 `chroma-backup` 快照）。
10. **租户隔离不变**：分布式模式同样走 tenant/database/collection 三级，你现有 `kb_manager.set_tenant(user_id)` 的隔离逻辑无需改。

---

## 11. 备选方案（不想上 Kafka/对象存储时）

### 方案 X：保持单 chroma + 定时卷备份（成本最低，够用）
- 不动架构，保留 `chroma-backup` 每 6h 快照（已存在）。
- 这是**不是多副本**，是「单点 + 可恢复」。chroma 挂了会短暂不可用，但靠卷备份 + 源文档重建兜底，RTO 取决于重建耗时。
- 适合：内部工具、可用性要求不极端的场景。

### 方案 Y：Chroma Cloud（托管分布式，最省力）
- 注册 Chroma Cloud，拿到 endpoint + key，把 `CHROMA_HOST` 指向云 endpoint。
- 自动多副本/高可用，你只管连。代价：数据出域 + 按量付费。
- 适合：不想运维 Kafka/对象存储、且能接受数据上云。

---

## 12. 落地检查清单（照着打勾）

- [ ] 决定对象存储：OSS / MinIO（第 2、3 节）
- [ ] 决定能否重建索引（第 2 节，建议接受）
- [ ] 加 `minio` / 配 OSS 凭证（第 3 节）
- [ ] 加 `kafka` 服务（第 4 节）
- [ ] 替换 `chroma` 为 frontend+coordinator+worker，核对 env 名（第 5 节）
- [ ] backend `CHROMA_HOST` 改 `chroma-frontend`（第 6 节）
- [ ] 迁移前备份旧 `chroma_data` 卷（第 10 节第 9 条）
- [ ] 启分布式 chroma，验证三角色 healthy
- [ ] 逐个知识库 rebuild / `RESET=1` 重建（第 7 节）
- [ ] 验证检索与长期记忆（第 7 节）
- [ ] 调整备份策略：撤 `chroma-backup`，开 OSS 版本控制/跨地域或 MinIO mirror（第 8 节）
- [ ] 加监控：Kafka 堆积、对象存储错误、frontend 探活（第 10 节第 8 条）
- [ ] 回滚预案就绪（第 10 节第 9 条）
