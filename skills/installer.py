"""技能安装器：.xskill(zip 单文件) 下载校验、安全解压、落盘、卸载、替换升级。

安全要点：
- 逐条成员路径校验：解压目标规范化后必须位于技能根目录内（zip-slip 防护）；
- 拒绝符号链接成员（防解压后指向技能目录之外的链接）；
- 大小上限与 manifest 严格校验后才落盘；
- 安装到目标目录采用「临时目录 → 原子 replace」，中断不会留下半截技能。
"""
from __future__ import annotations

import io
import shutil
import tempfile
import zipfile
from pathlib import Path

from skills.manifest import MANIFEST_FILE, SKILL_MD_FILE, SkillError, load_manifest

# 单包体积上限（含脚本/文档）：50MB
MAX_XSKILL_BYTES = 50 * 1024 * 1024
_ARCHIVE_PREFIX = "xskill-"


def skill_dir(skills_root: Path, slug: str) -> Path:
    return (Path(skills_root) / slug).resolve()


def _reject_entry(info: zipfile.ZipInfo, root: Path) -> None:
    """校验单个 zip 成员安全；不安全直接抛 SkillError。"""
    filename = info.filename
    if filename.startswith(("/", "\\")) or ":" in filename.split("/")[0]:
        raise SkillError(f"技能包包含非法路径成员: {filename}")
    # 路径穿越（.. 段）
    norm = Path(filename)
    if any(part == ".." for part in norm.parts):
        raise SkillError(f"技能包包含目录穿越成员: {filename}")
    # 符号链接成员（Unix 外部属性为 S_IFLNK）
    mode = (info.external_attr >> 16) & 0xFFFF
    if mode == 0xA000 or (info.external_attr >> 16) & 0o170000 == 0o120000:
        raise SkillError(f"技能包不允许包含符号链接: {filename}")
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise SkillError(f"技能包成员越界: {filename}")


def _extract_safe(zf: zipfile.ZipFile, root: Path) -> None:
    # 先 resolve：macOS 的 /var、/tmp 等可能是符号链接（/var→/private/var），
    # 若不规范化，「目标在 root 内」的词法前缀判断会把合法成员误判为越界（zip-slip）。
    root = root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        _reject_entry(info, root)
    zf.extractall(root)  # 已全部校验过，安全


def _locate_content_root(tmp: Path) -> Path:
    """定位技能内容根：manifest.json/SKILL.md 位于顶层，或位于唯一的顶层子目录。"""
    if (tmp / MANIFEST_FILE).exists() or (tmp / SKILL_MD_FILE).exists():
        return tmp
    children = [p for p in tmp.iterdir() if p.is_dir()]
    for child in children:
        if (child / MANIFEST_FILE).exists() or (child / SKILL_MD_FILE).exists():
            return child
    raise SkillError(
        "技能包内找不到 manifest.json 或 SKILL.md（技能包结构不完整）"
    )


def install_zip_bytes(skills_root: Path, data: bytes) -> tuple:
    """下载内容 → 校验 → 原子落盘为 <skills_root>/<slug>/。

    返回 (SkillManifest, 安装目录 Path)。若该 slug 已存在（升级/重装），
    会先用新包原子替换旧目录（调用方应先在 DB 里确认版本与覆盖策略）。
    """
    skills_root = Path(skills_root)
    if not data:
        raise SkillError("技能包为空")
    if len(data) > MAX_XSKILL_BYTES:
        raise SkillError(f"技能包超过大小上限 {MAX_XSKILL_BYTES // (1024 * 1024)}MB")

    tmp = Path(tempfile.mkdtemp(prefix=_ARCHIVE_PREFIX))
    try:
        try:
            zf = zipfile.ZipFile(io.BytesIO(data))
            if zf.testzip() is not None:
                raise SkillError("技能包 zip 校验失败（文件损坏）")
            _extract_safe(zf, tmp)
        except zipfile.BadZipFile as e:
            raise SkillError(f"不是有效的 .xskill 技能包: {e}") from e

        content_root = _locate_content_root(tmp)
        manifest = load_manifest(content_root)  # 校验 manifest + 入口存在性在下方做

        skills_root.mkdir(parents=True, exist_ok=True)
        dest = skill_dir(skills_root, manifest.slug)
        staging = dest.parent / f".staging-{manifest.slug}-{manifest.version}"

        # 目标落盘 + 原子替换
        shutil.rmtree(staging, ignore_errors=True)
        shutil.move(str(content_root), str(staging))
        if dest.exists():
            shutil.rmtree(dest)
        staging.replace(dest)

        # 落盘后再做最终校验（含 CLI 入口存在性）
        final = load_manifest(dest)
        return final, dest
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove_skill(skills_root: Path, slug: str) -> None:
    """删除已安装技能目录（卸载）。不存在时静默成功。"""
    dest = skill_dir(skills_root, slug)
    if dest.exists():
        shutil.rmtree(dest)
