"""结构化日志配置 —— 便于集中收集（JSON 输出到 stdout，由 Loki/ELK/Vector 等采集）。

设计：
- dev（默认，本地桌面）：可读文本，方便调试。
- production / 配了 DATABASE_URL：单行 JSON，字段固定（ts/level/logger/msg/位置），
  便于日志系统按字段检索与告警，无需改动应用即可接采集 agent。
通过环境变量覆盖：LOG_LEVEL（默认 INFO）、LOG_FORMAT（json|text，默认随环境推导）。
"""
import json
import logging
import sys
from datetime import datetime, timezone

from config import settings


class JSONFormatter(logging.Formatter):
    """单行 JSON 日志，机器可解析，方便集中收集与按字段过滤。"""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "lineno": record.lineno,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str | None = None, fmt: str | None = None) -> None:
    """配置根日志（含 uvicorn/fastapi 日志）统一输出到 stdout。

    LOG_LEVEL / LOG_FORMAT 从 .env 读取（config.settings），无代码默认值。
    """
    lvl = (level or settings.log_level).upper()

    out_fmt = (fmt or settings.log_format).lower()

    handler = logging.StreamHandler(sys.stdout)
    if out_fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"))

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(lvl)

    # uvicorn / fastapi 自身日志也统一到同一 handler，避免双份输出与格式不一致
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi"):
        lg = logging.getLogger(name)
        lg.handlers = [handler]
        lg.setLevel(lvl)
        lg.propagate = False


def get_logger(name: str) -> logging.Logger:
    """获取命名 logger（与标准 logging 一致，仅统一入口便于使用）。"""
    return logging.getLogger(name)
