#!/usr/bin/env python3
"""本地技能注册脚本：把 data/skills/ 下已安装的技能登记到数据库。

用途：通过 install_skill.py 安装到磁盘的技能，需要在数据库中登记后才会出现在
技能市场和对话任务中。本脚本扫描 data/skills/ 并写入 skills（市场快照）
和 installed_skills（用户安装）两张表。

用法：
    # 注册指定技能给指定用户
    python scripts/register_skill.py wechat-article-publish --user-id <user_id>

    # 注册所有本地技能
    python scripts/register_skill.py --all --user-id <user_id>

    # 列出所有本地已安装技能
    python scripts/register_skill.py --list
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from sqlalchemy import select  # noqa: E402

from infra.db import InstalledSkill, SessionLocal, Skill, _utcnow  # noqa: E402
from skills.manifest import SkillError, load_manifest  # noqa: E402


def _local_skills() -> list[tuple[str, Path]]:
    """扫描 data/skills/ 下的本地技能目录。"""
    skills_root = _REPO_ROOT / "data" / "skills"
    if not skills_root.is_dir():
        return []
    result = []
    for child in sorted(skills_root.iterdir()):
        if child.is_dir() and not child.name.startswith("_") and not child.name.startswith("."):
            if (child / "manifest.json").exists() or (child / "SKILL.md").exists():
                result.append((child.name, child))
    return result


async def _register_one(slug: str, skill_dir: Path, user_id: str) -> None:
    """把一个技能登记到 skills 表和 installed_skills 表。"""
    manifest = load_manifest(skill_dir)
    async with SessionLocal() as db:
        # 1) 写入/更新 skills 表（市场快照）
        skill = (await db.execute(
            select(Skill).where(Skill.slug == manifest.slug)
        )).scalar_one_or_none()
        if skill is None:
            skill = Skill(slug=manifest.slug)
            db.add(skill)
        skill.name = manifest.name
        skill.version = manifest.version
        skill.description = manifest.description
        skill.author = manifest.author
        skill.emoji = manifest.emoji
        skill.category = manifest.category
        skill.homepage = manifest.homepage
        skill.has_cli = manifest.has_cli
        skill.source_key = "local"
        skill.artifact_url = ""
        skill.release_url = ""
        skill.updated_at = _utcnow()

        # 2) 写入/更新 installed_skills 表（用户安装）
        inst = (await db.execute(
            select(InstalledSkill).where(
                InstalledSkill.user_id == user_id, InstalledSkill.slug == manifest.slug
            )
        )).scalar_one_or_none()
        if inst is None:
            inst = InstalledSkill(user_id=user_id, slug=manifest.slug)
            db.add(inst)
        inst.name = manifest.name
        inst.version = manifest.version
        inst.description = manifest.description
        inst.emoji = manifest.emoji
        inst.category = manifest.category
        inst.source_key = "local"
        inst.status = "ok"
        inst.error = ""
        inst.updated_at = _utcnow()

        await db.commit()
        print(f"[register] {manifest.name} v{manifest.version} (slug={manifest.slug}) 已登记")
        print(f"           分类: {manifest.category} | 用户: {user_id}")


async def main() -> int:
    ap = argparse.ArgumentParser(description="把本地技能登记到 ai-workbench 数据库")
    ap.add_argument("slug", nargs="?", help="技能 slug（留空配合 --all 或 --list）")
    ap.add_argument("--all", action="store_true", help="注册所有本地技能")
    ap.add_argument("--list", action="store_true", help="列出所有本地技能")
    ap.add_argument("--user-id", default="local-dev", help="用户 ID（默认 local-dev）")
    args = ap.parse_args()

    local = _local_skills()

    if args.list:
        if not local:
            print("（data/skills/ 下没有已安装的技能）")
            return 0
        print(f"本地已安装技能（共 {len(local)} 个）：")
        for slug, path in local:
            try:
                m = load_manifest(path)
                print(f"  {slug:30s} v{m.version:8s} {m.name}（{m.category}）")
            except SkillError as e:
                print(f"  {slug:30s} [清单错误: {e}]")
        return 0

    targets: list[tuple[str, Path]] = []
    if args.all:
        targets = local
    elif args.slug:
        for slug, path in local:
            if slug == args.slug:
                targets = [(slug, path)]
                break
        if not targets:
            print(f"[register] 错误：data/skills/ 下找不到技能 {args.slug}", file=sys.stderr)
            print(f"           可用技能：{', '.join(s for s, _ in local) or '无'}", file=sys.stderr)
            return 1
    else:
        ap.print_help()
        return 1

    for slug, path in targets:
        try:
            await _register_one(slug, path, args.user_id)
        except SkillError as e:
            print(f"[register] {slug} 登记失败：{e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
