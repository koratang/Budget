// RULE-01 页面层：同一单元在页面（PAGE-F04-02 表格渲染文本）、接口（grid）、导出（xlsx）三处同值：
// 明细 0.334 ×3 → 0.33、0.33、0.33，合计 1.00；1.005 → 1.01。
// 前置：cd app/backend && .venv/bin/python -m tests.acceptance.e4_env reset；后端 8014（e4_server）已启动。
import { execFileSync } from 'node:child_process'
import { writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, BASE, loginAs, check, finish } from './e4_harness.mjs'

const BACKEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../backend')
const OUT = process.env.E4_OUT || '/tmp/claude-0/-home-user/001a2709-c0f1-57ab-bb23-2c886d9a31b8/scratchpad'
const DB = 'postgresql://budget:budget@127.0.0.1:5432/budget_acc4'
const psql = (sql) => execFileSync('psql', [DB, '-Atc', sql], { encoding: 'utf8' }).trim()
const results = []
const browser = await chromium.launch()

const setup = await browser.newPage()
await loginAs(setup, 'linxiao')
const cands = await (await setup.request.get(`${BASE}/api/tasks/candidates`)).json()
const us = cands.items.find((c) => c.unit_type === 'platform' && c.name === 'Amazon-US-01')
const pub = await setup.request.post(`${BASE}/api/tasks`, {
  data: { year: 2027, deadline: '2026-12-20', units: [{ unit_type: 'platform', scope_object_id: us.scope_object_id }] },
})
if (pub.status() !== 201) throw new Error(await pub.text())
await setup.close()
// 前置：未舍入明细值直接入库（三个新品明细 0.334；浴室柜新品 2 月 1.005）
psql(`UPDATE platform_unit pu SET revenue_cny = 0.334 FROM category c, store s WHERE c.id = pu.category_id
  AND s.id = pu.store_id AND s.name = 'Amazon-US-01' AND pu.is_new AND pu.month = '2027-01-01' AND c.name IN ('框镜','灯镜','镜柜')`)
psql(`UPDATE platform_unit pu SET revenue_cny = 1.005 FROM category c, store s WHERE c.id = pu.category_id
  AND s.id = pu.store_id AND s.name = 'Amazon-US-01' AND pu.is_new AND pu.month = '2027-02-01' AND c.name = '浴室柜'`)

const page = await (await browser.newContext({ viewport: { width: 1600, height: 1000 } })).newPage()
await loginAs(page, 'wanghao')
const mine = await (await page.request.get(`${BASE}/api/filling-units`)).json()
const unitId = mine.items.find((u) => u.name === 'Amazon-US-01').id
const grid = await (await page.request.get(`${BASE}/api/filling-units/${unitId}/grid`)).json()
const keyOf = (cat, item) => grid.rows.find((r) => r.values.category === cat && r.values.is_new === '新品' && r.key.endsWith(`|${item}`))?.key
const cells = [
  ['框镜', keyOf('框镜', 'revenue_cny'), '2027-01', '0.33'],
  ['灯镜', keyOf('灯镜', 'revenue_cny'), '2027-01', '0.33'],
  ['镜柜', keyOf('镜柜', 'revenue_cny'), '2027-01', '0.33'],
  ['店铺合计', 'total|revenue_cny', '2027-01', '1.00'],
  ['浴室柜', keyOf('浴室柜', 'revenue_cny'), '2027-02', '1.01'],
]

await page.goto(`${BASE}/filling/platform/${unitId}`)
await page.locator('revo-grid').first().waitFor()
await page.waitForFunction(() => document.querySelector('revo-grid')?.querySelectorAll('.rgCell').length > 0)
async function domText(rowKey, field) {
  await page.evaluate(async ({ rowKey, field }) => {
    const g = document.querySelector('revo-grid')
    const src = await g.getSource('rgRow')
    const y = src.findIndex((m) => m.__rowKey === rowKey)
    if (y >= 0) await g.scrollToRow(y)
    await g.scrollToColumnProp(field)
    await new Promise((r) => setTimeout(r, 400))
  }, { rowKey, field })
  const el = page.locator(`span[data-cell="${rowKey}::${field}"]`).filter({ visible: true }).first()
  await el.waitFor({ timeout: 10000 })
  return (await el.innerText()).trim()
}

const exp = await page.request.get(`${BASE}/api/export?view=budget-platform&filters=${encodeURIComponent(JSON.stringify({ unit_id: unitId }))}`)
const xlsx = path.join(OUT, 'rule01_export.xlsx')
writeFileSync(xlsx, await exp.body())
const exported = JSON.parse(execFileSync(path.join(BACKEND, '.venv/bin/python'), ['-c', `
import json, sys
from decimal import Decimal
from openpyxl import load_workbook
ws = load_workbook(sys.argv[1]).worksheets[0]
rows = list(ws.iter_rows(values_only=True)); h = list(rows[0])
out = {}
for r in rows[1:]:
    if r[2] == '收入（人民币）' and r[1] in ('新品', '—'):
        for m, col in (('2027-01', '1 月'), ('2027-02', '2 月')):
            v = r[h.index(col)]
            out[f"{r[0]}|{m}"] = None if v in (None, '—') else format(Decimal(str(v)).quantize(Decimal('0.01')), 'f')
print(json.dumps(out, ensure_ascii=False))
`, xlsx], { encoding: 'utf8' }))

for (const [name, rowKey, field, want] of cells) {
  const api = grid.rows.find((r) => r.key === rowKey)?.values[field]
  const shown = await domText(rowKey, field)
  const xl = exported[`${name}|${field}`]
  check(results, `${name} ${field}：页面 ${shown}、接口 ${api}、导出 ${xl}，期望 ${want}`,
    shown === want && api === want && xl === want)
}
await page.screenshot({ path: path.join(OUT, 'rule01_page.png') })
await browser.close()
finish(results)
