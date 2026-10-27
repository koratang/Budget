// E1 浏览器验收共用：重建 budget_acc1 → 启动钉钉替身（8021）与后端（8011，开发配置，托管 build:dev 产物）→ Playwright。
// 用法：node e2e/<id>.spec.mjs；环境变量 E1_STATIC_DIR 指向 `vite build --mode development --outDir <dir>` 的产物目录
// （缺省用 app/backend/app/static，须为 build:dev 产物）。
import { spawn, execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'

// playwright 为本机全局安装（NODE_PATH），ESM import 不读 NODE_PATH，用 require 解析
const { chromium } = createRequire(import.meta.url)('playwright')

const here = path.dirname(fileURLToPath(import.meta.url))
export const BACKEND = path.resolve(here, '../../backend')
const PY = path.join(BACKEND, '.venv/bin/python')
export const PORT = 8011
export const STUB_PORT = 8021
export const BASE = `http://127.0.0.1:${PORT}`
export const STUB = `http://127.0.0.1:${STUB_PORT}`
const DB_URL = 'postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc1'

const ENV = {
  ...process.env,
  DATABASE_URL: DB_URL,
  APP_ENV: 'dev',
  DEV_IDENTITY_SWITCH: 'true',
  SCHEDULER_ENABLED: 'false',
  APP_BASE_URL: BASE,
  DATA_DIR: '/tmp/e1_acc_data',
  DINGTALK_BASE_URL: STUB,
  DINGTALK_APP_KEY: 'stub',
  DINGTALK_APP_SECRET: 'stub',
  DINGTALK_AGENT_ID: '10001',
  DINGTALK_CORP_ID: 'ding-stub',
}

export function py(...args) {
  return execFileSync(PY, ['-m', 'tests.acceptance.e1_env', ...args], { cwd: BACKEND, env: ENV, encoding: 'utf8' })
}

async function waitFor(url) {
  for (let i = 0; i < 100; i++) {
    try {
      const r = await fetch(url)
      if (r.status < 500) return
    } catch {}
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error(`服务未就绪：${url}`)
}

const LAUNCH = `
import os, uvicorn
from pathlib import Path
import app.main as m
if os.environ.get('E1_STATIC_DIR'):
    m.STATIC_DIR = Path(os.environ['E1_STATIC_DIR']).resolve()
if os.environ.get('E1_NOW'):
    # 可控时钟（验收用）：进程内固定当前时间
    from datetime import datetime
    from app.core.clock import clock
    clock.set_now(datetime.fromisoformat(os.environ['E1_NOW']))
uvicorn.run(m.app, host='127.0.0.1', port=${PORT}, log_level='warning')
`

export async function startEnv(scenario = 'default', opts = {}) {
  py('reset', scenario)
  const procs = []
  const stub = spawn(PY, ['-m', 'uvicorn', 'dingtalk_stub.main:app', '--port', String(STUB_PORT), '--log-level', 'warning'],
    { cwd: BACKEND, env: ENV, stdio: ['ignore', 'inherit', 'inherit'] })
  procs.push(stub)
  await waitFor(`${STUB}/_stub/messages`)
  await fetch(`${STUB}/_stub/reset`, { method: 'POST' })
  const backendLog = []
  let be = null
  async function startBackend(extra = {}) {
    be = spawn(PY, ['-c', LAUNCH], { cwd: BACKEND, env: { ...ENV, ...extra }, stdio: ['ignore', 'pipe', 'pipe'] })
    be.stdout.on('data', (d) => backendLog.push(String(d)))
    be.stderr.on('data', (d) => backendLog.push(String(d)))
    procs.push(be)
    await waitFor(`${BASE}/api/health`)
  }
  await startBackend(opts.backendEnv ?? {})
  const browser = await chromium.launch()
  const consoleErrors = []
  const pages = []
  return {
    pages,
    browser,
    backendLog,
    consoleErrors,
    async newPage() {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
      const page = await ctx.newPage()
      pages.push(page)
      page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`${page.url()} :: ${m.text()}`) })
      page.on('pageerror', (e) => consoleErrors.push(`${page.url()} :: pageerror ${e.message}`))
      return page
    },
    // 以新的环境变量（如 E1_NOW 可控时钟）重启后端；会话按 8 小时无操作规则可能失效，调用方重新切换身份
    async restartBackend(extra = {}) {
      const old = be
      old.kill('SIGTERM')
      await new Promise((r) => old.once('exit', r))
      await startBackend(extra)
    },
    async stop() {
      await browser.close()
      for (const p of procs) p.kill('SIGTERM')
    },
  }
}

