// E3（FLOW-21~32）浏览器验收共用：重建 budget_acc3 + 场景前置 → 钉钉替身 8023 → 后端 8013（固定时钟，托管 build:dev 产物）→ Playwright。
// 用法：node e2e/flow-xx.spec.mjs
// 环境变量：E3_STATIC_DIR = `vite build --mode development --outDir <dir>` 产物目录（缺省 app/backend/app/static，须为 build:dev 产物）；
//          PLAYWRIGHT_MODULE = playwright 包路径（缺省全局 /opt/node22/lib/node_modules/playwright）。
import { spawn, execFileSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { readFileSync } from 'node:fs'

const require = createRequire(import.meta.url)
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || '/opt/node22/lib/node_modules/playwright')

const here = path.dirname(fileURLToPath(import.meta.url))
export const BACKEND = path.resolve(here, '../../backend')
const PY = path.join(BACKEND, '.venv/bin/python')
export const PORT = 8013
export const STUB_PORT = 8023
export const BASE = `http://127.0.0.1:${PORT}`
const STUB = `http://127.0.0.1:${STUB_PORT}`

const ENV = {
  ...process.env,
  E3_DATABASE_URL: 'postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc3',
  DATABASE_URL: 'postgresql+psycopg://budget:budget@127.0.0.1:5432/budget_acc3',
  E3_PORT: String(PORT),
  APP_ENV: 'dev',
  DEV_IDENTITY_SWITCH: 'true',
  SCHEDULER_ENABLED: 'false',
  APP_BASE_URL: BASE,
  DATA_DIR: '/tmp/e3_acc/data',
  E3_DATA_DIR: '/tmp/e3_acc',
  DINGTALK_BASE_URL: STUB,
  DINGTALK_APP_KEY: 'stub',
  DINGTALK_APP_SECRET: 'stub',
  DINGTALK_AGENT_ID: '10001',
  DINGTALK_CORP_ID: 'ding-stub',
}

export function py(...args) {
  const out = execFileSync(PY, ['-m', 'tests.acceptance.e3_env', ...args], { cwd: BACKEND, env: ENV, encoding: 'utf8', maxBuffer: 64 << 20 })
  const lines = out.trim().split('\n')
  return JSON.parse(lines[lines.length - 1])
}

async function waitFor(url) {
  for (let i = 0; i < 150; i++) {
    try {
      const r = await fetch(url)
      if (r.status < 500) return
    } catch {}
    await new Promise((r) => setTimeout(r, 200))
  }
  throw new Error(`服务未就绪：${url}`)
}

export async function startEnv(scenario, now) {
  const seeded = py('reset', scenario)
  const procs = []
  const stub = spawn(PY, ['-m', 'uvicorn', 'dingtalk_stub.main:app', '--port', String(STUB_PORT), '--log-level', 'warning'],
    { cwd: BACKEND, env: ENV, stdio: ['ignore', 'inherit', 'inherit'] })
  procs.push(stub)
  await waitFor(`${STUB}/_stub/messages`)
  const backendLog = []
  const be = spawn(PY, ['-m', 'tests.acceptance.e3_env', 'serve'], { cwd: BACKEND, env: { ...ENV, E3_NOW: now || '' }, stdio: ['ignore', 'pipe', 'pipe'] })
  be.stdout.on('data', (d) => backendLog.push(String(d)))
  be.stderr.on('data', (d) => backendLog.push(String(d)))
  procs.push(be)
  await waitFor(`${BASE}/api/health`)
  // 浏览器进程需 UTF-8 区域设置：本容器默认无 LANG（C 区域），Chromium 会把非 ASCII 下载文件名退化为「download」
  const browser = await chromium.launch({ env: { ...process.env, LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' } })
  const consoleErrors = []
  return {
    seeded,
    browser,
    backendLog,
    consoleErrors,
    async newPage() {
      const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true })
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

const userIds = new Map()
/** 开发身份：经 /api/dev/login-as 切换（Cookie 落在当前浏览器上下文） */
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

/** 页面内表格 → 二维文字数组（去首尾空白） */
export async function tableText(locator) {
  return locator.evaluate((t) => [...t.querySelectorAll('tr')].map((tr) => [...tr.querySelectorAll('th,td')].map((c) => c.textContent.replace(/\s+/g, ' ').trim())))
}

/** 上传文件（按内容传入：路径含中文时 setInputFiles(路径) 在本环境不生效） */
export function fileOf(p) {
  return { name: path.basename(p), mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', buffer: readFileSync(p) }
}

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

export async function run(id, scenario, now, body) {
  const env = await startEnv(scenario, now)
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
  console.log(`passed=${passed}; failed=${failed}`)
  if (failures.length) console.log('失败：\n' + failures.join('\n'))
  process.exit(ok && failed === 0 ? 0 : 1)
}
