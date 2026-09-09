<template>
  <div class="chat-layout">
    <!-- 左侧栏 -->
    <aside class="sidebar">
      <div class="sidebar-top">
        <div class="sidebar-top-title">对话任务</div>
        <button class="new-btn" @click="newConversation">＋ 新建任务</button>
      </div>

      <!-- 技能任务：每个已安装技能一张专属任务入口卡片 -->
      <div v-if="installedSkills.length" class="task-section">
        <div class="task-section-head">
          <span class="task-section-title">技能任务</span>
          <button class="task-section-more" title="去技能市场安装 / 管理技能" @click="router.push('/market')">去市场</button>
        </div>
        <TaskCard
          v-for="s in installedSkills"
          :key="s.slug"
          :skill="s"
          :active="currentSkillSlug === s.slug"
          @open="openSkillTask"
        />
      </div>

      <div class="conv-list">
        <template v-for="g in timeGroups" :key="g.key">
          <div class="conv-group-title">{{ g.label }}</div>
          <div
            v-for="c in g.list"
            :key="c.conversation_id"
            :class="['conv-item', { active: c.conversation_id === currentId }]"
            @click="selectConversation(c.conversation_id)"
          >
            <span v-if="c.skill_id" class="conv-emoji" aria-hidden="true">{{ skillEmojiOf(c) }}</span>
            <span class="conv-title">{{ c.title || '新对话' }}</span>
          </div>
        </template>
        <div v-if="!filteredConversationCount" class="conv-empty">暂无会话</div>
      </div>

    </aside>

    <!-- 右侧栏 -->
    <main class="main">
      <header class="topbar">
        <div class="topbar-left">
          <div class="topbar-title">智作台 · 对话任务</div>
          <div v-if="activeSkill" class="topbar-skill">
            <span class="topbar-skill-emoji">{{ activeSkill.emoji || '🧩' }}</span>
            <span class="topbar-skill-name">{{ activeSkill.name }}</span>
            <span class="topbar-skill-slug">{{ activeSkill.slug }}</span>
          </div>
        </div>
        
      </header>


      <div class="messages" ref="messagesEl" @scroll="onMessagesScroll">
        <div v-if="!messages.length" class="empty-hint">
          <div class="empty-logo">✨</div>
          <p>开始和智作台聊聊吧</p>
        </div>

        <div
          v-for="(m, i) in messages"
          :key="i"
          :class="['msg', m.role === 'user' ? 'msg-user' : 'msg-bot']"
        >
          <div class="msg-avatar">{{ m.role === 'user' ? userAvatarText : botAvatarText }}</div>

          <template v-if="m.role === 'user'">
            <div class="msg-user-col">
              <!-- 横向行：retry 与 msg-body 水平排列，配合 row-reverse 让 retry 落在气泡左侧并与气泡垂直居中 -->
              <div class="msg-user-row">
                <div v-if="canRetry(i) && (!m.versions || m.currentVersion === m.versions.length - 1)" class="msg-actions user-actions user-actions-retry">
                  <button class="icon-btn retry-btn" data-tooltip="重试" @click="retryUserMsg(i)">
                    <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="23 4 23 10 17 10"></polyline>
                      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path>
                    </svg>
                  </button>
                </div>
                <div
                    :class="['msg-body', { 'msg-body-editing': editingIndex === i }]"
                    :style="editingIndex === i && editWidth ? { width: editWidth + 'px' } : {}"
                  >
                  <template v-if="editingIndex === i">
                    <div class="edit-box">
                      <textarea
                        v-model="editingText"
                        class="edit-input"
                        rows="1"
                        @keydown.enter.exact.prevent="sendEdit"
                      ></textarea>
                      <div class="edit-actions">
                        <div class="edit-actions-right">
                          <button class="edit-link-btn" data-tooltip="从本地选取" @click="pickEditFile" aria-label="从本地选取文件">
                            <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                            </svg>
                          </button>
                          <button class="edit-cancel" @click="cancelEdit">Cancel</button>
                          <button class="edit-send" :disabled="!editingText.trim()" @click="sendEdit">Send</button>
                        </div>
                      </div>
                    </div>
                  </template>
                  <template v-else>
                    <div class="msg-content">{{ m.content }}</div>
                  </template>
                </div>
              </div>
              <div class="msg-actions user-actions user-actions-below">
                <div class="user-actions-right">
                  <button class="icon-btn" :data-tooltip="copiedIndex === i ? '已复制' : 'Copy'" @click="copyMessage(m.content, i)">
                    <svg v-if="copiedIndex === i" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                  </button>
                  <button class="icon-btn" data-tooltip="编辑" @click="editUserMsg(i)">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                    </svg>
                  </button>
                  <span v-if="m._displayTime" class="msg-time">{{ formatTime(m._displayTime) }}</span>
                  <div v-if="m.versions && m.versions.length > 1" class="version-nav">
                    <button class="version-arrow" :disabled="m.currentVersion <= 0" @click="switchVersion(i, m.currentVersion - 1)">
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="15 18 9 12 15 6"></polyline>
                      </svg>
                    </button>
                    <!-- 分页显示：用 viewVersion 兜底 currentVersion，避免 saveCurrentReply / typingTimers
                         完成等路径意外把 currentVersion 重置回 last 时，pagination 卡在最新版本。 -->
                    <span class="version-text">{{ ((m.viewVersion ?? m.currentVersion) + 1) }} / {{ m.versions.length }}</span>
                    <button class="version-arrow" :disabled="m.currentVersion >= m.versions.length - 1" @click="switchVersion(i, m.currentVersion + 1)">
                      <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="9 18 15 12 9 6"></polyline>
                      </svg>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- bot 消息：操作栏移出气泡，在气泡外侧显示（截图 1 风格） -->
          <template v-else>
            <div class="msg-bot-col">
              <div class="msg-body">
                <!-- 思考中 / 工具执行中：根据工具状态显示不同提示（≥10s 显示已耗时） -->
                <div v-if="m.thinking" class="typing">
                  <span class="dot"></span><span class="dot"></span><span class="dot"></span>
                  <span class="tool-info">{{ toolStatusText(m) }}<template v-if="thinkElapsed(m) >= 10"> · 已 {{ thinkElapsed(m) }} 秒</template></span>
                </div>
                <!-- 工具结果摘要（仅在 final 前收到 tool_result 时短暂展示） -->
                <div v-else-if="m.toolStatus && !m.content" class="typing tool-result-summary">
                  <span class="tool-info">{{ toolStatusText(m) }}</span>
                </div>
                <!-- 打字机播放中 / 已完成：逐字显示文本，播放时光标闪烁 -->
                <div v-else class="msg-content" :class="{ playing: m.playing }">{{ m.content }}</div>
              </div>
              <!-- 操作栏：在气泡外（截图 1 风格：复制 + 时间戳 在左，Continue 在右） -->
              <div v-if="!m.thinking && m.content" class="msg-actions bot-actions">
                <div class="bot-actions-left">
                  <button class="icon-btn" :data-tooltip="copiedIndex === i ? '已复制' : 'Copy'" @click="copyMessage(m.content, i)">
                    <svg v-if="copiedIndex === i" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                    <svg v-else viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                      <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                    </svg>
                  </button>
                  <span v-if="m._displayTime" class="msg-time">{{ formatTime(m._displayTime) }}</span>
                </div>
                <button v-if="m.stopped && isLatestVersion(i)" class="continue-btn" @click="continueBotMsg(i)">Continue</button>
              </div>
            </div>
          </template>
        </div>
      </div>

      <button v-if="!isAtBottom" class="jump-bottom-btn" @click="jumpToBottom" title="回到最新消息">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round" stroke-linejoin="round">
          <polyline points="6 9 12 15 18 9"></polyline>
        </svg>
        <span>回到底部</span>
      </button>

      <div class="composer">
        <textarea
          v-model="inputText"
          class="composer-input"
          placeholder="Enter 发送，Shift+Enter 换行"
          :disabled="!wsOpen"
          @keydown.enter.exact.prevent="onEnter"
        ></textarea>
        <!-- 发送 / 停止 共用同一个按钮：未在生成时为「发送」(向上箭头)，
             生成中时切换为「停止」(圆角方块)，互斥显示，避免出现两个按钮。
             注意「生成中」= 后端 agent 运行中(isStreaming) 或 前端打字机仍在播放(anyTyping)：
             final/done 事件到达后 activeRuns 即被清空，但打字机还要播好几秒，
             若只看 isStreaming，按钮会在打字机播放期间提前变回「发送」。 -->
        <button
          v-if="isStreaming || anyTyping"
          class="action-btn stop-btn"
          @click="stop"
          title="停止生成"
        >
          <!-- 圆角方块：rx=3 让边角更圆滑，与截图一致 -->
          <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
            <rect x="6" y="6" width="12" height="12" rx="3" ry="3"></rect>
          </svg>
        </button>
        <template v-else>
          <!-- 非生成态：在 Send 左边显示「从本地选取」纸夹按钮（截图 3） -->
          <button class="composer-attach" data-tooltip="从本地选取" @click="pickComposerFile" aria-label="从本地选取文件">
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
            </svg>
          </button>
          <button
            class="action-btn send-btn"
            @click="send"
            :disabled="!wsOpen || !inputText.trim()"
            title="发送"
          >
            <!-- 向上箭头：粗一点的 stroke 与加宽的图标尺寸与截图一致 -->
            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="12" y1="19" x2="12" y2="6"></line>
              <polyline points="5 12 12 5 19 12"></polyline>
            </svg>
          </button>
        </template>
      </div>
      <div v-if="!wsOpen" class="ws-warn">连接未就绪，正在重连…</div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, nextTick, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import api from '@/api/client'
