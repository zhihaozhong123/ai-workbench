# 公众号文章批量发布（智作台技能 XST-Skill v1）

> 把内容草稿一键发布到微信公众号；NLP 自动生成标题 / 摘要 / 关键词 / 封面图描述。

## 这是什么

智作台（AI Workbench）的**技能包**：用户安装后，在「对话任务」会出现一个**公众号文章发布**的专属入口；
Agent 会注入技能系统提示，并自动获得 `skill_wechat_article_publish` 工具，
按需调用完成「文章生成 → 公众号草稿」的全流程。

## 目录

```
wechat-article-publish/
├── manifest.json          # 权威元数据
├── SKILL.md               # 给 Agent 的技能说明
├── AGENT.md               # 注入 Agent 的系统提示
├── scripts/
│   └── main.py            # CLI（确定性 NLP + 公众号 HTML 生成）
├── requirements.txt       # Python 依赖
└── README.md              # 本文件
```

## 快速开发

```bash
# 1) 安装依赖
pip install -r requirements.txt

# 2) 本地手测
echo '{"params":{"content":"# 标题\n\n这是一段正文示例。","publish":false}}' \
  | python scripts/main.py
```

预期输出（截断）：

```json
{
  "ok": true,
  "data": {
    "title": "标题：内容",
    "summary": "…",
    "keywords": ["关键词1", "关键词2"],
    "cover_prompt": "公众号封面图，主题：「…」，融合元素：…",
    "html": "<!DOCTYPE html>…",
    "publish_url": null,
    "status": "generated"
  }
}
```

## 在智作台安装

```bash
# 在 ai-workbench 项目根目录打包
python scripts/build_skill.py data/skills/wechat-article-publish
# → dist/skill-wechat-article-publish-1.0.0.xskill

# 发布到 GitHub Release（一键：tag + release + asset）
bash scripts/release_skill.sh data/skills/wechat-article-publish
```

随后在智作台「技能市场 → 管理技能源」添加 `zhihaozhong123/<repo>` 即可同步、安装。

## 发布到真实公众号（生产）

1. 申请微信公众号「AppID / AppSecret」；
2. 在宿主 `.env` 写入（manifest.runtime.env_whitelist 已声明注入）：
   ```
   WECHAT_APP_ID=your_app_id
   WECHAT_APP_SECRET=your_app_secret
   ```
3. 把 `scripts/main.py` 中 `publish_to_wechat` 的真实实现注释取消（cgi-bin/token + draft/add）。

## 安全

- 凭据不进技能包（仅由 env_whitelist 注入）；
- 子进程隔离（超时 30s / Redis 分布式信号量）；
- `publish=true` 时严格依赖 WECHAT_APP_ID / WECHAT_APP_SECRET；缺凭证返回结构化错误而非 mock。