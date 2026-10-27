// FLOW-31 预算规则库（PAGE-F12-01 / PAGE-F12-02 / PAGE-F07-02）。期望值逐字取自契约 FLOW-31。
import { BASE, check, eq, loginAs, run, tableText } from './_e3_harness.mjs'

const PRESETS = ['新渠道连续 2 个月收入达成率低于 70%', '部门费用额度使用率超出时间进度 10 个百分点以上', '品类毛利率比预算低 3 个百分点以上']

async function as(page, name) {
  await page.context().clearCookies()
  await loginAs(page, name)
}

async function ruleDetail(page, id) {
  return (await page.request.get(`${BASE}/api/rules/${id}`)).json()
}

async function approveUi(page, versionId) {
  await page.goto(`${BASE}/approvals/rule-version/${versionId}`)
  await page.locator('[data-approve]').click()
  await page.locator('[data-confirm-approve]').click()
  await page.locator('[data-result]').waitFor()
  return (await page.locator('[data-result]').textContent()).trim()
}

async function openRule(page, id) {
  await page.goto(`${BASE}/rules/${id}`)
  const root = page.locator('[data-page-id="PAGE-F12-02"]')
  await root.locator('#h-his').waitFor()
  await page.waitForTimeout(300)
  return root
}

async function history(root) {
  return (await tableText(root.locator('section[aria-labelledby="h-his"] table'))).slice(1)
}