import TaskCard from '@/components/TaskCard.vue'

const auth = useAuthStore()
const store = useChatStore()
const router = useRouter()

const inputText = ref('')
const messagesEl = ref(null)
const editingIndex = ref(-1)
const editingText = ref('')
const copiedIndex = ref(-1)

// 思考耗时计时：每 5s 心跳一次，驱动「已 N 秒」显示（长任务等待可感知）
const nowTick = ref(Date.now())
let thinkTimer = null

/** 当前气泡已思考秒数（懒初始化起点；≥10s 才显示，短回复不打扰） */
function thinkElapsed(m) {
  if (!m._thinkStart || m._thinkStart > Date.now()) m._thinkStart = Date.now()
  return Math.max(0, Math.round((nowTick.value - m._thinkStart) / 1000))
}
const editWidth = ref(0)   // 编辑框宽度：动态跟随紧随的 agent 回复气泡宽度

// 用 storeToRefs 解构，保证模板中的响应式
const {
  conversations,
  currentId,
  messages,
  wsOpen,
  isStreaming,
  pendingIndex,
  installedSkills,
  installedMap,
  installedSlugs,
} = storeToRefs(store)

/** 前端打字机是否仍在播放（存在 playing 态的 assistant 气泡）。
 *  与 isStreaming（后端 agent 运行中）互补：final 之后 done 会清空 activeRuns，
 *  但打字机还在逐字播放，这期间停止按钮也必须保持可见、可点击。 */
