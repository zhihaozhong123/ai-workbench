#!/usr/bin/env bash
# ============================================================
# 智作台 一键启动：PG + Redis + Chroma + 后端 + 前端（全 docker）
#   ./up.sh          启动全部服务
#   ./up.sh app      额外以 Tauri dev 模式打开桌面 App（本机 cargo）
#   ./up.sh --build  强制重建后端镜像（代码变更后镜像内代码自动挂载同步，无需重建）
# 说明：无 nginx / Prometheus / Loki / Grafana，纯净前后端 + 三件套数据库
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="xst"
NET="${PROJECT}-net"
PG_C="${PROJECT}-postgres";  PG_VOL="${PROJECT}-pg-data"
REDIS_C="${PROJECT}-redis";  REDIS_VOL="${PROJECT}-redis-data"
CHROMA_C="${PROJECT}-chroma"; CHROMA_VOL="${PROJECT}-chroma-data"
BACKEND_C="${PROJECT}-backend"; BACKEND_IMG="${PROJECT}-backend"
FRONTEND_C="${PROJECT}-frontend"; FE_NODE_VOL="${PROJECT}-frontend-node-modules"
# 运行时数据：绑定挂载宿主机 ./data（含 skills / uploads / chroma 等），改文件即时生效，
# 也方便宿主机 register_skill.py / 后端容器直接复用同一份磁盘数据。
APP_VOL="$(pwd)/data"

# .env 里的连接信息（容器间直连用服务名，宿主机端口用于本机调试脚本）
PG_USER="${PG_USER:-xiaoshutong}"; PG_PASS="${PG_PASS:-xiaoshutong}"; PG_DB="${PG_DB:-xiaoshutong}"
REDIS_PASS="${REDIS_PASS:-xiaoshutong}"
BUILD=0; OPEN_APP=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    app) OPEN_APP=1 ;;
    *) echo "未知参数: $arg"; exit 1 ;;
  esac
done

log()  { echo -e "\033[1;32m[up]\033[0m $*"; }
warn() { echo -e "\033[1;33m[up]\033[0m $*"; }
die()  { echo -e "\033[1;31m[up]\033[0m $*"; exit 1; }

docker info >/dev/null 2>&1 || die "Docker 未运行，请先启动 Docker Desktop"

wait_for() { # wait_for <名称> <重试次数> <检测命令...>
  local name="$1" tries="$2"; shift 2
  for ((i=1; i<=tries; i++)); do
    if "$@" >/dev/null 2>&1; then log "$name 就绪"; return 0; fi
    sleep 2
  done
  die "$name 等待超时，请用 docker logs 排查"
}

# ---------- 1. 网络 ----------
docker network inspect "$NET" >/dev/null 2>&1 || docker network create "$NET" >/dev/null

# ---------- 2. PostgreSQL ----------
if docker ps --format '{{.Names}}' | grep -qx "$PG_C"; then
  log "PostgreSQL 已在运行"
else
  docker rm -f "$PG_C" >/dev/null 2>&1 || true
  log "启动 PostgreSQL (宿主机端口 15432)..."
  docker run -d --name "$PG_C" --network "$NET" \
    -e POSTGRES_USER="$PG_USER" -e POSTGRES_PASSWORD="$PG_PASS" -e POSTGRES_DB="$PG_DB" \
    -p 15432:5432 -v "$PG_VOL":/var/lib/postgresql/data \
    postgres:16-alpine >/dev/null
fi
wait_for "PostgreSQL" 30 docker exec "$PG_C" pg_isready -U "$PG_USER"

# ---------- 3. Redis ----------
if docker ps --format '{{.Names}}' | grep -qx "$REDIS_C"; then
  log "Redis 已在运行"
else
  docker rm -f "$REDIS_C" >/dev/null 2>&1 || true
  log "启动 Redis (宿主机端口 16379)..."
  docker run -d --name "$REDIS_C" --network "$NET" \
    -p 16379:6379 -v "$REDIS_VOL":/data \
    redis:7-alpine redis-server --requirepass "$REDIS_PASS" --appendonly yes >/dev/null
fi
wait_for "Redis" 15 docker exec "$REDIS_C" redis-cli -a "$REDIS_PASS" ping

# ---------- 4. Chroma ----------
if docker ps --format '{{.Names}}' | grep -qx "$CHROMA_C"; then
  log "Chroma 已在运行"
