// E1 浏览器验收共用：重建 budget_acc1 → 启动钉钉替身（8021）与后端（8011，开发配置，托管 build:dev 产物）→ Playwright。
// 用法：node e2e/<id>.spec.mjs；环境变量 E1_STATIC_DIR 指向 `vite build --mode development --outDir <dir>` 的产物目录
// （缺省用 app/backend/app/static，须为 build:dev 产物）。
import { spawn, execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { chromium } from 'playwright'

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
uvicorn.run(m.app, host='127.0.0.1', port=${PORT}, log_level='warning')
`

export async function startEnv(scenario = 'default') {
  py('reset', scenario)
  const procs = []
  const stub = spawn(PY, ['-m', 'uvicorn', 'dingtalk_stub.main:app', '--port', String(STUB_PORT), '--log-level', 'warning'],
    { cwd: BACKEND, env: ENV, stdio: ['ignore', 'inherit', 'inherit'] })
  procs.push(stub)
  await waitFor(`${STUB}/_stub/messages`)
  await fetch(`${STUB}/_stub/reset`, { method: 'POST' })
  const backendLog = []
  const be = spawn(PY, ['-c', LAUNCH], { cwd: BACKEND, env: ENV, stdio: ['ignore', 'pipe', 'pipe'] })
  be.stdout.on('data', (d) => backendLog.push(String(d)))
  be.stderr.on('data', (d) => backendLog.push(String(d)))
  procs.push(be)
  await waitFor(`${BASE}/api/health`)
  const browser = await chromium.launch()
  const consoleErrors = []
  return {
    browser,
    backendLog,
    consoleErrors,
    async newPage() {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } })
      const page = await ctx.newPage()
      page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`${page.url()} :: ${m.text()}`) })
      page.on('pageerror', (e) => consoleErrors.push(`${page.url()} :: pageerror ${e.message}`))
      return page
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

export async function run(id, scenario, body) {
  const env = await startEnv(scenario)
  let ok = false
  try {
    await body(env)
    ok = true
  } catch (e) {
    console.error(e)
    failed++
    failures.push(`异常：${e.message}`)
    if (env.backendLog.length) console.error('后端日志：\n' + env.backendLog.join('').slice(-4000))
  } finally {
    await env.stop()
  }
  console.log(`[${id}] 浏览器控制台错误 ${env.consoleErrors.length} 条`)
  for (const e of env.consoleErrors) console.log('  ' + e)
  const allOk = summary(env) && ok
  process.exit(allOk ? 0 : 1)
}