await run('FLOW-31', 'flow31', '2027-05-12 10:00', async (env) => {
  const page = await env.newPage()
  // 全新数据库首次启动后林晓打开规则库
  await as(page, '林晓')
  await page.goto(`${BASE}/rules`)
  const list = page.locator('[data-page-id="PAGE-F12-01"]')
  await list.locator('table tbody tr').first().waitFor()
  await page.waitForTimeout(300)
  const rows = (await tableText(list.locator('table'))).slice(1)
  console.log('  规则库：', JSON.stringify(rows))
  for (const name of PRESETS) {
    const r = rows.find((x) => x[0].startsWith(name))
    // 可信度列按设计显示生效版本的可信度（无生效版本为「—」）；待审批版本列显示 v1 的可信度
    check(!!r && r[2] === '—' && r[4].startsWith('待审批 v1（未验证经验'), `预置待审批预警规则「${name}」，可信度「未验证经验」`)
  }
  const items = (await (await page.request.get(`${BASE}/api/rules`)).json()).items
  const marginId = items.find((i) => i.name === PRESETS[2]).id
  const driverId = env.seeded.driver
  let d = await ruleDetail(page, marginId)
  check((await approveUi(page, d.versions[0].id)).length > 0, '林晓审批通过预置规则 v1')

  // 陈思雨提交「品类毛利率比预算低 3 个百分点以上」修改版
  await as(page, '陈思雨')
  let root = await openRule(page, marginId)
  await root.getByRole('button', { name: '编辑并提交新版本' }).click()
  const metrics = (await root.locator('#f-metric option').allTextContents()).map((s) => s.trim()).filter((s) => s && !s.startsWith('请选择'))
  eq(metrics, ['收入达成率', '毛利率差', '额度使用率减时间进度', '额度使用率', '预测偏差百分点'], '编辑表单提供 5 个指标')
  for (const id of ['#f-cmp', '#f-th', '#f-months', '#f-obj']) check(await root.locator(id).count() === 1, `表单含字段 ${id}（比较方式/阈值/连续月数/适用对象）`)
  check((await root.locator('fieldset', { hasText: '接收角色' }).locator('input[type=checkbox]').count()) >= 3 || (await root.textContent()).includes('接收角色'), '表单含接收角色')
  await root.locator('#f-th').fill('-2.5')
  if (await root.locator('input[type=checkbox][value]').first().isVisible() && (await root.locator('#f-obj').inputValue()) === 'category') {
    const boxes = root.locator('.radio-row input[type=checkbox]')
    if (!(await boxes.first().isChecked())) await boxes.first().check()
  }
  await root.locator('#f-basis').fill('2026 年 BI 回测：品类毛利率低于预算 2.5 个百分点即需关注')
  await root.getByRole('button', { name: '提交审批' }).click()
  eq((await root.locator('fieldset', { hasText: '可信度状态' }).locator('.field-error').textContent()).trim(), '请选择可信度状态', '不选可信度不能提交')
  await root.getByLabel('历史观察').check()
  await root.getByRole('button', { name: '提交审批' }).click()
  await root.locator('#h-his').waitFor()
  await page.waitForTimeout(300)
  let his = await history(root)
  console.log('  毛利率规则历史：', JSON.stringify(his))
  check(his.some((r) => r[0].includes('v2') && r[1] === '待审批' && r[3] === '历史观察'), '新建后状态「待审批」（v2，历史观察）')

  // 林晓审批通过 → v2 生效、v1 历史
  await as(page, '林晓')
  d = await ruleDetail(page, marginId)
  await approveUi(page, d.versions.find((v) => v.version_no === 2).id)
  root = await openRule(page, marginId)
  his = await history(root)
  check(his.some((r) => r[0].includes('v2') && r[1] === '生效') && his.some((r) => r[0].includes('v1') && r[1] === '历史'), '审批通过：v2「生效」，原生效 v1 转「历史」')

  // 驱动假设：陈思雨提交 v3（1.8 倍）→ 林晓填原因退回 → 修改后重新提交
  await as(page, '陈思雨')
  root = await openRule(page, driverId)
  await root.getByRole('button', { name: '编辑并提交新版本' }).click()
  await root.locator('#f-content').fill('Amazon 美国站 11 月销量 = 10 月 × 1.8')
  await root.getByLabel('未验证经验').check()
  await root.locator('#f-basis').fill('运营经验判断')
  await root.getByRole('button', { name: '提交审批' }).click()
  await root.locator('#h-his').waitFor()
  await as(page, '林晓')
  d = await ruleDetail(page, driverId)
  const v3 = d.versions.find((v) => v.version_no === 3)
  await page.goto(`${BASE}/approvals/rule-version/${v3.id}`)
  await page.locator('[data-reject]').click()
  await page.locator('[data-confirm-reject]').click()
  eq((await page.locator('[data-reason-error]').textContent()).trim(), '请填写退回原因', '退回必须填写原因')
  const reason = '只有经验判断，没有历史数据支撑 1.8 倍'
  await page.locator('#rej-reason').fill(reason)
  await page.locator('[data-confirm-reject]').click()
  await page.locator('[data-result]').waitFor()

  await as(page, '陈思雨')
  root = await openRule(page, driverId)
  const txt = await root.textContent()
  check(txt.includes('已退回 v3') && txt.includes(reason), '提交人看到 v3「已退回」与退回原因')
  check(txt.includes('已退回，不生效；v2 继续生效'), 'v3 不生效、v2 继续生效')
  his = await history(root)
  check(his.some((r) => r[0].includes('v3') && r[1] === '已退回') && his.some((r) => r[0].includes('v2') && r[1] === '生效'), '版本历史：v3 已退回、v2 生效')
  await root.getByRole('button', { name: '修改后重新提交' }).click()
  await root.locator('#f-content').fill('Amazon 美国站 11 月销量 = 10 月 × 1.7')
  await root.getByLabel('历史观察').check()
  await root.locator('#f-basis').fill('补充 2024 年数据')
  await root.getByRole('button', { name: '提交审批' }).click()
  await root.locator('#h-his').waitFor()
  await page.waitForTimeout(300)
  his = await history(root)
  check(his.some((r) => r[0].includes('v4') && r[1] === '待审批'), '重新提交生成新的待审批版本号 v4')
  // 版本历史列出全部版本的内容、可信度、依据、提交人、审批人、生效时间
  eq((await tableText(root.locator('section[aria-labelledby="h-his"] table')))[0], ['版本', '状态', '内容', '可信度', '依据', '提交人', '审批人', '生效时间'], '版本历史列')
  eq(his.length, 4, '版本历史列出全部 4 个版本')
  const v1row = his.find((r) => r[0].includes('v1'))
  check(v1row && v1row[2].includes('1.4') && v1row[3] === '未验证经验' && v1row[4] === '2025 年经验' && v1row[5] === '陈思雨' && v1row[6] === '林晓' && v1row[7] !== '—', `v1 历史行完整：${JSON.stringify(v1row)}`)

  // 额度标准：林晓通过后待CEO审批，周明远通过后才生效
  await page.goto(`${BASE}/rules/new`)
  root = page.locator('[data-page-id="PAGE-F12-02"]')
  await root.getByLabel('额度标准').check()
  await root.locator('#f-name').fill('新渠道月收入放量上限')
  await root.locator('#f-content').fill('起始后第 1–12 个月逐月上限 200,000.00 人民币/店铺/月')
  await root.getByLabel('未验证经验').check()
  await root.locator('#f-basis').fill('财务负责人估计')
  await root.getByRole('button', { name: '提交审批' }).click()
  await root.locator('#h-his').waitFor()
  const quotaId = Number(page.url().split('/rules/')[1])
  await as(page, '林晓')
  let q = await ruleDetail(page, quotaId)
  await approveUi(page, q.versions[0].id)
  root = await openRule(page, quotaId)
  his = await history(root)
  check(his[0][1] === '待CEO审批', `林晓通过后为「待CEO审批」：${his[0][1]}`)
  await as(page, '周明远')
  await approveUi(page, q.versions[0].id)
  root = await openRule(page, quotaId)
  his = await history(root)
  check(his[0][1] === '生效' && his[0][6].includes('周明远'), `周明远通过后才生效：${JSON.stringify(his[0])}`)
})
