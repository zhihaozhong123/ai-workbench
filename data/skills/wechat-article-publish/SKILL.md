# 公众号文章批量发布

> 智作台（AI Workbench）技能 — 把内容草稿一键发布到微信公众号，支持 NLP 自动生成标题/摘要/关键词/封面图描述。

## 何时调用本技能

适合以下任意场景时，主 Agent 应主动调度 `skill_wechat_article_publish`：

- 用户说「发公众号」「发到微信」「把这篇发到公众号」「生成一篇公众号文章」「写一篇推文」
- 用户提供了标题/正文，并明确希望发布到微信公众号
- 内容运营需要批量产出可发布到公众号的草稿

## 入参（`params`）

| 字段 | 必填 | 说明 |
|------|------|------|
| `content` | ✅ | 文章正文，建议为 Markdown |
| `title` |  | 标题；缺省时 NLP 自动生成 |
| `author` |  | 作者署名；缺省 `智作台` |
| `tags` |  | 标签列表；缺省时 NLP 抽取 |
| `publish` |  | 是否真正推送到微信；缺省 ` `false`（仅生成草稿） |

## 出参（`data`）

| 字段 | 说明 |
|------|------|
| `title` | 最终标题 |
| `summary` | 约 150 字摘要（NLP 启发式抽取） |
| `keywords` | 5 个核心关键词（jieba TF-IDF） |
| `cover_prompt` | 封面图生成提示词（基于关键词，可送文生图模型） |
| `html` | 公众号适配的 HTML（内联样式、图片占位） |
| `publish_url` | 真实推送后的文章链接；`publish=false` 时为 `null` |
| `status` | `generated`（仅生成草稿）或 `published`（已推送） |

## 调用方式

```bash
echo '{"params":{"content":"# 标题\n\n正文...","publish":false}}' \
  | python scripts/main.py
```

## 发布到公众号

`publish=true` 时调用 `publish_to_wechat`。生产部署需：

1. 申请微信公众号「AppID / AppSecret」并写入宿主 `.env`：
   ```
   WECHAT_APP_ID=your_app_id
   WECHAT_APP_SECRET=your_app_secret
   ```
2. 实现微信开放接口调用（cgi-bin/token 获取 access_token → cgi-bin/draft/add 写入草稿箱）。
   当前 CLI 默认返回 mock URL，便于本地演示。

## 安全

- 凭证不进技能包：通过 `manifest.runtime.env_whitelist` 由宿主 `.env` 注入；
- 子进程隔离：超时 30s、Redis 分布式信号量限制并发；
- 凭据未配置时 `publish=true` 会返回 `[ERROR]` 提示，绝不悄悄走 mock 路径。