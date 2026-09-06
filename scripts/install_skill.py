#!/usr/bin/env python3
"""技能引入脚本：从技能源码目录构建 .xskill 并安装到 ai-workbench 技能市场。

供内部维护人员使用：拿到外来开发人员提交的技能代码后，一键构建+安装。

用法：
    # 方式1：指定技能源码目录（绝对或相对路径）
    python scripts/install_skill.py /path/to/wechat-article-publish

    # 方式2：从 ai-workbench-skills 仓库按 分类/技能slug 安装
    #       需要设置 SKILLS_REPO 环境变量指向本地 ai-workbench-skills 克隆
    SKILLS_REPO=/path/to/ai-workbench-skills python scripts/install_skill.py wechat/wechat-article-publish

    # 方式3：只打包不安装（生成 .xskill 供分发）
    python scripts/install_skill.py /path/to/skill --build-only
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from skills.installer import install_zip_bytes  # noqa: E402
from skills.manifest import SkillError, load_manifest  # noqa: E402

_EXCLUDE_DIRS = {".git", "__pycache__", ".idea", ".vscode", "dist", ".venv", "node_modules"}
_EXCLUDE_SUFFIXES = {".pyc", ".pyo", ".DS_Store"}


def _build_xskill(skill_dir: Path) -> Path:
    """把技能目录打包成 .xskill，返回产物路径。"""
    manifest = load_manifest(skill_dir)
    out_dir = skill_dir.parent / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    artifact = out_dir / f"skill-{manifest.slug}-{manifest.version}.xskill"

    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
        for base, dirs, files in os.walk(skill_dir):
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            rel_base = Path(base).relative_to(skill_dir)
            for name in sorted(files):
                if Path(name).suffix in _EXCLUDE_SUFFIXES or name.startswith("."):
                    continue
                rel = (rel_base / name).as_posix()
                zf.write(skill_dir / rel, rel)
    return artifact


def _resolve_skill_dir(arg: str) -> Path:
    """解析技能目录：支持绝对路径、相对路径、或 分类/slug 形式。"""
    p = Path(arg).expanduser()
    if p.is_absolute() and p.is_dir():
        return p.resolve()
    # 相对路径
    rel = (_REPO_ROOT / p).resolve()
    if rel.is_dir():
        return rel
    # 分类/slug 形式：尝试从 SKILLS_REPO 环境变量解析
    skills_repo = os.environ.get("SKILLS_REPO", "").strip()
    if skills_repo:
        candidate = (Path(skills_repo).expanduser() / arg).resolve()
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"找不到技能目录: {arg}\n"
        f"  若使用「分类/slug」形式，请设置 SKILLS_REPO 环境变量指向本地 ai-workbench-skills 克隆。"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="构建并安装技能到 ai-workbench")
    ap.add_argument("skill", help="技能源码目录路径，或「分类/slug」（如 wechat/wechat-article-publish）")
    ap.add_argument("--build-only", action="store_true", help="只打包 .xskill，不安装")
    ap.add_argument("--skills-root", type=Path, default=None,
                    help="技能安装根目录（默认 data/skills）")
    args = ap.parse_args()

    try:
        skill_dir = _resolve_skill_dir(args.skill)
    except FileNotFoundError as e:
        print(f"[install] 错误：{e}", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(skill_dir)
    except SkillError as e:
        print(f"[install] 技能清单校验失败：{e}", file=sys.stderr)
        return 1

    print(f"[install] 技能: {manifest.name} v{manifest.version} (slug={manifest.slug})")
    print(f"[install] 源码: {skill_dir}")

    # 打包
    try:
        artifact = _build_xskill(skill_dir)
    except Exception as e:  # noqa: BLE001
        print(f"[install] 打包失败：{e}", file=sys.stderr)
        return 1
    print(f"[install] 打包完成: {artifact}")

    if args.build_only:
        return 0

    # 安装
    skills_root = args.skills_root or (_REPO_ROOT / "data" / "skills")
    skills_root.mkdir(parents=True, exist_ok=True)
    try:
        data = artifact.read_bytes()
        installed_manifest, dest = install_zip_bytes(skills_root, data)
    except SkillError as e:
        print(f"[install] 安装失败：{e}", file=sys.stderr)
        return 1

    print(f"[install] 安装成功: {dest}")
    print(f"[install] 分类: {installed_manifest.category}")
    print(f"[install] 提示: 在 ai-workbench 技能市场刷新即可看到该技能")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
