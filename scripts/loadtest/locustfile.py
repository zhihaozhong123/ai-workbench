#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""智作台 —— 并发压测脚本（基于 Locust）

覆盖真实用户旅程：注册/登录 → (可选)建库+建索引 → 问答(HTTP/SSE) → 列库/个人信息。

两种并发视角（用环境变量切换）：
  - TENANT_MODE=unique（默认）：每个模拟用户 = 一个独立租户
        → 用来回答「系统能顶住多少租户」。Locust --users N 即 N 个租户。
  - TENANT_MODE=pool          ：所有模拟用户从固定租户池取号（TENANT_POOL_SIZE 个）
        → 用来回答「单租户的并发操作能顶多少」。--users M 个并发用户抢这 N 个租户。

重要：后端限流是按「客户端 IP」计的固定窗口（见 observability/ratelimit.py，
_xclient_ip 优先读 X-Forwarded-For）。若所有压测流量都从同一台机器进来，会被算成
【同一个 IP 桶】，所有租户共享一份 rate_limit_per_minute 限额，压测会被提前卡成 429。
本脚本给每个用户打一个唯一 X-Forwarded-For，让限流器把每个租户当成独立客户端，
从而测出真实并发（同时也更贴近「多租户来自不同网络」的生产形态）。

依赖：pip install locust
用法示例：
  # 100 个租户、阶梯加压、HTTP 问答，跑 5 分钟
  locust -f scripts/loadtest/locustfile.py --host http://127.0.0.1:8000 \
         --users 100 --spawn-rate 10 --run-time 5m --headless

  # 测单租户并发（10 个租户，200 个并发用户抢）
  TENANT_MODE=pool TENANT_POOL_SIZE=10 locust -f scripts/loadtest/locustfile.py \
         --host http://127.0.0.1:8000 --users 200 --spawn-rate 20 --run-time 5m --headless

  # 带建索引（会消耗百炼 embedding 配额！仅付费 key / 小规模时开启）
  ENABLE_INDEXING=true locust -f scripts/loadtest/locustfile.py \
         --host http://127.0.0.1:8000 --users 50 --spawn-rate 5 --run-time 3m --headless

  # SSE 流式问答
  CHAT_MODE=sse locust -f scripts/loadtest/locustfile.py \
         --host http://127.0.0.1:8000 --users 100 --spawn-rate 10 --run-time 5m --headless

  # 只压「纯检索层」（不调 LLM，隔离 Chroma + rerank 瓶颈）。需先 ENABLE_INDEXING=true
  # 把各租户知识库建好索引，否则会大量 hit=false。配合 --tags search 仅跑检索任务：
  ENABLE_INDEXING=true locust -f scripts/loadtest/locustfile.py \
         --host http://127.0.0.1:8000 --users 200 --spawn-rate 20 --run-time 5m \
         --headless --tags search

