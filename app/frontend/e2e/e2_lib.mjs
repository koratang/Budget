// E2（FLOW-11~20）浏览器验收共用：前置脚本、后端进程（8012，库 budget_acc2）、钉钉替身（8022）、开发身份登录、表格单元格操作。
// 运行：cd app/frontend && NODE_PATH=/opt/node-tools/node_modules node e2e/flow-11.spec.mjs
import { spawn, execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
export const { chromium } = require('playwright')
export { assert }

const HERE = path.dirname(fileURLToPath(import.meta.url))
export const BACKEND = path.resolve(HERE, '../../backend')
const PY = path.join(BACKEND, '.venv/bin/python')
export const BASE = 'http://127.0.0.1:8012'
export const STUB = 'http://127.0.0.1:8022'

let checks = 0
export function ok(cond, msg) {
  assert.ok(cond, msg)
  checks += 1
}
export function eq(actual, expected, msg) {
  assert.deepEqual(actual, expected, msg)
  checks += 1
}
export const checkCount = () => checks

function py(args) {
  const out = execFileSync(PY, ['-m', 'tests.acceptance.e2_setup', ...args], { cwd: BACKEND, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] })
  const line = out.split('\n').find((l) => l.startsWith('E2JSON '))
  return JSON.parse(line.slice(7))
}
export const setup = (flow) => py(['reset', flow])
export const step = (name, ...args) => py(['step', name, ...args])
export const dump = (versionId) => py(['dump', String(versionId)])
export const dumpStore = (storeId) => py(['dump-store', String(storeId)])
export const xlsx = (file, ...edits) => py(['xlsx', file, ...edits])

async function waitHttp(url, tries = 80) {
  for (let i = 0; i < tries; i++) {
    try {
      const r = await fetch(url)
      if (r.status < 500) return
    } catch {
      /* 未就绪 */
    }
    await new Promise((r) => setTimeout(r, 250))
  }
  throw new Error(`等待 ${url} 超时`)
}

const procs = []
async function startProc(args, url) {
  const p = spawn(path.join(BACKEND, '.venv/bin/uvicorn'), args, { cwd: BACKEND, stdio: ['ignore', 'ignore', 'pipe'] })
  let err = ''
  p.stderr.on('data', (d) => (err = (err + d).slice(-4000)))
  p.on('exit', (code) => code && code !== 0 && code !== null && console.error(`进程退出 ${code}: ${err}`))
  procs.push(p)
  await waitHttp(url)
  return p
}

/** 启动钉钉替身（8022）与验收后端（8012，前置完成后启动，确保读到新库） */
export async function startSystem() {
  try {
    await fetch(`${STUB}/_stub/messages`)
  } catch {
    await startProc(['dingtalk_stub.main:app', '--port', '8022'], `${STUB}/_stub/messages`)
  }
  await fetch(`${STUB}/_stub/reset`, { method: 'POST' })
  await startProc(['tests.acceptance.e2_server:app', '--port', '8012'], `${BASE}/api/health`)
  const html = await (await fetch(`${BASE}/`)).text()
  ok(html.includes('<div id="app">') || html.includes('id="app"'), '后端托管前端构建产物')
}
export async function stopSystem() {
  for (const p of procs) p.kill('SIGTERM')
}

export async function setClock(text) {
  const r = await fetch(`${BASE}/_e2e/clock`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ now: text }) })
  assert.equal(r.status, 200)
}
export async function flushOutbox() {
  const r = await fetch(`${BASE}/_e2e/outbox`, { method: 'POST' })
  assert.equal(r.status, 200)
  return r.json()
}
export async function stubMessages() {
  return (await fetch(`${STUB}/_stub/messages`)).json()
}
export async function clearStub() {
  await fetch(`${STUB}/_stub/messages`, { method: 'DELETE' })
}

/** 新浏览器上下文 + 开发身份登录（/api/dev/login-as），返回页面 */
export async function as(browser, users, userid) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, baseURL: BASE, acceptDownloads: true })
  const page = await ctx.newPage()
  page.on('pageerror', (e) => console.error(`[${userid}] 页面脚本错误：`, e.message))
  await loginPage(page, users, userid)
  return page
}
export async function loginPage(page, users, userid) {
  const r = await page.request.post('/api/dev/login-as', { data: { user_id: users[userid] } })
  assert.equal(r.status(), 200, await r.text())
}

