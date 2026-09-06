// 端到端测试：注册 -> 跳登录页（预填账号+提示）-> 登录 -> 进入聊天页
// 用法：node e2e_register_login.mjs  (需先 `vite preview --port 4173` 起前端，后端在 127.0.0.1:8000)
import { chromium } from 'playwright'

const FRONT = process.env.FRONT_BASE || 'http://localhost:4173'
const STAMP = Date.now()
const EMAIL = `e2e_${STAMP}@test.com`
const PWD = 'e2epass123'
const NICK = `e2e_${STAMP}`

const log = (...a) => console.log('[E2E]', ...a)
let failed = false
function assert(cond, msg) {
  if (cond) { log('PASS:', msg) }
  else { failed = true; log('FAIL:', msg) }
}

const browser = await chromium.launch()
const ctx = await browser.newContext()
const page = await ctx.newPage()
page.on('console', (m) => { log(`console[${m.type()}]:`, m.text()) })
page.on('response', (r) => { if (r.url().includes('/api/login')) log(`NET /api/login -> ${r.status()}`); if (r.url().includes('/api/me')) log(`NET /api/me -> ${r.status()}`) })
page.on('requestfailed', (r) => { if (r.url().includes('/api/login')) log(`NETFAIL /api/login -> ${r.failure()?.errorText}`) })
page.on('requestfinished', (r) => { if (r.url().includes('/api/login')) log(`SENT /api/login (${r.method()})`) })

try {
  // 1) 打开登录页
  await page.goto(`${FRONT}/login`, { waitUntil: 'networkidle' })
  await page.waitForSelector('text=登录', { timeout: 10000 })
  log('打开登录页 OK')

  // 2) 切到注册 tab
  await page.click('button.tab:has-text("注册")')
  await page.waitForSelector('input[placeholder="昵称"]', { timeout: 5000 })
  log('切到注册 tab OK')

  // 3) 填写并注册
  await page.fill('input[placeholder="邮箱/手机号"]', EMAIL)
  await page.fill('input[placeholder="昵称"]', NICK)
  await page.fill('input[placeholder="密码（至少 6 位）"]', PWD)
  await page.click('button.submit:has-text("注 册")')

  // 4) 注册成功后应切到登录 tab，并出现提示、且账号已预填
  await page.waitForSelector('text=注册成功，请用该账号登录', { timeout: 10000 })
  assert(true, '注册成功提示出现（跳转到了登录页面）')
  // 登录 tab 激活
  const loginActive = await page.$eval('button.tab.active', (el) => el.textContent.trim())
  assert(loginActive === '登录', `注册后停留在登录 tab（当前=${loginActive}）`)
  // 账号预填
  const prefill = await page.inputValue('input[placeholder="邮箱/手机号"]')
  assert(prefill === EMAIL, `登录框已预填注册账号（当前=${prefill}）`)

  // 5) 在登录页输入密码并登录
  await page.fill('input[placeholder="密码"]', PWD)
  await page.click('button.submit:has-text("登 录")')

  // 5.5) 诊断：等待一会后记录状态（登录请求是否成功）
  await page.waitForTimeout(2500)
  const dbgUrl = page.url()
  const dbgErr = await page.$eval('.error-tip', (el) => el.textContent.trim()).catch(() => '(无 error-tip)')
  const dbgHint = await page.$eval('.hint-tip', (el) => el.textContent.trim()).catch(() => '(无 hint-tip)')
  log(`DIAG url=${dbgUrl} err=${dbgErr} hint=${dbgHint}`)

  // 6) 应跳转到聊天页 /chat
  await page.waitForURL('**/chat', { timeout: 10000 })
  assert(true, '登录后成功进入聊天页 /chat')
  // 聊天页关键元素：输入框
  await page.waitForSelector('textarea, input.chat-input, .chat-input', { timeout: 5000 }).catch(() => {})
  log('聊天页已加载')

  log(failed ? 'RESULT: 存在失败项 ❌' : 'RESULT: 全流程通过 ✅')
} catch (e) {
  failed = true
  log('EXCEPTION:', e.message)
} finally {
  await browser.close()
  process.exit(failed ? 1 : 0)
}
