// RULE-02 浏览器层：四类受限角色直接拼接链接访问范围外页面 → 页面显示「无权限」，前端不收到范围外记录。
// 前置：cd app/backend && .venv/bin/python -m tests.acceptance.e4_env reset rule02；后端 8014 已启动（e4_server）。
// 运行：node app/frontend/e2e/rule_02.spec.mjs
import { chromium, BASE, loginAs, check, finish } from './e4_harness.mjs'

const results = []
const browser = await chromium.launch()

// 1. 财务负责人经接口发布 2027 编制任务（含 Amazon-DE-01、外贸部、市场部等范围外单位）
const setup = await browser.newPage()
await loginAs(setup, 'linxiao')
const cands = await (await setup.request.get(`${BASE}/api/tasks/candidates`)).json()
const want = [['platform', 'Amazon-US-01'], ['platform', 'Amazon-DE-01'], ['b2b', '美国业务部'], ['b2b', '外贸部'],
  ['cost_ratio', ''], ['logistics_ratio', ''], ['dept_expense', '人力资源部'], ['dept_expense', '市场部']]
const units = cands.items.filter((c) => want.some(([t, w]) => c.unit_type === t && c.name.includes(w)))
  .map((c) => ({ unit_type: c.unit_type, scope_object_id: c.scope_object_id }))
const pub = await setup.request.post(`${BASE}/api/tasks`, { data: { year: 2027, deadline: '2026-12-20', units } })
if (pub.status() !== 201) throw new Error(`发布失败 ${pub.status()} ${await pub.text()}`)
const taskId = (await pub.json()).task.id
const progress = await (await setup.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()
const unitRows = progress.units || progress.items || []
const unitId = (name) => {
  const u = unitRows.find((x) => (x.name || x.unit_name || '').includes(name))
  if (!u) throw new Error(`找不到单位 ${name}: ${JSON.stringify(unitRows.map((x) => x.name || x.unit_name))}`)
  return u.id ?? u.unit_id
}
const ids = { de: unitId('Amazon-DE-01'), us: unitId('Amazon-US-01'), eu: unitId('外贸部'), mkt: unitId('市场部') }
await setup.close()

const cases = [
  ['wanghao', '王浩', `/filling/platform/${ids.de}`, 'Amazon-DE-01'],
  ['sunting', '孙婷', `/filling/b2b/${ids.eu}`, 'Bauhaus'],
  ['wujing', '吴静', `/dept-expense?unitId=${ids.mkt}`, '市场部'],
  ['wujing', '吴静', `/approvals/unit/${ids.mkt}`, '市场部'],
  ['jiangfan', '蒋帆', `/filling/platform/${ids.us}`, '收入'],
]

for (const [userid, name, path, secret] of cases) {
  const ctx = await browser.newContext()
  const page = await ctx.newPage()
  await loginAs(page, userid)
  const leaks = []
  page.on('response', async (resp) => {
    if (!resp.url().includes('/api/') || resp.url().includes('/api/me') || resp.url().includes('/api/auth')) return
    try {
      const body = await resp.text()
      if (resp.status() === 200 && body.includes(secret)) leaks.push(`${resp.status()} ${resp.url()}`)
      if (resp.status() === 403 && body !== '{"code":"forbidden","message":"无权限"}') leaks.push(`403 body ${body}`)
    } catch {}
  })
  await page.goto(BASE + path)
  let shown = false
  try {
    await page.getByText('无权限', { exact: true }).first().waitFor({ timeout: 15000 })
    shown = true
  } catch {}
  const main = await page.locator('main, .main, #app').first().innerText().catch(() => '')
  await page.screenshot({ path: `/tmp/claude-0/-home-user/001a2709-c0f1-57ab-bb23-2c886d9a31b8/scratchpad/rule02_${userid}_${path.replace(/\W+/g, '_')}.png` })
  check(results, `${name} 直链 ${path} 显示「无权限」`, shown, main.slice(0, 120).replace(/\s+/g, ' '))
  check(results, `${name} 直链 ${path} 前端未收到范围外记录`, leaks.length === 0, leaks.join('; '))
  await ctx.close()
}
await browser.close()
finish(results)
