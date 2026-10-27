// FLOW-07 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-07。
import { mkdirSync } from 'node:fs'
import { run, loginAs, BASE, check, eq, editCell, writeXlsx } from './e1_harness.mjs'

const DIR = '/tmp/e1_acc_files/flow07'
mkdirSync(DIR, { recursive: true })
const KD_H = ['期间', '金蝶科目', '科目名称', '部门', '平台/店铺', '站点', '客户', '摘要', '发生额']
const BI_H = ['月份', '店铺', '站点', 'SKU', '销量', '本币销售额', '币种', '广告费', '平台费用']

async function typeRate(page, label, value) {
  const cell = page.getByRole('textbox', { name: label })
  await cell.click()
  await page.keyboard.press('Control+A')
  await page.keyboard.type(value)
  const resp = page.waitForResponse((r) => r.url().includes('/api/master/fx/') && r.request().method() === 'PUT')
  await page.keyboard.press('Enter')
  return resp
}

async function importFile(page, source, file) {
  const r = await page.request.post(`${BASE}/api/imports`, { multipart: { file, source } })
  const id = (await r.json()).id
  let b
  for (let i = 0; i < 50; i++) { b = await (await page.request.get(`${BASE}/api/imports/${id}`)).json(); if (b.status !== 'validating') break; await page.waitForTimeout(200) }
  const c = await page.request.post(`${BASE}/api/imports/${id}/confirm`, { data: { overwrite: false } })
  return [b.status, c.status()]
}

