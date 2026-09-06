"""技能源目录同步（GitHub Releases 上游）。

职责：
- 技能源 key 规范化：接受 ``gh:owner/repo`` / ``owner/repo`` / GitHub 仓库 URL；
- 从 GitHub Releases 拉取「最新一个含 .xskill 资产」的版本，并读取仓库根的
  ``manifest.json``（缺失时回退 ``SKILL.md`` frontmatter）得到权威技能元数据；
- 返回结构化快照（含 .xskill 下载地址），由 api/routes_skills.py 负责写库。

限流与健壮性：
- GitHub 匿名 API 配额 60 次/时/IP，全部由上层 Redis TTL / DB last_fetched 缓存规避；
- 仓库不可达 / 无技能发布 / manifest 非法等错误都被归类并带中文说明返回，
  单源失败不影响其它源与平台整体。
"""
from __future__ import annotations

import re
import urllib.parse
from typing import Any

import httpx
import yaml

from observability.logging_config import get_logger
from skills.manifest import SkillError, build_manifest, parse_frontmatter

log = get_logger(__name__)

# .xskill 资产文件名规则：skill-<slug>-<version>.xskill
_XSKILL_RE = re.compile(r"\.xskill$", re.IGNORECASE)
_GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

_RAW_TIMEOUT = httpx.Timeout(15.0)


class GitHubSourceError(Exception):
    """技能源错误（面向用户的中文信息）。"""


# ---------------------------------------------------------------- 输入规范化
def normalize_source_input(raw: str) -> str:
    """把用户输入归一化为 skill_sources.source_key（gh:owner/repo）。

    支持：``gh:owner/repo`` / ``owner/repo`` / ``https://github.com/owner/repo`` /
    ``git@github.com:owner/repo.git`` 等。
    """
    text = (raw or "").strip().rstrip("/")
    if not text:
        raise GitHubSourceError("技能源不能为空")
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", text)
    if m:
        owner_repo = m.group(1)
    elif text.startswith("gh:"):
        owner_repo = text[3:]
    else:
        owner_repo = text
    owner_repo = owner_repo.removesuffix(".git")
    if not _GITHUB_REPO_RE.match(owner_repo):
        raise GitHubSourceError(
            "技能源格式无法识别：支持 GitHub 仓库地址（https://github.com/owner/repo）、"
            "owner/repo 或 gh:owner/repo"
        )
    owner, repo = owner_repo.split("/", 1)
    if not owner or not repo:
        raise GitHubSourceError("仓库名不完整（缺少 owner 或 repo）")
    return f"gh:{owner}/{repo}"


def source_key_parts(source_key: str) -> tuple[str, str]:
    owner_repo = source_key.removeprefix("gh:")
    owner, _, repo = owner_repo.partition("/")
    if not owner or not repo:
        raise GitHubSourceError(f"技能源不合法: {source_key}")
    return owner, repo


def source_url(source_key: str) -> str:
    owner, repo = source_key_parts(source_key)
    return f"https://github.com/{owner}/{repo}"


# ---------------------------------------------------------------- GitHub 拉取
def _headers(token: str = "") -> dict:
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "ai-workbench-skill-catalog/2.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


async def _api_get(client: httpx.AsyncClient, url: str, token: str) -> httpx.Response:
    resp = await client.get(url, headers=_headers(token))
    if resp.status_code == 404:
        raise GitHubSourceError("仓库不存在、无权限访问，或该地址不是 GitHub 仓库")
    if resp.status_code == 403:
        remaining = resp.headers.get("X-RateLimit-Remaining")
        log.warning("[技能源] GitHub 限流触发(剩余 %s)，请配置 GH_TOKEN 提升配额", remaining)
        raise GitHubSourceError(
            "GitHub API 触发限流（匿名 60 次/时已用尽）。请在服务器 .env 配置 "
            "GH_TOKEN 后重启，或稍后再同步。"
        )
    if resp.status_code != 200:
        raise GitHubSourceError(f"GitHub API 请求失败 HTTP {resp.status_code}")
    return resp


def _pick_latest_xskill_release(releases: list[dict]) -> dict | None:
    """在 release 列表里挑「最新一个发布（含 .xskill 资产）」的 release。"""
    for rel in releases:
        if rel.get("draft"):
            continue
        if not rel.get("assets"):
            continue
        if any(_XSKILL_RE.search(a.get("name", "")) for a in rel["assets"]):
            return rel
    return None


