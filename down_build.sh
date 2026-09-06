#!/usr/bin/env bash
# ============================================================
# 停止「模式二 · 构建产物 (.app)」的全部 docker 服务端口（保留数据）
# ------------------------------------------------------------
# 停止：
#   - 智作台 .app
#   - 全部 docker compose 服务（backend / nginx / chroma / db / redis / prometheus / pg-backup / chroma-backup）
#
# 注意：
#   - 所有服务由 docker 管理，docker compose down 停止全部容器；
#   - 数据清理（清库/清向量）不在本脚本，交由 up_build.sh 的「[1] 清数据」负责。
#
# 重要：本脚本只停 docker 服务、释放端口，绝不删除任何数据。
#       docker compose down（不带 -v）不会删卷，pg / Chroma 数据保留。
#
# 用法：bash down_build.sh
# ============================================================
set -u
cd "$(dirname "$0")"

echo "==> 停止智作台 .app ..."
if pkill -f "智作台" 2>/dev/null; then
  echo "    [OK] 已停止"
else
  echo "    （未在运行）"
fi

echo "==> 停止全部 docker 服务（db / redis / backend / nginx / chroma / prometheus / pg-backup / chroma-backup），保留数据卷 ..."
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  # 注意：不带 -v，数据卷（pg_data / chroma_data）一律保留，不会删除数据。
  docker compose down
  echo "    [OK] 依赖容器已停止（数据卷保留）"
else
  echo "    （未检测到 docker compose，跳过）"
fi

echo ""
echo "==> 自检：确认 docker 服务端口已释放 ..."
# down 应当释放的端口：nginx(8000)、chroma(18001)、pg(15432)、redis(16379)、prometheus(9090)、redis-exporter(9121)、pg-exporter(9187)、blackbox-exporter(9115)
_PORTS_OK=1
for _p in 8000 18001 15432 16379 9090 9121 9187 9115; do
  if lsof -nP -iTCP:"$_p" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "    [WARN] 端口 $_p 仍被占用：$(lsof -nP -iTCP:"$_p" -sTCP:LISTEN 2>/dev/null | awk 'NR>1{print $1, $2}' | head -2 | tr '\n' ' ')"
    _PORTS_OK=0
  else
    echo "    [OK] 端口 $_p 已释放"
  fi
done
if [ "$_PORTS_OK" = "1" ]; then
  echo "    [OK] 端口自检通过：docker 服务端口已全部释放。"
else
  echo "    [WARN] 端口自检未完全通过，请按上面提示处理（如需强制释放：lsof -tiTCP:8000 | xargs kill -9）。"
fi

echo ""
echo "[OK] 所有服务端口已停止。PostgreSQL / Chroma 向量 / 长期记忆 等数据均未删除。"
