// FLOW-06 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-06。
// 部门费用报告（/reports/dept）已于 2026-10-29 删除：导入后实际增加与停用科目数据保留改由 API 验收（tests/acceptance/test_flow_06.py）断言。
import { mkdirSync } from 'node:fs'
import { run, loginAs, BASE, check, writeXlsx } from './e1_harness.mjs'

const DIR = '/tmp/e1_acc_files/flow06'
mkdirSync(DIR, { recursive: true })
const KD_H = ['期间', '金蝶科目', '科目名称', '部门', '平台/店铺', '站点', '客户', '摘要', '发生额']

await run('FLOW-06', 'flow06', async (env) => {
  const bp = await env.newPage()
  const lin = await env.newPage()
  await loginAs(bp, '陈思雨')
  await loginAs(lin, '林晓')

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
})
