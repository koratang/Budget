// FLOW-03 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-03（前置：3 部门、4 店铺、3 B 端客户的预算与实际 + 已发布编制任务）。
import { run, loginAs, BASE, check, eq } from './e1_harness.mjs'

const BAD_KEY = /revenue|sales|gross|收入|销量|毛利|profit|qty/i

function keysOf(o, out = new Set()) {
  if (Array.isArray(o)) o.forEach((v) => keysOf(v, out))
  else if (o && typeof o === 'object') for (const [k, v] of Object.entries(o)) { out.add(k); keysOf(v, out) }
  return out
}

async function pageText(page) {
  await page.waitForTimeout(800)
  return page.locator('[data-page-id]').last().innerText()
}

await run('FLOW-03', 'flow03', async (env) => {
  for (const who of ['吴静', '郑可']) {
    const pg = await env.newPage()
    await loginAs(pg, who)
    await pg.goto(`${BASE}/dept-expense`)
    await pg.waitForSelector('revo-grid .rgCell')
    const t = await pageText(pg)
    check(t.includes('人力资源部') && !t.includes('财务部') && !t.includes('市场部'), `${who} 部门费用填报只见人力资源部`)
    await pg.goto(`${BASE}/reports/dept?year=2027`)
    await pg.locator('[data-testid="dept-table"]').waitFor()
    const r = await pg.locator('[data-testid="dept-table"]').innerText()
    check(r.includes('人力资源部') && r.includes('合计（我的部门）') && !r.includes('财务部') && !r.includes('市场部'),
      `${who} 部门费用报告只见人力资源部行与「合计（我的部门）」`)
  }

  const wang = await env.newPage()
  await loginAs(wang, '王浩')
  await wang.goto(`${BASE}/filling`)
  await wang.waitForSelector('[data-unit]')
  eq(await wang.locator('[data-unit]').evaluateAll((els) => els.map((e) => e.getAttribute('data-unit'))), ['Amazon-US-01'], '王浩我的填报只有 Amazon-US-01')
  await wang.locator('[data-unit] a').first().click()
  await wang.waitForSelector('revo-grid .rgCell')
  let t = await pageText(wang)
  check(t.includes('Amazon-US-01') && !/Amazon-CA-01|Wayfair-US-01|Lowes-US-01/.test(t), '王浩填报页只见 Amazon-US-01')
  await wang.goto(`${BASE}/reports/channel?month=2027-04`)
  await wang.locator('[data-testid="channel-table"]').waitFor()
  t = await wang.locator('[data-testid="channel-table"]').innerText()
  check(t.includes('Amazon-US-01') && t.includes('合计') && !/Amazon-CA-01|Wayfair-US-01|Lowes-US-01|Ferguson|Menards|Bauhaus|未归属渠道/.test(t),
    '王浩渠道×站点偏差只见 Amazon-US-01 行及其合计')

  const sun = await env.newPage()
  await loginAs(sun, '孙婷')
  await sun.goto(`${BASE}/filling`)
  await sun.waitForSelector('[data-unit] a')
  await sun.locator('[data-unit] a').first().click()
  await sun.waitForSelector('revo-grid .rgCell')
  const custs = await sun.evaluate(async () => [...new Set((await document.querySelector('revo-grid').getSource())
    .filter((r) => r.__rowKind !== 'total').map((r) => r.customer).filter(Boolean))])
  eq(custs.sort(), ['Ferguson', 'Menards'], '孙婷 B 端填报只见 Ferguson、Menards（无 Bauhaus）')
  check(!(await pageText(sun)).includes('Bauhaus'), '孙婷 B 端填报页面无 Bauhaus')
  await sun.goto(`${BASE}/reports/channel?month=2027-04`)
  await sun.locator('[data-testid="channel-table"]').waitFor()
  t = await sun.locator('[data-testid="channel-table"]').innerText()
  check(t.includes('Ferguson') && t.includes('Menards') && !t.includes('Bauhaus'), '孙婷偏差报告只见 Ferguson、Menards')

  const jf = await env.newPage()
  await loginAs(jf, '蒋帆')
  await jf.goto(`${BASE}/filling`)
  await jf.waitForSelector('[data-unit] a')
  const gridResp = jf.waitForResponse((r) => /\/api\/filling-units\/\d+\/grid/.test(r.url()))
  await jf.locator('[data-unit] a').first().click()
  const body = await (await gridResp).json()
  await jf.waitForSelector('revo-grid .rgCell')
  const bad = [...keysOf(body)].filter((k) => BAD_KEY.test(k))
  eq(bad, [], '蒋帆填报数据接口响应 JSON 中不存在收入、销量、毛利字段键')
  const items = [...new Set(body.rows.map((r) => r.values.item))].sort()
  eq(items, ['仓储费率', '关税率', '头程费率', '尾程费率'].sort(), '接口只含头程费率、尾程费率、仓储费率、关税率四项')
  const cols = await jf.evaluate(async () => (await document.querySelector('revo-grid').getColumns()).map((c) => c.name))
  console.log('    物流页列：' + cols.join('、'))
  check(cols.every((c) => !/收入|销量|毛利/.test(c)), '蒋帆页面列只含维度列与比例月份列')
  const shownItems = await jf.evaluate(async () => [...new Set((await document.querySelector('revo-grid').getSource()).map((r) => r.item))])
  eq(shownItems.sort(), ['仓储费率', '关税率', '头程费率', '尾程费率'].sort(), '蒋帆页面只展示四项比例')
  const rest = (await pageText(jf)).replace('各项按人民币收入的百分比计算', '').replace('本页不显示收入、销量与利润', '')
  check(!/收入|销量|毛利/.test(rest), '蒋帆页面除说明文字外无收入、销量、毛利内容')
})
