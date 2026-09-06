<template>
  <div class="set-page">
    <!-- 左：二级设置菜单 -->
    <aside class="set-nav">
      <button
        v-for="p in panels"
        :key="p.key"
        class="set-nav-item"
        :class="{ active: active === p.key }"
        @click="active = p.key"
      >
        <span class="set-nav-emoji">{{ p.emoji }}</span>
        <span>{{ p.label }}</span>
      </button>
    </aside>

    <!-- 右：内容区 -->
    <main class="set-main">
      <!-- ============ 账号信息 ============ -->
      <section v-if="active === 'account'" class="set-card">
        <div class="set-profile-head">
          <div class="set-avatar">{{ avatarText }}</div>
          <div class="set-profile-meta">
            <h2>{{ profile.nickname || profile.username || '未登录用户' }}</h2>
            <p>欢迎使用智作台 · AI Workbench，你的本地 Agent 工作台</p>
          </div>
        </div>
        <dl class="set-rows">
          <div class="set-row">
            <dt>用户 ID</dt>
            <dd><code>{{ profile.user_id }}</code></dd>
          </div>
          <div class="set-row">
            <dt>账号</dt>
            <dd>{{ profile.username }}</dd>
          </div>
          <div class="set-row">
            <dt>昵称</dt>
            <dd>{{ profile.nickname || '未设置' }}</dd>
          </div>
          <div class="set-row">
            <dt>注册时间</dt>
            <dd>{{ profile.created_at || '-' }}</dd>
          </div>
        </dl>
        <div class="set-card-actions">
          <button class="set-btn danger-ghost" @click="logout">退出登录</button>
        </div>
      </section>

      <!-- ============ 通用设置 ============ -->
      <section v-else-if="active === 'general'" class="set-card">
        <h3 class="set-card-title">通用设置</h3>

        <div class="set-block">
          <label class="set-block-label">后端服务地址</label>
          <div class="set-inline">
            <input v-model.trim="serverInput" class="set-input" placeholder="http://127.0.0.1:8000" />
            <button class="set-btn primary" @click="saveServer">保存</button>
            <button v-if="serverDirty" class="set-btn ghost" @click="resetServer">重置</button>
          </div>
          <p class="set-tip">桌面端默认连接本机后端（127.0.0.1:8000）；修改后立即生效，无需重启。</p>
        </div>

        <div class="set-block">
          <label class="set-block-label">本地偏好</label>
          <div class="set-inline">
            <button class="set-btn ghost danger-ghost" @click="resetLocalPrefs">清除本地偏好设置</button>
          </div>
          <p class="set-tip">重置侧栏折叠、更新开关等本地偏好，不影响账号与会话数据。</p>
        </div>

        <div class="set-block">
          <div class="set-switch-row">
            <div class="set-switch-text">
              <span>随系统开机自启</span>
              <em>桌面端暂未启用，敬请期待</em>
            </div>
            <span class="set-soon-chip">规划中</span>
          </div>
        </div>
      </section>

      <!-- ============ 检查更新 ============ -->
      <section v-else-if="active === 'update'" class="set-card">
        <div class="set-update-head">
          <div>
            <h3 class="set-card-title">检查更新</h3>
            <p class="set-tip">当前版本 <code>v{{ currentVersion }}</code></p>
          </div>
          <button class="set-btn primary" :disabled="updateState === 'checking'" @click="checkUpdateNow">
            {{ updateState === 'checking' ? '检查中…' : '检查更新' }}
          </button>
        </div>

        <div class="set-switch-row">
          <div class="set-switch-text">
            <span>自动检查更新</span>
            <em>启动应用时自动检测是否有新版本</em>
          </div>
          <button class="set-toggle" :class="{ on: prefs.autoCheck }" role="switch" :aria-checked="prefs.autoCheck" @click="toggle('autoCheck')">
            <span class="set-toggle-dot"></span>
          </button>
        </div>
        <div class="set-switch-row">
          <div class="set-switch-text">
            <span>自动更新</span>
            <em>发现新版本后自动下载安装包</em>
          </div>
          <button class="set-toggle" :class="{ on: prefs.autoDownload }" role="switch" :aria-checked="prefs.autoDownload" @click="toggle('autoDownload')">
            <span class="set-toggle-dot"></span>
          </button>
        </div>

        <div v-if="updateState === 'idle'" class="set-update-empty">尚未检查更新，点击右上角「检查更新」获取最新版本。</div>

        <div v-else-if="updateState === 'checking'" class="set-update-empty">正在向更新服务查询最新版本…</div>

        <div v-else-if="updateState === 'unavailable'" class="set-update-empty">
          暂未接入远端更新服务。请先配置远端更新 manifest（见 README「更新」章节）。
        </div>

        <div v-else-if="updateState === 'error'" class="set-update-empty err">
          检查更新失败：{{ updateError }}
        </div>

        <div v-else-if="updateState === 'ok'" class="set-update-result">
          <template v-if="updateInfo.has_update">
            <div class="set-update-card">
              <div class="set-update-card-head">
                <span class="set-new-flag">发现新版本</span>
                <span class="set-ver-big">{{ updateInfo.latest_version }}</span>
                <span v-if="updateInfo.published_at" class="set-ver-date">{{ fmtDate(updateInfo.published_at) }}</span>
              </div>
              <p v-if="updateInfo.notes" class="set-update-notes">{{ updateInfo.notes }}</p>
              <div v-if="updateInfo.download_url" class="set-inline" style="margin-top: 10px">
                <button class="set-btn primary" @click="downloadNow">⬇ 下载更新</button>
                <button class="set-btn ghost" @click="copyDownloadLink">复制下载链接</button>
              </div>
            </div>
          </template>
          <div v-else class="set-update-empty ok">当前已是最新版本（v{{ currentVersion }}）🎉</div>
        </div>
      </section>

      <!-- ============ 关于 ============ -->
      <section v-else class="set-card">
        <div class="set-about-head">
          <div class="set-about-badge">智</div>
          <div>
            <h2 class="set-about-name">智作台</h2>
            <p class="set-about-en">AI Workbench · v{{ currentVersion }}</p>
          </div>
        </div>
        <p class="set-about-desc">
          智作台是一款面向 macOS 的本地 Agent 工作台与技能市场应用。
          你可以在技能市场安装社区发布的技能，为每个技能开启专属 Agent 任务；
          通用对话默认提供联网搜索、网页打开、本机应用控制等内置工具。
        </p>
        <dl class="set-rows">
          <div class="set-row">
            <dt>桌面端</dt>
            <dd>macOS · Tauri v2</dd>
          </div>
          <div class="set-row">
            <dt>技术栈</dt>
            <dd>FastAPI · LangGraph · Vue 3 · PostgreSQL · Redis</dd>
          </div>
          <div class="set-row">
            <dt>技能分发</dt>
            <dd>GitHub Releases（.xskill）</dd>
          </div>
        </dl>
        <p class="set-copyright">© 2026 智作台 AI Workbench · 本地优先 · 企业级安全</p>
      </section>
    </main>

    <!-- 轻提示 -->
    <transition name="mk-fade">
      <div v-if="notice" class="mk-toast" role="status">{{ notice }}</div>
    </transition>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { getApiBase, setApiBase, APP_VERSION } from '@/config'
