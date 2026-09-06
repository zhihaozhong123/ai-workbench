# TOOLS · 工具与核心能力

> 本文件列出「智作台」可用的工具及其使用时机。
> ⚠️ 维护约定：此清单需与 `agent_runner.py` 中实际注册的 `tools=[...]` 保持一致，避免"说有却没注册"或"注册了却没说明"。

## 你的核心能力

1. **联网搜索 (web_search)**: 当用户想获取最新事实、实时信息（新闻、股价、天气等）时使用，返回文字结果。
2. **打开应用 (open_application)**: 当用户想打开本机上的某个应用程序时使用，例如「打开备忘录」「启动终端」。
3. **打开网页 (open_webpage)**: 当用户想在浏览器里打开某个网址、或说「打开百度」「去 xxx 网站看看」「搜索今天天气」时使用。执行层会优先使用本机已安装的 Google Chrome；若未安装 Chrome，则回退到系统默认浏览器。**不要**与 `open_application("Safari")` / `open_application("Google Chrome")` 同时调用，避免同时打开两个浏览器。
4. **AppleScript 自动化 (run_apple_script)**: 当用户需要更精细地操控本机（例如把文字输入到某个 App 的搜索框、切换窗口、控制音量等）时使用。仅在确实需要通过 AppleScript 完成自动化时才调用。
5. **本地文件查找 (find_local_files)**: 当用户只给了文件名没给完整路径时，先调用本工具在常用目录（Downloads / Desktop / Documents）找到真实完整路径，再把路径传给后续工具。**绝不可凭空编造路径**。
6. **长期记忆 (save_to_memory / recall_from_memory)**:
   - 用户表达偏好、习惯、个人信息时，主动调用 `save_to_memory` 保存。
   - 仅当用户偏好、历史事实可能相关时，才调用 `recall_from_memory` 回顾（无需每轮都调，避免无谓消耗）。
7. **计算器 (calculator)**: 需要数学计算时使用。
8. **时间查询 (get_current_time)**: 需要知道当前时间时使用。

> 技能专属任务下，还会按技能 manifest 注入 `skill_<slug>` 工具（确定性 CLI 执行，由 skills/runtime.py 守护超时与 env 白名单），详见技能市场的技能详情。