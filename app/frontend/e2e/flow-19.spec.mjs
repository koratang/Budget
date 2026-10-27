// FLOW-19 浏览器 E2E：林晓在 PAGE-F08-01 发起 2027 Q2 目标调整；王浩从「我的填报」进入 PAGE-F04-02 调整模式编辑 2027-04（已导入实际，锁定）与 2027-06，
// 先不填原因提交、再填原因提交；赵磊、林晓在 PAGE-F07-02 审核；周明远整次通过 → 版本列表 V3；同一季度再次发起被阻止。
// 期望值逐字取自 TDD验收契约.md FLOW-19。前置（e2_setup flow_19）：V1 经完整编制审批、V2 为 Q1 经 CEO 通过的调整、金蝶实际经导入接口导入至 2027-04。
// 其余 14 个调整单位的提交与审核不是本行验收对象，经接口完成。
import { setup, startSystem, setClock, as, loginPage, gotoGrid, editCell, cellText, tryEdit, run, ok, eq, dump } from './e2_lib.mjs'

const REASON = 'Prime Day 提前至 6 月，7 月部分销量前移至 6 月'
const BLOCK = '本季度已有一次经 CEO 审批通过的目标调整（V3，2027-05-12），2027-07-01 起可发起下季度调整'

async function approveUi(page, type, id, label) {
  await page.goto(`/approvals/${type}/${id}`)
  await page.locator('[data-approve]').click()
  const [r] = await Promise.all([page.waitForResponse((x) => x.url().endsWith('/approve')), page.locator('[data-confirm-approve]').click()])
  eq(r.status(), 200, label)
}

