<template>
  <div class="mk-page">
    <header class="mk-head">
      <div class="mk-titles">
        <h1 class="mk-title">技能市场</h1>
        <p class="mk-sub">浏览和安装智作台专属 AI 技能</p>
      </div>
      <button class="mk-icon-btn" title="管理技能源" aria-label="管理技能源" @click="openSourcesDialog">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06A2 2 0 1 1 4.21 16.96l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>
    </header>

    <!-- 搜索框：整行宽度（放大镜 + 输入框 + 搜索按钮） -->
    <div class="mk-search-row">
      <div class="mk-search-wrap">
        <span class="mk-search-icon" aria-hidden="true">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9ca3af" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <circle cx="11" cy="11" r="7" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </span>
        <input
          v-model.trim="keyword"
          class="mk-search-input"
          placeholder="搜索名称、slug 或 ID"
          @keydown.enter="search"
        />
      </div>
      <button class="mk-act primary" :disabled="loading" @click="search">搜索</button>
    </div>

    <!-- 类型筛选 -->
    <div class="mk-cats mk-cats-cat">
      <button
        v-for="t in typeTiers"
        :key="t.value"
        class="mk-cat"
        :class="{ active: activeType === t.value }"
        @click="pickType(t.value)"
      >{{ t.label }}</button>
    </div>

    <!-- 分类（来自后端） -->
    <div v-if="categories.length > 1" class="mk-cats mk-cats-cat">
      <button
        v-for="c in categories"
        :key="c"
        class="mk-cat"
        :class="{ active: activeCategory === c }"
        @click="pickCategory(c)"
      >{{ c }}</button>
    </div>

    <!-- 内容区 -->
    <div v-if="loading" class="mk-state">技能加载中…</div>
    <div v-else-if="errorText" class="mk-state err">
      <p>{{ errorText }}</p>
      <button class="mk-act primary" @click="load(true)">重试</button>
    </div>
    <template v-else>
      <div v-if="skills.length" class="mk-grid">
        <SkillCard
          v-for="s in skills"
          :key="s.slug"
          :skill="s"
          :busy="busySlug === s.slug"
          :busy-text="busyText"
          @install="doInstall"
          @uninstall="askUninstall"
          @open="openTask"
        />
      </div>
      <div v-else class="mk-state">{{ noSkillsTip }}</div>
    </template>

    <!-- 轻提示 -->
    <transition name="mk-fade">
      <div v-if="notice" class="mk-toast" :class="notice.type" role="status">
        {{ notice.text }}
      </div>
    </transition>

    <!-- 卸载确认 -->
    <div v-if="confirmSkill" class="mk-mask" @click.self="confirmSkill = null">
      <div class="mk-dialog">
        <h3 class="mk-dialog-title">卸载技能</h3>
        <p class="mk-dialog-body">
          确认卸载「{{ confirmSkill.name }}」？该技能的历史会话与消息将保留，
          只是不再出现在对话任务的技能入口中。
        </p>
        <div class="mk-dialog-actions">
          <button class="mk-act ghost" @click="confirmSkill = null">取消</button>
          <button class="mk-act danger" :disabled="busySlug === confirmSkill.slug" @click="doUninstall">
            {{ busySlug === confirmSkill.slug ? '卸载中…' : '确认卸载' }}
          </button>
        </div>
      </div>
    </div>

    <!-- 技能源管理 -->
    <div v-if="showSources" class="mk-mask" @click.self="showSources = false">
      <div class="mk-dialog wide">
        <div class="src-head">
          <h3 class="mk-dialog-title">技能源 · GitHub 发布仓库</h3>
          <button class="mk-close" title="关闭" @click="showSources = false">×</button>
        </div>
        <div class="src-form">
          <input
            v-model.trim="sourceInput"
            class="mk-input"
            placeholder="owner/repo 或 https://github.com/owner/repo"
            @keydown.enter="addSource"
          />
          <button class="mk-act primary" :disabled="sourceBusy || !sourceInput" @click="addSource">
            添加
          </button>
        </div>
        <p class="src-hint">
          将技能打包为 .xskill 并发布到该仓库的 GitHub Release，添加后即可同步到市场。
        </p>

        <div v-if="sourcesLoading" class="mk-state small">技能源加载中…</div>
        <ul v-else-if="sources.length" class="src-list">
          <li v-for="r in sources" :key="r.id" class="src-row">
            <div class="src-main">
              <div class="src-label">
                {{ r.label || r.source_key }}
                <span class="src-key">{{ r.source_key }}</span>
              </div>
              <div v-if="r.fetch_error" class="src-err" :title="r.fetch_error">上次同步失败，点击「立即同步」重试</div>
              <div class="src-sub">
                {{ r.skill_count }} 个技能 · {{ r.enabled ? '已启用' : '已停用' }} · 上次同步
                {{ r.last_fetched_at ? timeAgo(r.last_fetched_at) : '从未' }}
              </div>
            </div>
            <div class="src-actions">
              <button class="mk-act ghost mini" @click="toggleSource(r)">
                {{ r.enabled ? '停用' : '启用' }}
              </button>
              <button class="mk-act ghost mini danger" @click="removeSource(r)">删除</button>
            </div>
          </li>
        </ul>
        <div v-else class="mk-state small">还没有技能源，添加一个 GitHub 仓库即可开始</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import api from '@/api/client'
