#!/usr/bin/env bash
# ============================================================
# 智作台 —— 构建并启动（瘦客户端 .app + 多副本后端）
# ------------------------------------------------------------
# 架构：瘦客户端 + 服务器后端
#   - .app = 原生桌面壳（WebView 前端 + 本机执行层）
#   - 业务/数据/依赖(db/redis/chroma) 全在后端，由 docker compose 统一管理
#
# 用法：bash up_build.sh
#   启动时交互选择：
#     [0] 不清数据 —— 重启所有服务（保留 数据库 / 知识库 / 记忆 / 对话状态）
#     [1] 清数据 —— 清空 数据库（含业务表 + 对话状态 checkpoint）+ RAG 向量 + 长期记忆，并重启所有服务
#   后端副本数：取 docker-compose.yml 中 backend 的 deploy.replicas 值，
#               经 nginx(:8000) 负载均衡。
# 产物：src-tauri/target/release/bundle/macos/智作台.app
#
# 依赖：Docker Desktop（docker compose v2，支持 --wait）
# ============================================================
set -e
cd "$(dirname "$0")"

# ---------- 0. 前置：docker compose 必须可用 ----------
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "  [WARN] 未检测到 docker compose。请先安装并启动 Docker Desktop，再重新运行本脚本。"
  exit 1
fi

# ---------- 1. 选择：0=不清数据重启  1=清数据并重启 ----------
echo "============================================================"
echo " 启动模式选择"
echo "   [0] 不清数据 —— 重启所有服务（保留 数据库 / 知识库 / 记忆 / 对话状态 checkpoint）"
echo "   [1] 清数据 —— 清空 数据库（含业务表 + 对话状态 checkpoint）+ RAG 向量 + 长期记忆，并重启所有服务"
echo "============================================================"
while true; do
  read -r -p "请输入 0 或 1（默认 0）: " _ans
  _ans="${_ans:-0}"
  case "$_ans" in
    0|1) RESET="$_ans"; break ;;
    *) echo "    无效输入，请输入 0 或 1。" ;;
  esac
done
echo ""

# ---------- 2. 清数据（仅 RESET=1）：先拉起基础设施再执行 reset 脚本 ----------
# [2026-07-26] 所有服务回归 docker：reset 时需先拉起 db + redis + chroma，
# 然后宿主机脚本连 docker 端口（15432 / 16379 / 18001）执行重置。
if [ "$RESET" = "1" ]; then
  echo "==> 清数据：先拉起 db / redis / chroma 并等待就绪"
  docker compose up -d --wait db redis chroma
  echo "==> 清空 数据库（含业务表 + 对话状态 checkpoint）/ RAG 向量 / 长期记忆"
  uv run python scripts/reset_db.py 2>&1 | sed 's/^/    /' || true
  uv run python scripts/reset_chroma.py 2>&1 | sed 's/^/    /' || true
fi

# ---------- 3. 从 docker-compose.yml 读取 backend 副本数（deploy.replicas） ----------
REPLICAS=$(grep -m1 'replicas:' docker-compose.yml | grep -oE '[0-9]+' | head -1)
REPLICAS="${REPLICAS:-2}"
echo "==> 后端副本数（docker-compose.yml deploy.replicas）：$REPLICAS"

# ---------- 3.5 重新构建后端 / nginx 镜像（确保含最新代码修复，如 CORS 兜底）----------
# 注意：下方 up 仅复用已构建镜像，不会自动重新 build；不显式 build 会导致代码修复
# （如 main.py 的 CORS 兜底中间件）不进镜像，表现仍为「登录被 CORS 拦截」。
echo "==> 重新构建后端 / nginx 镜像（含最新代码修复）"
docker compose build backend nginx

# 清理上一次构建遗留的悬空镜像（旧 backend / nginx 镜像，标签为 <none>），
# 避免反复 `up_build.sh` 构建导致悬空镜像无限堆积、最终撑爆 Docker 虚拟磁盘
# （曾导致 PostgreSQL 因「No space left on device」无法写入 postmaster.pid 而持续 unhealthy）。
# 仅删除悬空镜像，不触碰任何数据卷与正在使用的镜像，安全。
docker image prune -f >/dev/null 2>&1 || true

