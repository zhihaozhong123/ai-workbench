"""技能市场与技能源管理 API。

- 技能源（GitHub Releases 仓库）增删改查 + 手动同步；
- 市场快照浏览 / 搜索 / 分类；
- 技能安装 / 升级 / 卸载 / 我的技能（任务入口数据）。

关键约束：
- 市场数据由「源」驱动：技能元数据一律来自源同步（GitHub / 本地 data/skills），禁止手工造数据；
- 本地技能（source_key=local）= 随平台分发的内置技能源码包，位于 data/skills/<slug>：
  卸载【绝不删除】磁盘技能文件与市场快照，只移除当前用户的安装记录（前端对话任务入口消失，
  市场重新点击「安装」即刻恢复）；
- 远程技能：安装 = 下载 .xskill → 严格校验 → 原子落盘 data_root/skills → 登记 installed_skills；
  卸载仅针对当前用户，无任何用户再安装时才清理其下载副本（市场快照保留，可随时重装）；
- 安装失败会登记 status=failed 并保留错误，前端展示「重试」，不影响平台与其它技能。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update

from api.deps import get_current_user
from config import settings
from infra.db import (
    InstalledSkill,
    SessionLocal,
    Skill,
    SkillSource,
    _utcnow,
    get_db,
)
import logging

from infra.state_store import get_lock, get_redis
from skills import catalog
from skills.installer import install_zip_bytes, remove_skill
from skills.manifest import SkillError, load_manifest

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/skills", tags=["技能市场"])

# 后台批量扫描节流：同一实例 60s 内最多触发一次「对过期源的全量后台刷新」
_refresh_lock = asyncio.Lock()
_last_scan_at: float = 0.0


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


# ---------------------------------------------------------------- 序列化
def _skill_dict(s: Skill, is_installed: bool = False) -> dict:
    return {
        "slug": s.slug,
        "name": s.name,
        "version": s.version,
        "description": s.description or "",
        "author": s.author or "",
        "emoji": s.emoji or "🧩",
        "category": s.category or "通用",
        "homepage": s.homepage or "",
        "has_cli": s.has_cli,
        "source_key": s.source_key,
        "source_url": catalog.source_url(s.source_key) if s.source_key else "",
        "release_url": s.release_url or "",
        "install_count": s.install_count or 0,
        "updated_at": _iso(s.updated_at),
        "is_installed": is_installed,
    }


def _installed_dict(s: InstalledSkill) -> dict:
    return {
        "slug": s.slug,
        "name": s.name,
        "version": s.version,
        "description": s.description or "",
        "emoji": s.emoji or "🧩",
        "category": s.category or "通用",
        "source_key": s.source_key,
        "status": s.status,
        "error": s.error or "",
        "installed_at": _iso(s.installed_at),
    }


def _source_dict(row: SkillSource, skill_count: int = 0) -> dict:
    return {
        "id": row.id,
        "source_key": row.source_key,
        "label": row.label or "",
        "url": row.url or catalog.source_url(row.source_key),
        "enabled": bool(row.enabled),
        "last_fetched_at": _iso(row.last_fetched_at),
        "fetch_error": row.fetch_error or "",
        "skill_count": skill_count,
    }


def _is_stale(row: SkillSource, now: datetime | None = None) -> bool:
    now = now or _utcnow()
    if row.last_fetched_at is None:
        return True
    elapsed = (now - row.last_fetched_at).total_seconds()
    return elapsed > float(settings.skill_catalog_ttl_seconds)


# ---------------------------------------------------------------- 源同步核心
async def _sync_source(db, row: SkillSource) -> dict:
    """同步单个源（在调用方事务/会话内执行），更新 fetch_error 与 last_fetched_at。

    返回 {ok, error, skill} 供前端即时反馈。
    """
    try:
        latest = await catalog.fetch_source_latest(row.source_key, settings.github_token)
    except (catalog.GitHubSourceError, SkillError) as e:
        row.fetch_error = str(e)[:500]
        row.last_fetched_at = _utcnow()
        await db.commit()
        log.warning("[技能源] 同步失败 %s: %s", row.source_key, e)
        return {"ok": False, "error": str(e), "skill": None}

    # upsert 市场快照（slug 唯一；install_count 为累计安装次数，同步绝不覆盖）
    skill = (await db.execute(select(Skill).where(Skill.slug == latest["slug"]))).scalar_one_or_none()
    if skill is None:
        skill = Skill(slug=latest["slug"], install_count=0)
        db.add(skill)
    for field, col in (
        ("name", "name"), ("version", "version"), ("description", "description"),
        ("author", "author"), ("emoji", "emoji"), ("category", "category"),
        ("homepage", "homepage"), ("has_cli", "has_cli"), ("source_key", "source_key"),
        ("artifact_url", "artifact_url"), ("release_url", "release_url"),
        ("asset_size", "asset_size"),
    ):
        setattr(skill, col, latest[field])
    skill.updated_at = _utcnow()

    row.fetch_error = ""
    row.last_fetched_at = _utcnow()
    await db.commit()
    await db.refresh(skill)
    log.info("[技能源] 同步成功 %s → %s v%s", row.source_key, skill.slug, skill.version)
    return {"ok": True, "error": "", "skill": _skill_dict(skill)}


async def _background_refresh_stale() -> None:
    """后台刷新所有「已启用且超过 TTL 未同步」的源。

    - 用 Redis SET NX 锁保证多副本只同步一次（锁 EX=TTL+60s）；
    - 单源失败仅记录 fetch_error，不阻断其它源。
    """
    global _last_scan_at
    try:
        redis = get_redis()
        acquired_scan = await redis.set("skill:scan", "1", nx=True, ex=120)
        if not acquired_scan:
            return
    except Exception as e:  # noqa: BLE001 - Redis 不可用时降级：仍执行（会因无锁多副本并发，可接受）
        log.warning("[技能源] Redis 扫描锁不可用：%s", e)
    try:
        async with SessionLocal() as db:
            rows = (await db.execute(
                select(SkillSource).where(SkillSource.enabled.is_(True))
            )).scalars().all()
            for row in rows:
                if not _is_stale(row):
                    continue
                try:
                    redis = get_redis()
                    locked = await redis.set(f"skill:sync:{row.id}", "1", nx=True, ex=3600)
                    if not locked:
                        continue  # 其它副本正在同步本源
                except Exception:  # noqa: BLE001
                    pass
                await _sync_source(db, row)
    except Exception as e:  # noqa: BLE001
        log.exception("[技能源] 后台刷新异常: %s", e)
    finally:
        _last_scan_at = asyncio.get_event_loop().time()


async def _maybe_spawn_refresh() -> None:
    """GET 类请求入口节流：同一实例 60s 内最多扫一次 stale 源。"""
    global _last_scan_at
    if _last_scan_at and asyncio.get_event_loop().time() - _last_scan_at < 60:
        return
    async with _refresh_lock:
        if _last_scan_at and asyncio.get_event_loop().time() - _last_scan_at < 60:
            return
        _last_scan_at = asyncio.get_event_loop().time()
        asyncio.create_task(_background_refresh_stale())


# ---------------------------------------------------------------- 请求体
class SourceIn(BaseModel):
    input: str                       # GitHub 仓库地址 / owner/repo / gh:owner/repo
    label: str = ""


class SourcePatch(BaseModel):
    enabled: bool | None = None
    label: str | None = None


# ---------------------------------------------------------------- 源管理
@router.get("/sources")
async def list_sources(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.execute(select(SkillSource).order_by(SkillSource.id))).scalars().all()
    counts = dict((await db.execute(
        select(Skill.source_key, func.count(Skill.id)).group_by(Skill.source_key)
    )).all())
    await _maybe_spawn_refresh()
    return {"sources": [_source_dict(r, counts.get(r.source_key, 0)) for r in rows]}


@router.post("/sources")
async def add_source(body: SourceIn, user=Depends(get_current_user), db=Depends(get_db)):
    try:
        key = catalog.normalize_source_input(body.input)
    except catalog.GitHubSourceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    row = (await db.execute(select(SkillSource).where(SkillSource.source_key == key))).scalar_one_or_none()
    if row is None:
        row = SkillSource(source_key=key, kind="github")
        db.add(row)
    row.enabled = True
    if body.label.strip():
        row.label = body.label.strip()[:120]
    row.url = catalog.source_url(key)
    row.fetch_error = ""
    await db.commit()
    await db.refresh(row)
    # 立即同步一次，让用户当场看到结果（失败会在 fetch_error 呈现，不返回 4xx）
    result = await _sync_source(db, row)
    counts = dict((await db.execute(
        select(Skill.source_key, func.count(Skill.id)).group_by(Skill.source_key)
    )).all())
    return {"source": _source_dict(row, counts.get(key, 0)), "sync": result}


@router.patch("/sources/{source_id}")
async def patch_source(
    source_id: int, body: SourcePatch, user=Depends(get_current_user), db=Depends(get_db)
):
    row = (await db.execute(select(SkillSource).where(SkillSource.id == source_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="技能源不存在")
    if body.enabled is not None:
        row.enabled = bool(body.enabled)
        if body.enabled:
            row.fetch_error = ""
    if body.label is not None:
        row.label = body.label.strip()[:120]
    await db.commit()
    return {"ok": True}


@router.delete("/sources/{source_id}")
async def delete_source(source_id: int, user=Depends(get_current_user), db=Depends(get_db)):
    row = (await db.execute(select(SkillSource).where(SkillSource.id == source_id))).scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="技能源不存在")
    removed_skills = (await db.execute(
        delete(Skill).where(Skill.source_key == row.source_key).returning(Skill.slug)
    )).all()
    await db.execute(delete(SkillSource).where(SkillSource.id == source_id))
    await db.commit()
    log.info("[技能源] 删除源 %s，清理市场快照 %s 个技能", row.source_key, len(removed_skills))
    # 已安装技能的快照仍在 installed_skills 与磁盘，不受影响
    return {"ok": True, "removed_skills": [r[0] for r in removed_skills]}


@router.post("/sync")
async def sync_all(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.execute(select(SkillSource).where(SkillSource.enabled.is_(True)))).scalars().all()
    results = []
    for row in rows:
        results.append(await _sync_source(db, row))
    ok_count = sum(1 for r in results if r["ok"])
    return {"ok": True, "total": len(results), "success": ok_count, "results": results}


# ---------------------------------------------------------------- 市场浏览
async def _installed_slugs(db, user_id: str) -> set[str]:
    rows = (await db.execute(
        select(InstalledSkill.slug).where(InstalledSkill.user_id == user_id)
    )).scalars().all()
    return set(rows)


@router.get("/market")
async def list_market(
    search: str = "",
    category: str = "",
    user=Depends(get_current_user),
    db=Depends(get_db),
):
    await _maybe_spawn_refresh()
    installed = await _installed_slugs(db, user["sub"])
    stmt = select(Skill)
    if category and category != "全部":
        stmt = stmt.where(Skill.category == category)
    if search and search.strip():
        kw = f"%{search.strip()}%"
        stmt = stmt.where(
            (Skill.name.ilike(kw)) | (Skill.slug.ilike(kw)) | (Skill.description.ilike(kw))
        )
    stmt = stmt.order_by(Skill.install_count.desc(), Skill.name.asc())
    skills = (await db.execute(stmt)).scalars().all()
    return {"skills": [_skill_dict(s, s.slug in installed) for s in skills]}


@router.get("/categories")
async def list_categories(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.execute(select(Skill.category).distinct())).scalars().all()
    cats = [c for c in rows if c]
    return {"categories": ["全部", *cats]}


# ---------------------------------------------------------------- 我的技能
@router.get("/installed")
async def list_installed(user=Depends(get_current_user), db=Depends(get_db)):
    rows = (await db.execute(
        select(InstalledSkill)
        .where(InstalledSkill.user_id == user["sub"])
        .order_by(InstalledSkill.installed_at.desc())
    )).scalars().all()
    return {"skills": [_installed_dict(s) for s in rows]}


# ---------------------------------------------------------------- 安装 / 卸载
async def _ensure_slug(slug: str) -> str:
    import re
    if not re.match(r"^[a-z0-9][a-z0-9-]{0,62}$", slug or ""):
        raise HTTPException(status_code=400, detail="slug 不合法")
    return slug


@router.post("/{slug}/install")
async def install_skill(slug: str, user=Depends(get_current_user), db=Depends(get_db)):
    slug = await _ensure_slug(slug)
    user_id = user["sub"]

    async with get_lock(f"skill:install:{slug}"):
        skill = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
        if not skill:
            raise HTTPException(
                status_code=404,
                detail="该技能不在市场快照中。请先在「技能源」添加其发布仓库并完成同步。",
            )

        is_local = skill.source_key == "local"

        # 本地技能：文件已在磁盘（由 install_skill.py 预置），直接登记，无需下载
        if is_local:
            skill_dir = Path(settings.skills_root) / slug
            if not skill_dir.is_dir():
                # 尝试从项目根目录的 data/skills 找本地技能（开发阶段技能包直接放在 data/skills/）
                alt_dir = Path(settings.skills_root).parent / "skills" / slug
                if alt_dir.is_dir():
                    skill_dir = alt_dir
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"本地技能文件缺失：{skill_dir}。请联系管理员运行 install_skill.py。",
                    )
            try:
                manifest = load_manifest(skill_dir)
            except (SkillError, OSError) as e:
                raise HTTPException(status_code=400, detail=f"技能清单读取失败：{e}") from e
        else:
            # 远程技能：下载 → 校验解压 → 原子落盘
            if not skill.artifact_url:
                raise HTTPException(
                    status_code=404,
                    detail="该技能不在市场快照中。请先在「技能源」添加其发布仓库并完成同步。",
                )
            try:
                data = await catalog.download_artifact(skill.artifact_url, settings.github_token)
                manifest, _dest = install_zip_bytes(settings.skills_root, data)
            except (catalog.GitHubSourceError, SkillError, OSError) as e:
                msg = str(e)[:2000]
                inst = (await db.execute(
                    select(InstalledSkill).where(
                        InstalledSkill.user_id == user_id, InstalledSkill.slug == slug
                    )
                )).scalar_one_or_none()
                if inst is None:
                    inst = InstalledSkill(user_id=user_id, slug=slug)
                    db.add(inst)
                inst.status = "failed"
                inst.error = msg
                inst.source_key = skill.source_key
                inst.updated_at = _utcnow()
                await db.commit()
                log.error("[技能] 安装失败 %s (user=%s): %s", slug, user_id, msg)
                raise HTTPException(status_code=400, detail=f"技能安装失败：{msg}") from e

        existed = (await db.execute(
            select(InstalledSkill).where(
                InstalledSkill.user_id == user_id, InstalledSkill.slug == slug
            )
        )).scalar_one_or_none()
        is_upgrade = existed is not None and existed.status == "ok"
        if existed is None:
            existed = InstalledSkill(user_id=user_id, slug=slug)
            db.add(existed)
        existed.name = manifest.name
        existed.version = manifest.version
        existed.description = manifest.description
        existed.emoji = manifest.emoji
        existed.category = manifest.category
        existed.source_key = skill.source_key
        existed.status = "ok"
        existed.error = ""
        existed.updated_at = _utcnow()
        if not is_upgrade:
            skill.install_count = (skill.install_count or 0) + 1
            skill.updated_at = _utcnow()
        await db.commit()
        await db.refresh(existed)
        log.info("[技能] %s %s v%s (user=%s)", "升级" if is_upgrade else "安装", slug, manifest.version, user_id)
        return {
            "ok": True,
            "upgrade": is_upgrade,
            "installed": _installed_dict(existed),
            "entry": manifest.entry,
            "has_cli": manifest.has_cli,
        }


@router.post("/{slug}/uninstall")
async def uninstall_skill(slug: str, user=Depends(get_current_user), db=Depends(get_db)):
    slug = await _ensure_slug(slug)
    user_id = user["sub"]
    inst = (await db.execute(
        select(InstalledSkill).where(
            InstalledSkill.user_id == user_id, InstalledSkill.slug == slug
        )
    )).scalar_one_or_none()
    if not inst:
        raise HTTPException(status_code=404, detail="尚未安装该技能")
    await db.execute(delete(InstalledSkill).where(InstalledSkill.id == inst.id))
    # 全局安装计数 -1（不小于 0）
    skill = (await db.execute(select(Skill).where(Skill.slug == slug))).scalar_one_or_none()
    if skill and (skill.install_count or 0) > 0:
        skill.install_count -= 1
        skill.updated_at = _utcnow()
    await db.commit()

    # 磁盘/市场策略（技能代码绝不因卸载而删除）：
    # - 本地技能（source_key=local）：代码包是 data/skills 下的内置技能源码，卸载只移除
    #   当前用户的安装记录 → 前端对话任务立即消失；磁盘文件与市场快照原样保留，
    #   重新点击「安装」即可再次使用（支持多人分别安装/卸载互不影响）。
    # - 远程技能：仅当平台再无任何用户安装时才清理其下载副本，释放磁盘；
    #   市场快照仍保留（来源同步可随时重装）。
    still_used = (await db.execute(
        select(InstalledSkill.id).where(InstalledSkill.slug == slug).limit(1)
    )).scalar_one_or_none()
    if still_used is None and skill is not None and skill.source_key != "local":
        try:
            remove_skill(settings.skills_root, slug)
        except OSError as e:
            log.warning("[技能] 卸载时清理下载副本失败 %s: %s", slug, e)

    log.info("[技能] 卸载 %s (user=%s)", slug, user_id)
    return {"ok": True}
