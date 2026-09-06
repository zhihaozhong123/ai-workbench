// 本机执行层桥接（仅 Tauri 桌面 app 内可用；网页端自动降级）。
// 后端经控制通道下发 local_control 指令时，由前端调用此模块在用户授权后真正执行。
const TAURI_INTERNAL = '__TAURI_INTERNALS__'

export function isTauri() {
  return typeof window !== 'undefined' && TAURI_INTERNAL in window
}

async function invoke(fn, args) {
  if (!isTauri()) throw new Error('not in tauri')
  const mod = await import('@tauri-apps/api/core')
  return mod.invoke(fn, args)
}

// 在客户端执行本机动作（Rust 执行层调 open/osascript/mdfind），返回结果字符串。
export async function executeLocal(action, payload) {
  try {
    return await invoke('execute_local_action', { action, payload: JSON.stringify(payload) })
  } catch (e) {
    return `[ERROR] 调用本机执行层失败: ${e}`
  }
}

// 读取 .app 的代码签名状态：developer_id / ad_hoc / unsigned / unknown
export async function getSignatureStatus() {
  try {
    return await invoke('get_signature_status')
  } catch {
    return 'unknown'
  }
}

// 弹本机操作授权确认框（仅桌面端）。返回 true=允许。
export async function askConfirm(message) {
  if (!isTauri()) return false
  try {
    const { ask } = await import('@tauri-apps/plugin-dialog')
    return await ask(message, { title: '智作台 · 本机操作授权', kind: 'warning' })
  } catch {
    return false
  }
}

// 本地操作授权状态（localStorage 持久化，首次授权后不再弹窗）
const AUTH_KEY = 'xst_local_control_authorized'

export function isLocalControlAuthorized() {
  try {
    return localStorage.getItem(AUTH_KEY) === '1'
  } catch {
    return false
  }
}

export function setLocalControlAuthorized(authorized) {
  try {
    if (authorized) {
      localStorage.setItem(AUTH_KEY, '1')
    } else {
      localStorage.removeItem(AUTH_KEY)
    }
  } catch {}
}

const ACTION_LABEL = {
  open_application: '打开应用',
  open_webpage: '打开网页',
  run_apple_script: '执行 AppleScript',
  find_local_files: '搜索本机文件',
}

export function actionLabel(action) {
  return ACTION_LABEL[action] || action
}
