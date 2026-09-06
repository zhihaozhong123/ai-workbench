"""
联网搜索工具 - 使用 SerpAPI 搜索互联网
"""
import time
from langchain_core.tools import tool

from config import settings


@tool
def web_search(query: str) -> str:
    """搜索互联网获取最新信息。当用户询问实时新闻、最新事件、或本地知识库中没有的信息时使用。
    参数 query: 搜索关键词。
    """
    api_key = settings.serpapi_api_key
    if not api_key:
        return "[ERROR] 搜索工具不可用: 未配置 SERPAPI_API_KEY。请在 .env 中设置。"

    try:
        from serpapi import GoogleSearch

        params = {
            "q": query,
            "api_key": api_key,
            "num": 5,
            "hl": "zh-cn",
            "gl": "cn",
        }
        search = GoogleSearch(params)
        # 偶发网络/SSL 抖动（如 SSL UNEXPECTED_EOF）常导致单次失败，重试可恢复，
        # 避免一次抖动就向用户报“搜索出错 / 网络连接问题”。
        results = None
        last_err = None
        for _ in range(3):
            try:
                results = search.get_dict()
                break
            except Exception as e:
                last_err = e
                time.sleep(1)
        if results is None:
            return f"[ERROR] 搜索出错: {last_err}"

        # 结构化答案优先（天气/计算器/知识图谱等），直接返回核心信息，无需再翻网页
        answer_box = results.get("answer_box") or {}
        atype = answer_box.get("type")
        if atype == "weather_result":
            w = answer_box
            lines = [f"📍 {w.get('location', '')} 天气实况:"]
            unit = (w.get("unit") or "Celsius")[:1]
            lines.append(f"  🌤 天气: {w.get('weather', '')}  {w.get('temperature', '')}°{unit}")
            lines.append(f"  🌧 降水: {w.get('precipitation', '')}   💧 湿度: {w.get('humidity', '')}   🍃 风: {w.get('wind', '')}")
            fc = w.get("forecast") or []
            if fc:
                lines.append("  📅 未来几天:")
                for d in fc[:5]:
                    t = d.get("temperature", {})
                    lines.append(f"    · {d.get('day', '')}: {d.get('weather', '')} {t.get('high', '')}/{t.get('low', '')}°{unit}")
            return "\n".join(lines)
        # 其他类型的 answer_box（如计算器结果、知识卡片）也尽量提炼出来
        ab_title = answer_box.get("title") or answer_box.get("result") or answer_box.get("answer")
        if ab_title:
            ab_snippet = answer_box.get("snippet", "")
            return f"【{ab_title}】{ab_snippet}".strip()

        organic = results.get("organic_results", [])
        if not organic:
            return f"未找到关于「{query}」的搜索结果。"

        lines = [f"关于「{query}」的搜索结果:"]
        for i, r in enumerate(organic[:5], 1):
            title = r.get("title", "无标题")
            snippet = r.get("snippet", "")
            link = r.get("link", "")
            lines.append(f"\n{i}. {title}\n   {snippet}\n   🔗 {link}")

        result = "\n".join(lines)
        # 截断过长内容，避免搜索结果撑爆上下文 / 无谓烧 token
        if len(result) > 2000:
            result = result[:2000] + f"\n...(已截断，完整结果共 {len(result)} 字)"
        return result

    except ImportError:
        return "[ERROR] 搜索工具不可用: google-search-results 未安装。请运行 pip install google-search-results"
    except Exception as e:
        return f"[ERROR] 搜索出错: {str(e)}"
