"""运行指标 —— 基于 prometheus_client，暴露 Prometheus exposition 文本供拉取。

覆盖可观测性最小集：进程级指标（CPU / 常驻内存 / python 版本等），
由 prometheus_client 内置收集器自动提供，无需手写埋点。

HTTP 端点：/metrics（Prometheus 文本）与 /metrics.json（人类可读摘要）。
"""
import time

from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest


def get_metrics_text() -> bytes:
    """返回 Prometheus exposition 格式指标文本（供 /metrics 拉取）。"""
    return generate_latest(REGISTRY)


def get_content_type() -> str:
    return CONTENT_TYPE_LATEST


def get_metrics() -> dict:
    """人类可读摘要（供 /metrics.json）：解析进程级通用指标。"""
    import re
    text = generate_latest(REGISTRY).decode()

    def _val(name: str) -> float:
        pat = re.compile(rf'^{re.escape(name)}(?:\{{[^}}]*\}})?\s+([-0-9.eE]+)$', re.M)
        m = pat.search(text)
        return float(m.group(1)) if m else 0.0

    start = _val("process_start_time_seconds")
    uptime = round(time.time() - start, 1) if start else None
    return {
        "process_cpu_seconds_total": round(_val("process_cpu_seconds_total"), 3),
        "process_resident_memory_bytes": int(_val("process_resident_memory_bytes")),
        "uptime_seconds": uptime,
    }