/** 打开表格页并等待 RevoGrid 渲染 */
export async function gotoGrid(page, url) {
  await page.goto(url)
  await page.locator('revo-grid').first().waitFor()
  await page.waitForFunction(() => document.querySelector('revo-grid')?.querySelectorAll('.rgCell').length > 0)
}

/** 读当前页面表格数据（RevoGrid 的行模型，即页面实际显示的值来源） */
export async function gridRows(page) {
  return page.evaluate(async () => {
    const g = document.querySelector('revo-grid')
    const src = await g.getSource('rgRow')
    const pinned = await g.getSource('rowPinEnd')
    return [...src, ...pinned].map((m) => ({ ...m }))
  })
}
export async function cellValue(page, rowKey, field) {
  const rows = await gridRows(page)
  const r = rows.find((m) => m.__rowKey === rowKey)
  return r ? r[field] : undefined
}

/** 页面上实际渲染出的单元格文本（滚动到该格后读 DOM） */
export async function cellText(page, rowKey, field) {
  const el = await locateCell(page, rowKey, field)
  return (await el.innerText()).trim()
}

async function locateCell(page, rowKey, field) {
  const loc = page.locator(`span[data-cell="${rowKey}::${field}"]`).filter({ visible: true }).first().locator('xpath=..')
  for (let attempt = 0; attempt < 4; attempt++) {
    const found = await page.evaluate(
      async ({ rowKey, field }) => {
        const g = document.querySelector('revo-grid')
        const src = await g.getSource('rgRow')
        const cols = await g.getColumns()
        const flat = []
        const walk = (cs) => cs.forEach((c) => (c.children ? walk(c.children) : flat.push(c)))
        walk(cols)
        if (!flat.some((c) => !c.pin && c.prop === field)) return false
        const y = src.findIndex((m) => m.__rowKey === rowKey)
        if (y >= 0) await g.scrollToRow(y)
        await g.scrollToColumnProp(field)
        await new Promise((r) => setTimeout(r, 400))
        return true
      },
      { rowKey, field },
    )
    assert.ok(found, `表格中找不到 ${rowKey} · ${field}`)
    try {
      await loc.waitFor({ timeout: 3000 })
      return loc
    } catch {
      /* 虚拟滚动尚未渲染到该格，重新滚动 */
    }
  }
  await loc.waitFor({ timeout: 3000 })
  return loc
}

/** 像用户一样编辑一个单元格：双击 → 输入 → 回车（失焦即保存），等待保存请求返回 */
export async function editCell(page, rowKey, field, value) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const cell = await locateCell(page, rowKey, field)
    const resp = page.waitForResponse((r) => r.url().includes('/cells') && r.request().method() === 'PATCH', { timeout: 6000 })
    await cell.click()
    await cell.dblclick()
    const editor = page.locator('revogr-edit input, revogr-edit textarea').filter({ visible: true }).first()
    await editor.waitFor({ timeout: 5000 })
    await editor.fill(String(value))
    await editor.press('Enter')
    try {
      return await (await resp).json()
    } catch (e) {
      if (attempt) throw e
      await page.keyboard.press('Escape').catch(() => {})
      await page.waitForTimeout(500)
    }
  }
}

/** 尝试编辑：返回编辑器是否出现（只读格不出现编辑器） */
export async function tryEdit(page, rowKey, field) {
  const cell = await locateCell(page, rowKey, field)
  await cell.click()
  await cell.dblclick()
  await page.waitForTimeout(300)
  const editor = page.locator('revogr-edit input, revogr-edit textarea').filter({ visible: true }).first()
  const shown = await editor.isVisible().catch(() => false)
  if (shown) await editor.press('Escape')
  return shown
}

export async function run(name, fn) {
  const browser = await chromium.launch()
  const t0 = Date.now()
  try {
    await fn(browser)
    console.log(`${name} PASS checks=${checkCount()} seconds=${((Date.now() - t0) / 1000).toFixed(1)}`)
  } catch (e) {
    console.error(`${name} FAIL after checks=${checkCount()}:`, e)
    process.exitCode = 1
  } finally {
    await browser.close()
    await stopSystem()
  }
}