const anyTyping = computed(
  () => messages.value.some((m) => m.role === 'assistant' && m.playing)
)

/** 当前会话是否为某技能的专属会话 */
const currentSkillSlug = computed(() => {
  const cur = conversations.value.find((c) => c.conversation_id === currentId.value)
  return (cur && cur.skill_id) || ''
})

/** 顶栏展示的当前技能：仅在「该技能仍处于已安装」时展示，避免卸载后顶栏出现幽灵技能徽标。
 *  卸载后顶栏回到普通模式（智作台 · 对话任务），同时 sessions 中该技能的会话也会被过滤掉，
 *  避免出现「对话消息区域在渲染已卸载技能的内容、但左侧任务列表却不显示该技能」的不一致。 */
const activeSkill = computed(() => {
  const slug = currentSkillSlug.value
  if (!slug) return null
  // 若该技能已不在 installedSlugs 中，则视为已卸载，不再展示顶栏技能徽标
  if (!installedSlugs.value.has(slug)) return null
  const conv = conversations.value.find((c) => c.conversation_id === currentId.value)
  const inst = installedMap.value[slug]
  return {
    slug,
    name: (inst && inst.name) || (conv && conv.title) || slug,
    emoji: (inst && inst.emoji) || '🧩',
  }
})

function skillEmojiOf(c) {
  const s = installedMap.value[c.skill_id]
  return (s && s.emoji) || '🧩'
}

/** 用户消息头像：中文昵称取第一个字、英文昵称取大写首字母；都没取到时回退"我" */
const userAvatarText = computed(() => {
  const u = auth.user || {}
  const raw = u.nickname || u.username || '我'
  const ch = raw[0]
  if (!ch) return '我'
  // 拉丁字母 → 大写首字母；中文/其它文字保持原样
  return /[A-Za-z]/.test(ch) ? ch.toUpperCase() : ch
})

/** bot 消息头像：
 *  - 当前会话是某技能专属会话 → 用该技能的 emoji（与技能市场/任务卡片一致）；
 *  - 普通智作台会话 → 显示"智"字（平台标识）。 */
const botAvatarText = computed(() => (activeSkill.value ? activeSkill.value.emoji || '🧩' : '智'))

/** 点击技能任务卡片：创建/复用该技能的专属会话并打开 */
async function openSkillTask(skill) {
  if (!skill || skill.status === 'failed') return
  following.value = true
  try {
    const { data } = await api.post('/conversations', { skill_id: skill.slug })
    if (data.conversation_id === currentId.value) {
      await store.fetchHistory(data.conversation_id)
      scrollToBottom()
      return
    }
    await store.selectConversation(data.conversation_id)
    scrollToBottom()
  } catch (e) {
    console.error('打开技能任务失败', e?.response?.data?.detail || e)
  }
}

function dayDiffFromToday(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return 9999
  const t = new Date(d.getFullYear(), d.getMonth(), d.getDate())
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  return Math.round((today - t) / 86400000)
}

const timeGroups = computed(() => {
  const buckets = [
    { key: 'today', label: '今天', list: [] },
    { key: 'yesterday', label: '昨天', list: [] },
    { key: 'last7', label: '过去 7 天', list: [] },
    { key: 'last30', label: '过去 30 天', list: [] },
    { key: 'earlier', label: '更早', list: [] },
  ]
  // 已卸载技能的专属会话不再展示在对话任务列表中
  // （数据库仍保留历史会话，重新安装该技能后会重新出现在列表里）
  const installedSet = installedSlugs.value
  for (const c of conversations.value) {
    if (c.skill_id && !installedSet.has(c.skill_id)) continue
    const diff = dayDiffFromToday(c.updated_at)
    let b
    if (diff <= 0) b = buckets[0]
    else if (diff === 1) b = buckets[1]
    else if (diff <= 7) b = buckets[2]
    else if (diff <= 30) b = buckets[3]
    else b = buckets[4]
    b.list.push(c)
  }
  return buckets.filter((b) => b.list.length)
})

/** 过滤后剩余的会话总数（用于空态展示判断；含已卸载技能专属会话时被过滤掉） */
const filteredConversationCount = computed(() => {
  const installedSet = installedSlugs.value
  let n = 0
  for (const c of conversations.value) {
    if (c.skill_id && !installedSet.has(c.skill_id)) continue
    n++
  }
  return n
})

function selectConversation(id) {
  following.value = true
  store.selectConversation(id).then(scrollToBottom)
}

function newConversation() {
  following.value = true
  store.newConversation()
}

// 是否“跟随”：默认 true（在底部正常看最新输出时自动跟随）。
// 用户一旦向上滚动离开底部，就置为 false 并停止自动跟随；
// 此后即使再滑回底部，也不会自动恢复跟随（需点“回到底部”或发新消息）。
const following = ref(true)
// 是否真正贴底（仅控制「回到底部」按钮显隐，与是否自动跟随无关）
const isAtBottom = ref(true)

