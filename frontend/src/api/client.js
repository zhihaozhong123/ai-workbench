import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'

import { getBase } from '@/config'

// 统一 HTTP 客户端：自动带 access token，遇 401 用 refresh 静默换发并重试
// 基址在请求时动态读取（getBase），支持 App 内「设置服务器」运行时切换地址。
const api = axios.create({ baseURL: '' })

api.interceptors.request.use((config) => {
  // 动态基址：支持「设置服务器」运行时切换（无需重新打包）
  config.baseURL = getBase()
  const auth = useAuthStore()
  if (auth.accessToken) {
    config.headers.Authorization = `Bearer ${auth.accessToken}`
  }
  // 纯 App 路线：仅当运行在 Tauri WebView 内（window.__TAURI_INTERNALS__ 由 Tauri 注入，
  // 普通浏览器没有该运行时）才携带客户端标识头；后端 require_app_client 中间件据此
  // 拒绝网页端 / 直连调用，防止网页端访问 API。
  if (typeof window !== 'undefined' && (window.__TAURI_INTERNALS__ || window.__TAURI__)) {
    config.headers['X-XST-Client'] = 'xst-tv-7f3a'
  }
  return config
})

let refreshing = null

api.interceptors.response.use(
  (res) => res,
  async (error) => {
    const original = error.config
    if (error.response?.status === 401 && !original._retry) {
      original._retry = true
      const auth = useAuthStore()
      // 未登录状态下的 401（如登录/注册失败）：不触发刷新、不跳登录，
      // 直接返回错误供页面渲染（保留已填的用户名/密码）。
      if (!auth.accessToken) {
        return Promise.reject(error)
      }
      if (!auth.refreshToken) {
        const { default: router } = await import('@/router')
        const chat = useChatStore()
        chat.resetAll()
        auth.logout()
        router.replace('/login')
        return Promise.reject(error)
      }
      try {
        // 用裸 axios 直接打 /refresh，避免递归触发本拦截器
        if (!refreshing) {
          refreshing = axios
            .post(`${getBase()}/refresh`, { refresh_token: auth.refreshToken })
            .then((r) => {
              auth.setAuth(r.data)
              return r.data
            })
            .finally(() => {
              refreshing = null
            })
        }
        const data = await refreshing
        original.headers.Authorization = `Bearer ${data.access_token}`
        return api(original)
      } catch (e) {
        const { default: router } = await import('@/router')
        const chat = useChatStore()
        chat.resetAll()
        auth.logout()
        router.replace('/login')
        return Promise.reject(e)
      }
    }
    return Promise.reject(error)
  }
)

export default api
