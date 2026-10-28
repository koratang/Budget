// FLOW-36～40 业财分析浏览器验收 + DESIGN-31～39 截图（真实后端 8014、库 budget_acc4 基础种子，服务器无业财数据 → 示例数据）
import { BASE, chromium, check, finish, loginAs } from './e4_harness.mjs'

const OUT = process.env.VISUAL_DIR
const R = []
const browser = await chromium.launch()

async function session(userid) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await ctx.newPage()
  const errors = []
  page.on('pageerror', (e) => errors.push(String(e)))
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  await loginAs(page, userid)
  return { ctx, page, errors }
}
async function open(page, path) {
  await page.goto(BASE + path)
  await page.waitForSelector('.g5 .page-title')
  await page.waitForFunction(() => !document.querySelector('.g5 .skeleton'))
  await page.waitForTimeout(400)
}
const text = (page) => page.locator('main').innerText()
// 整页截图：视口拉到页面高度，固定侧栏随之延伸、当前菜单项可见；截完恢复 1280×900
async function shot(page, file) {
  const h = await page.evaluate(() => document.documentElement.scrollHeight)
  await page.setViewportSize({ width: 1280, height: Math.max(900, h) })
  await page.waitForTimeout(200)
  await page.screenshot({ path: file })
  await page.setViewportSize({ width: 1280, height: 900 })
}
const PAGES = [
  ['PAGE-F15-02', '/bizfin/finance'], ['PAGE-F15-03', '/bizfin/business'], ['PAGE-F15-05', '/bizfin/analysis/anaChannel'],
  ['PAGE-F15-06', '/bizfin/policy'], ['PAGE-F15-08', '/bizfin/keywork'], ['PAGE-F15-09', '/bizfin/data'],
]
const NAV6 = ['财务指标', '业务指标', '数据分析', '政策环境', '重点工作进度', '业财数据管理']
const REMOVED = ['经营总览驾驶舱', '业财联动关系', '经营建议']

