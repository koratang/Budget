// FLOW-16 浏览器 E2E：郑可在 PAGE-F05-01 填培训费 2027-04 并看历史参考，在 PAGE-F05-02 新增专项；2027-05-12 陈思雨登记使用。
// 期望值逐字取自 TDD验收契约.md FLOW-16。前置：经导入接口已导入 2025-12 至 2026-11 金蝶实际。
import { setup, startSystem, setClock, as, gotoGrid, editCell, cellText, gridRows, run, ok, eq } from './e2_lib.mjs'

await run('FLOW-16', async (browser) => {
  const s = setup('flow_16')
  await startSystem()
  await setClock('2026-12-22 15:00')
  const train = s.accounts['培训费']
  const care = s.accounts['员工关怀费']
  const hr = s.departments['人力资源部']

  const zk = await as(browser, s.users, 'zhengke')
  await zk.goto('/dept-expense')
  await zk.waitForURL(`**/dept-expense?unitId=${s.unit}`)
  await gotoGrid(zk, `/dept-expense?unitId=${s.unit}`)
  ok((await zk.locator('.page-head .sub').innerText()).includes('预算科目 × 月（人民币）'), '预算科目 × 月人民币')
  const cols = await zk.evaluate(async () => (await document.querySelector('revo-grid').getColumns()).flatMap((c) => (c.children ? c.children : [c])).map((c) => c.prop))
  eq(cols.filter((c) => /^2027-\d\d$/.test(c)).length, 12, '12 个月列')
  eq((await editCell(zk, `de:${train}|amount`, '2027-04', '50,000.00')).errors, [], '培训费 2027-04 50,000.00')
  eq(await cellText(zk, `de:${train}|amount`, '2027-04'), '50,000.00', '培训费 2027-04')
  eq(await cellText(zk, `de:${train}|prior`, '2027-04'), '上年 35,000.00', '培训费单元下上年同月实际')
  eq(await cellText(zk, `de:${train}|amount`, 'recent12'), '420,000.00', '近 12 月实际合计')
  eq(await cellText(zk, `de:${care}|amount`, 'recent12'), '无历史数据', '员工关怀费无历史数据')
  ok((await gridRows(zk)).find((r) => r.__rowKey === `de:${care}|amount`)?.__sub?.account === '无历史数据', '员工关怀费科目名下显示无历史数据')

  // 新增专项
  await zk.getByRole('link', { name: '管理专项预留额度' }).click()
  await zk.waitForURL('**/dept-expense/reserves**')
  await zk.locator('[data-new-reserve]').click()
  await zk.locator('#r-name').fill('管理层领导力训练营')
  await zk.locator('#r-acc').selectOption(String(train))
  await zk.locator('#r-month').selectOption('2027-04')
  await zk.locator('#r-amount').fill('180000.00')
  await Promise.all([zk.waitForResponse((r) => r.url().endsWith('/api/reserves') && r.request().method() === 'POST'), zk.locator('[data-save-reserve]').click()])
  const row = zk.locator('tr[data-reserve="管理层领导力训练营"]')
  await row.waitFor()
  const head = await zk.locator('table[aria-label="专项预留额度"] thead').innerText()
  ok(head.includes('上年同科目实际（2026-01～11，12 月未导入）'), `专项列表表头：${head}`)
  const cells = await row.locator('td').allInnerTexts()
  eq([cells[0], cells[1], cells[2], cells[3], cells[6]], ['管理层领导力训练营', '培训费', '2027-04', '180,000.00', '390,000.00'], '专项行')
  await gotoGrid(zk, `/dept-expense?unitId=${s.unit}`)
  eq(await cellText(zk, `de:${train}|subtotal`, '2027-04'), '230,000.00', '培训费 2027-04 预算含专项')

  // 2027-05-12 陈思雨登记使用
  await setClock('2027-05-12 09:30')
  const bp = await as(browser, s.users, 'chensiyu')
  await bp.goto(`/dept-expense/reserves?departmentId=${hr}`)
  const r2 = bp.locator('tr[data-reserve="管理层领导力训练营"]')
  await r2.waitFor()
  await r2.getByRole('button', { name: '登记使用' }).click()
  await bp.locator('#u-amount').fill('96,000.00')
  await bp.locator('#u-date').fill('2027-04-22')
  await bp.locator('#u-voucher').fill('记-2027-04-0233')
  await Promise.all([bp.waitForResponse((r) => r.url().includes('/usages')), bp.getByRole('button', { name: '登记', exact: true }).click()])
  await bp.waitForTimeout(500)
  const after = await bp.locator('tr[data-reserve="管理层领导力训练营"] td').allInnerTexts()
  eq([after[4], after[5]], ['96,000.00', '84,000.00'], '已用 96,000.00、剩余 84,000.00')
})
