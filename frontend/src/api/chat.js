import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

import { BASE, getWsBase, getBase } from '@/config'
import { isTauri, executeLocal, getSignatureStatus, askConfirm, actionLabel, isLocalControlAuthorized, setLocalControlAuthorized } from '@/tauriLocal'

// WebSocket 聊天封装：连接 /ws/chat?token=<access>
// - 自动重连；access 过期(1008) 时先 refresh 再重连
// handlers: { onOpen, onClose, onEvent(ev) }
export function createChatSocket(handlers = {}) {
  const auth = useAuthStore()
  let ws = null
  let closedByUser = false
  let reconnectTimer = null
  let refreshPromise = null

  const url = () => `${getWsBase()}/ws/chat?token=${encodeURIComponent(auth.accessToken)}`

  // 处理后端下发的本机控制指令：弹确认 → 客户端执行 → 回传结果
  async function handleLocalControl(data) {
    if (!isTauri()) {
      try {
        ws.send(JSON.stringify({
          type: 'local_control_result',
          request_id: data.request_id,
          result: '[ERROR] 本机控制需在「智作台.app」桌面端中使用。',
        }))
      } catch {}
      return
    }

    // 如果已授权，直接执行，不再弹确认框
    let allowed = isLocalControlAuthorized()
    if (!allowed) {
      const label = actionLabel(data.action)
      allowed = await askConfirm(`智作台请求执行本机操作「${label}」，是否允许？`)
      // 用户首次授权后，记下授权状态，后续不再询问
      if (allowed) {
        setLocalControlAuthorized(true)
      }
    }

    let result
    if (allowed) {
      result = await executeLocal(data.action, data.payload || {})
    } else {
      result = '[ERROR] 用户拒绝了本次本机操作请求。'
    }
    try {
      ws.send(JSON.stringify({ type: 'local_control_result', request_id: data.request_id, result }))
    } catch {}
  }

  async function refreshToken() {
    if (!auth.refreshToken) throw new Error('no refresh token')
    if (!refreshPromise) {
      refreshPromise = axios
        .post(`${getBase()}/refresh`, { refresh_token: auth.refreshToken })
        .then((r) => {
          auth.setAuth(r.data)
          return r.data
        })
        .finally(() => {
          refreshPromise = null
        })
    }
    return refreshPromise
  }

  function connect() {
    if (closedByUser) return
    ws = new WebSocket(url())
    ws.onopen = () => {
      handlers.onOpen && handlers.onOpen()
      // 桌面端：连接后上报自身代码签名状态，便于服务端提醒配置 Developer ID
      if (isTauri()) {
        getSignatureStatus()
          .then((s) => ws.send(JSON.stringify({ type: 'signature_report', status: s })))
          .catch(() => {})
      }
    }
    ws.onmessage = async (ev) => {
      let data
      try {
        data = JSON.parse(ev.data)
      } catch {
        return
      }
      // 本机控制指令：在客户端执行层执行并回传结果（不交给业务层渲染）
      if (data && data.type === 'local_control') {
        await handleLocalControl(data)
        return
      }
      handlers.onEvent && handlers.onEvent(data)
    }
    ws.onclose = async (e) => {
      handlers.onClose && handlers.onClose()
      if (closedByUser) return
      if (e.code === 1008) {
        // access 过期 → 换 token 后重连
        try {
          await refreshToken()
          connect()
          return
        } catch {
          const { default: router } = await import('@/router')
          auth.logout()
          router.replace('/login')
          return
        }
      }
      // 其它断开：3 秒后重连
      reconnectTimer = setTimeout(connect, 3000)
    }
    ws.onerror = () => {
      try {
        ws.close()
      } catch {}
    }
  }

  function send(content, conversationId, opts = {}) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      // 注意：conversationId 为 null 时也要显式带上 "conversation_id": null，
      // 不能省略（否则后端会复用同一条 WebSocket 上一条消息的会话，造成串号）。
      ws.send(
        JSON.stringify({
          type: 'message',
          content,
          conversation_id: conversationId,
          mode: opts.mode || 'send',
          client_msg_id: opts.client_msg_id || null,
          run_id: opts.run_id || null,
          context_before_seq: opts.context_before_seq ?? null,
        })
      )
      return true
    }
    return false
  }

  function sendCancel(runId) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'cancel', run_id: runId || null }))
      return true
    }
    return false
  }

  function close() {
    closedByUser = true
    if (reconnectTimer) clearTimeout(reconnectTimer)
    if (ws) ws.close()
  }

  connect()
  return {
    send,
    sendCancel,
    close,
    /** 返回 WebSocket 是否仍然处于 OPEN 状态 */
    _alive: () => ws && ws.readyState === WebSocket.OPEN,
  }
}
