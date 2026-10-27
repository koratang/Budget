// FLOW-20 浏览器 E2E（钉钉本地替身 8022）：林晓在 PAGE-F08-01「以年初原始目标发布」Q1 快照、发起 Q2 滚动更新；王浩从「我的填报」滚动预测入口进入
// PAGE-F04-02 只改 5–12 月驱动并提交；孙婷在 PAGE-F08-01 提交本季度更新；金蝶 2027-04 实际导入后林晓发布 Q2 快照，再尝试修改。
// 期望值逐字取自 TDD验收契约.md FLOW-20。前置（e2_setup flow_20）：V1 经完整编制审批（Amazon-US-01 每月驱动计算值 ¥ 600,000.00）。
// 其余填报单位的提交不是本行界面验收对象，经接口完成；金蝶导入经导入接口（契约前置）。
import { setup, step, startSystem, setClock, as, loginPage, gotoGrid, editCell, cellText, tryEdit, run, ok, eq, flushOutbox, stubMessages, clearStub } from './e2_lib.mjs'

// 最新提交的驱动计算值（按需求公式手算）：15 × 78 × 77.65 USD × 7.12 = 646,855.56
const FORECAST = '¥ 646,855.56'
const ROLES = { 运营: ['wanghao', 'lijiaqi', 'huangzixuan', 'tangyue'], B端业务: ['sunting', 'liuyang'], 物流物控: ['jiangfan'], 财务BP: ['chensiyu'] }

async function confirmModal(page, button, confirm, urlPart) {
  await page.getByRole('button', { name: button }).click()
  const [r] = await Promise.all([page.waitForResponse((x) => x.url().includes(urlPart) && x.request().method() === 'POST'), page.getByRole('button', { name: confirm }).click()])
  return r
}
const summary = async (page, vid, storeId) =>
  Object.fromEntries((await (await page.request.get(`/api/versions/${vid}/summary${storeId ? `?store_id=${storeId}` : ''}`)).json()).months.map((m) => [m.month, m]))

