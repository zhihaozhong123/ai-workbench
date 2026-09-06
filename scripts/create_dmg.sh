#!/usr/bin/env bash
# ============================================================
# 智作台 —— 将 .app 封装为 .dmg 分发镜像
# ------------------------------------------------------------
# 前置：已通过 cargo tauri build 成功构建 智作台.app
# 用法：bash scripts/create_dmg.sh
# 产物：src-tauri/target/release/bundle/macos/智作台_2.0.0.dmg
# ============================================================
set -e
cd "$(dirname "$0")/.."

# -------- 版本号（从 tauri.conf.json 读取）--------
VERSION=$(python3 -c "import json; print(json.load(open('src-tauri/tauri.conf.json'))['version'])" 2>/dev/null || echo "0.0.0")
APP_NAME="智作台"
DMG_NAME="${APP_NAME}_${VERSION}"
APP_PATH="src-tauri/target/release/bundle/macos/${APP_NAME}.app"
DMG_PATH="src-tauri/target/release/bundle/macos/${DMG_NAME}.dmg"
STAGING="build_tmp/dmg_staging"

# -------- 检查 .app 是否存在 --------
if [ ! -d "$APP_PATH" ]; then
  echo "[ERROR] 未找到 ${APP_PATH}，请先执行 cargo tauri build 构建 .app"
  exit 1
fi

# -------- 清理临时目录 --------
rm -rf "$STAGING"
mkdir -p "$STAGING"

# -------- 拷贝 .app 到暂存区 --------
cp -R "$APP_PATH" "$STAGING/"

# -------- 创建 Applications 快捷方式（方便拖拽安装）--------
ln -s /Applications "$STAGING/Applications"

echo "==> 创建 DMG: ${DMG_PATH}"

# -------- 创建 DMG --------
hdiutil create \
  -volname "${DMG_NAME}" \
  -srcfolder "$STAGING" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

# -------- 清理 --------
rm -rf "$STAGING"

# -------- 输出信息 --------
DMG_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo "==> DMG 已生成: ${DMG_PATH} (${DMG_SIZE})"
echo "    用户双击 .dmg → 拖拽 智作台.app 到 Applications → 完成安装"
