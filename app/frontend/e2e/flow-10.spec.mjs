// FLOW-10 浏览器 E2E（可控时钟 + 钉钉接口本地替身 8021）：期望值逐字取自 TDD验收契约 FLOW-10。
// 起点：FLOW-09 的 24 个单位（编制期时钟 2026-11-02 10:00）；状态经各填报人 / 审核人的真实接口推进。
import { run, py, loginAs, BASE, STUB, check, eq } from './e1_harness.mjs'

const FIVE = ['未开始', '填报中', '已提交', '已退回', '已通过']

async function touch(page, unitId) {
  const g = await (await page.request.get(`${BASE}/api/filling-units/${unitId}/grid`)).json()
  const row = g.rows.find((r) => r.kind === 'input' && !(r.readonly_fields ?? []).includes('2027-01'))
  const r = await page.request.patch(`${BASE}/api/filling-units/${unitId}/cells`, { data: [{ row_key: row.key, field: '2027-01', value: '1', base: row.values['2027-01'] }] })
  if (r.status() !== 200) throw new Error(`保存失败 ${unitId} ${r.status()}`)
}

await run('FLOW-10', 'flow09', async (env) => {
  const lin = await env.newPage()
  await loginAs(lin, '林晓')
  const cands = (await (await lin.request.get(`${BASE}/api/tasks/candidates`)).json()).items
  const pub = await lin.request.post(`${BASE}/api/tasks`, { data: { year: 2027, deadline: '2026-12-20', units: cands.map((c) => ({ unit_type: c.unit_type, scope_object_id: c.scope_object_id })) } })
  eq(pub.status(), 201, '发布「2027 年度预算编制」（24 个单位）')
  py('outbox')
  await fetch(`${STUB}/_stub/messages`, { method: 'DELETE' })
  const taskId = (await pub.json()).task.id
  const units = (await (await lin.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()).units.sort((a, b) => a.id - b.id)
  const plan = [...Array(6).fill('submitted'), ...Array(3).fill('approved'), ...Array(2).fill('returned'), ...Array(4).fill('filling'), ...Array(9).fill('not_started')]
  const actor = await env.newPage()
  for (const [i, u] of units.entries()) {
    const st = plan[i]
    if (st === 'not_started') continue
    await loginAs(actor, u.filler.name)
    await touch(actor, u.id)
    if (st === 'filling') continue
    eq((await actor.request.post(`${BASE}/api/filling-units/${u.id}/submit`)).status(), 200, `${u.name} 提交`)
    if (st === 'submitted') continue
    await loginAs(actor, u.reviewer.name)
    const r = st === 'approved'
      ? await actor.request.post(`${BASE}/api/approvals/unit/${u.id}/approve`)
      : await actor.request.post(`${BASE}/api/approvals/unit/${u.id}/reject`, { data: { reason: '灯镜新品 10–12 月平均销量较 2026 同期高 40%，请补充依据' } })
    eq(r.status(), 200, `${u.name} ${st === 'approved' ? '通过' : '退回'}`)
  }
  py('outbox')
  await fetch(`${STUB}/_stub/messages`, { method: 'DELETE' })

  await lin.goto(`${BASE}/tasks/${taskId}`)
  await lin.waitForSelector('[data-unit] [data-unit-status]')
  const statuses = await lin.locator('[data-unit] [data-unit-status]').allInnerTexts()
  eq(statuses.length, 24, '看板列出 24 个单位')
  check(statuses.every((s) => FIVE.includes(s.trim())), '看板逐单位显示五种状态之一')
  const count = (s) => statuses.filter((x) => x.trim() === s).length
  eq([count('已提交'), count('已通过'), count('已退回'), count('填报中'), count('未开始')], [6, 3, 2, 4, 9], '6 已提交、3 已通过、2 已退回、其余未开始或填报中')
  eq((await lin.locator('[data-submit-rate]').innerText()).trim(), '37.5%', '提交率 =（6 + 3）÷ 24 = 37.5%')
  await lin.goto(`${BASE}/`)
  await lin.locator('[data-testid="kpi-submit"]').waitFor()
  const kpi = await lin.locator('[data-testid="kpi-submit"]').innerText()
  check(kpi.includes('37.5%'), `工作台「编制任务提交率」同为 37.5%：${kpi.replace(/\s+/g, ' ')}`)

  // 时钟推进到 2026-12-21 09:00 触发逾期任务（08:59 不触发）
  py('overdue', '2026-12-21T08:59:00')
  eq((await (await fetch(`${STUB}/_stub/messages`)).json()).length, 0, '2026-12-21 08:59 尚不提醒')
  py('overdue', '2026-12-21T09:00:00')
  const msgs = await (await fetch(`${STUB}/_stub/messages`)).json()
  eq(msgs.length, 15, '09:00 只向 15 个未提交单位发逾期提醒（每单位一条）')
  const users = await (await lin.request.get(`${BASE}/api/auth/dev-users`)).json()
  const uidOf = (name) => users.find((u) => u.name === name).dingtalk_userid
  const late = units.filter((_, i) => !['submitted', 'approved'].includes(plan[i]))
  const expected = late.map((u) => [uidOf(u.filler.name), uidOf(u.reviewer.name)].sort().join(',')).sort()
  eq(msgs.map((m) => [...new Set(m.userid_list)].sort().join(',')).sort(), expected, '每条提醒发给该单位填报人及其部门负责人')
  const doneOnly = units.filter((_, i) => ['submitted', 'approved'].includes(plan[i])).map((u) => uidOf(u.filler.name))
    .filter((id) => !late.some((u) => uidOf(u.filler.name) === id || uidOf(u.reviewer.name) === id))
  check(doneOnly.every((id) => msgs.every((m) => !m.userid_list.includes(id))), '已提交与已通过单位的填报人不收提醒')
  py('overdue', '2026-12-21T09:00:00')
  eq((await (await fetch(`${STUB}/_stub/messages`)).json()).length, 15, '再次触发不重复提醒')

  await env.restartBackend({ E1_NOW: '2026-12-21T09:05:00+08:00' })
  await loginAs(lin, '林晓')
  await lin.goto(`${BASE}/tasks/${taskId}`)
  const notice = lin.getByText('已过截止日期').locator('xpath=..')
  await notice.waitFor()
  const t = await notice.innerText()
  check(t.includes('已向 15 个未提交单位的填报人及其部门负责人发送钉钉逾期提醒'), `页面提示已发送逾期提醒的单位数 15：${t.replace(/\s+/g, ' ')}`)
  eq(await lin.getByText('逾期 · 已提醒').count(), 15, '15 个单位标「逾期 · 已提醒」')
}, { backendEnv: { E1_NOW: '2026-11-02T10:00:00+08:00' } })
