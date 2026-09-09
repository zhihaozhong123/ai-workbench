"""技能 CLI 子进程隔离执行器。

契约（XST-Skill CLI v1）：
- 平台以 ``python -u <entry> <cli>`` 启动技能进程，cwd=技能目录；
- 参数以 JSON 经 stdin 传入：``{"params": {...}}``；
- 结果以单行 JSON 经 stdout 返回：``{"ok": true, "data": {...}}``
  或 ``{"ok": false, "error": "..."}``；
- 退出码非 0 / 超时 / 输出非法 → 视为技能执行失败，返回结构化错误。

隔离与资源保护：
- 全局分布式信号量 ``skills_run``（Redis）限制并发子进程数；
- 单个调用超时上限（manifest 或配置），到点 kill；
- env 白名单注入：仅透传技能声明的宿主环境变量（如 API Key），
  平台其它密钥（DeepSeek / 百炼等）绝不进入子进程。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from config import settings
import logging
from skills.manifest import SkillManifest, SkillError, safe_entry_path

log = logging.getLogger(__name__)

# 子进程基础环境白名单：仅这些系统变量 + 技能 manifest 声明的 env_whitelist
_BASE_ENV_KEYS = (
    "PATH", "HOME", "TMPDIR", "LANG", "LC_ALL", "LC_CTYPE",
    "TZ", "LOGNAME", "USER", "SHELL", "TERM",
)
_MAX_STDERR_BYTES = 4096


def _build_env(manifest: SkillManifest, user_id: str) -> dict:
    env = {k: v for k, v in os.environ.items() if k in _BASE_ENV_KEYS}
    env["PYTHONIOENCODING"] = "utf-8"
    env["XST_SKILL_SLUG"] = manifest.slug
    if user_id:
        env["XST_USER_ID"] = user_id
    # 仅透传技能声明需要的宿主环境变量（.env 中已 load 到进程环境）
    for key in manifest.env_whitelist:
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def _error(message: str, detail: str = "") -> dict:
    err = f"[技能错误] {message}".strip()
    if detail:
        err = f"{err}\n{detail}"
    return {"ok": False, "error": err}


async def run_skill_cli(
    skill_dir: Path,
    manifest: SkillManifest,
    params: dict,
    user_id: str = "",
) -> dict:
    """执行技能 CLI 一次调用，返回标准化结果 dict。"""
    if not manifest.has_cli or not manifest.entry:
        return {"ok": False, "error": "[技能错误] 该技能未声明可执行工具（无 CLI）"}
    try:
        entry = safe_entry_path(skill_dir, manifest.entry)
    except SkillError as e:
        return {"ok": False, "error": str(e)}

    timeout = float(manifest.timeout_seconds or settings.skill_exec_timeout_seconds)
    payload = json.dumps({"params": params or {}}, ensure_ascii=False)

    try:
        # 延迟导入：避免在无 Redis 的纯构建/校验流程里触发连接初始化
        from infra.state_store import get_semaphore
    except Exception as e:  # noqa: BLE001
        log.warning("技能执行信号量不可用（将无并发上限执行）: %s", e)
        get_semaphore = None

    async def _run() -> dict:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-u", str(entry), str(manifest.cli or "run"),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(Path(skill_dir).resolve()),
            env=_build_env(manifest, user_id),
        )
        try:
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(payload.encode("utf-8")), timeout=timeout
                )
            except (asyncio.TimeoutError, TimeoutError):
                proc.kill()
                try:
                    await proc.wait()
                except Exception:  # noqa: BLE001
                    pass
                return _error(f"技能执行超时（>{int(timeout)}s 已终止）")
        finally:
            if proc.returncode is None:  # 兜底
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass

        if proc.returncode != 0:
            detail = (err or b"").decode("utf-8", "replace")[:_MAX_STDERR_BYTES]
            return _error(f"技能进程退出码 {proc.returncode}", detail)
        try:
            result = json.loads((out or b"{}").decode("utf-8", "replace").strip() or "{}")
        except ValueError as e:
            return _error("技能输出不是合法 JSON", str(e))
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            return _error("技能返回结构不合法（须为 {\"ok\": bool, ...}）")
        return result

    if get_semaphore is not None:
        sem = get_semaphore("skills_run", int(settings.skill_exec_max_concurrency))
        async with sem:
            return await _run()
    return await _run()
