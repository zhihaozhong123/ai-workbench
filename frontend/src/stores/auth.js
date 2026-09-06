import { defineStore } from 'pinia'

const ACCESS_KEY = 'xst_access_token'
const REFRESH_KEY = 'xst_refresh_token'
const USER_KEY = 'xst_user' // { user_id, username, nickname }

export const useAuthStore = defineStore('auth', {
  state: () => ({
    accessToken: '',
    refreshToken: '',
    user: null,
  }),
  getters: {
    isLoggedIn: (s) => !!s.accessToken,
  },
  actions: {
    // 从 localStorage 恢复（页面刷新后保持登录态）
    hydrate() {
      if (this.accessToken) return
      this.accessToken = localStorage.getItem(ACCESS_KEY) || ''
      this.refreshToken = localStorage.getItem(REFRESH_KEY) || ''
      const u = localStorage.getItem(USER_KEY)
      this.user = u ? JSON.parse(u) : null
    },
    // access_token 必存；refresh_token 不传则保留原值（refresh 接口返回原 refresh）
    setAuth({ access_token, refresh_token }, user = null) {
      this.accessToken = access_token
      this.refreshToken = refresh_token || this.refreshToken
      localStorage.setItem(ACCESS_KEY, access_token)
      localStorage.setItem(REFRESH_KEY, this.refreshToken)
      if (user) this.setUser(user)
    },
    setUser(user) {
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },
    logout() {
      this.accessToken = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      localStorage.removeItem(USER_KEY)
    },
  },
})
