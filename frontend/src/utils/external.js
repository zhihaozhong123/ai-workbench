// 在系统默认浏览器打开外部链接：
// - Tauri 桌面端：走 Rust execute_local_action('open_webpage')，优先 Chrome、回退默认浏览器；
// - 浏览器开发态：window.open 兜底。
import { isTauri, executeLocal } from '@/tauriLocal'

export async function openExternal(url) {
  if (!url) return
  if (isTauri()) {
    try {
      const res = await executeLocal('open_webpage', { url })
      if (typeof res === 'string' && res.startsWith('[ERROR]')) {
        console.warn('open_webpage 失败，回退 window.open：', res)
        window.open(url, '_blank', 'noopener,noreferrer')
      }
      return
    } catch (e) {
      console.warn('open_webpage 调用异常，回退 window.open：', e)
    }
  }
  window.open(url, '_blank', 'noopener,noreferrer')
}
