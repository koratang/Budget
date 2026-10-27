// SMOKE-03 浏览器 E2E：开发身份模拟 + 钉钉替身；期望值逐字取自 TDD验收契约 SMOKE-03。
// 林晓发布「2027 年度预算编制」→ 各填报人填一个单元并提交 → 各部门负责人通过 → 林晓「提交 CEO 审批」→ 周明远「通过并锁定」
import { run, loginAs, BASE, check, eq, editCell, cellValue } from './e1_harness.mjs'

// 单位 → [填报人, 部门负责人, 行键后缀(按页面数据源查找), 列, 值]
const PLAN = [
  ['Amazon-US-01', '王浩', '赵磊', (k) => k.startsWith('pu:') && k.endsWith(':1|spu_count') && k.split(':')[3] === '5', '2027-03', '10'],
  ['B端 · 美国业务部', '孙婷', '韩立群', (k) => k.endsWith('|sales_local'), '2027-03', '200000'],
  ['成本比例（财务BP）', '陈思雨', '林晓', (k) => k.endsWith(':5|purchase_cost_rate'), '2027-03', '30'],
  ['物流比例（物流物控）', '蒋帆', '何建国', (k) => k.endsWith(':5|first_leg_rate'), '2027-03', '6'],
  ['人力资源部', '郑可', '吴静', (k) => k.endsWith('|amount'), '2027-03', '300000'],
]

async function rowKey(page, pred) {
  const keys = await page.evaluate(async () => (await document.querySelector('revo-grid').getSource()).map((r) => r.__rowKey))
  const k = keys.find(pred)
  if (!k) throw new Error('未找到目标行')
  return k
}

async function boardStatus(page, taskId) {
  await loginAs(page, '林晓')
  await page.goto(`${BASE}/tasks/${taskId}`)
  await page.waitForSelector('[data-unit] [data-unit-status]')
  const out = {}
  for (const [name] of PLAN) out[name] = (await page.locator(`[data-unit="${name}"] [data-unit-status]`).innerText()).trim()
  out.__task = (await page.locator('[data-task-status]').innerText()).trim()
  return out
}

async function openMyUnit(page, who) {
  await loginAs(page, who)
  await page.goto(`${BASE}/filling`)
  await page.waitForSelector('[data-unit] a')
  await page.locator('[data-unit] a').first().click()
  await page.waitForSelector('revo-grid .rgCell')
  await page.waitForTimeout(300)
}

