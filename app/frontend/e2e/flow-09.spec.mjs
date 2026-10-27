// FLOW-09 浏览器 E2E（钉钉接口本地替身 8021）：期望值逐字取自 TDD验收契约 FLOW-09。
import { run, py, loginAs, BASE, STUB, check, eq } from './e1_harness.mjs'

const AMOUNT = [/\d{1,3}(,\d{3})+/, /[¥$€£￥]/, /(?<![\d-])\d+\.\d+/, /\d{4,}/]

async function openPublish(lin) {
  await lin.goto(`${BASE}/tasks`)
  await lin.locator('[data-publish]').click()
  await lin.locator('#p-year').selectOption('2027')
  await lin.locator('#p-dl').fill('2026-12-20')
  return lin.getByRole('dialog')
}

async function setRoles(lin, name, check_) {
  await lin.goto(`${BASE}/settings/roles`)
  await lin.locator('tr', { hasText: name }).getByRole('button', { name: '分配' }).click()
  const d = lin.getByRole('dialog')
  await check_(d)
  await d.getByRole('button', { name: '保存' }).click()
}

await run('FLOW-09', 'flow09', async (env) => {
  const lin = await env.newPage()
  await loginAs(lin, '林晓')
  // 缺填报人：研发部预算专员韩冰被撤销全部角色 → 整次发布失败并列出缺人单位，不生成单位、不发通知
  await lin.goto(`${BASE}/settings/roles`)
  await lin.locator('tr', { hasText: '韩冰' }).getByRole('button', { name: '分配' }).click()
  await lin.getByRole('dialog').getByRole('button', { name: '撤销全部角色' }).click()
  await lin.getByRole('button', { name: '确认撤销' }).click()
  await lin.getByText('已撤销 韩冰 的全部角色').waitFor()
  let modal = await openPublish(lin)
  check((await modal.innerText()).includes('研发部 · 缺填报人'), '发布弹窗中研发部显示「缺填报人」')
  await lin.locator('[data-publish-ok]').click()
  await modal.getByRole('alert').waitFor()
  const err = await modal.getByRole('alert').innerText()
  check(err.includes('研发部') && err.includes('缺少填报人或审核人'), `整次发布失败并列出缺人单位：${err}`)
  await modal.getByRole('button', { name: '取消' }).click()
  eq((await (await lin.request.get(`${BASE}/api/tasks`)).json()).items.length, 0, '未生成任务与单位')
  py('outbox')
  eq((await (await fetch(`${STUB}/_stub/messages`)).json()).length, 0, '未发送任何钉钉通知')
  // 恢复韩冰「部门预算专员 · 研发部」
  await setRoles(lin, '韩冰', async (d) => {
    await d.getByLabel('部门预算专员').check()
    await d.locator('label', { hasText: '研发部' }).locator('input').check()
  })
  await lin.getByRole('dialog').waitFor({ state: 'detached' })

  modal = await openPublish(lin)
  const chosen = await modal.getByText(/已选 \d+ 个单位/).innerText()
  check(chosen.includes('已选 24 个单位'), `发布弹窗默认 24 个单位：${chosen}`)
  const stores = await (await lin.request.get(`${BASE}/api/master/stores`)).json()
  eq([stores.stores.filter((s) => s.is_active).length, stores.stores.filter((s) => !s.is_active).map((s) => s.name)], [5, ['Lowes-US-02']], '主数据 5 个启用店铺 + 1 个停用店铺')
  check(!(await modal.innerText()).includes('Lowes-US-02'), '停用店铺无填报单位')
  await lin.locator('[data-publish-ok]').click()
  const toast = await lin.getByText(/已发布「2027 年度预算编制」/).innerText()
  console.log('    ' + toast)
  const taskId = (await lin.getByRole('link', { name: '查看进度' }).first().getAttribute('href')).split('/').pop()
  const prog = await (await lin.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()
  eq(prog.unit_count, 24, '生成 24 个填报单位')
  const byType = {}
  for (const u of prog.units) byType[u.unit_type] = (byType[u.unit_type] ?? 0) + 1
  eq(byType, { platform: 5, b2b: 2, cost_ratio: 1, logistics_ratio: 1, dept_expense: 15 }, '平台渠道 5、B 端 2、成本比例 1、物流比例 1、部门费用 15')
  await lin.goto(`${BASE}/tasks/${taskId}`)
  await lin.waitForSelector('[data-unit]')
  eq(await lin.locator('[data-unit]').count(), 24, '任务详情看板列出 24 个单位')

  // 各单位独立出现在对应填报人的「我的填报」
  const fillers = new Map()
  for (const u of prog.units) fillers.set(u.filler.name, [...(fillers.get(u.filler.name) ?? []), u.name])
  let ok = true
  for (const [name, unitNames] of fillers) {
    const pg = await env.newPage()
    await loginAs(pg, name)
    await pg.goto(`${BASE}/filling`)
    await pg.waitForSelector('[data-unit]')
    const shown = await pg.locator('[data-unit]').evaluateAll((els) => els.map((e) => e.getAttribute('data-unit')))
    if (!unitNames.every((n) => shown.includes(n))) { ok = false; console.log(`    ${name} 缺 ${unitNames} / ${shown}`) }
    await pg.context().close()
  }
  check(ok, `${fillers.size} 位填报人的「我的填报」均列出其负责的单位`)

  // 钉钉工作通知（发件箱投递到替身）
  py('outbox')
  const msgs = await (await fetch(`${STUB}/_stub/messages`)).json()
  const users = (await (await lin.request.get(`${BASE}/api/auth/dev-users`)).json())
  const userid = (name) => users.find((u) => u.name === name)
  let perOk = true
  let contentOk = true
  const sample = []
  for (const name of fillers.keys()) {
    const u = userid(name)
    const mine = msgs.filter((m) => m.userid_list.some((x) => x === u?.dingtalk_userid || x === u?.userid))
    if (mine.length !== 1) { perOk = false; console.log(`    ${name} 收到 ${mine.length} 条`) }
    for (const m of mine) {
      const text = `${m.msg.link.title} ${m.msg.link.text}`
      sample.push(text)
      const rest = text.replaceAll('2026-12-20', '').replaceAll('2027', '')
      if (!(text.includes('2027') && text.includes('2026-12-20') && /^https?:\/\//.test(m.msg.link.messageUrl)) || AMOUNT.some((re) => re.test(rest))) contentOk = false
    }
  }
  console.log('    通知示例：' + sample[0])
  check(perOk, `每个单位填报人收到 1 条工作通知（共 ${msgs.length} 条 / ${fillers.size} 位填报人）`)
  check(contentOk, '通知内容含「2027」「2026-12-20」与系统链接，不含任何金额')

  // 第二次发布被阻止
  modal = await openPublish(lin)
  await lin.locator('[data-publish-ok]').click()
  await modal.getByRole('alert').waitFor()
  const dup = await modal.getByRole('alert').innerText()
  check(dup.includes('「2027 年度预算编制」'), `第二次发布被阻止并提示已有任务名称：${dup}`)
  const after = await (await lin.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()
  eq([after.unit_count, (await (await lin.request.get(`${BASE}/api/tasks`)).json()).items.length], [24, 1], '单位数不变（24），任务仍为 1 个')
})