import { useChatStore } from '@/stores/chat'
import SkillCard from '@/components/SkillCard.vue'
import {
  fetchMarket,
  fetchCategories,
  fetchInstalled,
  installSkill,
  uninstallSkill,
  fetchSources,
  addSource as apiAddSource,
  patchSource,
  removeSource as apiRemoveSource,
} from '@/api/skills'

const router = useRouter()
const chat = useChatStore()

const skills = ref([])
const categories = ref(['全部'])
const activeCategory = ref('全部')
const keyword = ref('')
const loading = ref(true)
const errorText = ref('')
const searched = ref(false)

// 忙碌态（按 slug 区分，同一技能卡片只允许一个进行中操作）
const busySlug = ref('')
const busyAction = ref('')

// 类型筛选（顶部独立行：全部 / 标准版 / 定制版）—— 纯前端展示，
// 暂无后端字段对应；保留交互便于后续与 tdesign Chips 对齐
const typeTiers = [
  { label: '全部', value: '' },
  { label: '标准版', value: 'standard' },
  { label: '定制版', value: 'custom' },
]
const activeType = ref('')

function pickType(v) {
  if (activeType.value === v) return
  activeType.value = v
  search()
}

const notice = ref(null)
let _noticeTimer = 0
function toast(text, type = 'ok') {
  notice.value = { text, type }
  clearTimeout(_noticeTimer)
  _noticeTimer = setTimeout(() => {
    notice.value = null
  }, 3200)
}

function verGt(a, b) {
  const pa = String(a || '').split('.').map((n) => parseInt(n, 10) || 0)
  const pb = String(b || '').split('.').map((n) => parseInt(n, 10) || 0)
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0
    const y = pb[i] || 0
    if (x !== y) return x > y
  }
  return false
}

async function load(force) {
  loading.value = true
  errorText.value = ''
  try {
    const params = {}
    if (searched.value || force || keyword.value) params.search = keyword.value
    if (activeCategory.value && activeCategory.value !== '全部') params.category = activeCategory.value
    const [marketRes, instRes, catRes] = await Promise.all([
      fetchMarket(params),
      fetchInstalled(),
      fetchCategories(),
    ])
    const instMap = {}
    for (const s of instRes.data.skills || []) instMap[s.slug] = s
    skills.value = (marketRes.data.skills || []).map((s) => {
      const inst = instMap[s.slug]
      const statusOk = !!inst && inst.status === 'ok'
      return {
        ...s,
        is_installed: statusOk,
        is_failed: !!inst && inst.status === 'failed',
        failed_error: (inst && inst.error) || '',
        upgradable: statusOk && verGt(s.version, inst.version),
      }
    })
    const cats = catRes.data.categories || []
    if (cats.length) categories.value = cats
  } catch (e) {
    errorText.value = e?.response?.data?.detail || '技能市场加载失败，请检查后端服务'
  } finally {
    loading.value = false
  }
}

function search() {
  searched.value = !!keyword.value
  load()
}

function pickCategory(c) {
  if (activeCategory.value === c && !searched.value) return
  activeCategory.value = c
  search()
}

const noSkillsTip = computed(() => {
  if (searched.value) return '没有找到匹配的技能，换个关键词试试'
  if (errorText.value) return ''
  return '市场暂无技能。请先在「管理技能源」中添加一个发布技能的 GitHub 仓库并同步。'
})

// ---- 安装 / 卸载 / 打开任务 ----
async function doInstall(skill) {
  busySlug.value = skill.slug
  busyAction.value = 'install'
  try {
    const { data } = await installSkill(skill.slug)
    toast(data.upgrade ? `已升级「${skill.name}」` : `技能「${skill.name}」安装成功，可去对话任务使用`)
    await load()
    // 同步刷新全局 store 中的已安装技能列表，确保对话任务页即时感知变化
    const chat = useChatStore()
    await chat.loadInstalledSkills()
  } catch (e) {
    toast(e?.response?.data?.detail || '安装失败，请稍后重试', 'err')
    await load()
  } finally {
    busySlug.value = ''
    busyAction.value = ''
  }
}

