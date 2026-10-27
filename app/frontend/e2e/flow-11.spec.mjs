// FLOW-11 浏览器 E2E：王浩在 PAGE-F04-02 填 Amazon-US-01「美国 · 浴室柜 · 新品 · 2027-03」七个驱动，核对计算行、双币关键数与取值范围提示。
// 期望值逐字取自 TDD验收契约.md FLOW-11（各项费用金额与数据库值由 tests/acceptance/test_flow_11.py 断言）。
import { setup, startSystem, setClock, as, gotoGrid, editCell, cellText, tryEdit, gridRows, run, ok, eq } from './e2_lib.mjs'

const MAR = '2027-03'
const DRIVERS = [['spu_count', '10'], ['avg_sales', '120'], ['avg_price', '80.00'], ['discount_rate', '10'], ['refund_rate', '5'], ['ad_rate', '12'], ['commission_rate', '15']]

await run('FLOW-11', async (browser) => {
  const s = setup('flow_11')
  await startSystem()
  await setClock('2026-12-10 10:00')
  const page = await as(browser, s.users, 'wanghao')

  // 从「我的填报」进入
  await page.goto('/filling')
  await page.locator('tr[data-unit="Amazon-US-01"] a').click()
  await page.waitForURL(`**/filling/platform/${s.unit}`)
  await gotoGrid(page, `/filling/platform/${s.unit}`)
  ok((await page.locator('.page-head .sub').innerText()).includes('维度：月 × 店铺 × 站点 × 品类 × 新品/老品'), '维度说明')
  const meta = await page.locator('.meta-row').innerText()
  ok(meta.includes('渠道 Amazon') && meta.includes('站点 美国') && meta.includes('结算币种 USD'), `店铺/站点信息：${meta}`)
  const rows = await gridRows(page)
  const inputs = rows.filter((r) => r.__rowKind === 'input')
  eq(inputs.length, 70, '5 品类 × 新/老品 × 7 输入项')
  eq(new Set(inputs.map((r) => r.__rowKey.split('|')[1])), new Set(DRIVERS.map((d) => d[0])), '7 个输入项')

  const base = s.keys['浴室柜|new|spu_count'].split('|')[0]
  for (const [item, v] of DRIVERS) {
    const res = await editCell(page, `${base}|${item}`, MAR, v)
    eq(res.errors, [], `保存 ${item}`)
  }
  eq(await cellText(page, `${base}|sales_qty`, MAR), '1,200', '销量')
  eq(await cellText(page, `${base}|revenue_local`, MAR), '86,400.00', '收入 USD')
  eq(await cellText(page, `${base}|revenue_cny`, MAR), '615,168.00', '收入 人民币')
  eq(await cellText(page, `${base}|gross_profit`, MAR), '98,426.88', '毛利')
  eq(await cellText(page, `${base}|gross_margin`, MAR), '16.00%', '毛利率')
  const kpis = await page.locator('.kpis').innerText()
  ok(kpis.includes('$ 86,400.00 USD') && kpis.includes('¥ 615,168.00'), `双币关键数：${kpis}`)
  const oldBase = s.keys['浴室柜|old|spu_count'].split('|')[0]
  eq(await cellText(page, `${oldBase}|gross_margin`, MAR), '—', '人民币收入为 0 的单元毛利率')
  ok(!(await tryEdit(page, `${base}|revenue_cny`, MAR)), '计算行只读')

  // 2.5 与 120 均不保存并提示允许范围
  let res = await editCell(page, `${base}|spu_count`, MAR, '2.5')
  ok(res.errors.length === 1, 'SPU 2.5 被拒')
  let alert = await page.locator('[data-grid-errors]').innerText()
  ok(alert.includes('大于等于 0 的整数'), `SPU 提示：${alert}`)
  res = await editCell(page, `${base}|discount_rate`, MAR, '120')
  ok(res.errors.length === 1, '折扣率 120 被拒')
  alert = await page.locator('[data-grid-errors]').innerText()
  ok(alert.includes('0% 到 100%'), `比率提示：${alert}`)
  await page.reload()
  await gotoGrid(page, `/filling/platform/${s.unit}`)
  eq(await cellText(page, `${base}|spu_count`, MAR), '10', '刷新后 SPU 仍为 10')
  eq(await cellText(page, `${base}|discount_rate`, MAR), '10.00%', '刷新后折扣率仍为 10.00%')
  eq(await cellText(page, `${base}|revenue_cny`, MAR), '615,168.00', '刷新后收入不变')
})
