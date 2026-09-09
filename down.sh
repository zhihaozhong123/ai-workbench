#!/usr/bin/env bash
# ============================================================
# 智作台 一键停止：停掉全部容器并【清空所有数据】
#   ./down.sh             停止 + 清空数据（下次 up.sh 是全新干净状态）
#   ./down.sh --keep-data 仅停止，保留数据
# 清空范围：PostgreSQL / Redis / Chroma / 后端应用数据 的所有 docker 数据卷
# ============================================================
set -euo pipefail
cd "$(dirname "$0")"

PROJECT="xst"
CONTAINERS=("$PROJECT-backend" "$PROJECT-frontend" "$PROJECT-chroma" "$PROJECT-redis" "$PROJECT-postgres")
DATA_VOLUMES=("$PROJECT-pg-data" "$PROJECT-redis-data" "$PROJECT-chroma-data" "$PROJECT-app-data")
KEEP_DATA=0
[[ "${1:-}" == "--keep-data" ]] && KEEP_DATA=1

log()  { echo -e "\033[1;32m[down]\033[0m $*"; }

if [[ $KEEP_DATA -eq 0 ]]; then
  echo ""
  echo "⚠️  将停止全部服务并【彻底清空】PostgreSQL / Redis / Chroma / 应用数据（不可恢复）"
  read -r -p "确认清空？输入 yes or y 继续: " ans
  [[ "$ans" == "yes" || "$ans" == "y" ]] || { log "已取消"; exit 0; }
fi

for c in "${CONTAINERS[@]}"; do
  if docker ps -a --format '{{.Names}}' | grep -qx "$c"; then
    docker rm -f "$c" >/dev/null && log "已停止并移除容器: $c"
  fi
done

if [[ $KEEP_DATA -eq 0 ]]; then
  for v in "${DATA_VOLUMES[@]}"; do
    docker volume rm "$v" >/dev/null 2>&1 && log "已清空数据卷: $v" || true
  done
  log "全部数据已清空，下次 ./up.sh 将从零开始（全新状态，无任何历史杂质）"
else
  log "数据卷已保留，下次 ./up.sh 恢复原数据"
fi

docker network rm "${PROJECT}-net" >/dev/null 2>&1 || true
log "完成。前端/后端容器已全部退出。"
