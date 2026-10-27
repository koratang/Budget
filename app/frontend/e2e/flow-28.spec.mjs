// FLOW-28 偏差说明（PAGE-F10-02 / 03 / 04）：陈思雨填写，王浩、林晓、周明远查看；王浩无入口、接口 403。期望值逐字取自契约 FLOW-28。
import { BASE, check, eq, loginAs, run } from './_e3_harness.mjs'

const CHANNEL_NOTE = '4 月中旬断货 12 天，补货 4-28 到仓'
const CATEGORY_NOTE = '3 款框镜因包装认证延期上架'
const DEPT_NOTE = '4 月 KBIS 展会一次性支付'
const WHEN = '2027-05-12 10:30'

const REPORTS = {
  channel: { url: '/reports/channel?month=2027-04', page: 'PAGE-F10-02', row: (p) => p.locator('[data-testid="channel-table"] tbody tr', { hasText: 'Amazon-US-01' }).first() },
  category: { url: '/reports/category?month=2027-04', page: 'PAGE-F10-03', row: (p) => p.locator('[data-testid="category-table"] tbody tr').filter({ has: p.page().locator('td:nth-child(1)', { hasText: /^框镜$/ }) }).filter({ has: p.page().locator('td:nth-child(2)', { hasText: /^新品$/ }) }).first() },
  dept: { url: '/reports/dept', page: 'PAGE-F10-04', row: (p) => p.locator('[data-testid="dept-table"] tbody tr', { hasText: '展会费' }).first() },
}

async function open(page, key) {
  const r = REPORTS[key]
  await page.goto(`${BASE}${r.url}`)
  const root = page.locator(`[data-page-id="${r.page}"]`)
  await root.locator('table tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  return r.row(root)
}

await run('FLOW-28', 'flow28', WHEN, async (env) => {
  const page = await env.newPage()
  await loginAs(page, '陈思雨')
  const notes = { channel: CHANNEL_NOTE, category: CATEGORY_NOTE, dept: DEPT_NOTE }
  for (const key of ['channel', 'category', 'dept']) {
    const row = await open(page, key)
    await row.getByRole('button', { name: '填写说明' }).click()
    const dlg = page.getByRole('dialog')
    if (key === 'channel') {
      await dlg.getByRole('button', { name: '保存说明' }).click()
      eq((await dlg.locator('.field-error').textContent()).trim(), '请填写说明内容', '空内容保存提示「请填写说明内容」')
    }
    await dlg.getByLabel('偏差说明').fill(notes[key])
    await dlg.getByRole('button', { name: '保存说明' }).click()
    await dlg.waitFor({ state: 'detached' })
    const txt = await row.textContent()
    check(txt.includes(notes[key]) && txt.includes(`陈思雨 · ${WHEN}`), `陈思雨保存${key}说明：${txt.trim().slice(-60)}`)
  }

  for (const who of ['王浩', '林晓', '周明远']) {
    await page.context().clearCookies()
    await loginAs(page, who)
    const keys = who === '王浩' ? ['channel', 'category'] : ['channel', 'category', 'dept']
    for (const key of keys) {
      const row = await open(page, key)
      const txt = await row.textContent()
      check(txt.includes(notes[key]) && txt.includes(`陈思雨 · ${WHEN}`), `${who} 在${key}报告对应行看到说明、填写人「陈思雨」与填写时间`)
      eq(await row.getByRole('button', { name: '填写说明' }).count(), 0, `${who} 无「填写说明」入口（${key}）`)
      check(await row.getByRole('button', { name: '查看全文' }).count() === 1, `${who} 只能查看全文（${key}）`)
    }
  }
  // 王浩调用保存接口返回 403
  await page.context().clearCookies()
  await loginAs(page, '王浩')
  const ch = await (await page.request.get(`${BASE}/api/reports/channel-site?month=2027-04`)).json()
  const us = ch.rows.find((r) => r.name === 'Amazon-US-01')
  const r = await page.request.put(`${BASE}/api/variance-notes`, { data: { report_type: 'channel-site', month: '2027-04', object_type: 'store', object_key: String(us.store_id ?? us.id ?? ''), note: '王浩尝试修改' } })
  eq(r.status(), 403, '王浩调用保存接口返回 403')
  eq(await r.json(), { code: 'forbidden', message: '无权限' }, '403 响应只含错误信息')
})
