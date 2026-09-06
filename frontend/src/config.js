// 后端地址配置
//
// 默认连本机/远程后端（127.0.0.1:8000）。可通过以下方式覆盖（优先级从高到低）：
//   1. 运行时：App 内「设置服务器」写入 localStorage（xst_api_base），无需重新打包
//   2. 构建时：在 frontend/.env 写  VITE_API_BASE=...
//   3. 构建时：VITE_API_BASE=https://... npm run build
//   4. 都不设置则使用下方默认值（http://127.0.0.1:8000）
//
// 手机/局域网访问时请把地址设为电脑的局域网 IP，例如：
//   http://192.168.1.50:8000
// 同时后端需监听 0.0.0.0（docker 部署下 nginx 已对外发布 :8000）。

const STORAGE_KEY = 'xst_api_base'
const DEFAULT_BASE = 'http://127.0.0.1:8000'

// 读取当前后端基址（HTTP 根，不含 /api）
export function getApiBase() {
  if (typeof localStorage !== 'undefined') {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (stored && stored.trim()) return stored.trim().replace(/\/+$/, '')
  }
  return (import.meta.env.VITE_API_BASE || DEFAULT_BASE).replace(/\/+$/, '')
}

// 设置后端基址（写入 localStorage，下次请求/重连生效）。传空则清除覆盖、回退到默认值。
export function setApiBase(url) {
  const clean = (url || '').trim().replace(/\/+$/, '')
  if (typeof localStorage !== 'undefined') {
    if (clean) localStorage.setItem(STORAGE_KEY, clean)
    else localStorage.removeItem(STORAGE_KEY)
  }
  return clean || getApiBase()
}

// 当前 HTTP 接口基址（后端路由统一挂在 /api 下）
export function getBase() {
  return `${getApiBase()}/api`
}

// WebSocket 基址：把 http(s) 协议对应换成 ws(s)
export function getWsBase() {
  return getApiBase().replace(/^http/, 'ws')
}

// 兼容旧导入：模块加载时计算一次的常量。
// 注意：运行期改地址请用 getBase()/getWsBase()，这两个常量仅供一次性初始化使用。
export const BASE = getBase()
export const WS_BASE = getWsBase()

// 应用品牌与版本（展示用；打包/更新版本号以 src-tauri/tauri.conf.json 与远端 manifest 为准）
export const APP_NAME = '智作台'
export const APP_NAME_EN = 'AI Workbench'
export const APP_VERSION = '0.1.0'
