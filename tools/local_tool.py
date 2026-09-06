"""
本地电脑控制工具 - 经客户端执行层在用户本机执行动作（macOS）

当智作台运行在用户的电脑上时，这些工具可以让 agent「操控本地电脑」：
1. open_application: 打开本机已安装的应用程序（如「备忘录」「Safari」「终端」）。
2. open_webpage: 用系统默认浏览器打开网页（跟随系统默认浏览器，不一定是 Safari）。
3. run_apple_script: 执行 AppleScript，实现更精细的本地自动化（窗口管理、键入、跨 App 操作等）。
4. find_local_files: 在用户本机搜索文件，用于「把本地 xxx 文件发给某邮箱」「找一下我电脑上的 xxx」。

执行位置（瘦客户端架构）：
- 服务端不再直接 subprocess，而是把指令经「控制通道」下发到客户端；
- 客户端（Rust 执行层）在用户授权后真正执行 open/osascript，并把结果回传。
- 首次/新增目标 App 时，macOS 会弹 TCC 授权框（需 .app 已用 Developer ID 签名）。
- 非 macOS 客户端会返回友好提示，不会崩溃。

权限说明（仅首次需要，授权对象是打包的「智作台.app」）：
- 「自动化 (Automation)」：允许进程向其它 App / System Events 发送 Apple 事件。
- 「辅助功能 (Accessibility)」：真正去「按键/点击」其它 App 界面时需要。
未签名时 TCC 不稳；客户端会检测签名状态并上报服务端打日志提醒配置 Developer ID。
"""
import contextvars

from langchain_core.tools import tool

from core.control_manager import request_local_exec

# 当前会话用户（在 chat_stream 入口设置），用于把指令路由到正确的客户端。
_CURRENT_USER: contextvars.ContextVar[str] = contextvars.ContextVar("xst_user", default="")


def set_current_user(user_id: str):
    """在每次对话入口设置当前用户，使本机控制指令能路由到该用户的客户端。"""
    _CURRENT_USER.set(user_id)


@tool
async def open_application(app_name: str) -> str:
    """打开用户本机上的一个应用程序。适用于「打开备忘录」「启动 Safari」「打开终端」等请求。
    参数 app_name: 应用名称或 .app 路径，例如「备忘录」「Safari」「终端」「/System/Applications/Calculator.app」。
    """
    return await request_local_exec(
        _CURRENT_USER.get(), "open_application", {"app_name": app_name}
    )


@tool
async def open_webpage(url: str) -> str:
    """在浏览器中打开一个网页。执行层会优先使用本机已安装的 Google Chrome；
    若未安装 Chrome，则回退到系统默认浏览器。适用于「打开百度」「在浏览器里打开 https://..."
    「帮我去这个网站看看」「搜索今天天气」等请求。不要与 open_application 同时调用去打开浏览器，
    避免同时打开两个浏览器。
    参数 url: 完整网址，需包含 https:// 或 http://。
    """
    return await request_local_exec(_CURRENT_USER.get(), "open_webpage", {"url": url})


@tool
async def run_apple_script(script: str) -> str:
    """执行一段 AppleScript，对本地电脑做更精细的自动化控制
    （例如：把文本输入到某个 App 的搜索框、切换窗口、控制音量、读写文件等）。
    当你需要「不只是打开应用/网页，而是真的去操作某个程序界面」时使用。
    参数 script: 标准的 AppleScript 代码字符串，例如
      'tell application "System Events" to keystroke "hello"'
    注意：若脚本涉及模拟键鼠输入，需要已授予智作台「辅助功能」权限；
    若只是查询/打开，则「自动化」权限即可。脚本执行失败会返回错误信息供你排查。
    """
    return await request_local_exec(_CURRENT_USER.get(), "run_apple_script", {"script": script})


@tool
async def find_local_files(name: str, dirs: list = None, ext: str = "", max_results: int = 10) -> str:
    """在用户本机搜索文件，用于「把本地 xxx 文件发给某邮箱」「找一下我电脑上的 xxx」等需求。

    当用户只给了文件名（可能不完整、缺扩展名，例如「学前招生入学申请表」「2026招生表」）而没有完整路径时，
    先调用本工具在用户本机搜索（默认全盘 Spotlight 检索 Downloads / Desktop / Documents 等常用位置），
    把定位到的完整路径返回给用户确认。

    参数：
    - name: 文件名关键词/片段（支持部分匹配，会匹配「包含该片段」的文件名），例如「招生」「申请表2026」「合同」。
    - dirs: 可选，限定搜索目录列表（当前由客户端全盘检索，此参数预留）。
    - ext: 可选，限定扩展名，如 ".xls,.pdf,.docx,.png"（逗号分隔，点号可写可不写）；为空则不限类型。
    - max_results: 最多返回几条匹配，默认 10（按修改时间从新到旧）。

    返回：匹配到的文件完整路径列表（含大小、修改时间）；找不到时给出友好提示，绝不会编造路径。
    """
    return await request_local_exec(
        _CURRENT_USER.get(),
        "find_local_files",
        {"name": name, "ext": ext or "", "max_results": max_results or 10},
    )
