#!/usr/bin/env python3
"""技能打包 CLI：把技能目录打成 .xskill（zip 单文件），作为 GitHub Release 资产分发。

用法：
    uv run python scripts/build_skill.py <技能目录> [-o 输出目录]

产物：skill-<slug>-<version>.xskill（zip 顶层即技能内容：manifest.json / SKILL.md / scripts/...）。
打包后配合 scripts/release_skill.sh 发布到 GitHub Release。

技能目录规范（详见 docs/skill-development.md）：
- 根 manifest.json（权威元数据；若缺失将兼容回退读取 SKILL.md frontmatter）
- SKILL.md（给 Agent 的技能说明）
- 可选 scripts/main.py（确定性 CLI，契约见 skills/runtime.py）
- AGENT.md / README.md / references 等可选
"""
from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from skills.manifest import SkillError, load_manifest  # noqa: E402

_EXCLUDE_DIRS = {".git", "__pycache__", ".idea", ".vscode", "dist", ".venv", "node_modules"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".DS_Store"}


def _walk_relative(skill_dir: Path):
    for base, dirs, files in os.walk(skill_dir):
        rel_base = Path(base).relative_to(skill_dir)
        dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
        for name in sorted(files):
            if Path(name).suffix in _EXCLUDE_SUFFIXES or name.startswith("."):
                continue
            yield (rel_base / name).as_posix()


def main() -> int:
    ap = argparse.ArgumentParser(description="打包智作台技能为 .xskill")
    ap.add_argument("skill_dir", type=Path, help="技能目录（含 manifest.json 或 SKILL.md）")
    ap.add_argument("-o", "--out", type=Path, default=None, help="输出目录（默认 <技能目录>/../dist）")
    args = ap.parse_args()

    skill_dir: Path = args.skill_dir.resolve()
    if not skill_dir.is_dir():
        print(f"[build] 错误：技能目录不存在 {skill_dir}", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(skill_dir)
    except SkillError as e:
        print(f"[build] 技能包校验失败：{e}", file=sys.stderr)
        return 1

    out_dir = (args.out or skill_dir.parent / "dist").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"skill-{manifest.slug}-{manifest.version}.xskill"

    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in _walk_relative(skill_dir):
            zf.write(skill_dir / rel, rel)

    print(f"[build] 打包完成：{artifact}")
    print(f"[build]   技能   : {manifest.name} (v{manifest.version})")
    print(f"[build]   slug   : {manifest.slug}")
    print(f"[build]   CLI    : {'有 (' + (manifest.entry or '') + ')' if manifest.has_cli else '无（纯提示词技能）'}")
    print(f"[build] 下一步：在技能 git 仓库执行 scripts/release_skill.sh {skill_dir} 发布到 GitHub Release")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
