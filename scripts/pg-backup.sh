#!/bin/sh
# PostgreSQL 每日备份（由 docker-compose 的 pg-backup 服务调用）
# 环境变量由 compose 注入：PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE
# 备份文件落 /backups（挂载到 pg_backups 卷），保留最近 7 天。
set -e

mkdir -p /backups
echo "[pg-backup] start, target=${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE}"

# 启动即做一次，之后每 24h 一次
while :; do
  STAMP=$(date +%F_%H-%M)
  if pg_dump -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" \
        -Fc -f "/backups/xst-${STAMP}.dump"; then
    echo "[pg-backup] dumped /backups/xst-${STAMP}.dump"
  else
    echo "[pg-backup] dump FAILED at ${STAMP}" >&2
  fi
  # 仅保留 7 天
  find /backups -name 'xst-*.dump' -mtime +7 -delete
  sleep 86400
done