function askUninstall(skill) {
  confirmSkill.value = skill
}

const confirmSkill = ref(null)

async function doUninstall() {
  const skill = confirmSkill.value
  if (!skill) return
  busySlug.value = skill.slug
  busyAction.value = 'uninstall'
  try {
    await uninstallSkill(skill.slug)
    confirmSkill.value = null
    toast(`技能「${skill.name}」已卸载`)
    await load()
    // 同步刷新全局 store 中的已安装技能列表，确保对话任务页即时移除该技能入口
    const chat = useChatStore()
    await chat.loadInstalledSkills()
  } catch (e) {
    toast(e?.response?.data?.detail || '卸载失败，请稍后重试', 'err')
  } finally {
    busySlug.value = ''
    busyAction.value = ''
  }
}

/** 打开技能任务：创建/复用专属会话后跳转对话任务页 */
async function openTask(skill) {
  try {
    const { data } = await api.post('/conversations', { skill_id: skill.slug })
    chat.requestOpenConversation(data.conversation_id)
    router.push('/tasks')
  } catch (e) {
    toast(e?.response?.data?.detail || '打开技能任务失败', 'err')
  }
}

// ---- 技能源管理 ----
const showSources = ref(false)
const sourcesLoading = ref(false)
const sources = ref([])
const sourceInput = ref('')
const sourceBusy = ref(false)

async function openSourcesDialog() {
  showSources.value = true
  await refreshSources()
}

async function refreshSources() {
  sourcesLoading.value = true
  try {
    const { data } = await fetchSources()
    sources.value = data.sources || []
  } catch (e) {
    toast(e?.response?.data?.detail || '技能源加载失败', 'err')
  } finally {
    sourcesLoading.value = false
  }
}

async function addSource() {
  if (!sourceInput.value) return
  sourceBusy.value = true
  try {
    const { data } = await apiAddSource(sourceInput.value)
    sourceInput.value = ''
    if (data.sync && data.sync.ok) {
      toast(`已添加技能源并同步成功：${data.source.source_key}`)
    } else {
      toast(`技能源已添加，但首次同步失败：${data.sync?.error || '未知错误'}`, 'err')
    }
    await refreshSources()
    await load()
  } catch (e) {
    toast(e?.response?.data?.detail || '添加技能源失败', 'err')
  } finally {
    sourceBusy.value = false
  }
}

async function toggleSource(r) {
  try {
    await patchSource(r.id, { enabled: !r.enabled })
    await refreshSources()
  } catch (e) {
    toast(e?.response?.data?.detail || '操作失败', 'err')
  }
}

async function removeSource(r) {
  if (!window.confirm(`确认删除技能源「${r.label || r.source_key}」？将同时清理该源同步出的市场快照。`)) return
  try {
    await apiRemoveSource(r.id)
    toast('技能源已删除')
    await refreshSources()
    await load()
  } catch (e) {
    toast(e?.response?.data?.detail || '删除失败', 'err')
  }
}

const busyText = computed(() =>
  busyAction.value === 'uninstall' ? '卸载中…' : '安装中…'
)

function timeAgo(iso) {
  const diff = Date.now() - new Date(iso).getTime()
  if (diff < 60000) return '刚刚'
  const min = Math.floor(diff / 60000)
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  return `${Math.floor(hr / 24)} 天前`
}

onMounted(() => load())
</script>

<style scoped>
.mk-page {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 26px 30px 40px;
}
.mk-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}
.mk-title {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 700;
  color: #1f2937;
}
.mk-sub {
  margin: 0;
  font-size: 13px;
  color: #9ca3af;
}