# ---------- 4. 重启所有服务（多副本 backend 经 nginx :8000 负载）----------
# [2026-07-26] 所有服务回归 docker，显式列出全部要启动的服务。
# --force-recreate：重建并重启全部容器（数据在卷中保留，清数据由上面 reset 控制）
# --wait：等待各服务 healthcheck 就绪（含 backend /readyz）后才返回
echo "==> 重启服务（全 docker）：$REPLICAS 副本 backend + nginx + chroma + db + redis + pg-backup + 可观测性(grafana/loki/promtail/prometheus/redis-exporter/pg-exporter/blackbox-exporter)"
docker compose up -d --force-recreate --wait --scale "backend=$REPLICAS" \
  db redis backend nginx chroma prometheus grafana loki promtail redis-exporter pg-exporter blackbox-exporter pg-backup chroma-backup
echo "==> 后端容器已启动（$REPLICAS 副本经 nginx :8000 负载均衡）"

# ---------- 4.5 就绪自检：确保「选 1」后真的能注册/登录 ----------
# 轮询 /readyz（校验 DB+Redis 连通），并对登录接口做一次探测，避免「容器起来了但还没就绪 /
# 实际连不上库」导致 .app 打开后登录一直转圈。自检不通过会明确告警，不会静默成功。
echo "==> 自检：等待 nginx:8000 就绪并探测登录接口…"
_PROBE_OK=0
for _i in $(seq 1 20); do
  _rz=$(curl -s --max-time 3 http://127.0.0.1:8000/readyz 2>/dev/null || true)
  if echo "$_rz" | grep -q '"status":"ready"'; then
    echo "    [readyz] ready on poll #${_i}"
    _PROBE_OK=1
    break
  fi
  sleep 3
done
if [ "$_PROBE_OK" = "1" ]; then
  _code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 -X POST http://127.0.0.1:8000/api/login \
    -H "Content-Type: application/json" -H "X-XST-Client: xst-tv-7f3a" \
    -d '{"username":"__probe__","password":"__probe__"}' 2>/dev/null || echo 000)
  # HTTP 401 = 账号不存在/未授权 -> 说明登录接口可达且后端已连上 DB（探测成功）
  # HTTP 200/其他 = 接口可达；000 = 无响应（后端未起或 nginx 未转发）
  if [ "$_code" = "000" ]; then
    echo "    [LOGIN PROBE] HTTP 000 -> 无响应! 后端可能未启动或 nginx 未转发"
    echo "        请检查: docker logs xiaoshutong-backend-1"
  else
    echo "    [LOGIN PROBE] HTTP ${_code} -> 登录接口可达, 后端与 DB 连接正常 (探测通过)"
    echo "        说明: 返回 401 表示账号不存在(正常, 选 1 后账号已被清空), 可立即在 .app 注册/登录"
  fi
else
  echo "    [WARN] /readyz 在 60s 内未就绪, 后端可能未正常启动"
  echo "        请检查: docker logs xiaoshutong-backend-1"
fi

# ---------- 5. 构建 .app（非关键：失败不中断脚本，后端仍在运行） ----------
APP="src-tauri/target/release/bundle/macos/智作台.app"
echo "==> 先构建前端（确保 dist/ 存在，避免 .app 缺前端资源崩溃）"
( cd frontend && npm install && npm run build ) 2>&1 | sed 's/^/    /'
echo "==> 构建 .app（仅前端壳 + 本机执行层，不打包后端）"
if cargo tauri build 2>&1 | sed 's/^/    /'; then
  echo "    .app 构建完成"

  # -------- 5.1 封装 DMG 分发镜像 --------
  echo "==> 封装 DMG 分发镜像..."
  if bash scripts/create_dmg.sh 2>&1 | sed 's/^/    /'; then
    DMG_FILE="src-tauri/target/release/bundle/macos/智作台_$(python3 -c "import json; print(json.load(open('src-tauri/tauri.conf.json'))['version'])").dmg"
    echo "    DMG 已生成: ${DMG_FILE}"
  else
    echo "    [WARN] DMG 封装失败（不影响 .app 使用）。可手动执行 'bash scripts/create_dmg.sh'。"
  fi
else
  echo "    [WARN] .app 构建失败（不影响后端运行）。可手动执行 'cargo tauri build'，或直接使用已有 .app。"
fi

# ---------- 6. 启动 .app ----------
if [ -e "$APP" ]; then
  echo "==> 启动 .app：open \"$APP\""
  if open "$APP" 2>/dev/null; then
    echo "[OK] 完成。智作台.app 已启动（连 http://127.0.0.1:8000，后端 $REPLICAS 副本经 nginx 负载）。"
  else
    echo "  [WARN] 自动启动被 macOS 拦截（未公证/未签名）。请在 Finder 右键「智作台.app」→ 打开。"
  fi
else
  echo "  [WARN] 未找到产物 $APP（构建可能失败）。后端已在运行，可手动打开已有 .app 或重新构建。"
fi
