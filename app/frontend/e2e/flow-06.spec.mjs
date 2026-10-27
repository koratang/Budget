// FLOW-06 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-06。
import { mkdirSync } from 'node:fs'
import { run, loginAs, BASE, check, eq, writeXlsx } from './e1_harness.mjs'

const DIR = '/tmp/e1_acc_files/flow06'
mkdirSync(DIR, { recursive: true })
const KD_H = ['期间', '金蝶科目', '科目名称', '部门', '平台/店铺', '站点', '客户', '摘要', '发生额']

async function deptReportRow(page, account) {
  await page.goto(`${BASE}/reports/dept?year=2027`)
  await page.locator('[data-testid="dept-table"]').waitFor()
  const row = page.locator('[data-testid="dept-table"] tbody tr', { hasText: account }).first()
  return (await row.count()) ? (await row.innerText()).replace(/\s+/g, ' ') : null
}

await run('FLOW-06', 'flow06', async (env) => {
  const bp = await env.newPage()
  const lin = await env.newPage()
  await loginAs(bp, '陈思雨')
  await loginAs(lin, '林晓')
  const before = await deptReportRow(lin, '市场推广费')
  console.log('    导入前 市场部 市场推广费：' + before)

  await bp.goto(`${BASE}/master/accounts`)
  await bp.getByRole('button', { name: '新增映射' }).first().click()
  await bp.locator('#m-code').fill('6601.12')
  await bp.locator('#m-name').fill('广告宣传费')
  await bp.locator('#m-sub').selectOption({ label: '市场推广费' })
  await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await bp.getByText('6601.12 已映射到「市场推广费」').waitFor()
  check(true, '陈思雨把 6601.12 广告宣传费映射到「市场推广费」')

  await bp.goto(`${BASE}/actuals/import`)
  await bp.locator('input[type=file][aria-label="选择 Excel 文件"]').setInputFiles(writeXlsx(`${DIR}/金蝶_2027-04_利润表.xlsx`, KD_H, [
    ['2027-04', '6601.12', '广告宣传费', '市场部', '', '', '', '', 38000.0]]))
  await bp.getByRole('button', { name: '上传并校验' }).click()
  await bp.getByRole('button', { name: '确认导入' }).click()
  await bp.getByText(/已导入|导入成功|已生效/).first().waitFor()
  const after = await deptReportRow(lin, '市场推广费')
  console.log('    导入后 市场部 市场推广费：' + after)
  const amt = (s) => Number((s.match(/[\d,]+\.\d{2}/g) || [])[1]?.replace(/,/g, ''))
  eq(amt(after) - amt(before), 38000, '市场部 2027-04「市场推广费」实际增加 38,000.00')
  check(after.includes('38,000.00'), '报告行显示 38,000.00')

  await bp.goto(`${BASE}/master/accounts`)
  await bp.getByRole('tab', { name: '预算科目' }).click()
  await bp.getByRole('button', { name: '新增预算科目' }).click()
  await bp.locator('#sm-name').fill('员工关怀费')
  await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await bp.getByRole('dialog').waitFor({ state: 'detached' })
  await bp.locator('tr', { hasText: '差旅费' }).getByRole('button', { name: '改名' }).click()
  await bp.locator('#sm-name').fill('差旅交通费')
  await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await bp.getByText('「差旅费」已改名为「差旅交通费」').waitFor()
  await bp.locator('tr', { hasText: '招待费' }).getByRole('button', { name: '停用' }).click()
  await bp.getByRole('button', { name: '确认停用' }).click()
  await bp.getByText('已停用「招待费」').waitFor()
  await bp.getByRole('tab', { name: '科目映射' }).click()
  await bp.getByRole('button', { name: '新增映射' }).first().click()
  const opts = await bp.locator('#m-sub option').allInnerTexts()
  check(opts.includes('员工关怀费') && opts.includes('差旅交通费') && !opts.includes('差旅费') && !opts.includes('招待费'),
    '科目映射下拉出现「员工关怀费」「差旅交通费」，不再出现「差旅费」「招待费」')
  await bp.getByRole('dialog').getByRole('button', { name: '取消' }).click()

  // 新填报：林晓发布含市场部的编制任务 → 邓琳的部门费用填报
  await lin.goto(`${BASE}/tasks`)
  await lin.locator('[data-publish]').click()
  await lin.locator('#p-year').selectOption('2027')
  await lin.locator('#p-dl').fill('2026-12-20')
  const modal = lin.getByRole('dialog')
  for (const fs of await modal.locator('fieldset').all()) { const all = fs.locator('legend input'); if (await all.isChecked()) await all.uncheck() }
  await modal.locator('fieldset label', { hasText: '市场部' }).locator('input').check()
  await lin.locator('[data-publish-ok]').click()
  await lin.getByText('已发布「2027 年度预算编制」').waitFor()
  const dl = await env.newPage()
  await loginAs(dl, '邓琳')
  await dl.goto(`${BASE}/dept-expense`)
  await dl.waitForSelector('revo-grid .rgCell')
  const accs = await dl.evaluate(async () => [...new Set((await document.querySelector('revo-grid').getSource())
    .filter((r) => r.__rowKind === 'input').map((r) => r.account))])
  check(accs.includes('员工关怀费') && accs.includes('差旅交通费') && !accs.includes('差旅费') && !accs.includes('招待费'),
    `部门费用填报出现「员工关怀费」「差旅交通费」，不再出现「差旅费」「招待费」：${accs.join('、')}`)

  const hosp = await deptReportRow(lin, '招待费')
  check(hosp && hosp.includes('12,000.00') && hosp.includes('5,200.00'), `「招待费」已有预算与实际在部门费用报告中仍显示：${hosp}`)
})