.mk-cats {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.mk-cat {
  border: 1px solid #e7eaf0;
  background: #fff;
  color: #4b5563;
  font-size: 12.5px;
  padding: 6px 14px;
  border-radius: 999px;
  cursor: pointer;
  transition: all 0.15s;
}
.mk-cat:hover {
  border-color: #c9d6ff;
  color: #2563eb;
}
.mk-cat.active {
  background: #2563eb;
  border-color: #2563eb;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.22);
}

.mk-input {
  height: 36px;
  border: 1px solid #e3e6ee;
  border-radius: 9px;
  padding: 0 12px;
  font-size: 13px;
  color: #1f2937;
  background: #fff;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  min-width: 220px;
}
.mk-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}
.mk-act {
  height: 36px;
  padding: 0 14px;
  border: none;
  border-radius: 9px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.mk-act:disabled {
  opacity: 0.55;
  cursor: default;
}
.mk-act.primary {
  background: #2563eb;
  color: #fff;
  font-weight: 600;
}
.mk-act.primary:hover:not(:disabled) {
  background: #1d4ed8;
}
.mk-act.primary-ghost {
  background: #eef3ff;
  color: #1d4ed8;
  font-weight: 600;
}
.mk-act.primary-ghost:hover {
  background: #e0e9ff;
}
.mk-act.ghost {
  background: #fff;
  border: 1px solid #e3e6ee;
  color: #4b5563;
}
.mk-act.ghost:hover:not(:disabled) {
  border-color: #c9d6ff;
  color: #2563eb;
}
.mk-act.ghost.mini {
  height: 26px;
  font-size: 12px;
  padding: 0 10px;
}
.mk-act.danger {
  background: #ef4444;
  color: #fff;
  font-weight: 600;
}
.mk-act.danger:hover:not(:disabled) {
  background: #dc2626;
}
.mk-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 14px;
}
.mk-state {
  padding: 64px 20px;
  text-align: center;
  color: #9ca3af;
  font-size: 14px;
}
.mk-state.err {
  color: #dc2626;
}
.mk-state.small {
  padding: 24px 12px;
  font-size: 13px;
}
.mk-state .mk-act {
  margin-top: 14px;
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
.mk-toast.err {
  background: #ef4444;
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

/* 弹窗 */
.mk-mask {
  position: fixed;
  inset: 0;
  z-index: 200;
  background: rgba(17, 24, 39, 0.38);
  display: flex;
  align-items: center;
  justify-content: center;
  backdrop-filter: blur(2px);
}
.mk-dialog {
  width: 420px;
  max-width: calc(100vw - 48px);
  background: #fff;
  border-radius: 16px;
  padding: 22px 24px;
  box-shadow: 0 24px 64px rgba(17, 24, 39, 0.24);
  max-height: 84vh;
  overflow-y: auto;
}
.mk-dialog.wide {
  width: 560px;
}
.mk-dialog-title {
  margin: 0 0 12px;
  font-size: 16px;
  color: #1f2937;
}
.mk-dialog-body {
  margin: 0 0 18px;
  font-size: 13px;
  color: #6b7280;
  line-height: 1.7;
}
.mk-dialog-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
.mk-close {
  border: none;
  background: #f1f3f8;
  width: 28px;
  height: 28px;
  border-radius: 8px;
  font-size: 17px;
  color: #6b7280;
  cursor: pointer;
  line-height: 1;
}
.mk-close:hover {
  background: #e5e9f2;
}

/* 技能源 */
.src-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
}
.src-head .mk-dialog-title {
  margin: 0;
}
.src-form {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.src-form .mk-input {
  flex: 1;
}
.src-hint {
  margin: 0 0 12px;
  font-size: 11.5px;
  color: #9ca3af;
}
.src-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.src-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #eef0f5;
  border-radius: 11px;
  padding: 10px 12px;
  background: #fafbfd;
}
.src-main {
  min-width: 0;
}
.src-label {
  font-size: 13px;
  color: #1f2937;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}
.src-key {
  font-size: 11px;
  color: #9ca3af;
  font-weight: 400;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}
.src-sub {
  margin-top: 3px;
  font-size: 11px;
  color: #9ca3af;
}
.src-err {
  margin-top: 3px;
  font-size: 11px;
  color: #dc2626;
}
.src-actions {
  display: flex;
  gap: 6px;
  flex-shrink: 0;
}

/* 搜索框：整行宽度（放大镜 + 输入 + 搜索按钮） */
.mk-search-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.mk-search-wrap {
  flex: 1;
  position: relative;
}
.mk-search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  display: inline-flex;
  pointer-events: none;
}
.mk-search-input {
  width: 100%;
  height: 38px;
  border: 1px solid #e3e6ee;
  border-radius: 9px;
  padding: 0 12px 0 36px;
  font-size: 13px;
  color: #1f2937;
  background: #fff;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.mk-search-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12);
}

/* 第二行分类（紧贴搜索行） */
.mk-cats.mk-cats-cat {
  margin-top: 10px;
}

/* 标题右侧图标按钮（管理技能源） */
.mk-icon-btn {
  width: 36px;
  height: 36px;
  border: 1px solid #e3e6ee;
  background: #fff;
  color: #4b5563;
  border-radius: 9px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
  flex-shrink: 0;
}
.mk-icon-btn:hover {
  border-color: #c9d6ff;
  color: #2563eb;
  background: #f5f8ff;
}
</style>
