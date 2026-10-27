// FLOW-02 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-02（前置：年初原始目标 + 2027-04 金蝶实际）。
import { run, loginAs, BASE, check, eq } from './e1_harness.mjs'

const ALL_STORES = ['Amazon-US-01', 'Amazon-CA-01', 'Amazon-UK-01', 'Amazon-DE-01', 'Wayfair-US-01', 'HomeDepot-US-01',
  'Lowes-US-01', 'Lowes-US-02', 'Shopify-US-01', 'TikTok-US-01']
const CUSTOMERS = ['Ferguson', 'Menards', 'Bauhaus']

async function reportText(page) {
  await page.goto(`${BASE}/reports/channel?month=2027-04`)
  await page.locator('[data-testid="channel-table"]').waitFor()
  return page.locator('[data-testid="channel-table"]').innerText()
}

async function assignWang(page, stores) {
  await page.goto(`${BASE}/settings/roles`)
  const row = page.locator('tr', { hasText: '王浩' }).first()
  await row.getByRole('button', { name: '分配' }).click()
  const drawer = page.getByRole('dialog')
  await drawer.waitFor()
  for (const name of ALL_STORES) {
    const box = drawer.locator('.tree-shops label', { hasText: name }).locator('input')
    if ((await box.count()) === 0) continue
    const want = stores.includes(name)
    if ((await box.isChecked()) !== want) await box.click()
  }
  const resp = page.waitForResponse((r) => r.url().includes('/api/admin/users/') && r.request().method() === 'PUT')
  await drawer.getByRole('button', { name: '保存' }).click()
  return (await resp).status()
}

await run('FLOW-02', 'reports', async (env) => {
  const lin = await env.newPage()
  const wang = await env.newPage()
  await loginAs(lin, '林晓')
  await loginAs(wang, '王浩')
  eq(await assignWang(lin, ['Amazon-US-01']), 200, '林晓在角色与权限保存「运营 · 渠道/店铺范围 = Amazon-US-01」')
  let t = await reportText(wang)
  check(t.includes('Amazon-US-01') && !ALL_STORES.filter((s) => s !== 'Amazon-US-01').some((s) => t.includes(s)),
    '王浩第一次只见 Amazon-US-01 行')
  eq(await assignWang(lin, ['Amazon-US-01', 'Amazon-CA-01']), 200, '林晓把范围改为 Amazon-US-01、Amazon-CA-01')
  await wang.reload()
  await wang.locator('[data-testid="channel-table"]').waitFor()
  t = await wang.locator('[data-testid="channel-table"]').innerText()
  check(t.includes('Amazon-CA-01') && t.includes('Amazon-US-01') && !t.includes('Wayfair-US-01'),
    '王浩下一次请求即出现 Amazon-CA-01 行（未重新登录）')

  for (const who of ['陈思雨', '赵磊']) {
    const pg = await env.newPage()
    await loginAs(pg, who)
    await pg.goto(`${BASE}/settings/roles`)
    await pg.getByText('无权限').first().waitFor()
    check(await pg.getByText('无权限').first().isVisible(), `${who} 打开角色分配页面显示「无权限」`)
    const nav = await pg.locator('nav, aside').first().innerText()
    check(!nav.includes('角色与权限'), `${who} 侧栏无「角色与权限」菜单`)
    const r = await pg.request.put(`${BASE}/api/admin/users/1/roles`, { data: { roles: ['ceo'] } })
    eq([r.status(), await r.json()], [403, { code: 'forbidden', message: '无权限' }], `${who} 调用保存接口返回 403`)
  }

  // 林晓撤销自己唯一的财务负责人角色
  await lin.goto(`${BASE}/settings/roles`)
  await lin.locator('tr', { hasText: '林晓' }).first().getByRole('button', { name: '分配' }).click()
  const drawer = lin.getByRole('dialog')
  await drawer.getByRole('button', { name: '撤销全部角色' }).click()
  const resp = lin.waitForResponse((r) => r.url().includes('/api/admin/users/') && r.request().method() === 'PUT')
  await lin.getByRole('button', { name: '确认撤销' }).click()
  const rr = await resp
  eq([rr.status(), (await rr.json()).message], [409, '系统至少需要保留一名财务负责人'], '撤销最后一名财务负责人返回「系统至少需要保留一名财务负责人」')
  await lin.getByText('系统至少保留一位财务负责人').first().waitFor()
  check(await lin.getByText('系统至少保留一位财务负责人').first().isVisible(), '页面显示阻止提示（PAGE-F01-02 文案）')
  const me = await (await lin.request.get(`${BASE}/api/me`)).json()
  eq(me.roles, ['finance_head'], '林晓角色未被写入改动')

  for (const who of ['周明远', '林晓', '陈思雨']) {
    const pg = await env.newPage()
    await loginAs(pg, who)
    const text = await reportText(pg)
    const missing = [...ALL_STORES, ...CUSTOMERS, '未归属渠道'].filter((n) => !text.includes(n))
    eq(missing, [], `${who} 看到全部店铺、B 端客户与未归属渠道行`)
  }
})
