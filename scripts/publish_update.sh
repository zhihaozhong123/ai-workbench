#!/usr/bin/env bash
# ============================================================
# 智作台 —— 发布更新（生成签名 + 更新清单 JSON）
# ------------------------------------------------------------
# 用法：
#   首次使用（生成密钥对）：
#     bash scripts/publish_update.sh init
#   每次发布新版本（签名 .dmg + 生成更新清单）：
#     bash scripts/publish_update.sh release
# ============================================================
set -e
cd "$(dirname "$0")/.."

VERSION=$(python3 -c "import json; print(json.load(open('src-tauri/tauri.conf.json'))['version'])" 2>/dev/null || echo "0.0.0")
APP_NAME="智作台"
DMG_PATH="src-tauri/target/release/bundle/macos/${APP_NAME}_${VERSION}.dmg"
KEYS_DIR="scripts/updater_keys"
PRIVATE_KEY="${KEYS_DIR}/private.key"
PUBLIC_KEY="${KEYS_DIR}/public.key"
MANIFEST_DIR="scripts/update_manifest"
SIG_FILE="${MANIFEST_DIR}/${VERSION}.sig"

# -------- init: 生成 Ed25519 密钥对用于更新签名 --------
do_init() {
  mkdir -p "$KEYS_DIR"
  if [ -f "$PRIVATE_KEY" ]; then
    echo "[WARN] 密钥对已存在，跳过生成。如需重新生成，请删除 ${KEYS_DIR}/ 后重试。"
    echo "  公钥（请填入 tauri.conf.json → plugins.updater.pubkey）："
    cat "$PUBLIC_KEY"
    return 0
  fi

  echo "==> 生成更新签名密钥对 (Ed25519)..."
  openssl genpkey -algorithm ED25519 -out "$PRIVATE_KEY"
  openssl pkey -in "$PRIVATE_KEY" -pubout -out "$PUBLIC_KEY"

  PUBKEY_CONTENT=$(cat "$PUBLIC_KEY" | sed '1d;$d' | tr -d '\n')
  echo ""
  echo "==> 密钥对已生成！"
  echo "  私钥: ${PRIVATE_KEY}  （务必安全保管，不提交到 git）"
  echo "  公钥: ${PUBLIC_KEY}"
  echo ""
  echo "==> 请将以下公钥填到 src-tauri/tauri.conf.json 中："
  echo "    \"plugins\": { \"updater\": { \"pubkey\": \"${PUBKEY_CONTENT}\" } }"
  echo ""
}

# -------- release: 签名 DMG + 生成更新清单 --------
do_release() {
  if [ ! -f "$PRIVATE_KEY" ]; then
    echo "[ERROR] 未找到私钥 ${PRIVATE_KEY}，请先执行: bash scripts/publish_update.sh init"
    exit 1
  fi

  if [ ! -f "$DMG_PATH" ]; then
    echo "[ERROR] 未找到 ${DMG_PATH}，请先执行 bash scripts/create_dmg.sh 生成 DMG"
    exit 1
  fi

  mkdir -p "$MANIFEST_DIR"

  # -------- 对 DMG 签名 --------
  echo "==> 对 DMG 签名..."
  openssl pkeyutl -sign -inkey "$PRIVATE_KEY" -rawin -in "$DMG_PATH" -out "$SIG_FILE"
  SIG_BASE64=$(base64 -i "$SIG_FILE")

  # -------- 生成更新清单 JSON --------
  PUB_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
  ARCH=$(uname -m)

  MANIFEST_FILE="${MANIFEST_DIR}/update_${ARCH}.json"
  DMG_FILENAME=$(basename "$DMG_PATH")

  cat > "$MANIFEST_FILE" <<JSON
{
  "version": "${VERSION}",
  "notes": "智作台 ${VERSION} 版本更新",
  "pub_date": "${PUB_DATE}",
  "platforms": {
    "darwin-${ARCH}": {
      "signature": "${SIG_BASE64}",
      "url": "http://192.168.0.105:8000/download/${DMG_FILENAME}"
    }
  }
}
JSON

  echo "==> 更新清单已生成: ${MANIFEST_FILE}"
  echo ""
  echo "==> 发布步骤："
  echo "  1. 上传 ${DMG_PATH} 到你的服务器下载目录"
  echo "  2. 上传 ${MANIFEST_FILE} 到更新端点 URL"
  echo "  3. tauri.conf.json 中 plugins.updater.endpoints 应指向:"
  echo "     http://192.168.0.105:8000/update/darwin/${ARCH}/{{current_version}}"
  echo ""
  echo "    （服务端需将请求路由到对应的 update_${ARCH}.json 文件）"
}

case "${1:-release}" in
  init) do_init ;;
  release) do_release ;;
  *)
    echo "用法: bash scripts/publish_update.sh [init|release]"
    echo "  init    - 首次生成 Ed25519 密钥对"
    echo "  release - 签名 DMG 并生成更新清单（默认）"
    ;;
esac