else
  docker rm -f "$CHROMA_C" >/dev/null 2>&1 || true
  log "启动 Chroma (宿主机端口 18001)..."
  docker run -d --name "$CHROMA_C" --network "$NET" \
    -e CHROMA_SERVER_HOST=0.0.0.0 -e CHROMA_SERVER_PORT=8000 \
    -p 18001:8000 -v "$CHROMA_VOL":/data \
    chromadb/chroma:1.5.9 >/dev/null
fi
# 1.5.9 单二进制镜像无 curl：用 /proc/net/tcp 检测 8000(0x1F40) LISTEN(0A)
wait_for "Chroma" 30 docker exec "$CHROMA_C" sh -c \
  "grep -Eq ':1F40[[:space:]]+[^[:space:]]+[[:space:]]+0A' /proc/net/tcp /proc/net/tcp6"

# ---------- 5. 后端 ----------
if [[ $BUILD -eq 1 ]] || ! docker image inspect "$BACKEND_IMG" >/dev/null 2>&1; then
  log "构建后端镜像（首次或 --build 时执行，需要几分钟）..."
  docker build -t "$BACKEND_IMG" . >/dev/null
fi
if docker ps --format '{{.Names}}' | grep -qx "$BACKEND_C"; then
  log "后端已在运行"
else
  docker rm -f "$BACKEND_C" >/dev/null 2>&1 || true
  log "启动后端 (宿主机端口 8000)..."
  # --env-file 传入 .env（密钥等）；随后的 -e 覆盖其中的 localhost 地址为容器网络地址
  docker run -d --name "$BACKEND_C" --network "$NET" \
    --env-file .env \
    -e DB_HOST="$PG_C" -e DB_PORT=5432 \
    -e REDIS_URL="redis://:${REDIS_PASS}@${REDIS_C}:6379/0" \
    -e CHROMA_HOST="$CHROMA_C" -e CHROMA_PORT=8000 \
    -p 8000:8000 -v "$APP_VOL":/app/data \
    "$BACKEND_IMG" >/dev/null
fi
wait_for "后端" 60 curl -sf http://127.0.0.1:8000/

# ---------- 5.5 本地技能自动登记到市场（幂等 upsert）----------
# data/skills/ 下的内置技能在 down.sh 清空 DB 后会从市场消失，这里每次启动
# 后端就绪后自动补登记（register_skill.py 为 upsert，重复执行无副作用）。
if docker exec "$BACKEND_C" /app/.venv/bin/python scripts/register_skill.py --all; then
  log "本地技能已登记到市场"
else
  warn "本地技能自动登记失败：可稍后手动执行 docker exec $BACKEND_C /app/.venv/bin/python scripts/register_skill.py --all"
fi

# ---------- 6. 前端（vite dev 热更新）----------
if docker ps --format '{{.Names}}' | grep -qx "$FRONTEND_C"; then
  log "前端已在运行"
else
  docker rm -f "$FRONTEND_C" >/dev/null 2>&1 || true
  log "启动前端 (宿主机端口 5173，首次自动 npm install)..."
  docker run -d --name "$FRONTEND_C" \
    -w /app -v "$(pwd)/frontend":/app -v "$FE_NODE_VOL":/app/node_modules \
    -p 5173:5173 node:20-alpine \
    sh -c "npm install --no-audit --no-fund && npm run dev -- --host 0.0.0.0" >/dev/null
fi
wait_for "前端" 90 sh -c 'curl -sf http://127.0.0.1:5173/ | grep -q html'

# ---------- 7. 桌面 App（可选）----------
if [[ $OPEN_APP -eq 1 ]]; then
  log "以 Tauri dev 模式打开桌面 App（需要本机 Rust 环境）..."
  ( cd src-tauri && cargo tauri dev ) || \
    warn "桌面 App 启动失败：请确认本机已安装 Rust 并执行 cargo install tauri-cli"
fi

echo ""
log "全部服务已启动 ✅"
echo "    前端(网页):  http://127.0.0.1:5173"
echo "    后端 API:    http://127.0.0.1:8000  (文档 /docs)"
echo "    PostgreSQL:  127.0.0.1:15432"
echo "    Redis:       127.0.0.1:16379"
echo "    Chroma:      127.0.0.1:18001"
echo "  停止并清空数据: ./down.sh"
