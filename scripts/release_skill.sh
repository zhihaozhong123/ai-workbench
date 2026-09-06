#!/usr/bin/env bash
# 发布技能到 GitHub Release：打包 .xskill → git commit + tag → gh release create。
#
# 用法（在【技能 git 仓库】根目录或任意子目录执行）：
#   bash /path/to/ai-workbench/scripts/release_skill.sh [技能目录] [--dry-run]
#
# 说明：
#   - 技能目录默认 "."（即技能仓库根）；必须包含 manifest.json（或 SKILL.md frontmatter）；
#   - tag 取 manifest 的 version，自动补 v 前缀（如 v1.0.0）；
#   - 需要已安装并登录 gh CLI，且仓库已配置 GitHub 远端（gh auth status 可验证）；
#   - 发布成功后，在智作台「技能市场 → 添加技能源」填入本仓库地址即可安装/升级。
set -euo pipefail

SKILL_DIR="${1:-.}"
FLAGS=()
SKIP_TAG=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --no-tag) SKIP_TAG=1 ;;
  esac
done

SKILL_DIR="$(cd "$SKILL_DIR" && pwd)"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 1) 校验并取版本号
VER="$("$REPO_ROOT/.venv/bin/python" - "$SKILL_DIR" <<'PY' 2>/dev/null || uv run --project "$REPO_ROOT" python - "$SKILL_DIR"
import sys
sys.path.insert(0, "$REPO_ROOT")
from skills.manifest import load_manifest
m = load_manifest(sys.argv[1])
print(m.version)
PY
)"
if [[ -z "$VER" ]]; then
  echo "[release] 无法读取技能版本，请检查 manifest.json（或 SKILL.md frontmatter）" >&2
  exit 1
fi
TAG="v$VER"

# 2) 打包
"$REPO_ROOT/.venv/bin/python" "$SCRIPT_DIR/build_skill.py" "$SKILL_DIR" -o "$SKILL_DIR/dist" 2>/dev/null \
  || uv run --project "$REPO_ROOT" python "$SCRIPT_DIR/build_skill.py" "$SKILL_DIR" -o "$SKILL_DIR/dist"
ASSET="$(ls "$SKILL_DIR"/dist/skill-*-"$VER".xskill 2>/dev/null | head -1)"
if [[ -z "$ASSET" ]]; then
  echo "[release] 未找到打包产物 dist/skill-*-$VER.xskill" >&2
  exit 1
fi

echo "[release] slug 产物：$ASSET"
echo "[release] tag：$TAG"

if [[ "${DRY:-0}" == "1" ]]; then
  echo "[release] --dry-run：以上步骤已完成，跳过 git/gh 发布。"
  exit 0
fi

# 3) git commit + tag（在技能仓库内）
if [[ "$SKIP_TAG" == "0" ]]; then
  git -C "$SKILL_DIR" add -A
  git -C "$SKILL_DIR" commit -m "release: $TAG" 2>/dev/null || echo "[release] 无新提交，沿用已有提交"
  if git -C "$SKILL_DIR" rev-parse "$TAG" >/dev/null 2>&1; then
    echo "[release] tag $TAG 已存在，跳过打 tag"
  else
    git -C "$SKILL_DIR" tag "$TAG"
  fi
  git -C "$SKILL_DIR" push origin main --tags
else
  echo "[release] --no-tag：跳过 git tag/push"
fi

# 4) 创建 GitHub Release 并附资产
if command -v gh >/dev/null 2>&1; then
  NOTES="$(cd "$SKILL_DIR" && sed -n '/^## /,$p' CHANGELOG.md 2>/dev/null | head -20 || true)"
  gh release create "$TAG" "$ASSET" --repo "$(git -C "$SKILL_DIR" config --get remote.origin.url)" \
    ${NOTES:+--notes "$NOTES"} --title "技能发布 ${TAG}" 2>/dev/null \
    || gh release create "$TAG" "$ASSET" --repo "$(git -C "$SKILL_DIR" config --get remote.origin.url)" --title "技能发布 ${TAG}"
  echo "[release] 发布成功：$TAG（在智作台技能市场添加该仓库即可看到）"
else
  echo "[release] 未安装 gh CLI，请手动创建 GitHub Release 并上传：$ASSET"
fi
