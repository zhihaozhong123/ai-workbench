"""版本更新检查 API。

GET /api/update/check（JWT 鉴权）
- 读取远端更新 manifest（任何可匿名访问的 JSON，通常托管在 GitHub Releases/Pages）；
- 与当前 settings.app_version 比较，返回 has_update / notes / download_url；
- 未配置 UPDATE_MANIFEST_URL → 501；远端拉取失败 → 503，由前端区分呈现。

远端 manifest 建议结构：
{
  "version": "0.2.0",
  "notes": "更新说明（支持多行）",
  "published_at": "2026-09-06T00:00:00Z",
  "download_url": "https://github.com/owner/repo/releases/latest/download/ai-workbench.dmg"
}
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_current_user
from config import settings
from observability.logging_config import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/api/update", tags=["版本更新"])


def _ver_tuple(v: str) -> tuple[int, ...]:
    """将 'v1.2.3-beta' 归一为 (1,2,3)，忽略非数字尾巴，用于版本比较。"""
    out: list[int] = []
    for seg in str(v or "").strip().lstrip("v").split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        out.append(int(digits) if digits else 0)
    return tuple(out)


@router.get("/check")
async def check_update(user=Depends(get_current_user)):
    url = (settings.update_manifest_url or "").strip()
    if not url:
        raise HTTPException(
            status_code=501,
            detail="尚未配置远端更新服务（UPDATE_MANIFEST_URL）",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            manifest = resp.json()
    except Exception as e:  # noqa: BLE001 - 网络/解析失败统一按不可用处理
        log.warning("[更新] 远端 manifest 拉取失败 %s: %s", url, e)
        raise HTTPException(status_code=503, detail="更新服务暂时不可用，请稍后重试") from e

    current = (settings.app_version or "0.0.0").strip()
    latest = str(manifest.get("version") or "").strip()
    has_update = bool(latest) and _ver_tuple(latest) > _ver_tuple(current)

    log.info(
        "[更新] 检查结果 current=%s latest=%s has_update=%s", current, latest or "-", has_update
    )
    return {
        "current_version": current,
        "latest_version": latest,
        "has_update": has_update,
        "notes": manifest.get("notes") or manifest.get("release_notes") or "",
        "published_at": manifest.get("published_at") or "",
        "download_url": manifest.get("download_url") or "",
    }