// ---------- FLOW-38 口径 + DESIGN 截图（林晓，示例数据）----------
{
  const { ctx, page, errors } = await session('linxiao')
  for (const [pid, path] of PAGES) {
    await open(page, path)
    const t = await text(page)
    check(R, `FLOW-38 ${pid} 无 NaN / undefined`, !/NaN|undefined/.test(t))
    check(R, `FLOW-40 首次进入 ${pid} 显示「示例数据」标记`, (await page.locator('[data-demo-badge]').count()) === 1)
    const sw = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)
    check(R, `DESIGN ${pid} 1280 宽无页面级横向滚动`, sw)
    if (OUT) await shot(page, `${OUT}/${pid}.png`)
  }
  await open(page, '/bizfin/finance')
  const nav = await page.locator('aside').innerText()
  check(R, 'FLOW-36 林晓侧栏业财分析 6 项、无已删除模块', nav.includes('业财分析') && NAV6.every((n) => nav.includes(n)) && !REMOVED.some((n) => nav.includes(n)))
  for (const old of ['/bizfin/dashboard', '/bizfin/linkage', '/bizfin/advice']) {
    await page.goto(BASE + old)
    await page.waitForTimeout(800)
    check(R, `FLOW-36 旧链接 ${old} 回到首页`, new URL(page.url()).pathname === '/')
  }
  let t = ''
  await open(page, '/bizfin/finance')
  t = await text(page)
  // 可编辑项读输入框；派生项（如 F4.9）为只读文本
  const val = async (code) => {
    const inp = page.locator(`tr[data-code="${code}"] [data-f="actual"]`)
    if (await inp.count()) return inp.inputValue()
    return (await page.locator(`tr[data-code="${code}"] td.num`).first().innerText()).trim()
  }
  const f1 = await val('F1'); const ch = await Promise.all(['F1.1', 'F1.2', 'F1.3', 'F1.4', 'F1.5'].map(val))
  const mk = await Promise.all(['F1.6', 'F1.7', 'F1.8'].map(val))
  const sum = (a) => a.reduce((s, x) => s + Number(String(x).replace(/,/g, '')), 0)
  check(R, 'FLOW-38 F1 = 渠道Σ = 市场Σ = 9840', Number(f1.replace(/,/g, '')) === 9840 && Math.abs(sum(ch) - 9840) < 0.05 && Math.abs(sum(mk) - 9840) < 0.05, `${f1} ${sum(ch)} ${sum(mk)}`)
  const pairs = { F2: 3092.6, F3: 31.4, F4: 553.9, F5: 5.63, 'F4.9': 25.8 }
  for (const [c, v] of Object.entries(pairs)) {
    const got = Number((await val(c)).replace(/,/g, ''))
    check(R, `FLOW-38 ${c} = ${v}`, Math.abs(got - v) < 0.051, String(got))
  }
  await open(page, '/bizfin/data')
  const chk = page.locator('[data-checks]')
  const okN = await chk.locator('.chk.ok').count(); const allN = await chk.locator('.chk').count()
  check(R, 'FLOW-38 勾稽校验 10 项全部通过', okN === 10 && allN === 10, `ok=${okN} all=${allN}`)
  await open(page, '/bizfin/analysis/anaChannel')
  t = await text(page)
  check(R, 'FLOW-38 渠道效益贡献毛利合计 = 净利润（勾稽一致）', t.includes('勾稽一致') && t.includes('553.9'))
  if (OUT) {
    for (const id of ['anaTraffic', 'anaUser', 'anaOrder', 'anaCategory', 'anaLogiPre', 'anaLogiPost', 'anaWarehouse', 'anaAdmin']) {
      await open(page, `/bizfin/analysis/${id}`)
      check(R, `FLOW-38 数据分析 ${id} 无 NaN`, !/NaN|undefined/.test(await text(page)))
      await shot(page, `${OUT}/PAGE-F15-05-${id}.png`)
    }
  }
  // 维度切换
  await open(page, '/bizfin/finance')
  await page.getByRole('button', { name: '月度', exact: true }).click()
  await page.getByLabel('月份').selectOption('3')
  await page.waitForTimeout(300)
  t = await text(page)
  const f1m = await val('F1')
  check(R, 'FLOW-38 切到月度 3 月：期间与数值变化', t.includes('2026年 03月') && f1m.replace(/,/g, '') !== '9840', f1m)
  await page.getByRole('button', { name: '年度', exact: true }).click()
  await page.waitForTimeout(300)
  check(R, 'FLOW-38 切回年度恢复 9840', (await val('F1')).replace(/,/g, '') === '9840')
  check(R, 'FLOW-38 林晓全程无前端错误', errors.length === 0, errors.slice(0, 3).join(' | '))
  await ctx.close()
}

// ---------- FLOW-36 权限 ----------
{
  const { ctx, page } = await session('wanghao')
  await page.goto(BASE + '/')
  await page.waitForSelector('aside')
  check(R, 'FLOW-36 王浩侧栏无业财分析', !(await page.locator('aside').innerText()).includes('业财分析'))
  check(R, 'FLOW-36 王浩接口 403', (await page.request.get(BASE + '/api/bizfin/sections')).status() === 403)
  await ctx.close()
}
{
  const { ctx, page } = await session('zhoumingyuan')
  for (const [pid, path] of PAGES) {
    await open(page, path)
    const editable = await page.locator('main input:not([type=file]):not([aria-label*="搜索"]), main textarea, main select:not([aria-label="月份"])').count()
    const addBtn = await page.locator('main button', { hasText: /新增|删除|导入粘贴|恢复示例|清空/ }).count()
    check(R, `FLOW-36 周明远 ${pid} 无编辑控件`, editable === 0 && addBtn === 0, `inputs=${editable} btns=${addBtn}`)
  }
  const r = await page.request.put(BASE + '/api/bizfin/sections/policy', { data: { data: [], revision: null, is_demo: true } })
  check(R, 'FLOW-36 周明远保存 403', r.status() === 403)
  await ctx.close()
}

