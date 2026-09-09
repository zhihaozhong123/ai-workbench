#!/usr/bin/env python3
"""本地技能注册脚本：把 data/skills/ 下的技能登记到数据库的市场快照表。

用途：放置在 data/skills/ 下的本地技能，需要登记到 skills 表后才会出现在
技能市场中。用户在市场点击「安装」后，才会写入 installed_skills 表。

默认只登记 skills 表（市场），不自动安装给任何用户。
使用 --installed 可同时登记到 installed_skills（仅用于本地测试）。

用法：
    # 仅登记到市场（推荐）
    python scripts/register_skill.py <skill-slug>

    # 登记所有本地技能到市场
    python scripts/register_skill.py --all

    # 登记到市场并直接安装给指定用户（本地测试用）
    python scripts/register_skill.py <skill-slug> --installed --user-id <user_id>

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

from sqlalchemy import delete, select  # noqa: E402

from infra.db import Conversation, InstalledSkill, Message, SessionLocal, Skill, _utcnow  # noqa: E402
from skills.installer import remove_skill  # noqa: E402
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


async def _register_one(slug: str, skill_dir: Path, user_id: str, also_install: bool) -> None:
    """把技能登记到 skills 表；also_install=True 时同时登记 installed_skills 表。"""
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

        # 2) 仅在 --installed 时写入 installed_skills 表（用户安装）
        if also_install:
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
        action = "登记到市场" if not also_install else f"登记到市场并安装给用户 {user_id}"
        print(f"[register] {manifest.name} v{manifest.version} (slug={manifest.slug}) {action}")
        print(f"           分类: {manifest.category} | source_key=local")


async def _purge_one(slug: str) -> int:
    """从数据库和磁盘彻底删除指定技能（市场快照、安装记录、专属会话）。磁盘目录不存在时静默跳过。"""
    from config import settings

    async with SessionLocal() as db:
        # 1) 删除该技能的专属会话及下属消息
        conv_ids = (await db.execute(
            select(Conversation.id).where(Conversation.skill_id == slug)
        )).scalars().all()
        removed_convs = len(conv_ids)
        if conv_ids:
            await db.execute(delete(Message).where(Message.conversation_id.in_(conv_ids)))
            await db.execute(delete(Conversation).where(Conversation.skill_id == slug))

        # 2) 删除所有用户的安装记录
        removed_installed = (await db.execute(
            delete(InstalledSkill).where(InstalledSkill.slug == slug).returning(InstalledSkill.id)
        )).all()

        # 3) 删除市场快照
        removed_market = (await db.execute(
            delete(Skill).where(Skill.slug == slug).returning(Skill.name)
        )).scalar_one_or_none()

        await db.commit()

    # 4) 清理磁盘安装目录（如果存在）
    disk_ok = False
    try:
        skill_dir = Path(settings.skills_root) / slug
        if skill_dir.is_dir():
            remove_skill(settings.skills_root, slug)
            disk_ok = True
    except Exception as e:
        print(f"[purge] 磁盘目录清理失败（可手动删除）: {e}", file=sys.stderr)

    print(
        f"[purge] 技能 {slug} 已清理："
        f"市场快照={'已删除' if removed_market else '无'}, "
        f"安装记录={len(removed_installed)}条, "
        f"会话={removed_convs}个, "
        f"磁盘目录={'已删除' if disk_ok else '不存在/失败'}"
    )
    return 0


async def main() -> int:
    ap = argparse.ArgumentParser(description="把本地技能登记到 ai-workbench 技能市场")
    ap.add_argument("slug", nargs="?", help="技能 slug（留空配合 --all 或 --list）")
    ap.add_argument("--all", action="store_true", help="登记所有本地技能到市场")
    ap.add_argument("--list", action="store_true", help="列出所有本地技能")
    ap.add_argument("--installed", action="store_true",
                    help="同时登记到 installed_skills（仅本地测试，默认不安装）")
    ap.add_argument("--user-id", default="local-dev",
                    help="配合 --installed 使用的用户 ID（默认 local-dev）")
    ap.add_argument("--purge", action="store_true",
                    help="彻底删除指定技能：市场快照、安装记录、相关会话与磁盘目录")
    args = ap.parse_args()

    if args.purge:
        if not args.slug:
            print("[purge] 错误：请提供要删除的技能 slug", file=sys.stderr)
            return 1
        return await _purge_one(args.slug)

    local = _local_skills()

    if args.list:
        if not local:
            print("（data/skills/ 下没有技能）")
            return 0
        print(f"本地技能（共 {len(local)} 个）：")
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
            await _register_one(slug, path, args.user_id, args.installed)
        except SkillError as e:
            print(f"[register] {slug} 登记失败：{e}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
