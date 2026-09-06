<template>
  <aside class="wb-sidebar" :class="{ collapsed }">
    <!-- 品牌区 -->
    <div class="wb-brand" @click="go('/tasks')">
      <div class="wb-brand-badge">智</div>
      <transition name="wb-fold">
        <div v-if="!collapsed" class="wb-brand-text">
          <div class="wb-brand-name">智作台</div>
          <div class="wb-brand-sub">AI Workbench</div>
        </div>
      </transition>
    </div>

    <!-- 一级导航 -->
    <nav class="wb-nav">
      <div
        v-for="item in menus"
        :key="item.key"
        class="wb-nav-item"
        :class="{ active: isActive(item), collapsed }"
        :title="collapsed ? item.label : ''"
        @click="go(item.path)"
      >
        <span class="wb-nav-emoji">{{ item.emoji }}</span>
        <transition name="wb-fold">
          <span v-if="!collapsed" class="wb-nav-label">{{ item.label }}</span>
        </transition>
        <span v-if="!collapsed && item.badge" class="wb-nav-badge">{{ item.badge }}</span>
      </div>
    </nav>

    <!-- 底部：用户 + 折叠 + 版本 -->
    <div class="wb-side-bottom">
      <div v-if="!collapsed" class="wb-user" @click="go('/settings')">
        <div class="wb-user-avatar">{{ avatarText }}</div>
        <div class="wb-user-meta">
          <div class="wb-user-name">{{ nickname }}</div>
          <div class="wb-user-signout" @click.stop="logout">退出登录</div>
        </div>
      </div>
      <button
        class="wb-collapse-btn"
        :title="collapsed ? '展开侧栏' : '收起侧栏'"
        @click="toggleCollapse"
      >
        <svg v-if="collapsed" viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="13 17 18 12 13 7"></polyline><polyline points="6 17 11 12 6 7"></polyline></svg>
        <svg v-else viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="11 17 6 12 11 7"></polyline><polyline points="18 17 13 12 18 7"></polyline></svg>
      </button>
      <div v-if="collapsed" class="wb-version" :title="`智作台 v${APP_VERSION}`">v{{ APP_VERSION }}</div>
      <div v-else class="wb-version">智作台 v{{ APP_VERSION }}</div>
    </div>
  </aside>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { APP_VERSION } from '@/config'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const chatStore = useChatStore()

const menus = [
  { key: 'tasks', label: '对话任务', emoji: '💬', path: '/tasks' },
  { key: 'market', label: '技能市场', emoji: '🧩', path: '/market' },
  { key: 'data', label: '数据管理', emoji: '🗂', path: '/placeholder/data' },
  { key: 'task-center', label: '任务中心', emoji: '📋', path: '/placeholder/task-center' },
  { key: 'schedule', label: '定时任务', emoji: '⏰', path: '/placeholder/schedule' },
  { key: 'models', label: '模型管理', emoji: '🧠', path: '/placeholder/models' },
  { key: 'channels', label: '频道管理', emoji: '📡', path: '/placeholder/channels' },
  { key: 'plugins', label: '插件管理', emoji: '🔌', path: '/placeholder/plugins' },
  { key: 'more', label: '更多', emoji: '✨', path: '/placeholder/more' },
  { key: 'settings', label: '系统设置', emoji: '⚙️', path: '/settings' },
]

// 折叠态持久化（刷新后保持用户习惯）
const collapsed = ref(localStorage.getItem('wb.sidebar.collapsed') === '1')
function toggleCollapse() {
  collapsed.value = !collapsed.value
  localStorage.setItem('wb.sidebar.collapsed', collapsed.value ? '1' : '0')
}

function isActive(item) {
  if (item.key === 'placeholder') return false
  if (route.name === 'tasks' || route.name === 'market' || route.name === 'settings') {
    return route.name === item.key
  }
  // 占位模块高亮
  if (route.name === 'placeholder') {
    return route.params.key === item.key
  }
  return route.path === item.path
}

function go(path) {
  if (route.fullPath === path) return
  router.push(path)
}

const nickname = computed(() => {
  const u = auth.user
  if (u?.nickname) return u.nickname
  if (u?.username) return u.username
  return '我'
})
const avatarText = computed(() => (nickname.value ? nickname.value[0] : '我'))

function logout() {
  chatStore.resetAll()
  auth.logout()
  router.replace('/login')
}
</script>

<style scoped>
.wb-sidebar {
  width: 208px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-right: 1px solid #e7eaf0;
  transition: width 0.18s ease;
}
.wb-sidebar.collapsed {
  width: 64px;
}
.wb-brand {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 18px 14px 14px;
  cursor: pointer;
  user-select: none;
}
.wb-brand-badge {
  width: 34px;
  height: 34px;
  flex-shrink: 0;
  border-radius: 10px;
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  color: #fff;
  font-size: 17px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 6px 16px rgba(37, 99, 235, 0.28);
}
.wb-brand-text {
  min-width: 0;
}
.wb-brand-name {
  font-size: 15px;
  font-weight: 700;
  color: #1f2937;
  letter-spacing: 0.5px;
}
.wb-brand-sub {
  font-size: 10px;
  color: #9ca3af;
  letter-spacing: 0.6px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.wb-nav {
  flex: 1;
  padding: 6px 10px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.wb-nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 10px;
  border-radius: 9px;
  font-size: 13.5px;
  color: #4b5563;
  cursor: pointer;
  transition: background 0.14s, color 0.14s;
  position: relative;
}
.wb-nav-item:hover {
  background: #f3f5f9;
  color: #1f2937;
}
.wb-nav-item.active {
  background: #eaf0fe;
  color: #1d4ed8;
  font-weight: 600;
}
.wb-nav-item.active::before {
  content: '';
  position: absolute;
  left: -10px;
  top: 20%;
  bottom: 20%;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: #2563eb;
}
.wb-nav-item.collapsed {
  justify-content: center;
  padding: 9px 0;
}
.wb-nav-emoji {
  width: 20px;
  text-align: center;
  font-size: 15px;
  flex-shrink: 0;
}
.wb-nav-label {
  flex: 1;
  white-space: nowrap;
}
.wb-nav-badge {
  font-size: 10px;
  color: #fff;
  background: #2563eb;
  border-radius: 999px;
  padding: 1px 7px;
}
.wb-side-bottom {
  padding: 12px 10px;
  border-top: 1px solid #eef1f6;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.wb-user {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 6px;
  border-radius: 9px;
  cursor: pointer;
  transition: background 0.14s;
}
.wb-user:hover {
  background: #f3f5f9;
}
.wb-user-avatar {
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}
.wb-user-meta {
  flex: 1;
  min-width: 0;
}
.wb-user-name {
  font-size: 13px;
  color: #1f2937;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.wb-user-signout {
  font-size: 11px;
  color: #9ca3af;
  opacity: 0;
  transition: opacity 0.15s;
}
.wb-user:hover .wb-user-signout {
  opacity: 1;
  color: #ef4444;
}
.wb-collapse-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 30px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  transition: background 0.14s, color 0.14s;
}
.wb-collapse-btn:hover {
  background: #f3f5f9;
  color: #4b5563;
}
.wb-version {
  font-size: 11px;
  color: #c3c9d3;
  text-align: center;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  user-select: none;
}
.wb-fold-enter-active,
.wb-fold-leave-active {
  transition: opacity 0.12s ease;
}
.wb-fold-enter-from,
.wb-fold-leave-to {
  opacity: 0;
}
</style>