// 开发身份：以姓名切换（经 /api/dev/login-as，Cookie 落在当前浏览器上下文）
const userIds = new Map()
export async function loginAs(page, name) {
  if (!userIds.size) {
    const r = await page.request.get(`${BASE}/api/auth/dev-users`)
    for (const u of await r.json()) userIds.set(u.name, u.id)
  }
  const id = userIds.get(name)
  if (!id) throw new Error(`无开发身份：${name}`)
  const r = await page.request.post(`${BASE}/api/dev/login-as`, { data: { user_id: id } })
  if (r.status() !== 200) throw new Error(`login-as ${name} → ${r.status()} ${await r.text()}`)
}

export function resetUserCache() { userIds.clear() }

let passed = 0
let failed = 0
const failures = []
export function check(cond, label) {
  if (cond) { passed++; console.log(`  ✓ ${label}`) } else { failed++; failures.push(label); console.log(`  ✗ ${label}`) }
}
export function eq(actual, expected, label) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected)
  check(ok, ok ? label : `${label}（期望 ${JSON.stringify(expected)}，实际 ${JSON.stringify(actual)}）`)
}
export function summary(env) {
  console.log(`passed=${passed}; failed=${failed}`)
  if (failures.length) console.log('失败：\n' + failures.join('\n'))
  return failed === 0
}

export async function run(id, scenario, body, opts = {}) {
  const env = await startEnv(scenario, opts)
  let ok = false
  try {
    await body(env)
    ok = true
  } catch (e) {
    console.error(e)
    failed++
    failures.push(`异常：${e.message}`)
    if (env.backendLog.length) console.error('后端日志：\n' + env.backendLog.join('').slice(-4000))
    for (const [i, pg] of env.pages.entries()) {
      await pg.screenshot({ path: `/tmp/e1_acc_files/fail-${id}-${i}.png`, fullPage: true }).catch(() => {})
      console.error(`失败截图 /tmp/e1_acc_files/fail-${id}-${i}.png  ${pg.url()}`)
    }
  } finally {
    await env.stop()
  }
  console.log(`[${id}] 浏览器控制台错误 ${env.consoleErrors.length} 条`)
  for (const e of env.consoleErrors) console.log('  ' + e)
  const allOk = summary(env) && ok
  process.exit(allOk ? 0 : 1)
}

// 在 BudgetGrid（RevoGrid）中按行键与列编辑一个单元格：打开单元格编辑器 → 输入 → 回车提交（触发真实保存请求）
export async function editCell(page, rowKey, prop, value) {
  const idx = await page.evaluate(async ({ rowKey, prop }) => {
    const g = document.querySelector('revo-grid')
    const src = await g.getSource()
    const i = src.findIndex((r) => r.__rowKey === rowKey)
    if (i < 0) return -1
    await g.scrollToRow(i)
    await g.scrollToColumnProp(prop)
    return i
  }, { rowKey, prop })
  if (idx < 0) throw new Error(`表格中没有行 ${rowKey}`)
  await page.waitForTimeout(200)
  await page.evaluate(async ({ idx, prop }) => {
    const g = document.querySelector('revo-grid')
    await g.setCellEdit(idx, prop)
  }, { idx, prop })
  const editor = page.locator('revo-grid input, revo-grid textarea').first()
  await editor.waitFor({ timeout: 5000 })
  await editor.fill(String(value))
  const resp = page.waitForResponse((r) => /\/cells/.test(r.url()) && r.request().method() === 'PATCH', { timeout: 10000 })
    .catch(() => null)
  await editor.press('Enter')
  return resp
}

// 读表格某行某列当前显示值（来自页面中表格的数据源）
export async function cellValue(page, rowKey, prop) {
  return page.evaluate(async ({ rowKey, prop }) => {
    const g = document.querySelector('revo-grid')
    const src = await g.getSource()
    const r = src.find((x) => x.__rowKey === rowKey)
    return r ? r[prop] : undefined
  }, { rowKey, prop })
}

// 生成上传用 Excel（openpyxl，数字以数字单元格写入）
export function writeXlsx(file, header, rows) {
  const code = 'import json,sys\nfrom openpyxl import Workbook\nd=json.loads(sys.argv[2])\nwb=Workbook();ws=wb.active\nws.append(d["h"])\n[ws.append(r) for r in d["r"]]\nwb.save(sys.argv[1])'
  execFileSync(PY, ['-c', code, file, JSON.stringify({ h: header, r: rows })], { cwd: BACKEND, env: ENV })
  // 以内容 + 原文件名交给 setInputFiles（本机 Playwright 按路径上传中文文件名时不触发选择）
  return { name: path.basename(file), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: readFileSync(file) }
}
