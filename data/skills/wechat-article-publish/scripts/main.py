#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公众号文章批量发布技能 CLI 入口（XST-Skill CLI v1 契约）。"""
from __future__ import annotations

import os
import sys

if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from cli.app import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
