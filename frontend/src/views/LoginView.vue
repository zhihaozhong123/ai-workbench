<template>
  <div class="auth-page">
    <canvas ref="canvas" class="bg-canvas"></canvas>
    <div class="glow glow-1"></div>
    <div class="glow glow-2"></div>

    <!-- logo + 标语：表单（卡片）外的正上方 -->
    <div class="brand">
      <img :src="logo" alt="智作台" class="brand-logo" />
      <div class="brand-slogan">欢迎使用智作台 · AI 技能工作台</div>
    </div>

    <div class="auth-card">
      <div class="tabs">
        <button :class="['tab', { active: mode === 'login' }]" @click="mode = 'login'">登录</button>
        <button :class="['tab', { active: mode === 'register' }]" @click="mode = 'register'">注册</button>
      </div>

      <!-- 登录 -->
      <form v-if="mode === 'login'" class="form" @submit.prevent="onLogin">
        <input v-model.trim="loginForm.username" class="input" type="text" placeholder="邮箱/手机号" maxlength="120" />
        <div class="input-wrap">
          <input
            v-model="loginForm.password"
            class="input"
            :type="showLoginPwd ? 'text' : 'password'"
            placeholder="密码"
          />
          <button
            type="button"
            class="eye-btn"
            :aria-label="showLoginPwd ? '隐藏密码' : '显示密码'"
            @click="showLoginPwd = !showLoginPwd"
          >
            <svg v-if="showLoginPwd" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-7-11-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
              <line x1="1" y1="1" x2="23" y2="23" />
            </svg>
          </button>
        </div>
        <button class="submit" type="submit" :disabled="loading">{{ loading ? '登录中…' : '登 录' }}</button>
      </form>

      <!-- 注册（用户名 + 昵称 + 密码） -->
      <form v-else class="form" @submit.prevent="onRegister">
        <input v-model.trim="regForm.username" class="input" type="text" placeholder="邮箱/手机号" maxlength="120" />
        <input v-model.trim="regForm.nickname" class="input" type="text" placeholder="昵称" maxlength="32" />
        <div class="input-wrap">
          <input
            v-model="regForm.password"
            class="input"
            :type="showRegPwd ? 'text' : 'password'"
            placeholder="密码（至少 6 位）"
          />
          <button
            type="button"
            class="eye-btn"
            :aria-label="showRegPwd ? '隐藏密码' : '显示密码'"
            @click="showRegPwd = !showRegPwd"
          >
            <svg v-if="showRegPwd" viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-7-11-7a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 7 11 7a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
              <line x1="1" y1="1" x2="23" y2="23" />
            </svg>
          </button>
        </div>
        <button class="submit" type="submit" :disabled="loading">{{ loading ? '注册中…' : '注 册' }}</button>
      </form>

      <div v-if="hint" class="hint-tip">{{ hint }}</div>
      <div v-if="error" class="error-tip">{{ error }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import api from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import logo from '@/assets/logo.png'

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()
const route = useRoute()

const mode = ref('login')
const loading = ref(false)
const error = ref('')
const hint = ref('')
const showLoginPwd = ref(false)
const showRegPwd = ref(false)
const canvas = ref(null)
let raf = null
let onResize = null

const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({ username: '', nickname: '', password: '' })

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const PHONE_RE = /^\+?\d{6,20}$/
const validateAccount = (u) => EMAIL_RE.test(u) || PHONE_RE.test(u)

async function afterAuth(data) {
  // 先关闭旧 WebSocket 并清空旧用户的所有对话数据（防止切换用户时串号）
  chat.resetAll()
  auth.setAuth(data)
  try {
    const { data: me } = await api.get('/me')
    auth.setUser({ user_id: me.user_id, username: me.username, nickname: me.nickname })
  } catch {}
  const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/tasks'
  router.replace(redirect)
}

async function onLogin() {
  error.value = ''
  hint.value = ''
  if (!loginForm.username) {
    error.value = '请输入邮箱或手机号'
    return
  }
  if (!loginForm.password) {
    error.value = '请输入密码'
    return
  }
  loading.value = true
  try {
    // 去除密码首尾空白，规避移动端自动大写/自动纠错带入的空格导致“注册成功却登录不上”
    const { data } = await api.post('/login', {
      username: loginForm.username,
      password: loginForm.password.trim(),
    })
    await afterAuth(data)
  } catch (e) {
    error.value = e.response?.data?.detail || '登录失败'
  } finally {
    loading.value = false
  }
}

async function onRegister() {
  error.value = ''
  hint.value = ''
  if (!validateAccount(regForm.username)) {
    error.value = '请输入有效的邮箱或手机号'
    return
  }
  if (regForm.password.trim().length < 6) {
    error.value = '密码至少 6 位'
    return
  }
  loading.value = true
  try {
    // 去除密码首尾空白
    const { data } = await api.post('/register', {
      username: regForm.username,
      password: regForm.password.trim(),
      nickname: regForm.nickname,
    })
    // 注册成功：不自动登录，切到登录 tab 并预填账号，引导用户再次登录（符合「注册→登录→聊天」分步流程）
    const registered = regForm.username
    regForm.username = ''
    regForm.nickname = ''
    regForm.password = ''
    loginForm.username = registered
    mode.value = 'login'
    hint.value = '注册成功，请用该账号登录'
  } catch (e) {
    error.value = e.response?.data?.detail || '注册失败'
  } finally {
    loading.value = false
  }
}

function initParticles() {
  const c = canvas.value
  if (!c) return
  const ctx = c.getContext('2d')
  const dpr = window.devicePixelRatio || 1
  const resize = () => {
    c.width = window.innerWidth * dpr
    c.height = window.innerHeight * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  onResize = resize
  window.addEventListener('resize', resize)
  const ps = Array.from({ length: 70 }, () => ({
    x: Math.random() * window.innerWidth,
    y: Math.random() * window.innerHeight,
    vx: (Math.random() - 0.5) * 0.5,
    vy: (Math.random() - 0.5) * 0.5,
    r: Math.random() * 1.8 + 0.4,
  }))
  const tick = () => {
    ctx.clearRect(0, 0, c.width, c.height)
    for (const p of ps) {
      p.x += p.vx
      p.y += p.vy
      if (p.x < 0 || p.x > window.innerWidth) p.vx *= -1
      if (p.y < 0 || p.y > window.innerHeight) p.vy *= -1
      ctx.beginPath()
      ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2)
      ctx.fillStyle = 'rgba(130,170,255,0.55)'
      ctx.fill()
    }
    raf = requestAnimationFrame(tick)
  }
  tick()
}

onMounted(() => {
  initParticles()
  // 进入登录页时彻底清空旧用户的聊天数据（防止直接刷新/URL 跳转后残留）
  chat.resetAll()
})
onBeforeUnmount(() => {
  if (raf) cancelAnimationFrame(raf)
  if (onResize) window.removeEventListener('resize', onResize)
})
</script>