await run('SMOKE-03', 'smoke03', async (env) => {
  const page = await env.newPage()
  // 林晓经登录页「开发模式身份切换」进入
  await page.goto(`${BASE}/login`)
  await page.getByText('开发模式身份切换').waitFor()
  const sel = page.locator('select').filter({ has: page.locator('option', { hasText: '林晓' }) }).first()
  const opt = await sel.locator('option', { hasText: '林晓' }).first().getAttribute('value')
  await sel.selectOption(opt)
  await page.getByRole('button', { name: '以此身份进入' }).click()
  await page.waitForURL((u) => !u.pathname.startsWith('/login'))
  // 发布编制任务
  await page.goto(`${BASE}/tasks`)
  await page.locator('[data-publish]').click()
  await page.locator('#p-year').selectOption('2027')
  await page.locator('#p-dl').fill('2026-12-20')
  await page.locator('[data-publish-ok]').click()
  await page.getByText('已发布「2027 年度预算编制」').waitFor()
  const taskHref = await page.getByRole('link', { name: '查看进度' }).first().getAttribute('href')
  const taskId = taskHref.split('/').pop()
  const states = Object.fromEntries(PLAN.map(([n]) => [n, []]))
  const taskStates = []
  let b = await boardStatus(page, taskId)
  for (const [n] of PLAN) states[n].push(b[n])
  taskStates.push(b.__task)

  const filled = {}
  for (const [name, filler, head, pred, prop, value] of PLAN) {
    await openMyUnit(page, filler)
    const key = await rowKey(page, pred)
    const resp = await editCell(page, key, prop, value)
    check(resp && resp.status() === 200, `${name}：${filler} 编辑单元 ${prop} 保存 200`)
    filled[name] = { key, prop, shown: await cellValue(page, key, prop), url: page.url() }
    b = await boardStatus(page, taskId)
    states[name].push(b[name])
    await openMyUnit(page, filler)
    await page.locator('[data-submit]').click()
    await page.locator('[data-confirm-submit]').click()
    await page.getByText('已提交，已通知').waitFor()
    b = await boardStatus(page, taskId)
    states[name].push(b[name])
    await loginAs(page, head)
    await page.goto(`${BASE}/approvals`)
    await page.locator(`[data-approval*="${name}"] a`).first().click()
    await page.locator('[data-approve]').click()
    await page.locator('[data-confirm-approve]').click()
    await page.locator('[data-result]').waitFor()
    b = await boardStatus(page, taskId)
    states[name].push(b[name])
  }
  for (const [name] of PLAN) eq(states[name], ['未开始', '填报中', '已提交', '已通过'], `${name} 单位状态依次显示`)

  await loginAs(page, '林晓')
  await page.goto(`${BASE}/tasks/${taskId}`)
  await page.locator('[data-submit-ceo]').click()
  await page.locator('[data-confirm-ceo]').click()
  await page.getByRole('button', { name: '已提交 CEO 审批' }).waitFor()
  b = await boardStatus(page, taskId)
  taskStates.push(b.__task)
  await loginAs(page, '周明远')
  await page.goto(`${BASE}/approvals`)
  await page.locator('[data-approval*="2027 年度预算编制"] a').first().click()
  const approveText = (await page.locator('[data-approve]').innerText()).trim()
  eq(approveText, '通过并锁定', 'CEO 审批按钮为「通过并锁定」')
  await page.locator('[data-approve]').click()
  await page.locator('[data-confirm-approve]').click()
  await page.locator('[data-result]').waitFor()
  b = await boardStatus(page, taskId)
  taskStates.push(b.__task)
  console.log('  任务状态显示序列：' + taskStates.join(' → '))
  eq(taskStates.length, 3, '任务状态经历三个阶段')

  await page.goto(`${BASE}/versions`)
  const vrow = page.locator('tr', { hasText: '年初原始目标' }).first()
  await vrow.waitFor()
  const vtext = await vrow.innerText()
  check(/已锁定/.test(vtext), `版本列表出现「年初原始目标」且带锁定标记：${vtext.replace(/\s+/g, ' ')}`)

  // 随后任一身份修改该版本任一单元均被拒绝且数值不变
  const everyone = ['林晓', '周明远', '陈思雨', '王浩', '孙婷', '蒋帆', '郑可', '吴静', '赵磊', '韩立群', '何建国']
  const units = await (await page.request.get(`${BASE}/api/tasks/${taskId}/progress`)).json()
  for (const [name, filler] of PLAN) {
    const unitId = units.units.find((u) => u.name === name).id
    const f = filled[name]
    // 填报人在页面上尝试编辑：表格锁定，编辑器不打开、无保存请求
    await openMyUnit(page, filler)
    check(await page.locator('[data-locked]').isVisible(), `${name}：页面显示锁定提示`)
    await page.evaluate(async ({ key, prop }) => {
      const g = document.querySelector('revo-grid')
      const i = (await g.getSource()).findIndex((r) => r.__rowKey === key)
      await g.setCellEdit(i, prop)
    }, { key: f.key, prop: f.prop })
    check(await page.locator('revo-grid input').count() === 0, `${name}：锁定后单元格不可进入编辑`)
    let allRejected = true
    for (const who of everyone) {
      await loginAs(page, who)
      const r = await page.request.patch(`${BASE}/api/filling-units/${unitId}/cells`, {
        data: [{ row_key: f.key, field: f.prop, value: '1', base: null }],
      })
      if (![403, 409].includes(r.status())) { allRejected = false; console.log(`    ${who} → ${r.status()}`) }
    }
    check(allRejected, `${name}：11 个身份修改请求均被拒绝（403/409）`)
    await openMyUnit(page, filler)
    eq(await cellValue(page, f.key, f.prop), f.shown, `${name}：数值不变`)
  }
})
