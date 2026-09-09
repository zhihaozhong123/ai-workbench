"""XST-Skill 技能包契约。

权威元数据 = 技能仓库根 `manifest.json`（本 schema，见 ``SKILL_SCHEMA_VERSION``）；
若缺失，则兼容回退读取 skill-template 产物的 ``SKILL.md`` frontmatter
（name/description/version/author + metadata.openclaw 下的 slug/emoji/category），
从而让用 skill-template 写好的技能无需改动即可被识别、打包与安装。

- ``load_manifest(skill_root)``：从技能目录加载并校验，返回 :class:`SkillManifest`。
- ``to_catalog()``：市场展示快照（不含 system_prompt，避免大文本进 Redis/DB）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SKILL_SCHEMA_VERSION = 1
MANIFEST_FILE = "manifest.json"
SKILL_MD_FILE = "SKILL.md"

_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class SkillError(ValueError):
    """技能包格式/校验错误（携带面向用户的中文信息）。"""


# ---------------------------------------------------------------- helpers
def _pick(d: dict, *paths: str, default: Any = None) -> Any:
    """按嵌套路径取字段（如 ('metadata', 'openclaw', 'slug')）。"""
    for path in paths:
        cur = d
        ok = True
        for key in path.split("."):
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and cur is not None:
            return cur
    return default


def _req_str(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillError(f"技能包缺少必填字段: {label}")
    return value.strip()


def _validate_slug(slug: str) -> str:
    slug = slug.strip().lower()
    if not _SLUG_RE.match(slug):
        raise SkillError(
            f"slug 不合法: {slug!r}。slug 仅允许小写字母/数字/中划线，"
            "且须以字母或数字开头结尾。"
        )
    return slug


def _validate_version(version: str) -> str:
    version = version.strip()
    if not _VERSION_RE.match(version):
        raise SkillError(f"version 不合法: {version!r}，须为语义化版本 x.y.z（如 1.0.0）")
    return version


# ---------------------------------------------------------------- dataclass
@dataclass
class SkillManifest:
    """规范化后的技能元数据（已校验）。

    ``system_prompt`` 在加载技能目录时解析（若声明 ``system_prompt_file``，
    会读取该文件内容合并进来；仅存文件名时留待安装目录读取时再拼装）。
    """

    slug: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    emoji: str = ""
    category: str = ""
    homepage: str = ""
    entry: str | None = None          # 技能 CLI 入口（相对技能根，如 scripts/main.py）
    cli: str | None = None            # CLI 子命令（如 run）
    env_whitelist: list[str] = field(default_factory=list)
    timeout_seconds: float | None = None
    permissions: list[str] = field(default_factory=list)
    min_app_version: str = ""
    system_prompt: str = ""           # 注入 Agent 的提示词（内联 + 可选文件内容）
    has_cli: bool = False

    # ---------- 市场快照 ----------
    def to_catalog(self, source: str = "", install_count: int = 0) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "emoji": self.emoji,
            "category": self.category,
            "homepage": self.homepage,
            "has_cli": self.has_cli,
            "source": source,
            "install_count": install_count,
        }


# ---------------------------------------------------------------- loaders
def _read_json_manifest(skill_root: Path) -> dict:
    try:
        raw = json.loads((skill_root / MANIFEST_FILE).read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        raise SkillError(f"manifest.json 解析失败: {e}") from e
    if not isinstance(raw, dict):
        raise SkillError("manifest.json 顶层必须是 JSON 对象")
    return raw


def parse_frontmatter(text: str) -> dict | None:
    """解析 Markdown 顶部的 ---frontmatter---，失败/缺失返回 None。"""
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    body = text[3:end].strip()
    try:
        data = yaml.safe_load(body)
    except Exception:  # noqa: BLE001 - 非本平台产物，容忍 frontmatter 解析失败
        return None
    return data if isinstance(data, dict) else None


def _extract_skillmd_body(raw: str) -> str:
    """提取 SKILL.md 中 frontmatter 之后的正文部分。"""
    if not raw.startswith("---"):
        return raw.strip()
    end = raw.find("\n---", 3)
    if end < 0:
        return ""
    return raw[end + 4:].strip()


def _read_skillmd_manifest(skill_root: Path) -> dict:
    """把 SKILL.md frontmatter 映射成与 manifest.json 等价的扁平 dict。

    同时提取 SKILL.md 正文作为 ``system_prompt``。若 frontmatter 声明了
    ``references`` 列表（编排型技能引用外部子技能文件），会读取每个引用
    文件的内容拼接到 ``system_prompt`` 末尾，实现"引用而非内联"。
    """
    md_file = skill_root / SKILL_MD_FILE
    if not md_file.exists():
        raise SkillError(
            f"不是有效的技能包：{skill_root.name} 目录下既没有 {MANIFEST_FILE} 也没有 {SKILL_MD_FILE}"
        )
    raw = md_file.read_text(encoding="utf-8")
    fm = parse_frontmatter(raw) or {}
    body = _extract_skillmd_body(raw)

    # 支持 references（编排型技能引用外部子技能文件）
    refs = _pick(fm, "references")
    if isinstance(refs, list) and refs:
        ref_parts = []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            ref_path_raw = ref.get("path", "")
            if not ref_path_raw:
                continue
            ref_path = (skill_root / ref_path_raw).resolve()
            if ref_path.is_file():
                ref_content = ref_path.read_text(encoding="utf-8").strip()
                # 去掉子技能自身的 frontmatter，只取正文
                ref_fm = parse_frontmatter(ref_content)
                if ref_fm is not None:
                    ref_content = _extract_skillmd_body(ref_content)
                section = ref.get("section") or ref_path_raw
                ref_parts.append(f"\n{'='*60}\n# 引用技能：{section}\n{'='*60}\n\n{ref_content}")
        if ref_parts:
            body = f"{body}\n\n{''.join(ref_parts)}" if body else "".join(ref_parts)

    result = {
        "slug": _pick(fm, "metadata.openclaw.slug", "metadata.slug", "slug"),
        "name": _pick(fm, "name"),
        "version": _pick(fm, "metadata.openclaw.version", "metadata.version", "version"),
        "description": _pick(fm, "description"),
        "author": _pick(fm, "author"),
        "emoji": _pick(fm, "metadata.openclaw.emoji", "metadata.emoji", "emoji"),
        "category": _pick(fm, "metadata.openclaw.category", "metadata.category", "category"),
        "homepage": _pick(fm, "homepage", "repository"),
        "system_prompt": body,
    }

    # 透传 permissions（local_control 等）
    perms = _pick(fm, "permissions")
    if isinstance(perms, list):
        result["permissions"] = perms

    # 透传 runtime（entry / cli / env_whitelist / timeout_seconds）
    runtime = _pick(fm, "runtime")
    if isinstance(runtime, dict):
        result["runtime"] = runtime

    return result


def _apply_defaults(m: dict) -> dict:
    m.setdefault("schema_version", SKILL_SCHEMA_VERSION)
    m.setdefault("description", "")
    m.setdefault("author", "")
    m.setdefault("emoji", "")
    m.setdefault("category", "通用")
    m.setdefault("homepage", "")
    m.setdefault("permissions", [])
    m.setdefault("min_app_version", "")
    return m


def build_manifest(data: dict, system_prompt_file_content: str = "") -> SkillManifest:
    """从（可能是 SKILL.md frontmatter 转来的）dict 校验并构建 SkillManifest。"""
    data = _apply_defaults(dict(data))
    schema_version = data.get("schema_version", SKILL_SCHEMA_VERSION)
    if int(schema_version) != SKILL_SCHEMA_VERSION:
        raise SkillError(
            f"不支持的技能包 schema_version={schema_version}（当前支持 {SKILL_SCHEMA_VERSION}）"
        )

    slug = _validate_slug(_req_str(data.get("slug"), "slug"))
    name = _req_str(data.get("name"), "name")
    version = _validate_version(_req_str(data.get("version"), "version"))

    runtime = data.get("runtime")
    runtime = runtime if isinstance(runtime, dict) else {}
    entry = runtime.get("entry") or data.get("entry")
    cli = runtime.get("cli") or data.get("cli") or "run"
    env_whitelist = runtime.get("env_whitelist") or data.get("env_whitelist") or []
    if not isinstance(env_whitelist, list) or not all(isinstance(e, str) for e in env_whitelist):
        raise SkillError("runtime.env_whitelist 必须是字符串数组")
    permissions = data.get("permissions") or []
    if not isinstance(permissions, list):
        raise SkillError("permissions 必须是数组")

    timeout = runtime.get("timeout_seconds") or data.get("timeout_seconds")
    try:
        timeout = float(timeout) if timeout else None
    except (TypeError, ValueError):
        raise SkillError("runtime.timeout_seconds 必须是数字（秒）") from None

    system_prompt = str(data.get("system_prompt") or "").strip()
    sp_file = data.get("system_prompt_file")
    if sp_file:
        content = (system_prompt_file_content or "").strip()
        if content:
            system_prompt = (
                f"{system_prompt}\n\n{content}".strip() if system_prompt else content
            )
        else:
            system_prompt = (
                f"{system_prompt}\n\n（技能说明见文件：{sp_file}）".strip()
                if system_prompt
                else f"（技能说明见文件：{sp_file}）"
            )

    return SkillManifest(
        slug=slug,
        name=name,
        version=version,
        description=str(data.get("description") or "").strip(),
        author=str(data.get("author") or "").strip(),
        emoji=str(data.get("emoji") or "").strip(),
        category=str(data.get("category") or "通用").strip(),
        homepage=str(data.get("homepage") or "").strip(),
        entry=str(entry).strip() if entry else None,
        cli=str(cli).strip() if cli else None,
        env_whitelist=list(env_whitelist),
        timeout_seconds=timeout,
        permissions=list(permissions),
        min_app_version=str(data.get("min_app_version") or "").strip(),
        system_prompt=system_prompt,
        has_cli=bool(entry),
    )


def load_manifest(skill_root: Path) -> SkillManifest:
    """从技能目录加载并校验清单。

    优先 manifest.json；缺失时回退读取 SKILL.md frontmatter。
    ``system_prompt_file`` 若声明且文件存在，内容会被读入 ``system_prompt``。
    """
    skill_root = Path(skill_root)
    if not skill_root.is_dir():
        raise SkillError(f"技能目录不存在: {skill_root}")

    manifest_file = skill_root / MANIFEST_FILE
    if manifest_file.exists():
        data = _read_json_manifest(skill_root)
    else:
        data = _read_skillmd_manifest(skill_root)

    sp_file_name = data.get("system_prompt_file") if isinstance(data, dict) else None
    sp_content = ""
    if isinstance(sp_file_name, str) and sp_file_name.strip():
        sp_path = skill_root / sp_file_name.strip()
        if sp_path.is_file():
            sp_content = sp_path.read_text(encoding="utf-8")
    return build_manifest(data, sp_content)


def safe_entry_path(skill_root: Path, entry: str | None) -> Path | None:
    """校验技能 CLI 入口位于技能根内（防目录穿越），返回绝对路径。"""
    if not entry:
        return None
    p = (Path(skill_root) / entry).resolve()
    root = Path(skill_root).resolve()
    if not p.is_relative_to(root):
        raise SkillError(f"技能入口越界（不允许指向技能目录之外）: {entry}")
    if not p.is_file():
        raise SkillError(f"技能入口文件不存在: {entry}")
    return p
