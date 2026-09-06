"""公众号文章发布技能单元测试。"""
import json
import subprocess
import sys
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent.parent
MAIN = SKILL_ROOT / "scripts" / "main.py"


def _run_cli(params: dict, cli: str = "run") -> dict:
    proc = subprocess.run(
        [sys.executable, str(MAIN), cli],
        input=json.dumps({"params": params}),
        capture_output=True,
        text=True,
        cwd=str(SKILL_ROOT),
    )
    return json.loads(proc.stdout.strip())


SAMPLE_CONTENT = (
    "# 人工智能改变生活\n\n"
    "人工智能正在深刻改变我们的生活方式。从智能助手到自动驾驶，AI 技术无处不在。"
    "它不仅提升了工作效率，还创造了全新的商业模式。未来，AI 将在医疗、教育、"
    "金融等领域发挥更大作用，让生活变得更加便捷和智能。"
)


def test_generate_article_success():
    result = _run_cli({"content": SAMPLE_CONTENT, "publish": False})
    assert result["ok"] is True
    data = result["data"]
    assert data["status"] == "generated"
    assert data["publish_url"] is None
    assert data["title"]
    assert data["summary"]
    assert isinstance(data["keywords"], list)
    assert len(data["keywords"]) <= 5
    assert "<h1>" in data["html"]
    assert "人工智能" in data["cover_prompt"]


def test_missing_content():
    result = _run_cli({})
    assert result["ok"] is False
    assert "content" in result["error"]


def test_publish_without_credentials():
    result = _run_cli({"content": SAMPLE_CONTENT, "publish": True})
    assert result["ok"] is True
    assert result["data"]["status"] == "published"
    assert result["data"]["publish_url"].startswith("https://mp.weixin.qq.com/s/__mock_")


def test_health():
    result = _run_cli({}, cli="health")
    assert result["ok"] is True
    assert result["data"]["slug"] == "wechat-article-publish"
    assert result["data"]["status"] == "ok"


def test_explicit_title():
    result = _run_cli({"content": SAMPLE_CONTENT, "title": "自定义标题"})
    assert result["data"]["title"] == "自定义标题"
