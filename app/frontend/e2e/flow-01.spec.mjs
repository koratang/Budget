// FLOW-01 浏览器 E2E（钉钉接口本地替身 8021）：期望值逐字取自 TDD验收契约 FLOW-01。
import { run, py, BASE, STUB, check, eq } from './e1_harness.mjs'

const NO_ROLE = '未开通预算权限，请联系财务负责人'
const DISABLED = '无法登录：钉钉账号已停用或不在企业通讯录中'
const LINK = '/reports/channel-site?month=2027-04'

async function scan(page, name) {
  await page.locator('button.qr').click()
  await page.waitForURL((u) => u.href.startsWith(STUB))
  await page.getByRole('link', { name: new RegExp(`^${name}（`) }).click()
}

await run('FLOW-01', 'default', async (env) => {
  // ① 王浩扫码进入
  let page = await env.newPage()
  await page.goto(`${BASE}/login`)
  check(await page.locator('input[type=password]').count() === 0, '登录页无密码输入框（无账号密码登录入口）')
  await scan(page, '王浩')
  await page.waitForURL(`${BASE}/`)
  await page.getByText('王浩').first().waitFor()
  const shell = await page.locator('body').innerText()
  check(shell.includes('王浩') && shell.includes('运营'), '工作台显示「王浩」与角色名称「运营」')
  const ck = (await page.context().cookies()).find((c) => c.name === 'budget_session')
  check(ck && ck.httpOnly === true, '建立 HttpOnly 会话 Cookie budget_session')

  // ② 赵一鸣无角色
  const p2 = await env.newPage()
  await p2.goto(`${BASE}/login`)
  await scan(p2, '赵一鸣')
  await p2.waitForURL((u) => u.pathname === '/login')
  await p2.getByText(NO_ROLE).waitFor()
  check(await p2.getByText(NO_ROLE).isVisible(), `赵一鸣停留在登录页并显示「${NO_ROLE}」`)
  check(!(await p2.context().cookies()).some((c) => c.name === 'budget_session'), '赵一鸣不建会话')

  // ③ 王浩已登录后在通讯录被停用 → 同步 → 下一次请求 401 → 回到登录页显示提示；再次扫码同样被拒
  await fetch(`${STUB}/_stub/users/wanghao`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ active: false }) })
  py('contact-sync')
  const r401 = page.waitForResponse((r) => r.url().includes('/api/') && r.status() === 401)
  await page.goto(`${BASE}/tasks`)
  check((await r401).status() === 401, '停用后下一次请求返回 401')
  await page.waitForURL((u) => u.pathname === '/login')
  await page.getByText(DISABLED).waitFor()
  check(await page.getByText(DISABLED).isVisible(), `回到登录页显示「${DISABLED}」`)
  await page.getByRole('button', { name: '换个账号扫码' }).click().catch(() => {})
  await page.goto(`${BASE}/login`)
  await scan(page, '王浩')
  await page.waitForURL((u) => u.pathname === '/login')
  await page.getByText(DISABLED).waitFor()
  check(await page.getByText(DISABLED).isVisible(), '再次扫码同样被拒')
  eq((await page.request.get(`${BASE}/api/me`)).status(), 401, '被拒后无有效会话（/api/me 401）')

  // ④ 通知链接未登录进入 → 登录后回到原链接（先恢复王浩在通讯录中的状态）
  await fetch(`${STUB}/_stub/users/wanghao`, { method: 'PATCH', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ active: true }) })
  py('contact-sync')
  page = await env.newPage()
  await page.goto(`${BASE}${LINK}`)
  await page.waitForURL((u) => u.pathname === '/login')
  eq(new URL(page.url()).searchParams.get('redirect'), LINK, '未登录跳登录页并携带原链接')
  await scan(page, '王浩')
  await page.waitForURL((u) => u.pathname !== '/login' && !u.href.startsWith(STUB))
  const u = new URL(page.url())
  eq(u.pathname + u.search, LINK, '登录后回到原链接')
  await page.waitForTimeout(1500)
  const pid = await page.locator('[data-page-id]').last().getAttribute('data-page-id').catch(() => null)
  eq(pid, 'PAGE-F10-02', '原链接打开渠道×站点偏差页面')
})