function scrollToBottom() {
  // 仅当处于跟随模式才自动滚动，否则保留用户当前查看的位置
  if (!following.value) return
  nextTick(() => {
    const el = messagesEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

// 用户主动滚动：只要离开底部就关闭跟随；滑回底部不重新开启跟随。
function onMessagesScroll() {
  const el = messagesEl.value
  if (!el) return
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  if (distance >= 40) following.value = false
  isAtBottom.value = distance < 40
}

// 主动回到最新：恢复跟随并滚到底部（按钮 / 发新消息时调用）
function jumpToBottom() {
  following.value = true
  isAtBottom.value = true
  scrollToBottom()
}

function onEnter(e) {
  if (e.isComposing || e.keyCode === 229) return
  e.preventDefault()
  send()
}

function send() {
  const text = inputText.value.trim()
  if (!text || !wsOpen.value) return
  inputText.value = ''
  store.sendMessage(text, {
    versions: [{ content: text, reply: null }],
    currentVersion: 0,
  })
  following.value = true
  scrollToBottom()
}

function stop() {
  // 1) 停掉所有正在播放的打字机：定格已输出的部分为「已停止」，
  //    并把部分回复写回版本数据（Continue / 切版本都依赖它）。
  //    需逐条处理而不能只清 typingTimers —— 否则气泡停留在 playing 态，
  //    消息不标 stopped（Continue 按钮不出现）、部分内容也不落版本。
  for (let i = 0; i < messages.value.length; i++) {
    const m = messages.value[i]
    if (m.role !== 'assistant' || !m.playing) continue
    clearBubbleTypewriter(m)   // 清定时器 + 从 typingTimers 移除 + 置空 _typewriterTimer
    m.playing = false
    if (!m._frozen) {
      m.stopped = true
      saveCurrentReply(i)      // 已输出的部分内容存为该版本回复
    }
  }
  // 2) 兜底清理可能残余的定时器（如冻结态消息的定时器）
  typingTimers.forEach((t) => clearInterval(t))
  typingTimers.length = 0
  // 3) 取消后端仍在进行的 agent 运行（打字机阶段 activeRuns 已空，此调用无副作用）
  store.stopGenerating()
}

async function copyMessage(text, index) {
  try {
    await navigator.clipboard.writeText(text || '')
    copiedIndex.value = index
    setTimeout(() => {
      if (copiedIndex.value === index) copiedIndex.value = -1
    }, 2000)
  } catch (e) {
    console.error('复制失败', e)
  }
}

/** 通过 Tauri dialog 选取本地文件（仅 Tauri WebView 可用）。
 *  返回选中的绝对路径，单选模式；取消或失败返回 null。 */
async function pickLocalFile() {
  try {
    const { open } = await import('@tauri-apps/plugin-dialog')
    const result = await open({ multiple: false, directory: false })
    if (typeof result === 'string' && result) return result
    return null
  } catch (e) {
    console.warn('本地文件选择不可用（开发模式浏览器或 Tauri 插件未注入）:', e?.message || e)
    return null
  }
}

/** 编辑框：从本地选取文件，把路径以「[附件: ...]」插入文本末尾 */
async function pickEditFile() {
  const path = await pickLocalFile()
  if (!path) return
  const sep = editingText.value && !editingText.value.endsWith('\n') ? '\n' : ''
  editingText.value = `${editingText.value}${sep}[附件: ${path}]\n`
}

/** composer：从本地选取文件，把路径以「[附件: ...]」插入输入末尾 */
async function pickComposerFile() {
  const path = await pickLocalFile()
  if (!path) return
  const sep = inputText.value && !inputText.value.endsWith('\n') ? '\n' : ''
  inputText.value = `${inputText.value}${sep}[附件: ${path}]\n`
}

/** 用户消息后是否有被暂停的回复（暂停后才显示操作栏） */
function hasPendingReply(userIndex) {
  const next = messages.value[userIndex + 1]
  if (!next || next.role !== 'assistant') return false
  return next.stopped
}

/** 是否可以重试：被暂停且 agent 还没给出任何回复 */
function canRetry(userIndex) {
  const next = messages.value[userIndex + 1]
  if (!next || next.role !== 'assistant') return false
  return next.stopped && !next.content
}

function retryUserMsg(index) {
  if (isStreaming.value) {
    stop()
  }
  const text = messages.value[index].content
  const next = messages.value[index + 1]
  const userMsgId = messages.value[index].message_id

  // 如果后面的 bot 消息没有内容且是最后一条，复用它重新触发，不要创建新会话
  if (next && next.role === 'assistant' && !next.content && index + 1 === messages.value.length - 1) {
    next.stopped = false
    next.thinking = true; next._thinkStart = Date.now()
    next.playing = false
    next.tool = ''
    next.toolStatus = ''
    next.toolResult = ''
    next._fullReply = ''
    store.resendMessage(text, index + 1, { mode: 'regenerate', messageId: userMsgId })
    scrollToBottom()
    return
  }

  // 删除旧的被停止的 assistant 回复（如果有的话）
  if (next && next.role === 'assistant' && next.stopped) {
    messages.value.splice(index + 1, 1)
  }
  // 在消息列表末尾追加重试：复制用户消息 + 新的 assistant 占位
  const newId =
    (crypto && crypto.randomUUID && crypto.randomUUID()) ||
    `m_${Date.now()}_${Math.random().toString(36).slice(2)}`
  messages.value.push({
    role: 'user', content: text, message_id: newId,
    version: 1, versions: [{ content: text, reply: null }], currentVersion: 0,
    viewVersion: 0,
  })
  messages.value.push({
    role: 'assistant',
    content: '',
    thinking: true,
    playing: false,
    tool: '',
    _fullReply: '',
  })
  store.resendMessage(text, messages.value.length - 1, { mode: 'send', messageId: newId })
  scrollToBottom()
}

/** 进入编辑态后，测量紧随其后的 agent 回复气泡宽度，让编辑框与其等宽（左右对齐） */
function measureEditWidth(index) {
  const root = messagesEl.value
  if (!root) return
  const msgEls = root.querySelectorAll('.msg')
  const botEl = msgEls[index + 1]
  if (!botEl) return
  const bubble = botEl.querySelector('.msg-body')
  if (!bubble) return
  editWidth.value = Math.max(320, bubble.offsetWidth)
}

function editUserMsg(index) {
  const m = messages.value[index]
  // 如果当前不是最新版本，先自动切到最新版本再编辑
  if (m.versions && m.currentVersion !== m.versions.length - 1) {
    switchVersion(index, m.versions.length - 1)
  }
  editingIndex.value = index
  editingText.value = messages.value[index].content
  // 编辑框宽度 = 紧随的 agent 回复气泡宽度
  nextTick(() => measureEditWidth(index))
}

function cancelEdit() {
  editingIndex.value = -1
  editingText.value = ''
}

function sendEdit() {
  const text = editingText.value.trim()
  if (!text || editingIndex.value < 0) return

  const userMsg = messages.value[editingIndex.value]
  const messageId = userMsg.message_id
  // 编辑前记录原始 seq：重生成时仅取该位置之前的历史作为上下文，
  // 避免后续「打」等消息反向影响本回复；与编辑后挪到底部无关。
  const originalSeq = userMsg.seq

  // 兜底：缺少 message_id（极少见）时退化为纯前端替换紧随的 assistant
  if (!messageId) {
    const insertIndex = editingIndex.value + 1
    const next = messages.value[insertIndex]
    if (next && next.role === 'assistant') {
      messages.value.splice(insertIndex, 1, {
        role: 'assistant', content: '', thinking: true, playing: false, tool: '', _fullReply: '',
      })
    }
    userMsg.content = text
    editingIndex.value = -1
    editingText.value = ''
    store.resendMessage(text, insertIndex)
    scrollToBottom()
    return
  }

  // 后端编辑（方案 B）：整段「[user]+[assistant]」挪到会话底部，
  // 原位置的「打」等后续消息保留并上移。
  api.post('/messages/edit', {
    conversation_id: currentId.value,
    message_id: messageId,
    content: text,
  }).then(({ data }) => {
    // 用后端返回的完整消息列表替换本地（被编辑消息已到底部，后续消息保留）
    messages.value = (data.messages || []).map((m) => {
      const cur = m.current_version || 0
      return {
        role: m.role,
        content: m.content,
        message_id: m.message_id,
        seq: m.seq,
        version: m.version || 1,
        versions: m.versions || null,
        currentVersion: cur,
        // 编辑后回到最新版本，viewVersion 同步
        viewVersion: cur,
      }
    })
    // 被编辑的 user 消息现在位于底部，把新的 assistant 占位插到它之后（即会话最底部）
    const userIndex = messages.value.findIndex(
      (m) => m.message_id === messageId && m.role === 'user'
    )
    if (userIndex < 0) {
      editingIndex.value = -1
      editingText.value = ''
      return
    }
    const insertIndex = userIndex + 1
    messages.value.splice(insertIndex, 0, {
      role: 'assistant', content: '', thinking: true, playing: false, tool: '', _fullReply: '',
    })
    editingIndex.value = -1
    editingText.value = ''
    // originalSeq：重生成上下文只取到编辑位置之前，避免「打」影响本回复
    store.resendMessage(text, insertIndex, { mode: 'regenerate', messageId, contextBeforeSeq: originalSeq })
    scrollToBottom()
  }).catch((e) => {
    console.error('编辑失败', e)
    editingIndex.value = -1
    editingText.value = ''
  })
}

/** 重新生成 agent 回复 */
function regenerateBotMsg(index) {
  if (isStreaming.value) {
    stop()
  }
  const prev = messages.value[index - 1]
  if (!prev || prev.role !== 'user') return

  const m = messages.value[index]
  // 如果当前 bot 消息没有内容且是最后一条，复用它重新触发，保持在同一条会话里
  if (!m.content && index === messages.value.length - 1) {
    m.stopped = false
    m.thinking = true; m._thinkStart = Date.now()
    m.playing = false
    m.tool = ''
    m.toolStatus = ''
    m.toolResult = ''
    m._fullReply = ''
    store.resendMessage(prev.content, index, { mode: 'regenerate', messageId: prev.message_id })
    scrollToBottom()
    return
  }

  // 否则删除当前 bot 及之后的所有消息，重新生成
  messages.value.splice(index)
  store.resendMessage(prev.content, null, { mode: 'regenerate', messageId: prev.message_id })
  scrollToBottom()
}

/** 继续生成：在已有回复的基础上追加新内容 */
function continueBotMsg(index) {
  if (isStreaming.value) {
    stop()
  }
  const prev = messages.value[index - 1]
  if (prev && prev.role === 'user') {
    const m = messages.value[index]
    // 标记 _continueFrom，playTypewriter 将不再清空已有内容
    m._continueFrom = m.content || ''
    m.stopped = false
    m.thinking = true; m._thinkStart = Date.now()
    m.playing = false
    m.tool = ''
    m.toolStatus = ''
    m.toolResult = ''
    store.resendMessage(prev.content, index, { mode: 'regenerate', messageId: prev.message_id })
    scrollToBottom()
  }
}

/** 切换用户消息的编辑版本（纯展示，不触发重新生成）。
 *  关键约束：
 *  1) 若用户切到「旧版本」(Q1/Q2) 而最新回复(A3/A5)仍在后台流式生成，
 *    必须把正在查看的旧回复「冻结」(置 _frozen)：既不被实时事件覆盖，
 *    也不会重新播放打字机；且立即停掉 setInterval 打字机——否则它会把 A5
 *    的字符继续往已替换为 A4 旧回复的气泡里追加，造成「答复混在一起」。
 *  2) A3/A5 的生成结果只更新到对应 assistant 消息的 _fullReply / 最新版本里，
 *    待用户切回最新版本时再静态展示。
 *  3) pagination 与气泡内容**必须同步**——除了 currentVersion，再单独维护一个
 *    viewVersion 作为「用户当前正在查看的版本」的事实源，只在 switchVersion 里
 *    显式写入。saveCurrentReply 等「最新版本指针」重置路径不应触碰 viewVersion。
 *    这样即使 currentVersion 被外部意外改回 last，pagination 仍能正确显示
 *    「用户实际看到的版本号」(fixes Bug 1)。 */
function switchVersion(userIndex, versionIndex) {
  // 防御：每次都重新读取 messages.value，避免拿到旧引用导致 mutation 不生效。
  const userMsg = messages.value[userIndex]
  if (!userMsg || !userMsg.versions) return
  if (versionIndex < 0 || versionIndex >= userMsg.versions.length) return

  const last = userMsg.versions.length - 1
  const version = userMsg.versions[versionIndex]

  // 1) 先更新 user 消息——必须最先做，否则后续渲染看不到正确的版本号与气泡内容。
  userMsg.currentVersion = versionIndex
  userMsg.viewVersion = versionIndex   // pagination 的事实源，不参与 latest 指针重置
  userMsg.content = version.content || ''

  const assistantMsg = messages.value[userIndex + 1]
  if (!assistantMsg || assistantMsg.role !== 'assistant') {
    // 没有 assistant 也允许（user 视图已更新），不算错误
    return
  }

  const isLatest = versionIndex === last

  // 2) 切到任意版本前都先停掉旧打字机，避免残余字符写入。
  clearBubbleTypewriter(assistantMsg)

  if (isLatest) {
    // 切回最新版本：解冻，恢复实时生成态 / 已生成内容（静态展示，不重放打字机）
    assistantMsg._frozen = false
    delete assistantMsg._pendingTool   // 之前冻结期间缓存的工具名不再需要
    if (assistantMsg.runId) {
      // 仍在后台生成中：显示「思考中…」，等待 final 到来再播放，绝不显示旧的冻结内容
      assistantMsg.thinking = true; assistantMsg._thinkStart = Date.now()
      assistantMsg.playing = false
      assistantMsg.tool = ''
      assistantMsg.toolStatus = ''
      assistantMsg.toolResult = ''
      assistantMsg.content = ''
    } else {
      // 已生成完成：直接静态展示最终回复
      assistantMsg.content = assistantMsg._fullReply || version.reply || ''
      assistantMsg.thinking = false
      assistantMsg.playing = false
      assistantMsg.tool = ''
      assistantMsg.toolStatus = ''
      assistantMsg.toolResult = ''
    }
    return
  }

  // 3) 切到旧版本：冻结展示，绝不让 A5/A3 的实时事件（tool_call/final/done）覆盖气泡。
  // 仅设置展示内容，绝不触碰 _fullReply（那是 A3/A5 的最新回复，必须保留）。
  assistantMsg._frozen = true
  assistantMsg.content = version.reply || ''
  assistantMsg.stopped = false
  assistantMsg.thinking = false
  assistantMsg.playing = false
  assistantMsg.tool = ''
  assistantMsg.toolStatus = ''
  assistantMsg.toolResult = ''
  delete assistantMsg._pendingTool
}

/** 将指定 assistant 消息的本轮回复保存到对应 user 消息的最新版本中。
 *  只保存 index 这一条，不再遍历全部消息，避免污染历史问题的版本数据。 */
function saveCurrentReply(index) {
  if (index == null) return
  const a = messages.value[index]
  if (!a || a.role !== 'assistant') return
  const u = messages.value[index - 1]
  if (!u || u.role !== 'user' || !u.versions) return
  const last = u.versions.length - 1
  if (u.versions[last]) u.versions[last].reply = a.content
  // 指向本轮真实答案所在的最新版本
  u.currentVersion = last
  // viewVersion 是 pagination 的事实源，由 switchVersion 显式维护；
  // 这里**绝不**主动改 viewVersion——若用户切到旧版本后又生成了一轮，
  // viewVersion 必须停留在用户实际查看的位置上，避免「pagination 与气泡
  // 内容对不上」的 bug（fixes Bug 1）。
}

/** 根据工具状态返回气泡提示文案 */
function toolStatusText(m) {
  const status = m.toolStatus
  const tool = m.tool || ''
  if (status === 'success') {
    return '✓ 操作完成，正在整理结果…'
  }
  if (status === 'error') {
    return '操作遇到问题，正在整理回复…'
  }
  if (status === 'calling') {
    switch (tool) {
      case 'open_webpage': return '🌐 正在打开网页…'
      case 'open_application': return '📱 正在打开应用…'
      case 'run_apple_script': return '⚙️ 正在执行本机自动化操作…'
      case 'web_search': return '🔍 正在联网搜索…'
      default: return tool.startsWith('skill_') ? '🛠️ 正在执行技能工具…' : '正在操作…'
    }
  }
  // thinking 且无工具调用：按技能任务/普通任务给具体的阶段提示。
  // 用户明确要求知道 agent 此刻在做什么、还要多久——不能只显示"思考中"。
  const isSkillTask = !!currentSkillSlug.value
  if (isSkillTask) {
    const elapsed = thinkElapsed(m)
    if (elapsed < 45) return '🛠️ 正在按技能要求处理任务，请稍候…'
    if (elapsed < 100) return '🛠️ 技能任务执行中（内容生成 / 工具调用）…'
    return '🛠️ 技能任务仍在执行（复杂任务耗时更久），请耐心等待…'
  }
  return '思考中…'
}

/** 格式化消息展示时间戳为 HH:MM（用于气泡下方操作行的灰色时间标签）。
 *  仅依赖前端 _displayTime 字段（首次播放打字机时记录），历史消息无该字段则不显示，避免编造。 */
function formatTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

/** 检查 bot 消息的前一个 user 是否处于最新版本 */
function isLatestVersion(assistantIndex) {
  const prev = messages.value[assistantIndex - 1]
  if (!prev || prev.role !== 'user') return true
  if (!prev.versions) return true
  return prev.currentVersion === prev.versions.length - 1
}

/** 检查 user 消息是否有可刷新的 bot 回复 */
function canRefresh(userIndex) {
  const next = messages.value[userIndex + 1]
  return next && next.role === 'assistant' && isLatestVersion(userIndex + 1)
}

// ---- 打字机效果 ----
const typingTimers = []

/** 停止指定 assistant 气泡正在运行的打字机定时器，避免它在切换版本/冻结时
 *  继续往气泡里追加字符、把旧版本（A1/A2/A3）的展示内容污染成「旧回复 + 半截新回复」。
 *  这是「冻结旧版本时仍出现流式/混合输出」bug 的根因：playTypewriter 的 setInterval
 *  会持续 append chars[i] 到 m.content，关闭在 m 上的引用，下一次 tick 直接覆盖。 */
function clearBubbleTypewriter(m) {
  if (!m || !m._typewriterTimer) return
  const t = m._typewriterTimer
  clearInterval(t)
  const ti = typingTimers.indexOf(t)
  if (ti >= 0) typingTimers.splice(ti, 1)
  m._typewriterTimer = null
}

function playTypewriter(index, fullText) {
  const m = messages.value[index]
  if (!m) return
  // 首次播放打字机时记录「展示时间」，用于气泡下方操作行的灰色时间标签。
  // 已 committed 的历史消息没这个字段（render 时 v-if 不渲染，避免编造）。
  if (!m._displayTime) m._displayTime = Date.now()
  m.thinking = false

  // continue 场景：保留已有内容，对新增加部分做打字机播放
  if (m._continueFrom) {
    const existing = m._continueFrom
    m._continueFrom = undefined

    // 找出已有内容末尾与后端回复开头的最大重叠，避免重复
    let newPart = fullText || ''
    if (newPart && existing) {
      const maxOverlap = Math.min(existing.length, newPart.length)
      let overlap = 0
      for (let o = maxOverlap; o > 0; o--) {
        if (existing.slice(-o) === newPart.slice(0, o)) {
          overlap = o
          break
        }
      }
      newPart = newPart.slice(overlap)
    }

    if (!newPart) {
      m.playing = false
      store.stopStreaming(index)
      saveCurrentReply(index)
      scrollToBottom()
      return
    }

    m.content = existing
    m.playing = true
    m.tool = ''
    m.toolStatus = ''
    m.toolResult = ''
    m._fullReply = existing + newPart

    const chars = Array.from(newPart)
    let i = 0
    const timer = setInterval(() => {
      if (i >= chars.length) {
        clearInterval(timer)
        const ti = typingTimers.indexOf(timer)
        if (ti >= 0) typingTimers.splice(ti, 1)
        if (m._typewriterTimer === timer) m._typewriterTimer = null
        m.playing = false
        store.stopStreaming(index)
        saveCurrentReply(index)
        scrollToBottom()
        return
      }
      // 防御：气泡一旦冻结（用户切到旧版本），立即停打字机，绝不再追加任何字符
      if (m._frozen) {
        clearInterval(timer)
        const ti = typingTimers.indexOf(timer)
        if (ti >= 0) typingTimers.splice(ti, 1)
        if (m._typewriterTimer === timer) m._typewriterTimer = null
        return
      }
      m.content += chars[i]
      i++
      scrollToBottom()
    }, 18)
    m._typewriterTimer = timer
    typingTimers.push(timer)
    return
  }

  m.playing = true
  m.tool = ''
  m.toolStatus = ''
  m.toolResult = ''
  m.content = ''

  const chars = Array.from(fullText || '')
  let i = 0
  const timer = setInterval(() => {
    // 组件卸载后 messagesEl 为 null，打字机照常运行
    if (i >= chars.length) {
      clearInterval(timer)
      const ti = typingTimers.indexOf(timer)
      if (ti >= 0) typingTimers.splice(ti, 1)
      if (m._typewriterTimer === timer) m._typewriterTimer = null
      m.playing = false
      store.stopStreaming(index)
      saveCurrentReply(index)
      scrollToBottom()
      return
    }
    // 防御：气泡一旦冻结，立即停打字机。
    if (m._frozen) {
      clearInterval(timer)
      const ti = typingTimers.indexOf(timer)
      if (ti >= 0) typingTimers.splice(ti, 1)
      if (m._typewriterTimer === timer) m._typewriterTimer = null
      return
    }
    m.content += chars[i]
    i++
    scrollToBottom()
  }, 18)
  m._typewriterTimer = timer
  typingTimers.push(timer)
}

// 恢复上次离开时还没播完的打字机消息（页面切走后有 final 到达）
function restoreTypewriters() {
  for (let i = 0; i < messages.value.length; i++) {
    const m = messages.value[i]
    if (!m._fullReply) continue
    // 防御：若该气泡正冻结（用户正在查看旧版本），绝不让 _fullReply 覆盖展示内容
    if (m._frozen) continue
    // 已收到 final（_fullReply 已写入）但因切走页面导致打字机未播完/未开始 →
    // 直接补全内容。对 live 与 committed 消息均适用，是纯展示恢复，
    // 不会与流式事件冲突（流式事件另有 runId 结构性护栏）。
    if (m.thinking || (m.playing && !m.content)) {
      m.content = m._fullReply
      m.thinking = false
      m.playing = false
    }
  }
}

// ---- 生命周期 ----
onMounted(async () => {
  auth.hydrate()

  // 思考耗时心跳：驱动「已 N 秒」显示
  thinkTimer = setInterval(() => { nowTick.value = Date.now() }, 5000)

  // 强制防护：如果当前用户没有选中会话但 messages 不为空，说明有旧数据残留，彻底清空
  if (!currentId.value && messages.value.length) {
    store.resetAll()
  }

  // 初始化 socket（store 保证只创建一次）
  store.initSocket()

  // 注册 final / done 回调
  store.onFinal(playTypewriter)
  store.onDone((idx) => {
    if (typingTimers.length === 0) {
      store.stopStreaming(idx)
      saveCurrentReply(idx)
    }
  })
  store.onStop(() => {
    typingTimers.forEach((t) => clearInterval(t))
    typingTimers.length = 0
  })

  // 恢复切走期间到达的回复
  restoreTypewriters()

  // 加载会话列表
  await store.loadConversations()
  // 加载已安装技能 → 左侧「技能任务」入口
  await store.loadInstalledSkills()

  // 跨页跳转（如技能市场「打开任务」）请求打开的会话
  const pendingId = store.consumePendingOpen()
  if (pendingId) {
    if (pendingId === currentId.value) {
      await store.fetchHistory(pendingId)
    } else {
      await store.selectConversation(pendingId)
    }
    scrollToBottom()
  }
})

onBeforeUnmount(() => {
  // 停止所有打字机定时器（DOM 即将销毁，无法 scrollToBottom）
  typingTimers.forEach((t) => clearInterval(t))
  typingTimers.length = 0
  // 停止思考耗时心跳
  if (thinkTimer) { clearInterval(thinkTimer); thinkTimer = null }

  // 标记正在播放的消息为非播放状态（回到页面前已渲染的内容保留）
  for (const m of messages.value) {
    if (m.playing) {
      m.playing = false
      // 内容保留 —— 下次回到页面时 restoreTypewriters 会补上完整内容
    }
  }

  // 注意：此处不调用 stopStreaming()，运行表(activeRuns)保持原样，
  // 这样切走页面时 agent 在后台继续思考、回到页面仍能正确路由到对应气泡。

  // 注销回调（避免旧组件残留引用）
  store.clearCallbacks()

  // ⚠️ 不关闭 socket！agent 继续在后台思考并生成回复
})

watch(() => messages.value.length, scrollToBottom)

// ---- 用户切换检测：如果当前登录用户变了，强制清空所有旧数据防止串号 ----
let lastUserId = auth.user?.user_id || null
watch(
  () => auth.user?.user_id,
  (newId) => {
    if (newId && lastUserId && newId !== lastUserId) {
      // 用户切换了：清空所有聊天数据并重连 WebSocket
      store.resetAll()
      store.initSocket()
    }
    lastUserId = newId || null
  },
  { immediate: true }
)
</script>

<style scoped>
/* ===== 左侧任务面板：技能任务入口 ===== */
.task-section {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 2px 10px 8px;
  border-bottom: 1px solid #f1f3f8;
  max-height: 42%;
  overflow-y: auto;
}
.task-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 4px 5px;
}
.task-section-title {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.6px;
  color: #b0b7c3;
}
.task-section-more {
  border: none;
  background: transparent;
  color: #9ca3af;
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 6px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}
.task-section-more:hover {
  color: #2563eb;
  background: #eef3ff;
}

/* ===== 会话列表项：技能会话标识 ===== */
.conv-emoji {
  flex-shrink: 0;
  font-size: 13px;
  line-height: 1;
}

/* ===== 顶栏：当前技能徽标 ===== */
.topbar-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.topbar-skill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px 3px 6px;
  border-radius: 999px;
  background: linear-gradient(90deg, #eef3ff, #f3efff);
  border: 1px solid #e3e9ff;
  font-size: 12px;
  color: #1f2937;
  max-width: 46%;
}
.topbar-skill-emoji {
  font-size: 13px;
}
.topbar-skill-name {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.topbar-skill-slug {
  color: #2563eb;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11px;
  white-space: nowrap;
}
.topbar-right {
  flex-shrink: 0;
  font-size: 12px;
  color: #9ca3af;
  padding: 3px 10px;
  border-radius: 999px;
  background: #f1f3f8;
}
</style>