import api from '@/api/client'
import { checkUpdate } from '@/api/update'
import { openExternal } from '@/utils/external'

const router = useRouter()
const auth = useAuthStore()
const chat = useChatStore()

const currentVersion = APP_VERSION
const panels = [
  { key: 'account', label: '账号信息', emoji: '👤' },
  { key: 'general', label: '通用设置', emoji: '🛠' },
  { key: 'update', label: '检查更新', emoji: '🔄' },
  { key: 'about', label: '关于', emoji: 'ℹ️' },
]
const active = ref('account')

// ---- 账号 ----
const profile = reactive({
  user_id: auth.user?.user_id || '-',
  username: auth.user?.username || '-',
  nickname: auth.user?.nickname || '',
  created_at: '',
})
const avatarText = computed(() => (profile.nickname || profile.username || '我')[0])

async function loadProfile() {
  try {
    const { data } = await api.get('/me')
    Object.assign(profile, data)
    auth.setUser({ user_id: data.user_id, username: data.username, nickname: data.nickname })
  } catch (e) {
    console.error('加载用户信息失败', e)
  }
}

function logout() {
  chat.resetAll()
  auth.logout()
  router.replace('/login')
}

// ---- 通用 ----
const serverInput = ref(getApiBase())
const serverDirty = computed(() => serverInput.value.replace(/\/+$/, '') !== getApiBase())
function saveServer() {
  setApiBase(serverInput.value)
  toast('服务地址已更新')
}
function resetServer() {
  serverInput.value = getApiBase()
}
function resetLocalPrefs() {
  if (!window.confirm('确认清除本地偏好设置（侧栏折叠、更新开关等）？不影响账号与会话数据。')) return
  for (const k of Object.keys(localStorage)) {
    if (k.startsWith('wb.') || k === 'xst_api_base') localStorage.removeItem(k)
  }
  serverInput.value = getApiBase()
  toast('本地偏好已清除')
}

// ---- 更新 ----
const prefs = reactive({
  autoCheck: localStorage.getItem('wb.autoCheck') === '1',
  autoDownload: localStorage.getItem('wb.autoDownload') === '1',
})
function toggle(key) {
  prefs[key] = !prefs[key]
  localStorage.setItem(`wb.${key}`, prefs[key] ? '1' : '0')
}

