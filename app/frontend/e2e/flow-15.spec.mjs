// FLOW-15 浏览器 E2E（双会话）：王浩与刘畅同时打开 Amazon-US-01，刘畅 2026-12-18 10:05 保存 130，王浩随后保存 125 → 冲突提示、值保持 130；
// 王浩提交后状态「已提交」、「我的填报」入口变为「查看」，任何人写入被拒。期望值逐字取自 TDD验收契约.md FLOW-15。
import { setup, startSystem, setClock, as, gotoGrid, editCell, cellText, tryEdit, run, ok, eq } from './e2_lib.mjs'

const MAR = '2027-03'
await run('FLOW-15', async (browser) => {
  const s = setup('flow_15')
  await startSystem()
  await setClock('2026-12-18 10:00')
  const key = s.keys['浴室柜|new|avg_sales']
  const url = `/filling/platform/${s.unit}`

  const wang = await as(browser, s.users, 'wanghao')
  const liu = await as(browser, s.users, 'liuchang')
  await gotoGrid(wang, url)
  await gotoGrid(liu, url)

  await setClock('2026-12-18 10:05')
  eq((await editCell(liu, key, MAR, '130')).errors, [], '刘畅保存 130')
  await setClock('2026-12-18 10:07')
  const res = await editCell(wang, key, MAR, '125')
  eq(res.errors.map((e) => e.code), ['conflict'], '王浩保存被拒')
  const notice = wang.locator('[data-conflict]')
  await notice.waitFor()
  ok((await notice.innerText()).includes('该数据已被 刘畅 于 2026-12-18 10:05 修改，请刷新后再改'), `冲突提示：${await notice.innerText()}`)
  await notice.getByRole('button', { name: '刷新' }).click()
  await wang.waitForTimeout(800)
  ok(['130', '130.0'].includes(await cellText(wang, key, MAR)), '单元值保持 130')

  // 提交后锁定
  await wang.locator('[data-submit]').click()
  await Promise.all([wang.waitForResponse((r) => r.url().endsWith('/submit')), wang.locator('[data-confirm-submit]').click()])
  await wang.waitForTimeout(500)
  eq((await wang.locator('[data-unit-status]').innerText()).trim(), '已提交', '单位状态已提交')
  ok(!(await tryEdit(wang, key, MAR)), '提交后表格只读')
  await wang.goto('/filling')
  const entry = wang.locator('tr[data-unit="Amazon-US-01"] a')
  ok((await entry.innerText()).startsWith('查看'), `我的填报入口：${await entry.innerText()}`)

  for (const who of ['wanghao', 'chensiyu']) {
    const p = who === 'wanghao' ? wang : await as(browser, s.users, who)
    const g = await (await p.request.get(`/api/filling-units/${s.unit}/grid`)).json()
    const base = g.rows.find((r) => r.key === key).values[MAR]
    const r = await p.request.patch(`/api/filling-units/${s.unit}/cells`, { data: [{ row_key: key, field: MAR, value: '99', base }] })
    eq(r.status(), 409, `${who} 写入被拒`)
    eq((await r.json()).message, '已提交，退回后才能修改', `${who} 提示`)
  }
  await gotoGrid(wang, url)
  ok(['130', '130.0'].includes(await cellText(wang, key, MAR)), '数值不变')
  ok((await wang.locator('[data-locked]').innerText()).includes('已提交，内容已锁定'), '页面锁定提示')
})
