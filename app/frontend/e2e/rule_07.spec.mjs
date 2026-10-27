// RULE-07 浏览器层：生产配置（APP_ENV=prod）后端托管生产构建产物，登录页无身份切换区。
// 由 app/backend/tests/acceptance/test_rule_07.py 启动生产进程后调用：E4_BASE=http://127.0.0.1:8014 node e2e/rule_07.spec.mjs
import { chromium, BASE, check, finish } from './e4_harness.mjs'

const results = []
const browser = await chromium.launch()
const page = await browser.newPage()
const apiCalls = []
page.on('request', (req) => { if (req.url().includes('/api/')) apiCalls.push(req.url().replace(BASE, '')) })
await page.goto(`${BASE}/login`)
await page.waitForLoadState('networkidle')
await page.locator('[data-page-id="PAGE-F01-01"]').waitFor({ timeout: 15000 })
const text = await page.locator('body').innerText()
const html = await page.content()
await page.screenshot({ path: '/tmp/claude-0/-home-user/001a2709-c0f1-57ab-bb23-2c886d9a31b8/scratchpad/rule07_login_prod.png', fullPage: true })
check(results, '登录页已渲染（PAGE-F01-01）', true, text.slice(0, 80).replace(/\s+/g, ' '))
check(results, '登录页无「开发模式身份切换」文字', !text.includes('开发模式身份切换') && !html.includes('开发模式身份切换'))
check(results, '登录页无身份切换组件（无 dev-users 请求、无 data-dev-switch 元素）',
  !apiCalls.some((u) => u.includes('dev-users')) && (await page.locator('[data-dev-switch], .dev-switch').count()) === 0,
  apiCalls.join(','))
const cfg = await (await page.request.get(`${BASE}/api/auth/config`)).json()
check(results, '/api/auth/config 开发开关为 false', cfg.dev_switch === false, JSON.stringify(cfg))
await browser.close()
finish(results)
