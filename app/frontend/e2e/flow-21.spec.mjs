// FLOW-21 版本对比（PAGE-F08-02）：林晓 / 王浩按「渠道 × 店铺 × 站点」对比 V1、V2。期望值逐字取自契约 FLOW-21。
import { BASE, check, eq, loginAs, run, tableText } from './_e3_harness.mjs'

await run('FLOW-21', 'flow21', '2027-03-15 10:00', async (env) => {
  const { v1, v2 } = env.seeded
  const page = await env.newPage()

  await loginAs(page, '林晓')
  await page.goto(`${BASE}/versions/compare`)
  await page.locator('#va').selectOption(String(v1))
  await page.locator('#vb').selectOption(String(v2))
  await page.locator('#dim').selectOption('channel')
  await page.locator('table.table tbody tr').first().waitFor()
  await page.waitForTimeout(300)
  const rows = await tableText(page.locator('[data-page-id="PAGE-F08-02"] table.table'))
  const body = rows.slice(2)
  const wf = body.find((r) => r[0].startsWith('Wayfair-US-01'))
  console.log('  Wayfair 行：', JSON.stringify(wf))
  eq(wf?.[3], '−¥ 4,200,000.00', 'Wayfair-US-01 收入差额 −4,200,000.00')
  eq(wf?.[6], '−¥ 840,000.00', 'Wayfair-US-01 毛利差额 −840,000.00')
  const dimRows = body.filter((r) => !r[0].startsWith('公司合计'))
  check(dimRows.length >= 4 && dimRows.every((r) => r.slice(7).every((c) => c === '—')), '维度行与维度合计行净利润显示「—」')
  const company = body.find((r) => r[0] === '公司合计（含 B端、部门费用与公司层其他损益）')
  console.log('  公司合计行：', JSON.stringify(company))
  check(!!company && company[7].startsWith('¥ ') && company[8].startsWith('¥ '), '公司合计行显示两版净利润')
  eq(company?.[9], '−¥ 840,000.00', '公司合计行净利润差额 −840,000.00')
  await page.screenshot({ path: '/tmp/e3_acc/flow-21-linxiao.png', fullPage: true })

  await page.context().clearCookies()
  await loginAs(page, '王浩')
  await page.goto(`${BASE}/versions/compare?a=${v1}&b=${v2}&dims=channel`)
  await page.locator('table.table tbody tr').first().waitFor()
  await page.waitForTimeout(300)
  const w = (await tableText(page.locator('[data-page-id="PAGE-F08-02"] table.table'))).slice(2)
  const storeRows = w.filter((r) => !r[0].endsWith('合计') && !r[0].startsWith('公司合计'))
  eq(storeRows.map((r) => r[0].split(' · ')[0]), ['Amazon-US-01'], '王浩结果只含其范围内店铺行')
  check(!w.some((r) => r[0].startsWith('公司合计')), '王浩无公司合计净利润行')
})
