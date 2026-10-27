// FLOW-08 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-08。
// 前置（PAGE-F02-03：B端业务负责人取自角色与权限中的客户范围）：林晓在角色与权限把新客户分配给孙婷。
import { run, loginAs, BASE, check, eq } from './e1_harness.mjs'

const SIX = ['销售额（USD）', '退款率', '推广费用率', '其他运营费用率', '平台佣金率', '库存索赔率'].sort()

async function b2bCustomers(page) {
  await page.goto(`${BASE}/filling`)
  await page.waitForSelector('[data-unit] a')
  await page.locator('[data-unit] a').first().click()
  await page.waitForSelector('revo-grid .rgCell')
  return page.evaluate(async () => (await document.querySelector('revo-grid').getSource())
    .filter((r) => r.__rowKind === 'input').map((r) => [r.customer, r.item]))
}

await run('FLOW-08', 'default', async (env) => {
  const bp = await env.newPage()
  await loginAs(bp, '陈思雨')
  await bp.goto(`${BASE}/master/customers`)
  const add = async (dept, cur) => {
    await bp.getByRole('button', { name: '新增客户' }).first().click()
    await bp.locator('#cm-name').fill('Floor & Decor')
    await bp.locator('#cm-dept').selectOption({ label: dept })
    await bp.locator('#cm-cur').selectOption(cur)
    const resp = bp.waitForResponse((r) => r.url().endsWith('/api/master/b-customers') && r.request().method() === 'POST')
    await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
    return resp
  }
  eq((await add('美国业务部', 'USD')).status(), 201, '陈思雨新增 B 端客户 Floor & Decor（美国业务部、USD）')
  await bp.getByText('已新增客户 Floor & Decor，已加入美国业务部的 B端填报').waitFor()
  const dup = await add('外贸部', 'EUR')
  eq(dup.status(), 422, '重名客户保存被拒')
  await bp.getByRole('dialog').getByText('客户名称不能重复', { exact: false }).locator('xpath=.').first().waitFor()
  const errText = await bp.getByRole('dialog').locator('.field-error').first().innerText()
  eq(errText.trim(), '客户名称不能重复', '重名客户保存提示「客户名称不能重复」')
  await bp.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  eq(await bp.locator('tbody tr', { hasText: 'Floor & Decor' }).count(), 1, '重名不新增')

  const lin = await env.newPage()
  await loginAs(lin, '林晓')
  await lin.goto(`${BASE}/settings/roles`)
  await lin.locator('tr', { hasText: '孙婷' }).getByRole('button', { name: '分配' }).click()
  await lin.getByRole('dialog').locator('label', { hasText: 'Floor & Decor' }).locator('input').check()
  await lin.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await lin.getByRole('dialog').waitFor({ state: 'detached' })
  await lin.goto(`${BASE}/tasks`)
  await lin.locator('[data-publish]').click()
  await lin.locator('#p-year').selectOption('2027')
  await lin.locator('#p-dl').fill('2026-12-20')
  const modal = lin.getByRole('dialog')
  for (const fs of await modal.locator('fieldset').all()) {
    const all = fs.locator('legend input')
    const isB2b = (await fs.locator('legend').innerText()).includes('B')
      && (await fs.innerText()).includes('B端 · 美国业务部')
    if (!isB2b && await all.isChecked()) await all.uncheck()
  }
  await lin.locator('[data-publish-ok]').click()
  await lin.getByText('已发布「2027 年度预算编制」').waitFor()

  const sun = await env.newPage()
  await loginAs(sun, '孙婷')
  const rows = await b2bCustomers(sun)
  const fd = rows.filter(([c]) => c === 'Floor & Decor').map(([, i]) => i).sort()
  eq(fd, SIX, '美国业务部 B 端填报出现 Floor & Decor 客户组（6 个输入项）')
  const liu = await env.newPage()
  await loginAs(liu, '刘洋')
  const rows2 = await b2bCustomers(liu)
  check(rows2.length > 0 && rows2.every(([c]) => c !== 'Floor & Decor'), '外贸部 B 端填报不出现 Floor & Decor')
  check(!(await liu.locator('[data-page-id]').last().innerText()).includes('Floor & Decor'), '外贸部填报页面无 Floor & Decor 文字')
})
