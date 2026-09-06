"""智作台技能平台核心（XST-Skill）。

- manifest  : 技能包契约解析与校验（manifest.json 权威，兼容 SKILL.md frontmatter）
- installer : .xskill 下载落盘 / 安全解压（zip-slip 防护）/ 卸载 / 升级
- runtime   : 技能 CLI 子进程隔离执行（JSON 契约、超时、env 白名单）
- catalog   : 技能源与 GitHub Releases 拉取（见 api/routes_skills.py 使用）
"""
