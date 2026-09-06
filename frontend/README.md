# 小书童 · 前端 (Vue 3)

小书童本地 macOS 桌面助手的 Web 前端，由 Tauri 用系统 WebView 渲染。技术栈：

- Vue 3 + Vite
- Vue Router（路由鉴权）
- Pinia（token / 用户信息状态）
- axios（HTTP，直连本机后端 `http://127.0.0.1:8000`，自动 401 续命）
- 原生 WebSocket（聊天，自动重连 + token 续命）

## 目录结构

```
frontend/
├── index.html
├── vite.config.js          # 仅做 Vue 编译与别名；不再需要 dev 代理（前端直连 127.0.0.1:8000）
├── src/
│   ├── main.js
│   ├── App.vue
│   ├── router/index.js     # /login、/chat、/me，含登录守卫
│   ├── stores/auth.js      # Pinia：双 token + 用户持久化
│   ├── api/client.js       # axios 封装（直连 127.0.0.1:8000/api，401 自动 refresh 重试）
│   ├── api/chat.js         # WebSocket 封装（直连 ws://127.0.0.1:8000，自动重连 / 续命）
│   ├── assets/logo.png     # 小书童 logo
│   ├── assets/style.css    # 全局纯黑酷炫主题
│   └── views/
│       ├── LoginView.vue   # 注册（用户名+昵称+密码）/ 登录（用户名+密码）
│       ├── ChatView.vue    # 会话列表 + 对话 + 工具调用展示
│       └── MeView.vue      # 个人信息页
```

## 运行

前端不再单独 `npm run dev`，而是由 Tauri 统一拉起（推荐）：

```bash
cd xiaoshutong
cargo tauri build      # 构建桌面 .app（frontendDist）
```

若只想单独调试前端（需后端已在 `127.0.0.1:8000` 运行）：

```bash
cd xiaoshutong/frontend
npm install
npm run dev            # 访问 http://localhost:5173
```

## 业务说明

- **主页 `/login`**：酷炫纯黑背景（粒子动画 + 光晕），中央是小书童 logo 与标语。可在
  「登录 / 注册」间切换：注册用「用户名 + 昵称 + 密码」，登录用「用户名 + 密码」。
- **聊天页 `/chat`**：类 ChatGPT 布局。左侧栏为会话列表（可新建）、底部展示用户昵称
  （无昵称时回退为用户名）；右侧栏右上角入口跳转个人信息页。聊天走
  WebSocket `ws://127.0.0.1:8000/ws/chat`，流式接收 `tool_call / final / done` 事件。
  点击左侧历史会话会从后端 `GET /conversations/{id}/messages` 恢复消息。
- **个人信息页 `/me`**：展示 `GET /api/me` 返回的用户信息，可退出登录。

## 与后端对接要点

- 所有 HTTP 请求直连 `http://127.0.0.1:8000/api`，带 `Authorization: Bearer <access_token>`；
  收到 401 自动用 `refresh_token` 调 `POST /api/refresh` 换发新 access 并重试。
- WebSocket 用 `?token=<access_token>` 鉴权；连接被拒(1008)或过期时自动 refresh 后重连。
- token 全部存于 `localStorage`，刷新页面后保持登录态。
