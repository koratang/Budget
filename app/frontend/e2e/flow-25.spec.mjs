// FLOW-25 渠道×站点偏差（PAGE-F10-02）：林晓打开 2027-04 报告；切换基准；BI 未到的 2027-05。期望值逐字取自契约 FLOW-25。
import { BASE, check, eq, loginAs, run, tableText } from './_e3_harness.mjs'

await run('FLOW-25', 'flow25', '2027-05-20 10:00', async (env) => {
  const page = await env.newPage()
  await loginAs(page, '林晓')
  await page.goto(`${BASE}/reports/channel?month=2027-04`)
  const root = page.locator('[data-page-id="PAGE-F10-02"]')
  const table = root.locator('[data-testid="channel-table"]')
  await table.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  const selects = root.locator('select')
  const baseOpts = await selects.nth(1).locator('option').allTextContents()
  eq(baseOpts.map((s) => s.trim()), ['年初原始目标', '最新调整后目标', '最新滚动预测'], '对比基准可切换年初原始目标与最新滚动预测')
  eq(await selects.nth(1).inputValue(), 'adj', '对比基准默认「最新调整后目标」')
  check((await root.textContent()).includes('对比基准：V2 2027Q2 目标调整'), '当前基准显示最新调整后目标版本')

  let rows = (await tableText(table)).slice(2)
  const us = rows.find((r) => r[0].includes('Amazon-US-01'))
  console.log('  Amazon-US-01 行：', JSON.stringify(us))
  check(us[3].includes('615,168.00'), '收入预算 615,168.00')
  check(us[4].includes('554,400.00'), '收入实际 554,400.00')
  check(us[6].includes('−') && us[6].includes('60,768.00'), '收入差额 −60,768.00')
  eq(us[7], '90.12%', '达成率 90.12%')
  check(us[9].includes('−') && us[9].includes('51,264.00'), '量差 −51,264.00')
  check(us[10].includes('−') && us[10].includes('15,664.00'), '价差 −15,664.00')
  check(us[11].includes('6,160.00') && !us[11].includes('−'), '汇率差 6,160.00')
  check(us[12].includes('0.00'), '口径差 0.00')
  const b2bIdx = rows.findIndex((r) => r[0] === 'B 端（按客户）')
  check(b2bIdx >= 0 && rows[b2bIdx + 1][0].includes('Ferguson'), '「B 端（按客户）」分组下 Ferguson 一行')
  eq(rows.filter((r) => r[0].includes('Ferguson')).length, 1, 'B 端分组只有 Ferguson 一行')
  check(rows.some((r) => r[0].includes('未归属渠道')), '「未归属渠道」行单列')

  // 展开 Amazon-US-01 明细：退款、各项费用、毛利、毛利率的预算/实际/差额/达成率；推广费用费率差 6,472.00
  await table.getByRole('button', { name: '展开 Amazon-US-01 明细' }).click()
  await page.waitForTimeout(300)
  const detail = await tableText(table.locator('tr.detail table').first())
  console.log('  明细：', JSON.stringify(detail))
  eq(detail[0].slice(0, 5), ['项目', '预算', '实际', '差额', '达成率'], '明细列：预算、实际、差额、达成率')
  const promo = detail.find((r) => r[0] === '推广费用')
  check(!!promo && promo[promo.length - 1].includes('6,472.00'), '推广费用费率差 6,472.00')
  eq(detail.slice(1).map((r) => r[0]), ['收入 USD', '退款', '采购成本', '佣金', '推广费用', '头程费', '尾程费', '关税', '仓储费', '库存索赔', '其他运营费用', '毛利'],
    '明细含收入、退款、各项费用、毛利')
  check(detail.slice(1).every((r) => r.length >= 5 && r[1] !== '' && r[2] !== ''), '明细各行有预算、实际、差额、达成率')
  const head2 = (await tableText(table))[1]
  check(head2.includes('差（百分点）'), '毛利率为百分点差（列「差（百分点）」）')
  check(us[17] === '88.00%' && us[18] === '86.83%' && us[19] === '−1.17', `毛利率预算/实际/百分点差：${us.slice(17, 20).join(' / ')}`)

  // 切换基准：年初原始目标 / 最新滚动预测
  await selects.nth(1).selectOption('orig')
  await page.waitForTimeout(800)
  check((await root.textContent()).includes('对比基准：V1 年初原始目标'), '可切换到年初原始目标')
  await selects.nth(1).selectOption('roll')
  await page.waitForTimeout(800)
  check((await root.textContent()).includes('对比基准：Q2 滚动预测快照'), '可切换到最新滚动预测')

  // 2027-05：金蝶已导入、BI 最近截至 2027-04
  await page.goto(`${BASE}/reports/channel?month=2027-05`)
  await table.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  const txt = await root.textContent()
  check(txt.includes('量价拆分待 BI 数据（最近 BI 数据截至 2027-04）'), '显示「量价拆分待 BI 数据（最近 BI 数据截至 2027-04）」')
  const head = (await tableText(table))[0].concat((await tableText(table))[1])
  check(!head.includes('收入差额拆分') && !head.includes('量差'), '2027-05 拆分区隐藏')
  rows = (await tableText(table)).slice(2)
  const us5 = rows.find((r) => r[0].includes('Amazon-US-01'))
  check(us5[4].includes('500,000.00') && us5[6] !== '—', '2027-05 只显示金额差')
})
