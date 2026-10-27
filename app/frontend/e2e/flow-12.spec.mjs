// FLOW-12 浏览器 E2E：孙婷在 PAGE-F04-03 为 Ferguson 2027-03 填销售额与比率，核对 6 个输入项、默认 0.00%、计算结果与双币显示。
// 期望值逐字取自 TDD验收契约.md FLOW-12（各项费用金额由 tests/acceptance/test_flow_12.py 对数据库断言）。
import { setup, startSystem, setClock, as, gotoGrid, editCell, cellText, gridRows, run, ok, eq } from './e2_lib.mjs'

const MAR = '2027-03'
await run('FLOW-12', async (browser) => {
  const s = setup('flow_12')
  await startSystem()
  await setClock('2026-12-10 10:00')
  const page = await as(browser, s.users, 'sunting')
  await page.goto('/filling')
  await page.locator('tr[data-unit="B端 · 美国业务部"] a').click()
  await page.waitForURL(`**/filling/b2b/${s.unit}`)
  await gotoGrid(page, `/filling/b2b/${s.unit}`)
  ok((await page.locator('.page-head .sub').innerText()).includes('月 × B 端客户'), '维度说明')
  const fer = `b2b:${s.customers.Ferguson}`
  const items = (await gridRows(page)).filter((r) => r.__rowKind === 'input' && r.__rowKey.startsWith(`${fer}|`)).map((r) => r.__rowKey.split('|')[1])
  eq(items, ['sales_local', 'refund_rate', 'promotion_rate', 'other_opex_rate', 'commission_rate', 'inventory_claim_rate'], '6 个输入项')
  eq(await cellText(page, `${fer}|commission_rate`, MAR), '0.00%', '平台佣金率默认')
  eq(await cellText(page, `${fer}|inventory_claim_rate`, MAR), '0.00%', '库存索赔率默认')
  for (const [item, v] of [['sales_local', '200,000.00'], ['refund_rate', '2'], ['promotion_rate', '3'], ['other_opex_rate', '1']]) {
    eq((await editCell(page, `${fer}|${item}`, MAR, v)).errors, [], `保存 ${item}`)
  }
  eq(await cellText(page, `${fer}|sales_local`, MAR), '200,000.00', 'USD 销售额')
  eq(await cellText(page, `${fer}|revenue_cny`, MAR), '1,424,000.00', '人民币收入')
  eq(await cellText(page, `${fer}|gross_profit`, MAR), '341,760.00', '毛利')
  eq(await cellText(page, `${fer}|gross_margin`, MAR), '24.00%', '毛利率')
  const kpis = await page.locator('.kpis').innerText()
  ok(kpis.includes('$ 200,000.00 USD') && kpis.includes('¥ 1,424,000.00'), `双币显示：${kpis}`)
})
