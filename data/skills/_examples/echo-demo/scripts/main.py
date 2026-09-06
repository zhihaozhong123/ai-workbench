#!/usr/bin/env python3
"""echo-demo 技能 CLI（XST-Skill CLI v1 契约示例）。

stdin : {"params": {"text": "..."}}
stdout: {"ok": true, "data": {"echo": "..."}}
"""
import json
import sys


def run(params: dict) -> dict:
    text = params.get("text") or ""
    if not text:
        raise ValueError("缺少参数 text")
    return {"echo": text}


def main() -> int:
    try:
        raw = sys.stdin.read() or "{}"
        req = json.loads(raw)
        params = req.get("params") or {}
        data = run(params)
        print(json.dumps({"ok": True, "data": data}, ensure_ascii=False))
        return 0
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
