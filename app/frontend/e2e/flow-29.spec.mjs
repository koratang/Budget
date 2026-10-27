// FLOW-29 导入后预警评估（PAGE-F11-01）：陈思雨确认 2027-04 金蝶导入 → 1 条预警 → 覆盖导入更新同一记录 → 何建国标记已处理。
// 期望值逐字取自契约 FLOW-29。
import { BASE, check, eq, fileOf, loginAs, run, tableText } from './_e3_harness.mjs'

const RULE = '部门费用额度使用率超出时间进度 10 个百分点以上'

async function importFile(page, file, overwrite) {
  await page.goto(`${BASE}/actuals/import`)
  const root = page.locator('[data-page-id="PAGE-F09-01"]')
  await root.locator('.tab', { hasText: '金蝶月度' }).click()
  await root.locator('input[type=file]').setInputFiles(fileOf(file))
  await root.getByRole('button', { name: '上传并校验' }).click()
  await root.locator('#pass-t').waitFor({ timeout: 60000 })
  if (overwrite) {
    await root.getByRole('button', { name: '确认覆盖导入' }).click()
    await page.getByRole('button', { name: '确认覆盖', exact: true }).click()
  } else {
    await root.getByRole('button', { name: /^确认导入$/ }).click()
  }
  await root.locator('.toast').waitFor({ timeout: 60000 })
  return (await root.locator('.toast').textContent()).trim()
}

async function alertRows(page) {
  await page.goto(`${BASE}/alerts`)
  const root = page.locator('[data-page-id="PAGE-F11-01"]')
  await root.locator('table tbody tr').first().waitFor()
  await page.waitForTimeout(400)
  return (await tableText(root.locator('table').first())).slice(1)
}

await run('FLOW-29', 'flow29', '2027-05-12 10:00', async (env) => {
  const f = env.seeded
  const page = await env.newPage()
  await loginAs(page, '陈思雨')
  const t1 = await importFile(page, f.april, false)
  console.log('  首次导入：', t1)
  check(t1.includes('预警评估新增 1 条'), '首次导入生成 1 条预警')

  let rows = await alertRows(page)
  console.log('  预警列表：', JSON.stringify(rows))
  eq(rows.length, 1, '预警列表 1 条')
  const r = rows[0]
  eq(r[0], `${RULE}（v1）`, '规则名称与 v1')
  eq(r[1], '物流物控部', '对象：物流物控部（人力资源部 8.33 个百分点不命中；待审批 v2 阈值 8 不参与）')
  eq(r[2], '2027-04', '期间 2027-04')
  check(r[3].startsWith('+13.33 个百分点') && r[3].includes('使用率 46.67%，时间进度 33.33%'), '指标值 13.33 个百分点（46.67% − 33.33%）')
  eq(r[4], '≥ 10 个百分点', '阈值 10')

  const t2 = await importFile(page, f.corrected, true)
  console.log('  覆盖导入：', t2)
  check(t2.includes('新增 0 条') && t2.includes('更新 1 条'), '覆盖导入：新增 0 条、更新 1 条')
  rows = await alertRows(page)
  eq(rows.length, 1, '覆盖导入后记录总数仍为 1')
  check(rows[0][3].startsWith('+14.00 个百分点'), '同一记录指标值更新为 14.00 个百分点')
  const root = page.locator('[data-page-id="PAGE-F11-01"]')
  await root.getByRole('button', { name: '详情' }).first().click()
  const changes = await page.locator('.timeline').last().textContent()
  check(changes.includes('未新增记录、未重复通知'), '记录变化：未新增记录、未重复通知')

  await page.context().clearCookies()
  await loginAs(page, '何建国')
  await alertRows(page)
  await root.getByRole('button', { name: '标记已处理' }).click()
  await page.getByRole('button', { name: '确认已处理' }).click()
  eq((await page.locator('#h-note ~ .field-error').textContent()).trim(), '请填写处理说明', '未填说明时提示「请填写处理说明」')
  const note = '4 月集中支付全年海外仓年度服务费，属一次性预付，5–12 月不再发生该项支出'
  await page.locator('#h-note').fill(note)
  await page.getByRole('button', { name: '确认已处理' }).click()
  await page.waitForTimeout(800)
  await root.locator('#f-st').selectOption('')
  await page.waitForTimeout(800)
  rows = (await tableText(root.locator('table').first())).slice(1)
  console.log('  处理后：', JSON.stringify(rows[0]))
  check(rows[0][5].startsWith('已处理') && rows[0][5].includes('何建国 · 2027-05-12 10:00'), '状态「已处理」并记录处理人何建国与时间')
  await root.getByRole('button', { name: '详情' }).first().click()
  const kv = await page.locator('dl.kv').textContent()
  check(kv.includes(`已处理（何建国 · 2027-05-12 10:00：${note}）`), '详情记录处理人、时间与说明')
})
