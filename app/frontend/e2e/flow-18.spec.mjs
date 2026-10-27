// FLOW-18 浏览器 E2E（钉钉本地替身 8022）：王浩提交 → 赵磊在待我审批退回（先空原因）→ 王浩看到原因修改重提 → 赵磊通过 → 林晓提交 CEO 被阻止
// → 其余单位通过后提交 → 周明远退回 → 林晓在任务详情看到 CEO 原因并把 Amazon-US-01 退回给填报人 → 再次全部通过 → 周明远「通过并锁定」。
// 期望值逐字取自 TDD验收契约.md FLOW-18。其余 4 个单位的填报与部门审核不是本行验收对象，经接口完成。
import { setup, startSystem, setClock, as, loginPage, gotoGrid, editCell, tryEdit, run, ok, eq, flushOutbox, stubMessages, clearStub, dump } from './e2_lib.mjs'

const REASON = '灯镜新品 10–12 月平均销量较 2026 同期高 40%'
const CEO_REASON = '请复核 Amazon-US-01 的广告费率后重新提交'
const OTHERS = {
  'B端 · 美国业务部': ['sunting', 'hanliqun', (s) => [`b2b:${s.customers.Ferguson}|sales_local`, '2027-03', '200000'], null],
  '成本比例（财务BP）': ['chensiyu', 'linxiao', (s) => [`ccr:${s.amz.channel}:${s.amz.site}:${s.amz.cats['浴室柜']}|purchase_cost_rate`, '2027-03', '30'], 'platform'],
  '物流比例（物流物控）': ['jiangfan', 'hejianguo', (s) => [`ccr:${s.amz.channel}:${s.amz.site}:${s.amz.cats['浴室柜']}|first_leg_rate`, '2027-03', '6'], 'platform'],
  人力资源部: ['zhengke', 'wujing', (s) => [`de:${s.accounts['工资薪酬']}|amount`, '2027-03', '300000'], null],
}

async function submitInGrid(page) {
  await page.locator('[data-submit]').click()
  const [r] = await Promise.all([page.waitForResponse((x) => x.url().endsWith('/submit')), page.locator('[data-confirm-submit]').click()])
  eq(r.status(), 200, '提交')
  await page.waitForTimeout(300)
}
async function approveUi(page, type, id) {
  await page.goto(`/approvals/${type}/${id}`)
  await page.locator('[data-approve]').click()
  const [r] = await Promise.all([page.waitForResponse((x) => x.url().endsWith('/approve')), page.locator('[data-confirm-approve]').click()])
  eq(r.status(), 200, `${type} ${id} 通过`)
  return r.json()
}
async function rejectUi(page, reason) {
  await page.locator('[data-reject]').click()
  await page.locator('[data-confirm-reject]').click()
  const err = page.locator('[data-reason-error]')
  await err.waitFor()
  eq((await err.innerText()).trim(), '请填写退回原因', '无原因退回被阻止')
  await page.locator('#rej-reason').fill(reason)
  const [r] = await Promise.all([page.waitForResponse((x) => x.url().endsWith('/reject')), page.locator('[data-confirm-reject]').click()])
  eq(r.status(), 200, '退回')
  return r.json()
}
const to = (msgs, uid) => msgs.filter((m) => m.userid_list.includes(uid))