const updateState = ref('idle') // idle | checking | ok | unavailable | error
const updateInfo = ref(null)
const updateError = ref('')

async function checkUpdateNow() {
  updateState.value = 'checking'
  updateError.value = ''
  try {
    const { data } = await checkUpdate()
    updateInfo.value = {
      current_version: data.current_version || currentVersion,
      latest_version: data.latest_version || '',
      has_update: !!data.has_update,
      notes: data.notes || data.update_notes || '',
      published_at: data.published_at || '',
      download_url: data.download_url || '',
    }
    updateState.value = 'ok'
  } catch (e) {
    const status = e?.response?.status
    if (status === 404 || status === 501 || status === 503) {
      updateState.value = 'unavailable'
    } else {
      updateState.value = 'error'
      updateError.value = e?.response?.data?.detail || e?.message || '未知错误'
    }
  }
}

function fmtDate(iso) {
  try {
    const d = new Date(iso)
    return isNaN(d) ? '' : d.toLocaleDateString()
  } catch {
    return ''
  }
}

function downloadNow() {
  if (!updateInfo.value?.download_url) return
  openExternal(updateInfo.value.download_url)
  toast('已在浏览器打开下载地址')
}

async function copyDownloadLink() {
  const url = updateInfo.value?.download_url
  if (!url) return
  try {
    await navigator.clipboard.writeText(url)
    toast('下载链接已复制')
  } catch {
    toast('复制失败，请手动复制链接')
  }
}

// ---- 轻提示 ----
const notice = ref(null)
let _t = 0
function toast(text) {
  notice.value = text
  clearTimeout(_t)
  _t = setTimeout(() => {
    notice.value = null
  }, 2600)
}

onMounted(async () => {
  await loadProfile()
})
</script>

<style scoped>
.set-page {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 20px;
  padding: 26px 30px;
  overflow: hidden;
}
.set-nav {
  width: 176px;
  flex-shrink: 0;
  background: #fff;
  border: 1px solid #e7eaf0;
  border-radius: 14px;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  height: fit-content;
}
.set-nav-item {
  display: flex;
  align-items: center;
  gap: 9px;
  padding: 10px 12px;
  border: none;
  border-radius: 9px;
  background: transparent;
  font-size: 13px;
  color: #4b5563;
  text-align: left;
  cursor: pointer;
  transition: all 0.15s;
}
.set-nav-item:hover {
  background: #f3f5f9;
  color: #1f2937;
}
.set-nav-item.active {
  background: #eaf0fe;
  color: #1d4ed8;
  font-weight: 600;
}
.set-nav-emoji {
  font-size: 15px;
  width: 18px;
  text-align: center;
}
.set-main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}
.set-card {
  background: #fff;
  border: 1px solid #e7eaf0;
  border-radius: 16px;
  padding: 24px 26px;
  max-width: 860px;
}
.set-card-title {
  margin: 0 0 16px;
  font-size: 16px;
  color: #1f2937;
}
.set-card-actions {
  margin-top: 18px;
}

/* 账号 */
.set-profile-head {
  display: flex;
  align-items: center;
  gap: 16px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f1f3f8;
}
.set-avatar {
  width: 58px;
  height: 58px;
  flex-shrink: 0;
  border-radius: 50%;
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  color: #fff;
  font-size: 24px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 20px rgba(37, 99, 235, 0.25);
}
.set-profile-meta h2 {
  margin: 0 0 4px;
  font-size: 18px;
  color: #1f2937;
}
.set-profile-meta p {
  margin: 0;
  font-size: 12.5px;
  color: #9ca3af;
}
.set-rows {
  margin: 0;
  padding: 6px 0;
}
.set-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
  padding: 11px 0;
  border-bottom: 1px solid #f5f6f9;
  font-size: 13px;
}
.set-row dt {
  color: #9ca3af;
}
.set-row dd {
  margin: 0;
  color: #1f2937;
  word-break: break-all;
  text-align: right;
}
.set-row code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  background: #f1f3f8;
  padding: 2px 8px;
  border-radius: 6px;
}