await run('FLOW-19', async (browser) => {
  const s = setup('flow_19')
  const before = { v1: dump(s.v1), v2: dump(s.v2) }
  ok(before.v1.locked && before.v2.locked && before.v1.sha256 !== before.v2.sha256, 'V1、V2 已锁定且不同')
  await startSystem()
  await setClock('2027-05-12 09:00')

  // 林晓发起 2027 Q2 目标调整
  const lin = await as(browser, s.users, 'linxiao')
  await lin.goto('/versions')
  await lin.getByRole('button', { name: '发起季度调整' }).waitFor()
  ok((await lin.locator('[data-page-id="PAGE-F08-01"]').innerText()).includes('金蝶实际已导入至 2027-04'), '当前日期与实际导入月份')
  await lin.getByRole('button', { name: '发起季度调整' }).click()
  const [started] = await Promise.all([lin.waitForResponse((x) => x.url().endsWith('/api/versions/adjustments') && x.request().method() === 'POST'),
    lin.getByRole('button', { name: '确认发起' }).click()])
  eq(started.status(), 200, '发起调整')
  const adjId = (await started.json()).id

  // 王浩从「我的填报」进入调整模式
  const wang = await as(browser, s.users, 'wanghao')
  await wang.goto('/filling')
  const entry = wang.locator('tr[data-unit="Amazon-US-01"]', { hasText: '第二季度目标调整' }).locator('a')
  await entry.waitFor()
  await entry.click()
  await wang.waitForURL('**/filling/platform/**')
  const unitId = Number(new URL(wang.url()).pathname.split('/').pop())
  await gotoGrid(wang, wang.url())
  const notice = await wang.locator('.notice-info').first().innerText()
  ok(notice.includes('调整模式') && notice.includes('2027-04 已导入金蝶实际，不可修改'), `调整模式提示：${notice}`)
  const key = s.keys['浴室柜|old|avg_sales']
  const colLabel = await wang.evaluate(async () => (await document.querySelector('revo-grid').getColumns()).flatMap((c) => c.children ?? [c]).find((c) => c.prop === '2027-04').name)
  ok(colLabel.includes('实际'), `2027-04 列标注：${colLabel}`)
  const aprBefore = await cellText(wang, key, '2027-04')
  ok(!(await tryEdit(wang, key, '2027-04')), '2027-04 单元格锁定不可编辑')
  // 绕过界面直接写 2027-04：保存被拒并提示
  const g = await (await wang.request.get(`/api/filling-units/${unitId}/grid`)).json()
  const r04 = await wang.request.patch(`/api/filling-units/${unitId}/cells`, { data: [{ row_key: key, field: '2027-04', value: '80', base: g.rows.find((r) => r.key === key).values['2027-04'] }] })
  eq((await r04.json()).errors.map((e) => e.message), ['该月已导入实际，不能调整'], '2027-04 保存被拒并提示')
  const res06 = await editCell(wang, key, '2027-06', '90')
  eq(res06.errors, [], '2027-06 可保存')
  ok(['90', '90.0'].includes(await cellText(wang, key, '2027-06')), '2027-06 显示新值')
  await gotoGrid(wang, wang.url())
  eq(await cellText(wang, key, '2027-04'), aprBefore, '2027-04 值未变')

  // 先不填调整原因提交 → 提示；再填原因提交
  eq((await wang.locator('[data-submit]').innerText()).trim(), '提交调整', '按钮「提交调整」')
  await wang.locator('[data-submit]').click()
  eq((await wang.locator('.field-error').first().innerText()).trim(), '请填写调整原因', '无原因提交提示')
  await wang.locator('#adj-reason').fill(REASON)
  await wang.locator('[data-submit]').click()
  const [sub] = await Promise.all([wang.waitForResponse((x) => x.url().endsWith('/submit')), wang.locator('[data-confirm-submit]').click()])
  eq(sub.status(), 200, '填写原因后提交')
  await wang.waitForTimeout(400)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '已提交', '调整单位已提交')

  // 其余单位提交（接口）
  const api = await as(browser, s.users, 'linxiao')
  const adj = await (await api.request.get(`/api/versions/adjustments/${adjId}`)).json()
  const units = adj.units ?? adj.adjustment?.units
  ok(Array.isArray(units) && units.length === 15, `调整单位 15 个：${units?.length}`)
  const userid = Object.fromEntries(Object.entries(s.users).map(([k, v]) => [v, k]))
  await loginPage(api, s.users, 'linxiao')
  for (const u of units.filter((x) => x.id !== unitId)) {
    await loginPage(api, s.users, userid[u.filler_id])
    eq((await api.request.post(`/api/filling-units/${u.id}/submit`, { data: { adjust_reason: '本单位无调整' } })).status(), 200, `${u.name} 提交`)
  }

  // 赵磊、林晓逐级通过（Amazon-US-01 在界面审核，其余经接口）
  const zhao = await as(browser, s.users, 'zhaolei')
  await zhao.goto('/approvals')
  ok((await zhao.locator('tbody').innerText()).includes('目标调整'), '赵磊待处理含目标调整')
  await approveUi(zhao, 'adjustment-unit', unitId, '赵磊通过 Amazon-US-01 调整')
  for (const level of ['dept', 'finance']) {
    for (const u of units) {
      if (u.id === unitId) {
        if (level === 'finance') await approveUi(lin, 'adjustment-unit', unitId, '林晓通过 Amazon-US-01 调整')
        continue
      }
      await loginPage(api, s.users, level === 'dept' ? s.names[u.reviewer_name] : 'linxiao')
      const r = await api.request.post(`/api/approvals/adjustment-unit/${u.id}/approve`)
      eq(r.status(), 200, `${u.name} ${level} 通过`)
    }
  }

  // 周明远整次通过
  await setClock('2027-05-12 16:30')
  const ceo = await as(browser, s.users, 'zhoumingyuan')
  await ceo.goto('/approvals')
  ok((await ceo.locator('tbody').innerText()).includes('目标调整'), 'CEO 待处理含整次调整')
  await approveUi(ceo, 'adjustment', adjId, '周明远整次通过')

  await loginPage(lin, s.users, 'linxiao')
  await lin.goto('/versions')
  const v3 = lin.locator('tbody tr', { has: lin.locator('strong', { hasText: /^V3$/ }) })
  await v3.waitFor()
  const cells = await v3.locator('td').allInnerTexts()
  ok(cells[2] === '调整后目标', `V3 类型：${cells[2]}`)
  ok(cells[5].includes('周明远'), `V3 审批人：${cells[5]}`)
  eq(cells[6], '2027-05-12 16:30', 'V3 审批时间')
  ok(cells[7].includes(REASON), `V3 调整原因：${cells[7]}`)

  // V1 与 V2 全部单元值与调整前逐值相同
  eq(dump(s.v1), before.v1, 'V1 逐值不变')
  eq(dump(s.v2), before.v2, 'V2 逐值不变')

  // 再次发起被阻止，按钮显示不可用原因
  ok(await lin.getByRole('button', { name: '发起季度调整' }).isDisabled(), '发起季度调整按钮不可用')
  eq((await lin.locator('[data-testid="adj-block"]').innerText()).trim(), BLOCK, '不可用原因')
  const again = await lin.request.post('/api/versions/adjustments')
  eq([again.status(), (await again.json()).message], [409, BLOCK], '再次发起被阻止')
})
