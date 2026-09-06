# 公众号文章发布技能 CLI 契约（XST-Skill v1）

## 子命令

| 命令 | 说明 |
|------|------|
| `run` | 生成文章草稿 / 发布到公众号（默认） |
| `health` | 健康检查 |
| `version` | 版本信息 |

## 入参

```json
{
  "params": {
    "content": "# 标题\n\n正文...",
    "title": "可选标题",
    "author": "作者",
    "tags": ["标签1"],
    "publish": false
  }
}
```

## 出参

成功：
```json
{
  "ok": true,
  "data": {
    "title": "...",
    "summary": "...",
    "keywords": ["..."],
    "cover_prompt": "...",
    "html": "...",
    "publish_url": null,
    "status": "generated"
  }
}
```

`publish=true` 且配置了凭证时，`status` 变为 `published`，`publish_url` 为真实链接。

## 环境变量

| 变量 | 说明 |
|------|------|
| `WECHAT_APP_ID` | 微信公众号 AppID |
| `WECHAT_APP_SECRET` | 微信公众号 AppSecret |