/* 通用 */
.set-block {
  padding: 14px 0;
  border-bottom: 1px solid #f5f6f9;
}
.set-block:last-child {
  border-bottom: none;
}
.set-block-label {
  display: block;
  font-size: 12.5px;
  color: #6b7280;
  margin-bottom: 8px;
  font-weight: 600;
}
.set-inline {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.set-input {
  height: 34px;
  min-width: 260px;
  border: 1px solid #e3e6ee;
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  color: #1f2937;
  outline: none;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.set-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
.set-tip {
  margin: 7px 0 0;
  font-size: 11.5px;
  color: #9ca3af;
  line-height: 1.6;
}
.set-switch-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 13px 0;
  border-bottom: 1px solid #f5f6f9;
}
.set-switch-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.set-switch-text span {
  font-size: 13px;
  color: #1f2937;
  font-weight: 600;
}
.set-switch-text em {
  font-style: normal;
  font-size: 11.5px;
  color: #9ca3af;
}
.set-soon-chip {
  font-size: 10.5px;
  color: #b45309;
  background: #fef3e2;
  border-radius: 999px;
  padding: 2px 10px;
  flex-shrink: 0;
}

/* 开关 */
.set-toggle {
  width: 42px;
  height: 23px;
  border-radius: 999px;
  border: none;
  background: #d7dbe4;
  position: relative;
  cursor: pointer;
  transition: background 0.18s;
  flex-shrink: 0;
}
.set-toggle.on {
  background: #2563eb;
}
.set-toggle-dot {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 17px;
  height: 17px;
  border-radius: 50%;
  background: #fff;
  box-shadow: 0 2px 5px rgba(17, 24, 39, 0.2);
  transition: left 0.18s;
}
.set-toggle.on .set-toggle-dot {
  left: 22px;
}

/* 按钮 */
.set-btn {
  height: 34px;
  padding: 0 16px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.set-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.set-btn.primary {
  background: #2563eb;
  color: #fff;
  font-weight: 600;
}
.set-btn.primary:hover:not(:disabled) {
  background: #1d4ed8;
}
.set-btn.ghost {
  background: #fff;
  border: 1px solid #e3e6ee;
  color: #4b5563;
}
.set-btn.ghost:hover {
  border-color: #c9d6ff;
  color: #2563eb;
}
.set-btn.danger-ghost {
  background: #fff;
  border: 1px solid #fecaca;
  color: #ef4444;
}
.set-btn.danger-ghost:hover {
  background: #fef2f2;
}
.set-btn.inline-link {
  display: inline-flex;
  align-items: center;
  text-decoration: none;
  margin-top: 10px;
}

/* 更新 */
.set-update-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}
.set-update-empty {
  margin-top: 18px;
  padding: 26px 18px;
  text-align: center;
  font-size: 13px;
  color: #9ca3af;
  background: #fafbfd;
  border: 1px dashed #e3e6ee;
  border-radius: 12px;
}
.set-update-empty.err {
  color: #dc2626;
}
.set-update-empty.ok {
  color: #10b981;
  border-color: #baf0dc;
  background: #f4fdf8;
}
.set-update-result {
  margin-top: 10px;
}
.set-update-card {
  border: 1px solid #e3e9ff;
  border-radius: 14px;
  padding: 18px 20px;
  background: linear-gradient(180deg, #f7f9ff, #fff);
}
.set-update-card-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.set-new-flag {
  font-size: 11px;
  font-weight: 600;
  color: #fff;
  background: #f59e0b;
  border-radius: 999px;
  padding: 3px 10px;
}
.set-ver-big {
  font-size: 22px;
  font-weight: 700;
  color: #1f2937;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.set-ver-date {
  font-size: 12px;
  color: #9ca3af;
}
.set-update-notes {
  margin: 12px 0 6px;
  font-size: 13px;
  color: #4b5563;
  line-height: 1.8;
  white-space: pre-line;
}

/* 关于 */
.set-about-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 14px;
}
.set-about-badge {
  width: 54px;
  height: 54px;
  border-radius: 14px;
  background: linear-gradient(135deg, #2563eb, #7c5cff);
  color: #fff;
  font-size: 25px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 8px 22px rgba(37, 99, 235, 0.28);
}
.set-about-name {
  margin: 0;
  font-size: 19px;
  color: #1f2937;
}
.set-about-en {
  margin: 3px 0 0;
  font-size: 12px;
  color: #9ca3af;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.set-about-desc {
  font-size: 13px;
  color: #4b5563;
  line-height: 1.8;
  margin: 6px 0 0;
}
.set-copyright {
  margin: 18px 0 0;
  font-size: 11.5px;
  color: #c3c9d3;
}

/* toast */
.mk-toast {
  position: fixed;
  left: 50%;
  top: 22px;
  transform: translateX(-50%);
  z-index: 300;
  padding: 10px 22px;
  border-radius: 10px;
  font-size: 13px;
  color: #fff;
  background: #1f2937;
  box-shadow: 0 10px 30px rgba(17, 24, 39, 0.25);
}
.mk-fade-enter-active,
.mk-fade-leave-active {
  transition: opacity 0.2s, transform 0.2s;
}
.mk-fade-enter-from,
.mk-fade-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}
</style>
