// RULE-08 计算刷新性能（NFR-001）：20,000 个预算单元的库中，王浩在平台渠道填报页（PAGE-F04-02）连续 100 次编辑驱动值
// （双击 → 输入 → 回车），记录「保存请求发出 → 页面受影响合计（人民币收入合计行该月）渲染完成」耗时（performance.now），
// 并核对每次合计与独立按公式重算（/_e2e/recompute，直接从驱动值计算）一致。
// 前置：cd app/backend && .venv/bin/python -m tests.acceptance.e4_env reset；后端 8014（e4_server，开发配置）已启动。
// 运行：node app/frontend/e2e/rule_08.spec.mjs
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, BASE, loginAs, check, finish } from './e4_harness.mjs'

const BACKEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend')
const OUT = process.env.E4_OUT || '/tmp/claude-0/-home-user/001a2709-c0f1-57ab-bb23-2c886d9a31b8/scratchpad'
const results = []
const browser = await chromium.launch()

// 1. 财务负责人发布 2027 编制任务（Amazon-US-01），再追加压测店铺单元使库内预算单元 ≥ 20,000
const setup = await browser.newPage()
await loginAs(setup, 'linxiao')
const cands = await (await setup.request.get(`${BASE}/api/tasks/candidates`)).json()
const us = cands.items.find((c) => c.unit_type === 'platform' && c.name === 'Amazon-US-01')
const pub = await setup.request.post(`${BASE}/api/tasks`, {
  data: { year: 2027, deadline: '2026-12-20', units: [{ unit_type: 'platform', scope_object_id: us.scope_object_id }] },
})
if (pub.status() !== 201) throw new Error(`发布失败 ${await pub.text()}`)
const units = execFileSync(path.join(BACKEND, '.venv/bin/python'), ['-m', 'tests.acceptance.e4_env', 'bulk', '20000'],
  { cwd: BACKEND, encoding: 'utf8' }).trim()
check(results, `库内预算单元 ≥ 20,000`, Number(units) >= 20000, `platform_unit 行数 ${units}`)
await setup.close()

// 2. 王浩打开填报页；先经接口预填驱动（SPU 5、单价 79.99、折扣 10%、销量 40），使每次编辑都改变合计
const ctx = await browser.newContext({ viewport: { width: 1600, height: 1000 } })
const page = await ctx.newPage()
await loginAs(page, 'wanghao')
const mine = await (await page.request.get(`${BASE}/api/filling-units`)).json()
const unitId = mine.items.find((u) => u.name === 'Amazon-US-01').id
const grid0 = await (await page.request.get(`${BASE}/api/filling-units/${unitId}/grid`)).json()
const months = grid0.columns.filter((c) => c.kind === 'value' && /^\d{4}-\d{2}$/.test(c.key)).map((c) => c.key)
const prefill = []
for (const r of grid0.rows.filter((x) => x.kind === 'input')) {
  const item = r.key.split('|')[1]
  const v = { spu_count: '5', avg_price: '79.99', discount_rate: '10', avg_sales: '40' }[item]
  if (v) for (const m of months) prefill.push({ row_key: r.key, field: m, value: v, base: r.values[m] ?? null })
}
const pf = await page.request.patch(`${BASE}/api/filling-units/${unitId}/cells`, { data: prefill })
if (pf.status() !== 200 || (await pf.json()).errors.length) throw new Error(`预填失败 ${await pf.text()}`)

