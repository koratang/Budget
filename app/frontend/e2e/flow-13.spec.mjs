// FLOW-13 浏览器 E2E：陈思雨在 PAGE-F04-04 填充全年 30%、库存索赔率 / 其他运营费用率、公司层其他损益；蒋帆在 PAGE-F04-05 填四项物流比例；
// 林晓在全公司预算审批详情（PAGE-F07-02）看到 2027-03（Q1 仅 3 月有数）净利润。期望值逐字取自 TDD验收契约.md FLOW-13。
import { setup, startSystem, setClock, as, loginPage, gotoGrid, editCell, cellText, gridRows, run, ok, eq } from './e2_lib.mjs'

const MAR = '2027-03'
const MONTHS = Array.from({ length: 12 }, (_, i) => `2027-${String(i + 1).padStart(2, '0')}`)

async function dimLabels(page) {
  return page.evaluate(async () => (await document.querySelector('revo-grid').getColumns()).filter((c) => c.pin).map((c) => c.name))
}
async function tab(page, label) {
  await Promise.all([page.waitForResponse((r) => r.url().includes('/grid')), page.getByRole('tab', { name: label }).click()])
  await page.waitForTimeout(1000)
}

await run('FLOW-13', async (browser) => {
  const s = setup('flow_13')
  await startSystem()
  await setClock('2026-12-12 10:00')
  const { channel, site, cats } = s.amz
  const combo = `ccr:${channel}:${site}:${cats['浴室柜']}`
  const csr = `csr:${channel}:${site}`

  const bp = await as(browser, s.users, 'chensiyu')
  await gotoGrid(bp, `/filling/cost/${s.cost}`)
  eq(await dimLabels(bp), ['渠道', '站点', '品类'], '采购成本占比 · 平台：月 × 渠道 × 站点 × 品类')
  await tab(bp, '采购成本占比 · B端客户')
  ok((await gridRows(bp)).filter((r) => r.__rowKind === 'input').every((r) => r.__rowKey.startsWith('b2bc:')), '采购成本占比 · B端客户：月 × B 端客户')
  await tab(bp, '库存索赔率与其他运营费用率')
  eq((await dimLabels(bp)).slice(0, 2), ['渠道', '站点'], '库存索赔率与其他运营费用率：月 × 渠道 × 站点')
  ok((await bp.locator('.g2').innerText()).includes('适用于该渠道站点下全部品类和新老品单元'), '作用范围说明')
  eq((await editCell(bp, `${csr}|inventory_claim_rate`, MAR, '1')).errors, [], '库存索赔率 1')
  eq((await editCell(bp, `${csr}|other_opex_rate`, MAR, '3')).errors, [], '其他运营费用率 3')

  await tab(bp, '采购成本占比 · 平台')
  await bp.getByRole('button', { name: '填充全年' }).click()
  await bp.locator('#fill-row').selectOption(`${combo}|purchase_cost_rate`)
  await bp.locator('#fill-val').fill('30')
  await Promise.all([bp.waitForResponse((r) => r.url().includes('/fill-year')), bp.locator('[data-fill-ok]').click()])
  await bp.waitForTimeout(800)
  const vals = []
  for (const m of MONTHS) vals.push(await cellText(bp, `${combo}|purchase_cost_rate`, m))
  eq(vals, Array(12).fill('30.00%'), '填充全年后 12 个月均为 30.00%')

  await tab(bp, '公司层其他损益')
  for (const [k, v] of [['finance_cost', '-5,000.00'], ['fx_gain_loss', '2,000.00'], ['income_tax', '-30,000.00']]) {
    eq((await editCell(bp, `opl|${k}`, MAR, v)).errors, [], `其他损益 ${k}`)
  }
  eq(await cellText(bp, 'opl|non_operating', MAR), '0.00', '营业外收支 0.00（与当前值相同，表格不发保存）')
  eq(await cellText(bp, 'total|other_pl', MAR), '−33,000.00', '其他损益合计')

  const lg = await as(browser, s.users, 'jiangfan')
  await gotoGrid(lg, `/filling/logistics/${s.logistics}`)
  const lrows = (await gridRows(lg)).filter((r) => r.__rowKind === 'input')
  eq(new Set(lrows.map((r) => r.__rowKey.split('|')[1])), new Set(['first_leg_rate', 'last_mile_rate', 'storage_rate', 'tariff_rate']), '物流页只有四项比例')
  const pageText = await lg.locator('[data-page-id="PAGE-F04-05"]').innerText()
  const colText = (await lg.evaluate(async () => (await document.querySelector('revo-grid').getColumns()).map((c) => c.name).join(' ')))
  ok(!/收入|销量|利润/.test(colText) && !/收入|销量|利润/.test(lrows.map((r) => r.item ?? '').join(' ')), `物流页无收入/销量/利润列：${colText}`)
  ok(pageText.includes('本页不显示收入、销量与利润'), '物流页说明')
  for (const [k, v] of [['first_leg_rate', '6'], ['last_mile_rate', '8'], ['storage_rate', '2'], ['tariff_rate', '4']]) {
    eq((await editCell(lg, `${combo}|${k}`, MAR, v)).errors, [], `物流 ${k}`)
  }

  // 运营页核对毛利已按上述比例重算（FLOW-11 单元 98,426.88）
  const op = await as(browser, s.users, 'wanghao')
  await gotoGrid(op, `/filling/platform/${s.platform}`)
  const base = s.keys['浴室柜|new|spu_count'].split('|')[0]
  eq(await cellText(op, `${base}|gross_profit`, MAR), '98,426.88', 'FLOW-11 单元毛利')

  // 全公司预算视图：Q1（仅 3 月有数）净利润 = 98,426.88 + 341,760.00 − 300,000.00 + (−33,000.00)
  const lx = await as(browser, s.users, 'linxiao')
  const pl = await (await lx.request.get(`/api/versions/${(await (await lx.request.get(`/api/filling-units/${s.cost}/grid`)).json()).unit.version_id}/pl`)).json()
  const mar = pl.months.find((m) => m.month === MAR)
  eq([mar.platform_gross_profit_display, mar.b2b_gross_profit_display, mar.dept_expense_display, mar.other_pl_display, mar.net_profit_display],
    ['98,426.88', '341,760.00', '300,000.00', '−33,000.00', '107,186.88'], '2027-03 公司净利润构成')
  // 各单位提交并经部门负责人通过、林晓提交 CEO 后，周明远在全公司预算视图（PAGE-F07-02）看到净利润（Q1 仅 3 月有数）
  const units = (await (await lx.request.get(`/api/tasks/${s.task}/progress`)).json()).units
  const fillers = { 'Amazon-US-01': ['wanghao', 'zhaolei'], 'B端 · 美国业务部': ['sunting', 'hanliqun'], '成本比例（财务BP）': ['chensiyu', 'linxiao'],
    '物流比例（物流物控）': ['jiangfan', 'hejianguo'], '人力资源部': ['zhengke', 'wujing'] }
  const api = await as(browser, s.users, 'linxiao')
  for (const u of units) {
    const [filler, head] = fillers[u.name]
    await loginPage(api, s.users, filler)
    eq((await api.request.post(`/api/filling-units/${u.id}/submit`)).status(), 200, `${u.name} 提交`)
    await loginPage(api, s.users, head)
    eq((await api.request.post(`/api/approvals/unit/${u.id}/approve`)).status(), 200, `${u.name} 通过`)
  }
  await loginPage(api, s.users, 'linxiao')
  eq((await api.request.post(`/api/tasks/${s.task}/submit-to-ceo`)).status(), 200, '提交 CEO')
  const ceo = await as(browser, s.users, 'zhoumingyuan')
  await ceo.goto(`/approvals/task/${s.task}`)
  const company = ceo.locator('[aria-label="全公司预算"]')
  await company.waitFor()
  const txt = await company.innerText()
  const q1 = await company.locator('tr', { hasText: '净利润' }).first().innerText()
  ok(q1.includes('107,186.88'), `按季度净利润（Q1 = 2027-03）：${q1}`)
  const otherRow = await company.locator('tr', { hasText: '公司层其他损益' }).first().innerText()
  ok(otherRow.includes('−33,000.00'), `公司层其他损益：${otherRow}`)
  const segs = await company.locator('table').last().innerText()
  ok(!/其他损益|财务费用|汇兑|所得税/.test(segs), `渠道 / B端行不含其他损益：${segs}`)
  ok(txt.includes('107,186.88'), '全公司净利润')
  ok(pl.channels.concat(pl.customers).every((seg) => !Object.keys(seg).some((k) => /other_pl|finance_cost|income_tax/.test(k))), '其他损益不进入渠道 / 客户行')
})
