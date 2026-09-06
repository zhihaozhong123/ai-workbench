"""公众号文章发布技能 CLI 层：参数解析与分发。"""
from __future__ import annotations

import json
import sys
from typing import List, Optional

from service.article_service import generate_article
from service.wechat_client import publish_draft
from util.constants import SKILL_SLUG, SKILL_VERSION


def _emit(result: dict) -> int:
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


def cmd_run() -> int:
    try:
        raw = sys.stdin.read() or "{}"
        req = json.loads(raw)
        params = req.get("params") or {}
    except json.JSONDecodeError as e:
        return _emit({"ok": False, "error": f"入参 JSON 非法: {e}"})
    try:
        result = generate_article(params)
        if bool(params.get("publish")):
            url = publish_draft(result["html"], result["title"])
            result["publish_url"] = url
            result["status"] = "published"
        return _emit({"ok": True, "data": result})
    except Exception as e:  # noqa: BLE001
        return _emit({"ok": False, "error": str(e)})


def cmd_health() -> int:
    return _emit({
        "ok": True,
        "data": {"slug": SKILL_SLUG, "version": SKILL_VERSION, "status": "ok"},
    })


def cmd_version() -> int:
    return _emit({"ok": True, "data": {"slug": SKILL_SLUG, "version": SKILL_VERSION}})


def main(argv: Optional[List[str]] = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    cmd = argv[0] if argv else "run"
    if cmd == "health":
        return cmd_health()
    if cmd == "version":
        return cmd_version()
    return cmd_run()