await run('FLOW-18', async (browser) => {
  const s = setup('flow_18')
  await startSystem()
  await setClock('2026-12-15 10:00')
  await flushOutbox()
  await clearStub()
  const key = s.keys['灯镜|new|avg_sales']
  const unitUrl = `/filling/platform/${s.unit}`

  const wang = await as(browser, s.users, 'wanghao')
  await gotoGrid(wang, unitUrl)
  eq((await editCell(wang, key, '2027-10', '120')).errors, [], '王浩填写')
  await submitInGrid(wang)
  await flushOutbox()
  eq(to(await stubMessages(), 'zhaolei').length, 1, '赵磊收到 1 条工作通知')

  const zhao = await as(browser, s.users, 'zhaolei')
  await zhao.goto('/approvals')
  const item = zhao.locator('tr', { hasText: 'Amazon-US-01' })
  await item.waitFor()
  await item.getByRole('link', { name: '审批' }).click()
  await zhao.waitForURL(`**/approvals/unit/${s.unit}`)
  await clearStub()
  eq((await rejectUi(zhao, REASON)).status, 'returned', '赵磊退回')
  await flushOutbox()
  eq(to(await stubMessages(), 'wanghao').length, 1, '王浩收到退回工作通知')

  await gotoGrid(wang, unitUrl)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '已退回', '状态已退回')
  ok((await wang.locator('[data-returned]').innerText()).includes(REASON), '填报页显示退回原因原文')
  ok(await tryEdit(wang, key, '2027-10'), '退回后可编辑')
  eq((await editCell(wang, key, '2027-10', '100')).errors, [], '王浩修改')
  await submitInGrid(wang)
  eq((await approveUi(zhao, 'unit', s.unit)).status, 'approved', '赵磊通过')

  // 仍有单位未通过时提交 CEO 被阻止并列出全部未通过单位名称
  const lin = await as(browser, s.users, 'linxiao')
  await lin.goto(`/tasks/${s.task}`)
  await lin.locator('[data-submit-ceo]').click()
  const blocked = lin.locator('[data-blocked-units] li')
  await blocked.first().waitFor()
  const names = (await blocked.allInnerTexts()).map((t) => t.replace(/（[^（]*）$/, ''))
  eq(new Set(names), new Set(Object.keys(OTHERS)), `列出全部未通过单位：${names.join('、')}`)
  await lin.getByRole('button', { name: '知道了' }).click()

  const api = await as(browser, s.users, 'linxiao')
  const units = (await (await api.request.get(`/api/tasks/${s.task}/progress`)).json()).units
  for (const [name, [filler, head, cell, tab]] of Object.entries(OTHERS)) {
    const u = units.find((x) => x.name === name)
    const [rk, f, v] = cell(s)
    await loginPage(api, s.users, filler)
    const g = await (await api.request.get(`/api/filling-units/${u.id}/grid${tab ? `?tab=${tab}` : ''}`)).json()
    const base = g.rows.find((r) => r.key === rk).values[f]
    eq((await api.request.patch(`/api/filling-units/${u.id}/cells${tab ? `?tab=${tab}` : ''}`, { data: [{ row_key: rk, field: f, value: v, base }] })).status(), 200, `${name} 填写`)
    eq((await api.request.post(`/api/filling-units/${u.id}/submit`)).status(), 200, `${name} 提交`)
    await loginPage(api, s.users, head)
    eq((await api.request.post(`/api/approvals/unit/${u.id}/approve`)).status(), 200, `${name} 通过`)
  }

  async function submitCeo() {
    await lin.goto(`/tasks/${s.task}`)
    await lin.locator('[data-submit-ceo]').click()
    const [r] = await Promise.all([lin.waitForResponse((x) => x.url().endsWith('/submit-to-ceo')), lin.locator('[data-confirm-ceo]').click()])
    eq(r.status(), 200, '提交 CEO 审批')
  }
  await submitCeo()

  const ceo = await as(browser, s.users, 'zhoumingyuan')
  await ceo.goto(`/approvals/task/${s.task}`)
  eq((await rejectUi(ceo, CEO_REASON)).status, 'in_progress', 'CEO 退回后任务回到进行中')

  await lin.goto(`/tasks/${s.task}`)
  const ceoNote = lin.locator('[data-ceo-return]')
  await ceoNote.waitFor()
  ok((await ceoNote.innerText()).includes(CEO_REASON), '任务详情显示 CEO 原因')
  ok((await lin.locator('[data-task-status]').innerText()).includes('CEO 已退回'), '任务状态')
  await lin.locator('tr[data-unit="Amazon-US-01"] [data-return-unit]').click()
  await lin.locator('#ret-reason').fill('请按 CEO 意见复核广告费率')
  await Promise.all([lin.waitForResponse((x) => x.url().endsWith('/return')), lin.locator('[data-confirm-return]').click()])
  await lin.waitForTimeout(500)
  eq((await lin.locator('tr[data-unit="Amazon-US-01"] [data-unit-status]').innerText()).trim(), '已退回', '林晓退回给填报人')

  await gotoGrid(wang, unitUrl)
  eq((await editCell(wang, key, '2027-10', '95')).errors, [], '王浩再次修改')
  await submitInGrid(wang)
  await approveUi(zhao, 'unit', s.unit)
  await submitCeo()
  await ceo.goto(`/approvals/task/${s.task}`)
  eq((await ceo.locator('[data-approve]').innerText()).trim(), '通过并锁定', 'CEO 按钮')
  eq((await approveUi(ceo, 'task', s.task)).status, 'completed', 'CEO 通过并锁定')

  await lin.goto('/versions')
  const vrow = lin.locator('tbody tr', { hasText: '年初原始目标' }).first()
  await vrow.waitFor()
  ok((await vrow.innerText()).includes('周明远'), `版本列表：${await vrow.innerText()}`)
  const vid = (await (await lin.request.get(`/api/filling-units/${s.unit}/grid`)).json()).unit.version_id
  eq(dump(vid).locked, true, '版本已锁定')
})
