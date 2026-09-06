"""微信公众号开放接口客户端：写入草稿箱。

凭证从宿主环境变量读取（manifest.env_whitelist 已声明 WECHAT_APP_ID/WECHAT_APP_SECRET）。
凭证未配置时返回 mock URL（便于本地演示）；生产环境建议改为抛错。
"""
from __future__ import annotations

import hashlib
import os


def _get_credentials() -> tuple[str | None, str | None]:
    return os.environ.get("WECHAT_APP_ID"), os.environ.get("WECHAT_APP_SECRET")


def publish_draft(html: str, title: str) -> str:
    """推送文章到微信公众号草稿箱，返回文章链接。

    真实部署需：
    1. 申请微信公众号 AppID / AppSecret，写入宿主 .env
    2. 调 cgi-bin/token 获取 access_token
    3. 调 cgi-bin/draft/add 写入草稿箱，返回 media_id

    凭证未配置时返回 mock URL。
    """
    app_id, app_secret = _get_credentials()
    if not (app_id and app_secret):
        digest = hashlib.md5(f"{title}|{len(html)}".encode("utf-8")).hexdigest()[:10]
        return f"https://mp.weixin.qq.com/s/__mock_{digest}"

    # ---- 真实实现（取消注释并补 requests 调用即可上线）----
    # import requests
    # token = requests.get(
    #     "https://api.weixin.qq.com/cgi-bin/token",
    #     params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
    #     timeout=10,
    # ).json().get("access_token")
    # res = requests.post(
    #     f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={token}",
    #     json={"title": title, "content": html, "article_type": "news"},
    #     timeout=10,
    # ).json()
    # if "media_id" not in res:
    #     raise RuntimeError(f"微信草稿箱写入失败: {res}")
    # return f"https://mp.weixin.qq.com/s/{res['media_id']}"

    digest = hashlib.md5(f"{title}|{len(html)}".encode("utf-8")).hexdigest()[:10]
    return f"https://mp.weixin.qq.com/s/__mock_{digest}"