await run('FLOW-20', async (browser) => {
  const s = setup('flow_20')
  await startSystem()
  const amz = s.store_ids['Amazon-US-01']

  // 2027-01-08 以年初原始目标发布 Q1 快照
  await setClock('2027-01-08 10:00')
  const lin = await as(browser, s.users, 'linxiao')
  await lin.goto('/versions')
  const r1 = await confirmModal(lin, '以年初原始目标发布', '确认发布', '/rolling/publish-original')
  eq(r1.status(), 200, '发布 Q1 快照')
  const q1 = (await r1.json()).id
  const [sq1, sv1] = [await summary(lin, q1), await summary(lin, s.v1)]
  const pick = (o) => Object.values(o).map((m) => [m.month, m.revenue, m.gross, m.net])
  eq(pick(sq1), pick(sv1), 'Q1 快照逐月数值与 V1 相同')
  eq(Object.keys(sq1).length, 12, '12 个月')
  await lin.reload()
  ok((await lin.locator('tbody').last().innerText()).includes('Q1 快照'), '版本列表出现 Q1 快照（无需任何填报人提交）')

  // 2027-04-10 已导入 1–3 月实际；2027-04-22 发起 Q2 滚动更新
  step('import-q1')
  await setClock('2027-04-22 09:00')
  await flushOutbox()
  await clearStub()
  await loginPage(lin, s.users, 'linxiao')
  await lin.goto('/versions')
  const r2 = await confirmModal(lin, '发起滚动更新', '确认发起', '/api/versions/rolling')
  eq(r2.status(), 200, '发起 Q2 滚动更新')
  const draft = (await r2.json()).id
  await flushOutbox()
  const msgs = await stubMessages()
  for (const [role, ids] of Object.entries(ROLES)) {
    for (const id of ids) ok(msgs.some((m) => m.userid_list.includes(id)), `${role} ${id} 收到工作通知`)
  }

  // 王浩从「我的填报」滚动预测入口进入：只开放 4–12 月
  const wang = await as(browser, s.users, 'wanghao')
  await wang.goto('/filling')
  const entry = wang.locator('tr[data-unit="Amazon-US-01"]', { hasText: '滚动' }).locator('a')
  await entry.waitFor()
  await entry.click()
  await wang.waitForURL('**/filling/platform/0?**')
  const url = wang.url()
  await gotoGrid(wang, url)
  ok((await wang.locator('.page-head .sub').innerText()).includes('只开放本季度及以后月份'), '滚动预测提示')
  const key = s.keys['浴室柜|old|avg_sales']
  for (const m of ['2027-01', '2027-02', '2027-03']) ok(!(await tryEdit(wang, key, m)), `${m} 不可编辑`)
  ok(await tryEdit(wang, key, '2027-04'), '2027-04 可编辑')
  for (let m = 5; m <= 12; m++) eq((await editCell(wang, key, `2027-${String(m).padStart(2, '0')}`, '78')).errors, [], `更新 2027-${m} 驱动`)
  eq(await cellText(wang, s.keys['浴室柜|old|spu_count'].replace('spu_count', 'revenue_cny'), '2027-06'), '646,855.56', '驱动计算值')
  eq(await cellText(wang, s.keys['浴室柜|old|spu_count'].replace('spu_count', 'revenue_cny'), '2027-04'), '600,000.00', '2027-04 驱动计算值')
  await wang.locator('[data-submit]').click()
  eq((await wang.locator('[data-submit]').innerText()).trim(), '提交滚动更新', '按钮文字')
  const [rs] = await Promise.all([wang.waitForResponse((x) => x.url().endsWith('/submit')), wang.locator('[data-confirm-submit]').click()])
  eq(rs.status(), 200, '王浩提交滚动更新')

  // 孙婷（B端业务）在预算版本页提交本季度更新
  const sun = await as(browser, s.users, 'sunting')
  await sun.goto('/versions')
  const sunRow = sun.locator('tr', { hasText: 'B端 · 美国业务部' })
  await sunRow.waitFor()
  await Promise.all([sun.waitForResponse((x) => x.url().includes('/submit')), sunRow.getByRole('button', { name: '提交本季度更新' }).click()])
  await sun.waitForTimeout(400)
  ok((await sunRow.innerText()).includes('已提交'), '孙婷已提交')

  // 其余运营、B端业务、物流物控、财务BP 单位提交（接口）
  const api = await as(browser, s.users, 'linxiao')
  const units = (await (await api.request.get(`/api/versions/rolling/${draft}`)).json()).units
  const byId = Object.fromEntries(Object.entries(s.users).map(([k, v]) => [v, k]))
  for (const u of units.filter((x) => !x.submitted)) {
    await loginPage(api, s.users, byId[u.filler_id])
    eq((await api.request.post(`/api/filling-units/rolling/${draft}/${encodeURIComponent(u.key)}/submit`)).status(), 200, `${u.name} 提交`)
  }

  // 金蝶 2027-04 实际已导入；2027-05-12 林晓发布 Q2 快照
  step('import-april')
  await setClock('2027-05-12 10:00')
  await loginPage(lin, s.users, 'linxiao')
  await lin.goto('/versions')
  const r3 = await confirmModal(lin, '发布快照', '确认发布', `/rolling/${draft}/publish`)
  eq(r3.status(), 200, '发布 Q2 快照')
  const pub = await r3.json()
  eq([pub.quarter_label, pub.published_on], ['2027 Q2', '2027-05-12'], '快照标注')
  await lin.reload()
  const row = lin.locator('tbody tr', { hasText: 'Q2 快照' })
  await row.waitFor()
  const cells = await row.locator('td').allInnerTexts()
  ok(cells[3] === '2027 Q2' && cells[4] === '不可修改' && cells[6].includes('2027-05-12'), `版本列表 Q2 快照：${cells.join(' | ')}`)
  const sq2 = await summary(lin, draft, amz)
  eq([sq2['2027-04'].revenue_display, sq2['2027-04'].source], ['¥ 554,400.00', 'actual'], '2027-04 取实际')
  for (let m = 5; m <= 12; m++) {
    const k = `2027-${String(m).padStart(2, '0')}`
    eq([sq2[k].revenue_display, sq2[k].source], [FORECAST, 'forecast'], `${k} 取最新提交的驱动计算值`)
  }

  // 尝试修改快照被拒
  const again = await lin.request.post(`/api/versions/rolling/${draft}/publish`, { data: { confirm_unsubmitted: true } })
  eq(again.status(), 409, '再次发布被拒')
  await loginPage(wang, s.users, 'wanghao')
  await gotoGrid(wang, url)
  ok(!(await tryEdit(wang, key, '2027-06')), '快照表格不可编辑')
  const rkey = encodeURIComponent(new URL(url).searchParams.get('key'))
  const g = await (await wang.request.get(`/api/filling-units/rolling/${draft}/${rkey}/grid`)).json()
  const patch = await wang.request.patch(`/api/filling-units/rolling/${draft}/${rkey}/cells`,
    { data: [{ row_key: key, field: '2027-06', value: '99', base: g.rows.find((r) => r.key === key).values['2027-06'] }] })
  console.log('写入快照：', patch.status(), await patch.text())
  ok([403, 409, 422].includes(patch.status()), `写入快照被拒：${patch.status()} ${await patch.text()}`)
  eq((await summary(lin, draft, amz))['2027-06'].revenue_display, FORECAST, '快照值不变')
})