阶梯加压（定位拐点）：把 --users 从 10 逐步加到 50/100/200/500，每次观察
Grafana（http://localhost:3000）里 kb_search_duration_seconds 的 p99、错误率、
embed_fail_total，以及 redis/pg/chroma 资源指标；延迟/错误率开始翘起的那一刻即容量上限。
"""
import os
import random
import threading
import uuid

from locust import HttpUser, task, between, tag

# ----------------------- 配置（环境变量覆盖） -----------------------
HOST = os.getenv("HOST", "http://127.0.0.1:8000")
TENANT_MODE = os.getenv("TENANT_MODE", "unique")          # unique | pool
TENANT_POOL_SIZE = int(os.getenv("TENANT_POOL_SIZE", "10"))
TEST_PASSWORD = os.getenv("TEST_PASSWORD", "Test123456")
CHAT_MODE = os.getenv("CHAT_MODE", "http")                # http | sse
ENABLE_INDEXING = os.getenv("ENABLE_INDEXING", "false").lower() == "true"
SAMPLE_DOC = os.getenv("SAMPLE_DOC", os.path.join(os.path.dirname(__file__), "sample_doc.txt"))
CHAT_QUESTION = os.getenv("CHAT_QUESTION", "这份文档的作者是谁？请简要回答。")
# 私有网段 10.0.0.0/8 作伪造客户端 IP（仅用于绕过单 IP 限流桶，不影响真实流量）
_FAKE_IP_PREFIX = "10.0"


# ----------------------- 租户池（pool 模式） -----------------------
_pool_lock = threading.Lock()
_tenant_counter = 0


def _next_pool_index() -> int:
    global _tenant_counter
    with _pool_lock:
        i = _tenant_counter
        _tenant_counter += 1
    return i


class XstUser(HttpUser):
    wait_time = between(0.5, 2.0)
    # 不在这里设 host：用命令行 --host 指定，便于切到 nginx:8000 生产入口

    # ----------------- 启动：注册/登录 + 可选建索引 -----------------
    def on_start(self):
        # 1) 决定本用户的租户身份
        if TENANT_MODE == "pool":
            idx = _next_pool_index() % TENANT_POOL_SIZE
            self.email = f"ltpool{idx}@loadtest.local"
        else:
            self.email = f"lt_{uuid.uuid4().hex[:12]}@loadtest.local"

        # 2) 注册（已存在则登录）。注册失败(non-2xx)由 Locust 自动记为失败。
        r = self.client.post(
            "/api/register",
            json={"username": self.email, "password": TEST_PASSWORD, "nickname": "lt"},
            name="/api/register",
        )
        if r.status_code == 409:
            r = self.client.post(
                "/api/login",
                json={"username": self.email, "password": TEST_PASSWORD},
                name="/api/login",
            )
        tok = (r.json() or {}).get("access_token")
        if not tok:
            # 拿不到 token（如限流 429 / 后端未就绪），本次用户作废，等下一轮重连
            return

        # 3) 唯一 X-Forwarded-For：让后端按 IP 限流把本租户当独立客户端
        fake_ip = f"{_FAKE_IP_PREFIX}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        self.headers = {
            "Authorization": f"Bearer {tok}",
            "X-Forwarded-For": fake_ip,
        }

        # 4) 可选：建库 + 建索引（最重路径，会消耗 embedding 配额）
        if ENABLE_INDEXING:
            self._index_once()

    def _index_once(self):
        try:
            with open(SAMPLE_DOC, "rb") as f:
                content = f.read()
        except OSError:
            return
        files = {"files": ("sample_doc.txt", content, "text/plain")}
        data = {"kb_name": "lt_kb", "description": "loadtest", "doc_name": "sample"}
        # 复用鉴权头，但不带 Content-Type（multipart 由 requests 自动设 boundary）
        h = {k: v for k, v in self.headers.items()}
        r = self.client.post(
            "/api/kb/upload", files=files, data=data, headers=h, name="/api/kb/upload",
        )
        # 400/409 多半是 kb_max_per_tenant 已满或已建过，属预期，忽略

    # ----------------- 业务任务（权重越高越频繁） -----------------
    @task(10)
    @tag("chat")
    def chat(self):
        """问答主路径（含 LLM）：HTTP 非流式 或 SSE 流式，二选一（CHAT_MODE）。"""
        if CHAT_MODE == "sse":
            with self.client.post(
                "/api/chat/stream",
                json={"message": CHAT_QUESTION},
                headers=self.headers,
                stream=True,
                catch_response=True,
                name="/api/chat/stream",
            ) as r:
                if r.status_code >= 400:
                    r.failure(f"chat/stream -> {r.status_code}: {r.text[:120]}")
                    return
                got = False
                for line in r.iter_lines(decode_unicode=True):
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    got = True
                if got:
                    r.success()
                else:
                    r.failure("chat/stream 未收到任何 data 事件")
        else:
            with self.client.post(
                "/api/chat",
                json={"message": CHAT_QUESTION},
                headers=self.headers,
                catch_response=True,
                name="/api/chat",
            ) as r:
                if r.status_code >= 400:
                    r.failure(f"chat -> {r.status_code}: {r.text[:120]}")
                else:
                    r.success()

    @task(5)
    @tag("search")
    def retrieval_search(self):
        """纯检索路径（不调 LLM）：隔离压测 Chroma + BM25 + RRF + rerank。
        用 --tags search 单独跑这条，可在 LLM 配额耗尽时仍压出检索层瓶颈。
        kb_name 省略 → 检索该租户全部知识库。"""
        with self.client.post(
            "/api/kb/search",
            json={"query": CHAT_QUESTION, "kb_name": None},
            headers=self.headers,
            catch_response=True,
            name="/api/kb/search",
        ) as r:
            if r.status_code >= 400:
                r.failure(f"kb/search -> {r.status_code}: {r.text[:120]}")
                return
            body = r.json()
            if not body.get("hit"):
                # 未命中：通常库未建索引 / embedding 不可用（额度耗尽）→ 记为失败便于区分
                r.failure("kb/search 未命中（hit=false，可能库未建索引或 embedding 不可用）")
            else:
                r.success()

    @task(2)
    @tag("light")
    def list_kb(self):
        with self.client.get(
            "/api/kb/list", headers=self.headers, catch_response=True, name="/api/kb/list"
        ) as r:
            if r.status_code >= 400:
                r.failure(f"kb/list -> {r.status_code}")
            else:
                r.success()

    @task(1)
    @tag("light")
    def me(self):
        with self.client.get(
            "/api/me", headers=self.headers, catch_response=True, name="/api/me"
        ) as r:
            if r.status_code >= 400:
                r.failure(f"me -> {r.status_code}")
            else:
                r.success()
