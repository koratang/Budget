// FLOW-17 浏览器 E2E：王浩在 TikTok-US-01（新渠道，起始 2027-03）填 3、4 月驱动 → 2027-04 标注超放量、3 月不标注；未填理由提交被阻止并指出 2027-04；
// 填写理由后提交成功。期望值逐字取自 TDD验收契约.md FLOW-17。
import { setup, startSystem, setClock, as, gotoGrid, editCell, cellText, run, ok, eq } from './e2_lib.mjs'

const CELLS = [['spu_count', '2027-04', '6'], ['avg_sales', '2027-04', '90.8'], ['avg_price', '2027-04', '90.23'],
  ['spu_count', '2027-03', '6'], ['avg_sales', '2027-03', '116.01'], ['avg_price', '2027-03', '36.32']]

await run('FLOW-17', async (browser) => {
  const s = setup('flow_17')
  await startSystem()
  await setClock('2026-12-15 10:00')
  const base = `pu:${s.store_ids['TikTok-US-01']}:${s.amz.site}:${s.amz.cats['灯镜']}:1`
  const wang = await as(browser, s.users, 'wanghao')
  await gotoGrid(wang, `/filling/platform/${s.unit}`)
  ok((await wang.locator('[data-new-channel]').innerText()).includes('2027-03'), '新渠道起始月')
  for (const [item, m, v] of CELLS) eq((await editCell(wang, `${base}|${item}`, m, v)).errors, [], `${item} ${m}`)
  eq(await cellText(wang, 'total|revenue_cny', '2027-04'), '350,000.00', '2027-04 收入合计')
  eq(await cellText(wang, 'total|revenue_cny', '2027-03'), '180,000.00', '2027-03 收入合计')
  const apr = wang.locator('span[data-cell="total|revenue_cny::2027-04"]').locator('xpath=..')
  const mar = wang.locator('span[data-cell="total|revenue_cny::2027-03"]').locator('xpath=..')
  ok((await apr.getAttribute('class')).includes('bg-flag'), '2027-04 单元标注')
  ok(!(await mar.getAttribute('class')).includes('bg-flag'), '2027-03 不标注')
  const flagNote = await wang.locator('.bg-notice-warn').first().innerText()
  ok(flagNote.includes('超出新渠道放量规则') && flagNote.includes('4 月') && !flagNote.includes('3 月（'), `标注说明：${flagNote}`)

  // 未填理由提交被阻止并指出 2027-04
  await wang.locator('[data-submit]').click()
  await Promise.all([wang.waitForResponse((r) => r.url().endsWith('/submit')), wang.locator('[data-confirm-submit]').click()])
  const err = wang.locator('[data-submit-error]')
  await err.waitFor()
  ok((await err.innerText()).includes('2027-04'), `提交被阻止：${await err.innerText()}`)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '填报中', '仍为填报中')

  await wang.getByLabel('2027-04 超出理由').fill('4 月 TikTok 大促报名已确认，达人合作已签约')
  await Promise.all([wang.waitForResponse((r) => r.url().includes('/over-limit-reasons')), wang.locator('[data-save-reasons]').click()])
  await wang.waitForTimeout(500)
  await wang.locator('[data-submit]').click()
  const [resp] = await Promise.all([wang.waitForResponse((r) => r.url().endsWith('/submit')), wang.locator('[data-confirm-submit]').click()])
  eq(resp.status(), 200, '填写理由后提交成功')
  await wang.waitForTimeout(500)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '已提交', '状态变为已提交')
})
