<template>
  <div class="me-page">
    <div class="me-card">
      <img :src="logo" class="me-logo" alt="智作台" />
      <h2 class="me-title">个人信息</h2>

      <div class="me-row"><span>用户 ID</span><b class="mono">{{ user?.user_id }}</b></div>
      <div class="me-row"><span>邮箱/手机号</span><b>{{ user?.username }}</b></div>
      <div class="me-row"><span>昵称</span><b>{{ user?.nickname || '未设置' }}</b></div>
      <div class="me-row"><span>注册时间</span><b>{{ user?.created_at }}</b></div>

      <p class="me-note">个人资料与更多偏好设置将迁移至「系统设置」，敬请期待。</p>

      <button class="back-btn" @click="router.push('/tasks')">返回对话任务</button>
      <button class="logout-btn" @click="logout">退出登录</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import logo from '@/assets/logo.png'

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()
const user = ref(auth.user)

onMounted(async () => {
  try {
    const { data } = await api.get('/me')
    auth.setUser({ user_id: data.user_id, username: data.username, nickname: data.nickname })
    user.value = auth.user
  } catch {}
})

function logout() {
  chat.resetAll()
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.me-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: #f3f4f6;
}
.me-card {
  width: 420px;
  max-width: calc(100vw - 32px);
  padding: 32px;
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 8px 30px rgba(17, 24, 39, .08);
}
.me-logo {
  width: 56px;
  height: 56px;
  border-radius: 14px;
  margin-bottom: 16px;
}
.me-title {
  margin: 0 0 20px;
  font-size: 20px;
  font-weight: 600;
  color: #1f2937;
}
.me-row {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 0;
  border-bottom: 1px solid #f1f5f9;
  font-size: 14px;
}
.me-row span {
  color: #6b7280;
}
.me-row b {
  color: #1f2937;
  font-weight: 500;
}
.mono {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
}
.me-note {
  margin: 20px 0 8px;
  font-size: 12px;
  color: #9ca3af;
  line-height: 1.6;
}
.back-btn,
.logout-btn {
  width: 100%;
  margin-top: 12px;
  padding: 11px 16px;
  font-size: 14px;
  font-weight: 600;
  border: none;
  border-radius: 10px;
  cursor: pointer;
  transition: opacity .15s;
}
.back-btn {
  color: #fff;
  background: #2563eb;
}
.back-btn:hover {
  opacity: .9;
}
.logout-btn {
  color: #dc2626;
  background: #fff;
  border: 1px solid #fecaca;
}
.logout-btn:hover {
  background: #fef2f2;
}
</style>
