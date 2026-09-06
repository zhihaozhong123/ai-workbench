#!/bin/sh
# Chroma 向量数据备份（由 docker-compose 的 chroma-backup 服务调用）
# 源：挂载的 chroma_data 卷（只读）；目标：chroma_backups 卷。每 6h 一次，本地保留 7 天。
#
# 说明：Chroma 以磁盘为持久化来源；本脚本在运行时对数据目录做 tar 快照（最佳努力）。
# 若担心运行快照一致性，可在备份前对 chroma 服务做短暂只读窗口，或改用底层存储卷快照。
# 向量丢失的兜底：可重新写入长期记忆重建向量，故本备份是加速恢复手段。
set -e

SRC=/source
DST=/backups
mkdir -p "$DST"
echo "[chroma-backup] start, source=${SRC}"

while :; do
  STAMP=$(date +%F_%H-%M)
  if tar czf "${DST}/chroma-${STAMP}.tar.gz" -C "$SRC" . 2>/dev/null; then
    echo "[chroma-backup] backed up ${DST}/chroma-${STAMP}.tar.gz"
  else
    echo "[chroma-backup] backup FAILED at ${STAMP}" >&2
  fi
  find "$DST" -name 'chroma-*.tar.gz' -mtime +7 -delete
  sleep 21600   # 6 小时
done
