import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { useAuthStore } from './auth'
import api from '@/api/client'
import { createChatSocket } from '@/api/chat'
import { fetchInstalled } from '@/api/skills'

/**
 * 聊天 Store：管理 WebSocket 连接和消息状态。
 *
 * WebSocket 在页面切换时保持存活，确保 agent 在用户浏览其他页面时
 * 继续思考并生成回复；回到聊天页即可看到完整回复。
 *
 * 会话历史 / 编辑版本 / 分页全部由后端 messages 表驱动，前端只负责展示与调用，
 * 不再用 localStorage 维护版本缓存（刷新/重登后由后端恢复）。
 */
export const useChatStore = defineStore('chat', () => {
  const auth = useAuthStore()

  // ---- 核心状态 ----
  const conversations = ref([])
  const currentId = ref(null)
  const messages = ref([])
  const wsOpen = ref(false)
  const isStreaming = ref(false)
  // activeRuns：当前正在进行（流式生成中）的运行，key = client_msg_id(=runId)，
  // value = 该运行对应的 assistant 占位消息在 messages.value 中的下标。
  // 每个 Q&A 对独立占一项，互不影响，从而支持并发提问且历史消息保持静止。
  const activeRuns = reactive({})
  // 当前正在流式生成的（最新一条）assistant 占位消息索引，供版本切换等逻辑判断
  const pendingIndex = ref(-1)
  // 待打开会话：技能市场「打开任务」等跨页面跳转时先写入，
  // ChatView onMounted 完成后消费并清除（在 Pinia 中跨路由共享）。
  const pendingSelectId = ref(null)

  // ---- 已安装技能（全局共享，供 ChatView 任务入口与会话过滤使用） ----
  const installedSkills = ref([])
  const installedMap = computed(() => {
    const m = {}
    for (const s of installedSkills.value) m[s.slug] = s
    return m
  })
  const installedSlugs = computed(() => {
    const set = new Set()
    for (const s of installedSkills.value) set.add(s.slug)
    return set
  })

  async function loadInstalledSkills() {
    try {
      const { data } = await fetchInstalled()
      installedSkills.value = (data.skills || []).filter((s) => s.status === 'ok')
    } catch (e) {
      console.error('加载已安装技能失败', e)
    }
  }

  // 根据 activeRuns 重新计算 isStreaming 与 pendingIndex，保证二者与运行表一致
  function refreshStreaming() {
    const ids = Object.keys(activeRuns)
    isStreaming.value = ids.length > 0
    pendingIndex.value = ids.length ? activeRuns[ids[ids.length - 1]] : -1
  }

  // 清空所有进行中的运行（切换会话 / 重载历史 / 切换用户时调用，防止索引错乱）
  function clearRuns() {
    for (const k of Object.keys(activeRuns)) delete activeRuns[k]
    refreshStreaming()
  }

  let socket = null
  let _connecting = false   // 互斥锁：防止 initSocket 并发创建多个 WebSocket

  // ---- 初始化 WebSocket ----
  function initSocket() {
    // 用户变更（注销后重登另一账号）：关闭旧 socket 重建，并清除旧用户所有数据防止串号。
    // ⚠️ 必须比对「用户身份」而非 token 字符串：同一用户的 access token 每 15 分钟
    // 会被 axios 静默刷新一次，刷新后 token 字符串必然不同，但 WS 连接依然有效，
    // 绝不能因此重建 socket / 清空会话数据。
    const curUserId = auth.user?.user_id || null
    if (socket && socket._userId && curUserId && socket._userId !== curUserId) {
      closeSocket()
      conversations.value = []
      currentId.value = null
      messages.value = []
      isStreaming.value = false
      clearRuns()
    }
    // 没有 socket，或 socket 已失效（closed/closing），都重新创建
    if (socket && socket._alive?.()) return
    if (_connecting) return   // 防止并发创建多个 socket

    _connecting = true
    try {
      socket = createChatSocket({
        onOpen: () => {
          wsOpen.value = true
          // 连接（含 1008 过期后换 token 重连、3s 断线重连）建立时同步记录：
          // token 可能已被 axios 静默刷新（同一用户），WS 建连用的就是最新 token
          if (socket) {
            socket._token = auth.accessToken
            socket._userId = auth.user?.user_id || null
          }
          loadConversations()
        },
        onClose: () => {
          wsOpen.value = false
          // 连接断开：后端 ws_chat 的 finally 会取消所有进行中的运行，
          // 且这些运行不会再发出任何事件（连接已死）。
          // 必须本地收尾所有 live 气泡，否则它们永远停留在「思考中」
          // （历史 bug：后端重启/网络断开杀死运行后无终止事件，前端假死）。
          const ids = Object.keys(activeRuns)
          for (const rid of ids) {
            const m = messages.value[activeRuns[rid]]
            if (m) {
              m.thinking = false
              m.playing = false
              m.tool = ''
              m.toolStatus = ''
              m.toolResult = ''
              m.runId = null
              if (!m.content && !m._fullReply) {
                m.stopped = true
                m.content = '⚠️ 连接中断，本次任务已停止。回复「继续」可从中断处接着执行。'
              }
            }
            delete activeRuns[rid]
          }
          refreshStreaming()
        },
        onEvent: handleEvent,
      })
      // 记录 socket 归属（用户身份 + 建连时 token），用于检测用户变更
      socket._token = auth.accessToken
      socket._userId = auth.user?.user_id || null
    } finally {
      _connecting = false
    }
  }

  /** 仅注销/登出时调用：关闭 WebSocket（防止自动重连） */
  function closeSocket() {
    if (socket) {
      socket.close()
      socket = null
    }
  }

  // ---- 会话管理 ----
  async function loadConversations() {
    try {
      const { data } = await api.get('/conversations')
      conversations.value = data
      // 防护：后端返回空会话列表但 messages 不为空 → 说明有残留数据，强制清空
      if (!data.length && messages.value.length) {
        currentId.value = null
        messages.value = []
        isStreaming.value = false
        clearRuns()
      }
    } catch {}
  }

  async function fetchHistory(id) {
    try {
      const { data } = await api.get(`/messages?conversation_id=${id}`)
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
          // viewVersion 是 pagination 事实源：刚加载时与 currentVersion 一致
          // （都指向最新版本），后续仅由 switchVersion 显式修改。
          viewVersion: cur,
        }
      })
      clearRuns()
    } catch {
      messages.value = []
      clearRuns()
    }
  }

  async function selectConversation(id) {
    if (id === currentId.value) return
    currentId.value = id
    await fetchHistory(id)
  }

  function newConversation() {
    currentId.value = null
    messages.value = []
    clearRuns()
  }

  /** 请求 ChatView 挂载后自动打开指定会话（技能任务「打开」跳转用） */
  function requestOpenConversation(id) {
    if (!id) return
    pendingSelectId.value = id
  }

  /** 消费待打开会话：返回已消费的会话 ID（无则 null）。由 ChatView 在就绪后调用。 */
  function consumePendingOpen() {
    const id = pendingSelectId.value
    pendingSelectId.value = null
    return id
  }

  /** 彻底重置：切换用户/登出时调用，清除所有状态防止串号 */
  function resetAll() {
    closeSocket()
    conversations.value = []
    currentId.value = null
    messages.value = []
    pendingSelectId.value = null
    wsOpen.value = false
    isStreaming.value = false
    clearRuns()
    _onFinal = null
    _onDone = null
    installedSkills.value = []
  }

  function createId() {
    return (crypto && crypto.randomUUID && crypto.randomUUID()) ||
      `m_${Date.now()}_${Math.random().toString(36).slice(2)}`
  }

  /** 发新消息前清理历史残留的「假死思考气泡」。
   *  场景：某轮运行异常结束后（旧版 bug / 极端路径），气泡可能停留在
   *  thinking 态且 runId 已不在 activeRuns——它们永远不会被任何事件收尾，
   *  在界面上越积越多，让用户分不清「哪一轮在跑」。发新消息 = 用户开始
   *  新交互，是清理这些尸体的最佳时机。 */
  function _sweepStaleThinking() {
    for (let i = 0; i < messages.value.length; i++) {
      const m = messages.value[i]
      if (m.role !== 'assistant' || !m.thinking) continue
      if (m.runId && activeRuns[m.runId] !== undefined) continue   // 还在跑，不动
      // 假死气泡：无运行对应的 thinking 态 → 标记为已中断
      m.thinking = false
      m.playing = false
      m.tool = ''
      m.toolStatus = ''
      m.toolResult = ''
      m.runId = null
      if (!m.content && !m._fullReply) {
        m.stopped = true
        m.content = '（本轮已结束）'
      }
    }
  }

  function sendMessage(text, extra = {}) {
    if (!text || !wsOpen.value) return false

    // 清理历史残留的假死思考气泡（不让旧轮次的尸体干扰新一轮）
    _sweepStaleThinking()

    // clientMsgId 绑定消息/版本；runId 绑定一次具体生成，重试时两者必须分离
    const clientMsgId = createId()
    const runId = createId()

    messages.value.push({
      role: 'user',
      content: text,
      message_id: clientMsgId,
      version: 1,
      versions: [{ content: text, reply: null }],
      currentVersion: 0,
      viewVersion: 0,   // 与 currentVersion 一致：初始查看最新版本
      ...extra,
    })
    const assistantIndex = messages.value.length
    messages.value.push({
      role: 'assistant',
      content: '',
      thinking: true,
      playing: false,
      tool: '',
      toolStatus: '',      // '', 'calling', 'success', 'error'
      toolResult: '',      // tool_result 的摘要，用于前端展示
      _fullReply: '', // 保存完整回复内容，用于页面切回时恢复
      runId, // 标记该 assistant 属于哪一次运行，精准路由流式事件
    })
    activeRuns[runId] = assistantIndex
    refreshStreaming()

    if (socket) {
      socket.send(text, currentId.value, { mode: 'send', client_msg_id: clientMsgId, run_id: runId })
      return true
    }
    return false
  }

  // ---- WebSocket 事件处理（结构性隔离）----
  // 核心规则：每个 assistant 消息要么是 live（带 runId，正在接收流式更新），
  // 要么是 committed（runId 为空，已是历史/完成态）。所有流式事件只允许写入
  // runId 匹配的 live 消息；committed 消息物理上不会被任何流式事件改动。
  // 这是「一问一答彻底隔离、互不串台」的结构性根保障 —— 不依赖路由代码不出错：
  // 即使将来某处路由逻辑有 bug，也只会导致事件被丢弃，绝不会污染历史气泡。
  function findAssistant(runId) {
    if (!runId) return -1
    for (let i = 0; i < messages.value.length; i++) {
      const m = messages.value[i]
      if (m.role === 'assistant' && m.runId === runId) return i
    }
    return -1
  }

  function handleEvent(ev) {
    // 安全校验：仅当 socket 归属的用户与当前登录用户不一致（注销换号后旧 socket
    // 的延迟事件）才丢弃，防止串号。
    // ⚠️ 绝不能比对 token 字符串：同一用户 access token 每 15 分钟被 axios 静默
    // 刷新一次，刷新后 socket._token（建连时的旧 token）≠ auth.accessToken（新
    // token），会把本用户的全部正常事件（final/done/…）静默丢弃，气泡永远停在
    // 「思考中/执行中」——2026-09-09「已 212 秒」假死事故的根因。
    if (socket && socket._userId && auth.user?.user_id && socket._userId !== auth.user.user_id) return

    const runId = ev.run_id || null

    // ready 不需要 runId，也不会改动消息内容
    if (ev.type === 'ready') {
      // 已经选定会话后，ready 只刷新列表，不允许异步事件改写当前会话。
      if (ev.conversation_id && !currentId.value) {
        currentId.value = ev.conversation_id
        loadConversations()
      } else if (ev.conversation_id) {
        loadConversations()
      }
      return
    }

    // 其余事件：必须找到 runId 匹配的 live 消息才允许操作。
    // 这是「committed 历史永远不会被流式事件碰到」的唯一也是终极的护栏。
    const targetIndex = runId ? findAssistant(runId) : -1
    const target = targetIndex >= 0 ? messages.value[targetIndex] : null
    if (!target || target.runId !== runId) {
      // 目标不是本次运行的 live 消息（不存在 / 已 committed / runId 丢失），
      // 丢弃事件，绝不污染其它消息。
      // 但 done/error 需要按 runId 清理 activeRuns（防御性清理）
      if ((ev.type === 'done' || ev.type === 'error') && runId && activeRuns[runId] !== undefined) {
        delete activeRuns[runId]
        refreshStreaming()
      }
      return
    }

    switch (ev.type) {
      case 'token':
      case 'clear_intermediate':
        // 正文由 playTypewriter 在 final 时统一播放；中间步骤由 thinking 态覆盖
        break
      case 'tool_call': {
        // 关键修复：用户切到旧版本后，最新一轮的 tool_call 仍会按 runId 路由到
        // 这条 assistant 气泡（runId 没清）。如果不拦，就会把气泡从「Q1 旧回复」
        // 强行打回「思考中…」，让旧版本回复完全消失，且 pagination 看起来"和
        // 切换版本不一致"。这里必须按 _frozen 严格分流：
        //  - 未冻结：正常进入「思考中…」展示；
        //  - 已冻结：仅把工具名暂存到 _pendingTool，**绝不** 改 thinking/tool，
        //    让气泡稳定显示用户当前查看的旧版本回复，待用户切回最新版本再恢复。
        if (target._frozen) {
          target._pendingTool = ev.name
          break
        }
        target.thinking = true
        target.tool = ev.name
        target.toolStatus = 'calling'
        target.toolResult = ''
        break
      }
      case 'tool_result': {
        // 工具已在本机执行完毕（成功或失败），不再显示「思考中…」，
        // 而是展示操作结果摘要，让用户知道浏览器/搜索已经触发了。
        if (target._frozen) break
        target.toolStatus = ev.error ? 'error' : 'success'
        target.toolResult = ev.preview || ''
        break
      }
      case 'final': {
        const fullText = ev.reply || ''
        target._fullReply = fullText
        // 用户若正查看旧版本（_frozen），绝不重放打字机：A3 结果只存进 _fullReply，
        // 待用户切回最新版本时再静态展示，从而旧回复（A1/A2）不会被覆盖或重新流式输出。
        if (!target._frozen && _onFinal) _onFinal(targetIndex, fullText)
        break
      }
      case 'done': {
        // 回填 message_id（一次性元数据写入，仍作用于本次运行的 live 消息）
        if (ev.user_message_id) {
          const u = messages.value[targetIndex - 1]
          if (u && u.role === 'user') u.message_id = ev.user_message_id
        }
        if (ev.assistant_message_id) target.message_id = ev.assistant_message_id
        // live → committed：清掉 runId，从此该消息不再接收任何流式事件
        target.runId = null
        // 兜底：done 到达但气泡仍是 thinking 且没有任何内容（运行被取消 / 无 final
        // 的异常结束路径）→ 清掉 thinking 标记 stopped，绝不留「永远思考中」的假死气泡
        if (target.thinking && !target.content && !target._fullReply) {
          target.thinking = false
          target.stopped = true
        }
        if (runId && activeRuns[runId] !== undefined) {
          delete activeRuns[runId]
          refreshStreaming()
        }
        if (target._frozen) {
          // 用户正查看旧版本：只把最新回复(A3)落进最新版本，绝不改动当前展示、绝不重放
          const u = messages.value[targetIndex - 1]
          if (u && u.versions) u.versions[u.versions.length - 1].reply = target._fullReply || ''
          break
        }
        if (_onDone) _onDone(targetIndex)
        else stopStreaming(targetIndex)
        break
      }
      case 'timeout':
      case 'loop_detected': {
        // 运行异常结束（整体超时 / 重复工具调用被中断）：必须清理气泡状态，
        // 否则 thinking 永远为 true，用户看到的是永远「思考中」的假死气泡。
        const wasFrozen = target._frozen
        target.thinking = false
        target.playing = false
        target.tool = ''
        target.toolStatus = ''
        target.toolResult = ''
        if (!wasFrozen) {
          target.content = ev.type === 'timeout'
            ? '⏱️ 本次任务超时了：' + (ev.message || '操作或等待时间过长，请稍后重试。')
            : '任务已中断：' + (ev.message || '检测到重复操作，已自动停止。')
        }
        target.runId = null
        if (runId && activeRuns[runId] !== undefined) {
          delete activeRuns[runId]
          refreshStreaming()
        }
        if (!wasFrozen && Object.keys(activeRuns).length === 0) {
          _onFinal = null
          _onDone = null
        }
        break
      }
      case 'error': {
        const wasFrozen = target._frozen
        target.thinking = false
        target.playing = false
        target.tool = ''
        target.toolStatus = ''
        target.toolResult = ''
        // 冻结态下不覆盖当前展示的旧回复
        if (!wasFrozen) target.content = '出错了：' + (ev.message || '未知错误')
        target.runId = null
        if (runId && activeRuns[runId] !== undefined) {
          delete activeRuns[runId]
          refreshStreaming()
        }
        if (!wasFrozen && Object.keys(activeRuns).length === 0) {
          _onFinal = null
          _onDone = null
        }
        break
      }
    }
  }

  // ---- 打字机/完成回调（由 ChatView 注入） ----
  let _onFinal = null
  let _onDone = null
  let _onStop = null

  function onFinal(fn) {
    _onFinal = fn
  }

  function onDone(fn) {
    _onDone = fn
  }

  function onStop(fn) {
    _onStop = fn
  }

  function clearCallbacks() {
    _onFinal = null
    _onDone = null
    _onStop = null
  }

  function stopStreaming(index) {
    if (index == null) {
      // 无参数：清空所有运行（组件卸载兜底）
      for (const k of Object.keys(activeRuns)) delete activeRuns[k]
    } else {
      const m = messages.value[index]
      if (m && m.runId && activeRuns[m.runId] !== undefined) {
        delete activeRuns[m.runId]
      }
    }
    refreshStreaming()
  }

  /** 用户点击「停止」：取消所有正在生成的消息 */
  function stopGenerating() {
    const ids = Object.keys(activeRuns)
    for (const rid of ids) {
      if (socket) socket.sendCancel(rid)
      const idx = activeRuns[rid]
      const m = messages.value[idx]
      if (m) {
        m.thinking = false
        m.playing = false
        m.tool = ''
        m.toolStatus = ''
        m.toolResult = ''
        m.stopped = true
      }
    }
    // 清除所有打字机定时器（ChatView 中由 onBeforeUnmount 管理，这里通过回调通知）
    if (_onStop) _onStop()
    for (const rid of ids) delete activeRuns[rid]
    refreshStreaming()
  }

  /** 重试 / 重生成：用已有（或新）用户消息重新触发 agent。
   *  opts: { mode: 'regenerate' | 'send', messageId } —— messageId 为该 user 消息的稳定 ID。
   *  不重复添加用户消息（targetIndex 指定要复用的 assistant 占位位置）。 */
  function resendMessage(text, targetIndex = null, opts = {}) {
    if (!text || !wsOpen.value) return false

    const clientMsgId = opts.messageId || createId()
    const runId = createId()

    let assistantIndex
    if (targetIndex !== null) {
      assistantIndex = targetIndex
    } else {
      assistantIndex = messages.value.length
      messages.value.push({
        role: 'assistant',
        content: '',
        thinking: true,
        playing: false,
        tool: '',
        toolStatus: '',
        toolResult: '',
        _fullReply: '',
        runId,
      })
    }
    const am = messages.value[assistantIndex]
    if (am) {
      am.runId = runId
      am._frozen = false   // 新的一次生成必须以 live 态运行，解冻任何旧版本的冻结
    }
    activeRuns[runId] = assistantIndex
    refreshStreaming()

    if (socket) {
      socket.send(text, currentId.value, {
        mode: opts.mode || 'regenerate',
        client_msg_id: clientMsgId,
        run_id: runId,
        context_before_seq: opts.contextBeforeSeq ?? null,
      })
      return true
    }
    return false
  }

  return {
    // state
    conversations,
    currentId,
    messages,
    wsOpen,
    isStreaming,
    pendingIndex,
    installedSkills,
    installedMap,
    installedSlugs,
    // socket
    initSocket,
    closeSocket,
    // conv
    loadConversations,
    fetchHistory,
    selectConversation,
    newConversation,
    requestOpenConversation,
    consumePendingOpen,
    loadInstalledSkills,
    // messaging
    sendMessage,
    resendMessage,
    onFinal,
    onDone,
    onStop,
    clearCallbacks,
    stopStreaming,
    stopGenerating,
    // reset
    resetAll,
  }
})