await run('FLOW-07', 'flow07', async (env) => {
  const bp = await env.newPage()
  await loginAs(bp, '陈思雨')
  await bp.goto(`${BASE}/master/fx`)
  await bp.getByRole('table', { name: '年度预算汇率' }).waitFor()
  eq((await typeRate(bp, 'USD 预算汇率', '7.12')).status(), 200, '编制期陈思雨录入 2027 USD 预算汇率 7.12')

  const lin = await env.newPage()
  await loginAs(lin, '林晓')
  await lin.goto(`${BASE}/tasks`)
  await lin.locator('[data-publish]').click()
  await lin.locator('#p-year').selectOption('2027')
  await lin.locator('#p-dl').fill('2026-12-20')
  const modal = lin.getByRole('dialog')
  for (const fs of await modal.locator('fieldset').all()) { const all = fs.locator('legend input'); if (await all.isChecked()) await all.uncheck() }
  for (const s of ['Amazon-US-01', 'Amazon-DE-01']) await modal.locator('fieldset label', { hasText: s }).locator('input').check()
  await lin.locator('[data-publish-ok]').click()
  await lin.getByText('已发布「2027 年度预算编制」').waitFor()

  const wang = await env.newPage()
  await loginAs(wang, '王浩')
  await wang.goto(`${BASE}/filling`)
  await wang.locator('[data-unit="Amazon-US-01"] a').click()
  await wang.waitForSelector('revo-grid .rgCell')
  const keys = await wang.evaluate(async () => (await document.querySelector('revo-grid').getSource()).map((r) => r.__rowKey))
  const k = (f) => keys.find((x) => x.split(':')[3] === '5' && x.includes(':1|') && x.endsWith(`|${f}`))
  for (const [f, v] of [['spu_count', '10'], ['avg_sales', '120'], ['avg_price', '80.00'], ['discount_rate', '10']]) {
    const r = await editCell(wang, k(f), '2027-03', v)
    check(r && r.status() === 200, `王浩填 ${f} = ${v}`)
  }
  await wang.waitForTimeout(500)
  const kpi = await wang.locator('.kpis').innerText()
  check(kpi.includes('86,400.00') && kpi.includes('USD') && kpi.includes('¥ 615,168.00'), `Amazon-US-01 收入 USD 86,400.00 折人民币 ¥ 615,168.00：${kpi.replace(/\s+/g, ' ')}`)

  await wang.goto(`${BASE}/filling`)
  await wang.locator('[data-unit="Amazon-DE-01"] a').click()
  await wang.waitForSelector('revo-grid .rgCell')
  const dkeys = await wang.evaluate(async () => (await document.querySelector('revo-grid').getSource()).map((r) => r.__rowKey))
  await editCell(wang, dkeys.find((x) => x.endsWith('|spu_count')), '2027-03', '2')
  await wang.locator('[data-submit]').click()
  await wang.locator('[data-confirm-submit]').click()
  await wang.locator('[data-submit-error]').waitFor()
  const err = await wang.locator('[data-submit-error]').innerText()
  check(err.includes('EUR'), `缺 EUR 时提交被阻止并提示含币种代码「EUR」：${err.replace(/\s+/g, ' ')}`)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '填报中', '单位未被提交')

  // 2027-04 当月平均汇率与 BI 折算
  await bp.goto(`${BASE}/master/sku`)
  await bp.getByRole('button', { name: '上传对照表' }).first().click()
  await bp.locator('#sku-file').setInputFiles(writeXlsx(`${DIR}/SKU对照表.xlsx`, ['SKU', 'SPU 编码', '品类', '首次上架日期'], [['BC-2201-WH', 'SPU-BC-2201', '浴室柜', '2025-06-01']]))
  await bp.getByRole('button', { name: '确认写入' }).click()
  await bp.getByRole('button', { name: '确认写入' }).waitFor({ state: 'detached' })
  eq(await importFile(bp, 'bi', writeXlsx(`${DIR}/BI_2027-04_销售明细.xlsx`, BI_H, [['2027-04', 'Amazon-US-01', 'US', 'BC-2201-WH', 1000, 77000, 'USD', 5000, 9000]])), ['passed', 200], '导入 2027-04 BI（本币 USD 77,000.00）')
  eq(await importFile(bp, 'kingdee', writeXlsx(`${DIR}/金蝶_2027-04_利润表.xlsx`, KD_H, [['2027-04', '6001', '主营业务收入', '运营部', 'Amazon-US-01', 'US', '', '', 550000]])), ['passed', 200], '导入 2027-04 金蝶')
  await bp.goto(`${BASE}/master/fx`)
  await bp.getByRole('tab', { name: '月度实际汇率' }).click()
  eq((await typeRate(bp, '2027-04 USD 当月平均汇率', '7.2000')).status(), 200, '录入 2027-04 USD 当月平均汇率 7.2000')
  await bp.goto(`${BASE}/actuals/reconcile`)
  await bp.locator('#f-m').selectOption('2027-04')
  await bp.locator('tr', { hasText: 'Amazon-US-01' }).first().waitFor()
  const rec = await bp.locator('tr', { hasText: 'Amazon-US-01' }).first().innerText()
  check(rec.includes('77,000.00') && rec.includes('7.2000') && rec.includes('¥ 554,400.00'), `2027-04 BI 本币 USD 77,000.00 折人民币 ¥ 554,400.00：${rec.replace(/\s+/g, ' ')}`)

  // CEO 锁定 2027 年初原始目标（补录 EUR 后提交 → 赵磊通过 → 林晓提交 CEO → 周明远通过并锁定）
  eq((await bp.request.put(`${BASE}/api/master/fx/budget`, { data: { year: 2027, currency: 'EUR', rate: '7.79' } })).status(), 200, '补录 EUR 预算汇率')
  const prog = await (await lin.request.get(`${BASE}/api/tasks`)).json()
  const taskId = prog.items[0].id
  const units = (await (await lin.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()).units
  const zl = await env.newPage()
  await loginAs(zl, '赵磊')
  for (const u of units) {
    eq((await wang.request.post(`${BASE}/api/filling-units/${u.id}/submit`)).status(), 200, `${u.name} 提交`)
    eq((await zl.request.post(`${BASE}/api/approvals/unit/${u.id}/approve`)).status(), 200, `${u.name} 赵磊通过`)
  }
  eq((await lin.request.post(`${BASE}/api/tasks/${taskId}/submit-to-ceo`)).status(), 200, '林晓提交 CEO 审批')
  const ceo = await env.newPage()
  await loginAs(ceo, '周明远')
  eq((await ceo.request.post(`${BASE}/api/approvals/task/${taskId}/approve`)).status(), 200, '周明远通过并锁定')

  await bp.goto(`${BASE}/master/fx`)
  await bp.getByRole('table', { name: '年度预算汇率' }).waitFor()
  check(await bp.getByText('已随年初原始目标锁定').first().isVisible(), '汇率页显示「已随年初原始目标锁定」')
  check(await bp.getByRole('textbox', { name: 'USD 预算汇率' }).count() === 0, 'USD 预算汇率单元格不可编辑')
  const put = await bp.request.put(`${BASE}/api/master/fx/budget`, { data: { year: 2027, currency: 'USD', rate: '7.20' } })
  eq(put.status(), 409, '修改 USD 被拒（接口 409）')
  const usd = (await bp.locator('tr', { hasText: 'USD' }).first().innerText())
  check(usd.includes('7.12'), `数值仍为 7.12：${usd.replace(/\s+/g, ' ')}`)
  // 新增 JPY：先有使用 JPY 的 B 端客户，汇率页出现 JPY 行后录入
  eq((await bp.request.post(`${BASE}/api/master/b-customers`, { data: { name: 'Toto Japan', department_id: (await (await bp.request.get(`${BASE}/api/master/b-customers`)).json()).department_options.find((d) => d.name === '外贸部').id, currency: 'JPY' } })).status(), 201, '新增使用 JPY 的 B 端客户（外贸部）')
  await bp.reload()
  await bp.getByRole('textbox', { name: 'JPY 预算汇率' }).waitFor()
  eq((await typeRate(bp, 'JPY 预算汇率', '0.0478')).status(), 200, '锁定后新增 JPY 预算汇率成功')
  await bp.reload()
  check((await bp.locator('tr', { hasText: 'JPY' }).first().innerText()).includes('0.0478'), 'JPY 预算汇率 0.0478 已保存')
})
