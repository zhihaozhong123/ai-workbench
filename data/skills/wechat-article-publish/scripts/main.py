#!/usr/bin/env python3
"""wechat-article-publish 技能运行时（XST-Skill CLI v1）。

真正的浏览器自动化由桌面端 local_control 工具（open_webpage / run_apple_script）
在 Agent 侧完成；本入口只负责在「用户已明确确认写作需求后」做一次结构化校验与回执，
帮助 Agent 在执行前核对标题/格式/排版/字数等参数无误。

CLI 契约（XST-Skill CLI v1）：
- 平台以 ``python -u scripts/main.py run`` 启动，cwd=技能目录；
- 参数以 JSON 经 stdin 传入：``{"params": {...}}``；
- 结果以单行 JSON 经 stdout 返回：``{"ok": true, "data": {...}}``
  或 ``{"ok": false, "error": "..."}``。

约定参数（均由 Agent 按对话共识传入）：
- title: 文章标题（≤64 字，超出会自动截断并标记）；
- format: 正文载体，Markdown（默认）或 HTML；
- layout: 排版方案，四套之一（A/B/C/D 或对应中文名）；
- wordcount: 目标字数/区间描述（如 “1200字” / “800-1000字”）；
- confirmed: 必须为 true，表示用户已明确确认，未确认直接拒绝。
"""

from __future__ import annotations

import json
import sys

MAX_TITLE_LEN = 64

# 四套排版模板（与 AGENT.md 保持一致）
LAYOUTS = {
    "A": "简洁商务风",
    "B": "清新文艺风",
    "C": "干货清单风",
    "D": "深度叙事风",
}


def _normalize_layout(raw: str) -> str:
    """把用户/Agent 传入的排版标识归一化为正式排版名。"""
    if not raw:
        return ""
    v = str(raw).strip()
    up = v.upper()
    if up in LAYOUTS:
        return LAYOUTS[up]
    # 兼容直接传中文名
    for name in LAYOUTS.values():
        if name in v or v in name:
            return name
    # 兼容传「A 简洁商务风」之类带前缀的串
    for key, name in LAYOUTS.items():
        if v.startswith(key) or f"{key}、" in v or f"{key}·" in v:
            return name
    return v


def _normalize_format(raw: str) -> str:
    v = str(raw or "").strip().lower()
    if v in {"html", "htm"}:
        return "HTML"
    return "Markdown"  # markdown / md / 其它一律按默认 Markdown


def _normalize_wordcount(raw: str) -> str:
    v = str(raw or "").strip()
    return v


def main() -> int:
    payload: dict = {}
    try:
        raw = sys.stdin.read()
        if raw.strip():
            parsed = json.loads(raw)
            payload = parsed if isinstance(parsed, dict) else {}
    except Exception:
        payload = {}
    params = (payload or {}).get("params") or {}

    # 安全护栏：未经用户确认，拒绝一切“已就绪”宣称
    if not bool(params.get("confirmed")):
        result = {"ok": False, "error": "未经确认，拒绝执行。请先与用户确认写作需求（标题/字数/排版/正文格式）后再调用。"}
    else:
        title = str(params.get("title") or "").strip()
        truncated = len(title) > MAX_TITLE_LEN
        if truncated:
            title = title[:MAX_TITLE_LEN]
        layout = _normalize_layout(params.get("layout") or params.get("style") or "")
        data = {
            "slug": "wechat-article-publish",
            "title": title,
            "title_truncated": truncated,
            "format": _normalize_format(params.get("format") or ""),
            "layout": layout or "（未指定，请确认排版模板）",
            "wordcount": _normalize_wordcount(params.get("wordcount") or ""),
            "confirmed": True,
            "status": "ready_for_browser",
            "message": "写作需求已确认并校验通过，准备在微信公众平台执行「新建图文 → 填标题 → 写正文 → 保存草稿」。",
        }
        result = {"ok": True, "data": data}

    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
