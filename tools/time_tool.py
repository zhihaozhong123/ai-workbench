"""
时间工具 - 获取当前日期时间
"""
from datetime import datetime
from langchain_core.tools import tool


@tool
def get_current_time() -> str:
    """获取当前日期和时间，返回格式化的时间字符串。"""
    now = datetime.now()
    weekday_cn = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"当前时间: {now.strftime('%Y年%m月%d日 %H:%M:%S')} {weekday_cn[now.weekday()]}"