// 页面内计时：fetch 发出 PATCH …/cells 时记 t0；requestAnimationFrame 循环记录合计格每次渲染出的文本与时刻
await page.addInitScript(() => {
  const orig = window.fetch
  window.__t0 = []
  window.fetch = (input, init) => {
    const url = typeof input === 'string' ? input : input.url
    if (init?.method === 'PATCH' && url.includes('/cells')) window.__t0.push(performance.now())
    return orig(input, init)
  }
  window.__renders = []
  window.__watch = null
  let last = null
  const loop = () => {
    if (window.__watch) {
      const el = document.querySelector(`span[data-cell="total|revenue_cny::${window.__watch}"]`)
      const t = el ? el.textContent.trim() : null
      if (t !== last) { window.__renders.push({ t: performance.now(), text: t, field: window.__watch }); last = t }
    }
    requestAnimationFrame(loop)
  }
  requestAnimationFrame(loop)
})
await page.goto(`${BASE}/filling/platform/${unitId}`)
await page.locator('revo-grid').first().waitFor()
await page.waitForFunction(() => document.querySelector('revo-grid')?.querySelectorAll('.rgCell').length > 0)

async function locate(rowKey, field) {
  await page.evaluate(async ({ rowKey, field }) => {
    const g = document.querySelector('revo-grid')
    const src = await g.getSource('rgRow')
    const y = src.findIndex((m) => m.__rowKey === rowKey)
    if (y >= 0) await g.scrollToRow(y)
    await g.scrollToColumnProp(field)
    await new Promise((r) => setTimeout(r, 300))
  }, { rowKey, field })
  const loc = page.locator(`span[data-cell="${rowKey}::${field}"]`).filter({ visible: true }).first().locator('xpath=..')
  await loc.waitFor({ timeout: 10000 })
  return loc
}

const salesRows = grid0.rows.filter((r) => r.kind === 'input' && r.key.endsWith('|avg_sales')).map((r) => r.key)
const samples = []
for (let i = 0; i < 100; i++) {
  const rowKey = salesRows[i % salesRows.length]
  const field = months[i % months.length]
  const value = String(41 + i)
  const cell = await locate(rowKey, field)
  await page.evaluate((f) => { window.__watch = f; window.__t0 = [] }, field)
  await page.waitForTimeout(100)
  const before = await page.evaluate(() => window.__renders.length)
  const resp = page.waitForResponse((r) => r.url().includes('/cells') && r.request().method() === 'PATCH', { timeout: 15000 })
  await cell.click()
  await cell.dblclick()
  const editor = page.locator('revogr-edit input, revogr-edit textarea').filter({ visible: true }).first()
  await editor.waitFor({ timeout: 5000 })
  await editor.fill(value)
  await editor.press('Enter')
  const body = await (await resp).json()
  if (body.errors?.length) throw new Error(`保存失败 ${JSON.stringify(body.errors)}`)
  const expected = (await (await page.request.get(`${BASE}/_e2e/recompute?store=Amazon-US-01&month=${field}`)).json()).total
  const hit = await page.waitForFunction(({ before, expected, field }) => {
    const r = window.__renders.slice(before).find((x) => x.field === field && x.text?.replace(/[¥\s]/g, '') === expected)
    return r ? { t1: r.t, t0: window.__t0[0] } : null
  }, { before, expected, field }, { timeout: 15000, polling: 50 }).then((h) => h.jsonValue()).catch(() => null)
  samples.push({ i, rowKey, field, value, expected, shown: hit ? expected : null,
    ms: hit && hit.t0 != null ? hit.t1 - hit.t0 : null })
}
const ok = samples.filter((s) => s.ms != null)
const ms = ok.map((s) => s.ms).sort((a, b) => a - b)
const p = (q) => ms[Math.min(ms.length - 1, Math.ceil(q * ms.length) - 1)]
check(results, '100 次保存的合计均与独立重算一致并已渲染', ok.length === 100, `一致 ${ok.length}/100`)
check(results, `P95 ≤ 3 秒（P50 ${p(0.5)?.toFixed(0)} ms，P95 ${p(0.95)?.toFixed(0)} ms，最大 ${ms.at(-1)?.toFixed(0)} ms）`,
  ms.length === 100 && p(0.95) <= 3000)
writeFileSync(path.join(OUT, 'rule08_samples.json'), JSON.stringify({ units: Number(units), samples }, null, 1))
await page.screenshot({ path: path.join(OUT, 'rule08_last.png') })
await browser.close()
finish(results)