async def _fetch_manifest_meta(
    client: httpx.AsyncClient, owner: str, repo: str, branch: str
) -> dict | None:
    """读取仓库根 manifest.json / SKILL.md，返回可用于 build_manifest 的原始 dict。"""
    manifest_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/manifest.json"
    resp = await client.get(manifest_url, headers=_headers())
    if resp.status_code == 200:
        try:
            data = resp.json()
        except ValueError as e:
            raise GitHubSourceError(f"manifest.json 不是合法 JSON: {e}") from e
        if isinstance(data, dict):
            return data

    skillmd_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/SKILL.md"
    resp = await client.get(skillmd_url, headers=_headers())
    if resp.status_code == 200:
        fm = parse_frontmatter(resp.text)
        if fm:
            return {
                "slug": _deep(fm, "metadata.openclaw.slug", "metadata.slug", "slug"),
                "name": _deep(fm, "name"),
                "version": _deep(fm, "metadata.openclaw.version", "metadata.version", "version"),
                "description": _deep(fm, "description"),
                "author": _deep(fm, "author"),
                "emoji": _deep(fm, "metadata.openclaw.emoji", "metadata.emoji", "emoji"),
                "category": _deep(fm, "metadata.openclaw.category", "metadata.category", "category"),
                "homepage": _deep(fm, "homepage"),
            }
    return None


def _deep(data: dict, *paths: str) -> Any:
    for path in paths:
        cur = data
        ok = True
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur is not None:
            return cur
    return None


async def fetch_source_latest(source_key: str, token: str = "") -> dict:
    """拉取某个技能源的最新发布信息。

    返回 dict：
        {source_key, slug, name, version, description, author, emoji, category,
         homepage, has_cli, artifact_url, release_url, asset_size, asset_name,
         default_branch}
    失败抛 GitHubSourceError / SkillError。
    """
    owner, repo = source_key_parts(source_key)
    headers = _headers(token)
    async with httpx.AsyncClient(timeout=_RAW_TIMEOUT) as client:
        # 1) 仓库信息（拿默认分支）
        repo_resp = await _api_get(
            client, f"https://api.github.com/repos/{owner}/{repo}", token
        )
        repo_data = repo_resp.json()
        default_branch = repo_data.get("default_branch") or "main"

        # 2) 最新 release（含 .xskill 资产）
        rel_resp = await _api_get(
            client,
            f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=30",
            token,
        )
        release = _pick_latest_xskill_release(rel_resp.json())
        if not release:
            raise GitHubSourceError(
                f"仓库 {owner}/{repo} 还没有发布过技能包（.xskill）。\n"
                "发布流程：写完技能后执行 scripts/release_skill.sh 生成 GitHub Release 并附上 .xskill 资产。"
            )
        asset = next(
            a for a in release["assets"] if _XSKILL_RE.search(a.get("name", ""))
        )

        # 3) 仓库根 manifest.json（权威）→ SKILL.md frontmatter 兜底
        meta = await _fetch_manifest_meta(client, owner, repo, default_branch)
        if meta is None:
            raise GitHubSourceError(
                f"仓库 {owner}/{repo} 缺少 manifest.json（或带 frontmatter 的 SKILL.md），无法识别技能元数据"
            )

        tag = release.get("tag_name", "")
        if not meta.get("version") and tag:
            meta["version"] = tag.removeprefix("v")
        if not meta.get("name"):
            meta["name"] = repo
        if not meta.get("homepage"):
            meta["homepage"] = source_url(source_key)
        try:
            manifest = build_manifest(meta)
        except SkillError as e:
            raise GitHubSourceError(f"技能包元数据校验失败：{e}") from e

        return {
            "source_key": source_key,
            "slug": manifest.slug,
            "name": manifest.name,
            "version": manifest.version,
            "description": manifest.description,
            "author": manifest.author,
            "emoji": manifest.emoji,
            "category": manifest.category,
            "homepage": manifest.homepage,
            "has_cli": manifest.has_cli,
            "artifact_url": asset["browser_download_url"],
            "release_url": release["html_url"],
            "asset_size": int(asset.get("size") or 0),
            "asset_name": asset.get("name", ""),
            "default_branch": default_branch,
        }


# ---------------------------------------------------------------- 下载 .xskill
async def download_artifact(url: str, token: str = "", max_bytes: int = 50 * 1024 * 1024) -> bytes:
    """下载 .xskill 资产（带大小上限与流式读取，防大文件打爆内存）。"""
    headers = _headers(token)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=15.0)) as client:
        async with client.stream("GET", url, headers=headers, follow_redirects=True) as resp:
            if resp.status_code not in (200, 302):
                raise GitHubSourceError(f"下载技能包失败 HTTP {resp.status_code}")
            content_length = resp.headers.get("content-length")
            if content_length and int(content_length) > max_bytes:
                raise GitHubSourceError(f"技能包超过大小上限 {max_bytes // (1024 * 1024)}MB")
            chunks = []
            size = 0
            async for chunk in resp.aiter_bytes(chunk_size=256 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise GitHubSourceError(f"技能包超过大小上限 {max_bytes // (1024 * 1024)}MB")
                chunks.append(chunk)
            return b"".join(chunks)
