"""公众号文章生成服务：NLP 抽取 + Markdown→HTML + 封面图提示词。

依赖 jieba（本地 TF-IDF，不依赖外部 API）。缺失时返回结构化错误，不让进程崩溃。
"""
from __future__ import annotations

import re
from typing import List

try:
    import jieba
    import jieba.analyse
except ImportError:  # pragma: no cover
    jieba = None
    jieba_analyse = None


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="author" content="{author}">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; max-width: 720px; margin: 0 auto; padding: 20px; color: #1f2937; line-height: 1.7; }}
  h1, h2, h3 {{ color: #111; margin-top: 1.4em; }}
  blockquote {{ border-left: 4px solid #2563eb; background: #f0f7ff; padding: 10px 16px; margin: 16px 0; color: #374151; }}
  code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 0.92em; }}
  pre {{ background: #1f2937; color: #f9fafb; padding: 12px 16px; border-radius: 8px; overflow-x: auto; }}
  img {{ max-width: 100%; border-radius: 6px; }}
  li {{ margin: 4px 0; }}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>"""


def _ensure_dep() -> None:
    if jieba is None:
        raise RuntimeError(
            "技能依赖 jieba 缺失，请先在技能目录执行 `pip install -r requirements.txt`。"
        )


def _split_sentences(text: str) -> List[str]:
    """按中英文句号/问号/感叹号/换行拆句。"""
    parts = re.split(r"(?<=[。！？!?\.])\s*|\n+", text.strip())
    return [p.strip() for p in parts if p and p.strip()]


def extract_keywords(content: str, top_k: int = 5) -> List[str]:
    _ensure_dep()
    tags = jieba.analyse.extract_tags(content, topK=top_k, withWeight=False)
    return tags or []


def extract_summary(content: str, max_sentences: int = 3, max_chars: int = 220) -> str:
    """启发式摘要：关键词命中 + 位置权重 + 长度偏好。"""
    sentences = _split_sentences(content)
    if not sentences:
        return ""
    if len(sentences) <= max_sentences:
        return "。".join(sentences)
    keywords = set(extract_keywords(content, top_k=20))
    scored = []
    for i, sent in enumerate(sentences):
        score = 0.0
        score += sum(1.0 for w in keywords if w in sent)
        if i == 0:
            score += 1.5
        elif i == len(sentences) - 1:
            score += 1.0
        score += min(len(sent) / 60.0, 1.5)
        scored.append((score, i, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    top = sorted(scored[:max_sentences], key=lambda x: x[1])
    summary = "。".join(s for _, _, s in top)
    if len(summary) > max_chars:
        summary = summary[: max_chars - 1] + "…"
    return summary


def generate_title(content: str, explicit: str = "", keywords: List[str] | None = None) -> str:
    if explicit:
        return explicit.strip()
    sentences = _split_sentences(content)
    if not sentences:
        return "未命名文章"
    title = sentences[0]
    title = re.sub(r"^#{1,6}\s*", "", title).strip()
    if not title:
        title = sentences[1] if len(sentences) > 1 else "未命名文章"
    if len(title) > 36:
        title = title[:35] + "…"
    if len(title) < 6 and keywords:
        title = f"{title}：{keywords[0]}"
    return title


def markdown_to_html(md: str) -> str:
    """极简 Markdown → 公众号适配 HTML。"""
    lines = md.split("\n")
    out: List[str] = []
    in_code = False
    in_quote = False
    for line in lines:
        if line.startswith("```"):
            if in_code:
                out.append("</pre>")
                in_code = False
            else:
                out.append("<pre>")
                in_code = True
            continue
        if in_code:
            out.append(line.replace("<", "&lt;").replace(">", "&gt;"))
            continue
        if line.startswith("> "):
            if not in_quote:
                out.append("<blockquote>")
                in_quote = True
            out.append(line[2:])
            continue
        if in_quote:
            out.append("</blockquote>")
            in_quote = False
        if line.startswith("# "):
            out.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("### "):
            out.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("- "):
            out.append(f"<li>{line[2:]}</li>")
        elif line.strip() == "":
            out.append("<br>")
        else:
            text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            out.append(f"<p>{text}</p>")
    if in_quote:
        out.append("</blockquote>")
    if in_code:
        out.append("</pre>")
    return "\n".join(out)


def generate_cover_prompt(title: str, keywords: List[str]) -> str:
    base = f"公众号封面图，主题：「{title}」"
    if keywords:
        base += f"，融合元素：{'、'.join(keywords[:3])}"
    return (
        base + "，现代扁平插画风格，主色蓝紫渐变，留白安全区，"
        "清晰可识别的标题文字位，构图适合 900×500。"
    )


def generate_article(params: dict) -> dict:
    """生成公众号文章草稿（不发布）。

    Returns:
        dict: title, summary, keywords, cover_prompt, html, publish_url(null), status(generated)
    """
    content = (params.get("content") or "").strip()
    if not content:
        raise ValueError("缺少参数 content（文章正文）")
    keywords = extract_keywords(content, top_k=5)
    title = generate_title(content, params.get("title") or "", keywords)
    summary = extract_summary(content)
    body = re.sub(r"^#{1,6}\s+.+?\n+", "", content, count=1).strip()
    body_html = markdown_to_html(body or content)
    html = HTML_TEMPLATE.format(
        title=title,
        author=params.get("author") or "智作台",
        body=body_html,
    )
    cover_prompt = generate_cover_prompt(title, keywords)
    return {
        "title": title,
        "summary": summary,
        "keywords": keywords,
        "cover_prompt": cover_prompt,
        "html": html,
        "publish_url": None,
        "status": "generated",
    }
