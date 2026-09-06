"""审计日志：把敏感操作写到独立的 ``audit`` logger。

生产（logging_config 的 JSON 格式）下输出结构化 JSON，便于 Loki/ELK 集中收集与告警；
本地（文本格式）下输出可读行。不落数据库表，避免表膨胀，且多实例各自输出由
日志系统统一聚合。
"""
import logging

audit_log = logging.getLogger("audit")


def log_audit(user_id: str | None, action: str, target: str = "",
              detail: str = "", ip: str = ""):
    """记录一条审计事件。

    action 取值示例：login / register / logout / skill_install / skill_uninstall / chat。
    """
    audit_log.info(
        "action=%s user=%s target=%s detail=%s ip=%s",
        action, user_id or "-", target, detail, ip,
    )