// ---------- FLOW-37 保存与冲突 / FLOW-39 事件 / FLOW-40 导入导出（陈思雨）----------
{
  const { ctx, page, errors } = await session('chensiyu')
  await open(page, '/bizfin/finance')
  const cell = page.locator('tr[data-code="F1.1"] [data-f="actual"]')
  await cell.fill('5200'); await cell.press('Enter'); await cell.blur()
  await page.waitForTimeout(1500)
  const sec = await (await page.request.get(BASE + '/api/bizfin/sections')).json()
  const f11 = sec.sections.indicators?.data.find((i) => i.code === 'F1.1')
  check(R, 'FLOW-37 F1.1 = 5200 已保存到服务器', !!f11 && Number(f11.actual) === 5200 && sec.sections.indicators.updated_by === '陈思雨', JSON.stringify(f11?.actual))

  // FLOW-39 政策事件新增 → 保存 → 刷新仍在
  await open(page, '/bizfin/policy')
  const n0 = await page.locator('tbody tr').count()
  await page.getByRole('button', { name: '＋ 新增事件' }).click()
  const last = page.locator('tbody tr').last()
  // 表格按时间排序：先填描述与影响，最后填时间（填时间后该行会移位）
  await last.getByLabel('事件描述').fill('美国对进口浴室柜加征 10% 关税'); await last.getByLabel('事件描述').blur()
  await last.getByLabel('事件影响').fill('毛利率下降约 1.2 个百分点'); await last.getByLabel('事件影响').blur()
  await last.getByLabel('时间').fill('2027-03-05'); await last.getByLabel('时间').blur()
  await page.waitForTimeout(1500)
  const polDbg = (await (await page.request.get(BASE + '/api/bizfin/sections')).json()).sections.policy
  await open(page, '/bizfin/policy')
  // 编辑态单元格是输入框，内容取输入值
  const descs = await page.locator('[aria-label="事件描述"]').evaluateAll((els) => els.map((e) => e.value))
  check(R, 'FLOW-39 新增政策事件刷新后仍在', (await page.locator('tbody tr').count()) === n0 + 1 && descs.includes('美国对进口浴室柜加征 10% 关税') && polDbg.data.some((e) => e.time === '2027-03-05'))
  await page.locator('tbody tr', { has: page.locator('input[value="2027-03-05"]') }).getByRole('button', { name: '删除' }).click()
  check(R, 'FLOW-39 删除需二次确认', (await page.getByRole('button', { name: '确认删除' }).count()) === 1 && (await page.locator('tbody tr').count()) === n0 + 1)
  await page.getByRole('button', { name: '确认删除' }).click()
  await page.waitForTimeout(1500)
  await open(page, '/bizfin/policy')
  check(R, 'FLOW-39 确认后删除并保存', (await page.locator('tbody tr').count()) === n0 && !(await page.locator('[aria-label="事件描述"]').evaluateAll((els) => els.map((e) => e.value))).includes('美国对进口浴室柜加征 10% 关税'))

  await open(page, '/bizfin/keywork')
  const total0 = await page.locator('[data-testid="count"]').innerText()
  await page.getByRole('button', { name: '＋ 新增工作' }).click()
  await page.waitForTimeout(300)
  const goal = page.getByLabel('工作目标').last()
  await goal.fill('Wayfair 美西新仓上线'); await goal.blur()
  const row = page.locator('tr', { has: page.locator('input[aria-label="工作目标"]').last() }).last()
  const prog = page.locator('input[aria-label="目前进度"]').last()
  await prog.fill('120'); await prog.blur()
  await page.waitForTimeout(1500)
  const kw = (await (await page.request.get(BASE + '/api/bizfin/sections')).json()).sections.keywork.data
  const mine = kw.find((k) => k.goal === 'Wayfair 美西新仓上线')
  check(R, 'FLOW-39 重点工作进度限制为 100 并保存', !!mine && Number(mine.progress) === 100, JSON.stringify(mine?.progress))
  check(R, 'FLOW-39 重点工作统计刷新', (await page.locator('[data-testid="count"]').innerText()) !== total0 && !!row)

  // FLOW-37 冲突：用旧版本号保存政策事件
  const pol = (await (await page.request.get(BASE + '/api/bizfin/sections')).json()).sections.policy
  const stale = await page.request.put(BASE + '/api/bizfin/sections/policy', { data: { data: pol.data, revision: pol.revision - 1, is_demo: true } })
  const body = await stale.json()
  check(R, 'FLOW-37 旧版本保存 409 并提示更新人', stale.status() === 409 && body.message === '「政策环境事件」已被陈思雨更新，请刷新后再改', body.message)

  // FLOW-40 导入
  await open(page, '/bizfin/data')
  await page.getByLabel('粘贴表格数据').fill('编码\t实际值\nF1.1\t5300\nF9.9\t100')
  await page.locator('[data-paste-import]').click()
  await page.waitForTimeout(1500)
  const t = await page.locator('body').innerText()
  check(R, 'FLOW-40 导入提示写入 1 条、未识别 1 条', t.includes('导入完成：成功更新 1 条指标，1 条未匹配到编码被跳过'), (t.match(/导入完成[^\n]*/) || [''])[0])
  const meta = (await (await page.request.get(BASE + '/api/bizfin/sections')).json()).sections
  check(R, 'FLOW-40 导入后指标与维度部分不再是示例数据', meta.indicators.is_demo === false && meta.biz_dim.is_demo === false && meta.policy.is_demo === false)
  await open(page, '/bizfin/finance')
  check(R, 'FLOW-40 财务指标页「示例数据」标记消失', (await page.locator('[data-demo-badge]').count()) === 0)
  await open(page, '/bizfin/analysis/anaTraffic')
  check(R, 'FLOW-40 推算子模块仍标示例数据', (await page.locator('[data-demo-badge]').count()) === 1)
  await open(page, '/bizfin/data')
  check(R, 'FLOW-40 保存记录表显示陈思雨', (await page.locator('[data-testid="save-meta"]').innerText()).includes('陈思雨'))
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /导出.*指标/ }).first().click()])
  const csv = await (await import('node:fs/promises')).readFile(await dl.path(), 'utf8')
  check(R, 'FLOW-40 导出指标 CSV 表头同原工作台', csv.replace(/^﻿/, '').startsWith('类型,') || csv.includes('编码'), csv.slice(0, 60))
  check(R, 'FLOW-40 陈思雨看不到恢复示例数据', (await page.locator('[data-reset]').count()) === 0)
  check(R, 'FLOW-40 陈思雨恢复接口 403', (await page.request.post(BASE + '/api/bizfin/reset')).status() === 403)
  check(R, 'FLOW-37/39/40 陈思雨全程无前端错误', errors.length === 0, errors.slice(0, 3).join(' | '))
  await ctx.close()
}

// ---------- FLOW-40 恢复示例数据（林晓）----------
{
  const { ctx, page } = await session('linxiao')
  await open(page, '/bizfin/data')
  await page.locator('[data-reset]').click()
  const dlg = page.locator('.el-message-box')
  await dlg.waitFor()
  check(R, 'FLOW-40 恢复前二次确认说明会清空服务器数据', (await dlg.innerText()).includes('服务器'))
  await dlg.getByRole('button', { name: /确定|恢复/ }).click()
  await page.waitForTimeout(1500)
  const sec = (await (await page.request.get(BASE + '/api/bizfin/sections')).json()).sections
  check(R, 'FLOW-40 恢复后服务器无已保存部分', Object.keys(sec).length === 0)
  await open(page, '/bizfin/finance')
  check(R, 'FLOW-40 恢复后重新显示示例数据', (await page.locator('[data-demo-badge]').count()) === 1 && (await page.locator('tr[data-code="F1.1"] [data-f="actual"]').inputValue()) !== '5,300')
  await ctx.close()
}

await browser.close()
finish(R)
