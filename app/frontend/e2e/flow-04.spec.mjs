// FLOW-04 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-04。
import { mkdirSync } from 'node:fs'
import { run, loginAs, BASE, check, eq, writeXlsx } from './e1_harness.mjs'

const DIR = '/tmp/e1_acc_files/flow04'
mkdirSync(DIR, { recursive: true })
const KD_H = ['期间', '金蝶科目', '科目名称', '部门', '平台/店铺', '站点', '客户', '摘要', '发生额']
const BI_H = ['月份', '店铺', '站点', 'SKU', '销量', '本币销售额', '币种', '广告费', '平台费用']
const MONTHS = Array.from({ length: 13 }, (_, k) => { const d = new Date(Date.UTC(2027, 2 + k, 1)); return d.toISOString().slice(0, 7) })

async function upload(page, tabLabel, file) {
  await page.goto(`${BASE}/actuals/import`)
  await page.getByRole('tab', { name: tabLabel }).click()
  await page.locator('input[type=file][aria-label="选择 Excel 文件"]').setInputFiles(file)
  await page.getByRole('button', { name: '上传并校验' }).click()
  const ok = page.getByRole('button', { name: /^确认(覆盖)?导入$/ })
  const bad = page.getByText('校验未通过')
  await Promise.race([ok.waitFor({ timeout: 60000 }), bad.waitFor({ timeout: 60000 })])
  if (await bad.isVisible()) return { passed: false, text: await page.locator('[data-page-id]').innerText() }
  const text = await page.locator('[data-page-id]').innerText()
  await ok.click()
  await page.getByText(/已导入|导入成功|已生效/).first().waitFor({ timeout: 30000 })
  return { passed: true, text }
}

await run('FLOW-04', 'default', async (env) => {
  const bp = await env.newPage()
  await loginAs(bp, '陈思雨')
  await bp.goto(`${BASE}/master/stores`)
  await bp.getByRole('button', { name: '新增店铺' }).click()
  const fillStore = async () => {
    await bp.locator('#s-ch').selectOption({ label: 'Wayfair' })
    await bp.locator('#s-name').fill('Wayfair-CA-01')
    await bp.locator('#s-site').selectOption({ label: '加拿大' })
    await bp.locator('#s-cur').selectOption('CAD')
    await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  }
  await fillStore()
  await bp.getByText('已新增店铺 Wayfair-CA-01').waitFor()
  await bp.locator('tbody tr', { hasText: 'Wayfair-CA-01' }).waitFor()
  check(await bp.locator('tbody tr', { hasText: 'Wayfair-CA-01' }).count() === 1, '陈思雨新增店铺 Wayfair-CA-01（渠道 Wayfair、站点加拿大、CAD）')
  await bp.getByRole('button', { name: '新增店铺' }).click()
  await fillStore()
  await bp.getByText('店铺名称已存在').first().waitFor()
  check(await bp.getByText('店铺名称已存在').first().isVisible(), '同名保存提示「店铺名称已存在」')
  await bp.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  eq(await bp.locator('tbody tr', { hasText: 'Wayfair-CA-01' }).count(), 1, '同名不新增')
  // 停用 Lowes-US-02
  await bp.locator('tr', { hasText: 'Lowes-US-02' }).getByRole('button', { name: '编辑' }).click()
  await bp.getByRole('dialog').getByLabel('停用').check()
  await bp.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  const confirmBtn = bp.getByRole('button', { name: '确认停用' })
  if (await confirmBtn.isVisible().catch(() => false)) await confirmBtn.click()
  await bp.getByText('已保存 Lowes-US-02').waitFor()
  await bp.locator('tbody tr.off', { hasText: 'Lowes-US-02' }).waitFor()
  check((await bp.locator('tr', { hasText: 'Lowes-US-02' }).innerText()).includes('停用'), 'Lowes-US-02 已停用')
  check(await bp.getByRole('button', { name: '设置新渠道' }).count() === 0 && await bp.getByRole('button', { name: '渠道标记' }).count() === 0,
    '财务BP 视角看不到新渠道标记控件')

  // 林晓：把 Wayfair-CA-01 加入运营黄子轩范围后发布编制任务
  const lin = await env.newPage()
  await loginAs(lin, '林晓')
  await lin.goto(`${BASE}/settings/roles`)
  await lin.locator('tr', { hasText: '黄子轩' }).getByRole('button', { name: '分配' }).click()
  await lin.getByRole('dialog').locator('.tree-shops label', { hasText: 'Wayfair-CA-01' }).locator('input').check()
  await lin.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await lin.getByRole('dialog').waitFor({ state: 'detached' })
  await lin.goto(`${BASE}/tasks`)
  await lin.locator('[data-publish]').click()
  await lin.locator('#p-year').selectOption('2027')
  await lin.locator('#p-dl').fill('2026-12-20')
  const modal = lin.getByRole('dialog')
  const platformText = await modal.locator('fieldset', { hasText: '平台渠道' }).innerText()
  check(platformText.includes('Wayfair-CA-01') && !platformText.includes('Lowes-US-02'), '发布弹窗平台渠道单位含 Wayfair-CA-01、不含停用的 Lowes-US-02')
  const deptGroup = modal.locator('fieldset', { hasText: '人力资源部' })
  await deptGroup.locator('legend input').uncheck()
  await deptGroup.locator('label', { hasText: '人力资源部' }).locator('input').check()
  await lin.locator('[data-publish-ok]').click()
  await lin.getByText('已发布「2027 年度预算编制」').waitFor()
  const taskId = (await lin.getByRole('link', { name: '查看进度' }).first().getAttribute('href')).split('/').pop()
  await lin.goto(`${BASE}/tasks/${taskId}`)
  await lin.waitForSelector('[data-unit]')
  const units = await lin.locator('[data-unit]').evaluateAll((els) => els.map((e) => e.getAttribute('data-unit')))
  check(units.includes('Wayfair-CA-01') && !units.includes('Lowes-US-02'), '编制任务生成的平台渠道单位含 Wayfair-CA-01、停用店铺不生成填报单位')

  const hz = await env.newPage()
  await loginAs(hz, '黄子轩')
  await hz.goto(`${BASE}/filling`)
  await hz.waitForSelector('[data-unit] a')
  await hz.locator('[data-unit] a').first().click()
  const sw = hz.getByLabel('切换填报单位（仅显示你负责的店铺）')
  await sw.waitFor()
  const opts = await sw.locator('option').allInnerTexts()
  check(opts.includes('Wayfair-CA-01') && !opts.includes('Lowes-US-02'), `填报店铺切换下拉含 Wayfair-CA-01、不列停用店铺：${opts.join('、')}`)

  // SKU 对照表（BI 导入前置）+ 导入含 Lowes-US-02 / Wayfair-CA-01 行的金蝶与 BI 文件
  await bp.goto(`${BASE}/master/sku`)
  await bp.getByRole('button', { name: '上传对照表' }).first().click()
  await bp.locator('#sku-file').setInputFiles(writeXlsx(`${DIR}/SKU对照表.xlsx`, ['SKU', 'SPU 编码', '品类', '首次上架日期'], [['BC-2201-WH', 'SPU-BC-2201', '浴室柜', '2025-06-01']]))
  await bp.getByRole('button', { name: '确认写入' }).click()
  await bp.getByRole('button', { name: '确认写入' }).waitFor({ state: 'detached' })
  const kd = await upload(bp, '金蝶月度', writeXlsx(`${DIR}/金蝶_2027-04_利润表.xlsx`, KD_H, [
    ['2027-04', '6001', '主营业务收入', '运营部', 'Lowes-US-02', 'US', '', '', 32000],
    ['2027-04', '6001', '主营业务收入', '运营部', 'Wayfair-CA-01', 'CA', '', '', 18000],
    ...MONTHS.map((m) => [m, '6001', '主营业务收入', '运营部', 'TikTok-US-01', 'US', '', '', 5000]),
  ]))
  check(kd.passed && !kd.text.includes('店铺不在主数据'), '金蝶文件含 Lowes-US-02、Wayfair-CA-01 行校验通过并导入')
  const bi = await upload(bp, 'BI 双月', writeXlsx(`${DIR}/BI_2027-04_销售明细.xlsx`, BI_H, [
    ['2027-04', 'Lowes-US-02', 'US', 'BC-2201-WH', 40, 4800, 'USD', 300, 600],
    ['2027-04', 'Wayfair-CA-01', 'CA', 'BC-2201-WH', 10, 2500, 'CAD', 100, 200],
  ]))
  check(bi.passed && !bi.text.includes('店铺不在主数据'), 'BI 文件含 Lowes-US-02、Wayfair-CA-01 行校验通过并导入')
  const rep = await (await lin.request.get(`${BASE}/api/reports/channel-site?month=2027-04`)).json()
  const names = rep.rows.map((r) => r.name)
  check(names.includes('Lowes-US-02') && names.includes('Wayfair-CA-01'), '停用店铺与新店铺的实际已入库（偏差报告出现其行）')

  // 林晓标记 TikTok-US-01 新渠道（起始 2027-03）
  await lin.goto(`${BASE}/master/stores`)
  await lin.locator('tr', { hasText: 'TikTok-US-01' }).getByRole('button', { name: '设置新渠道' }).click()
  await lin.getByRole('dialog').getByLabel('标记为新渠道').check()
  await lin.locator('#s-start').fill('2027-03')
  await lin.getByRole('dialog').getByRole('button', { name: '保存' }).click()
  await lin.getByText('TikTok-US-01 已标记为新渠道，2027-03 起 12 个月').waitFor()
  await lin.locator('tr', { hasText: 'TikTok-US-01' }).getByText('2027-03 起按新渠道处理').waitFor()
  const tkRow = await lin.locator('tr', { hasText: 'TikTok-US-01' }).innerText()
  check(tkRow.includes('2027-03 起按新渠道处理'), `渠道与店铺页（当前月 2026-10，起始月之前）显示：${tkRow.replace(/\s+/g, ' ')}`)
  const badges = []
  for (const m of MONTHS) {
    await lin.goto(`${BASE}/reports/channel?month=${m}`)
    await lin.locator('[data-testid="channel-table"]').waitFor()
    const row = lin.locator('[data-testid="channel-table"] tr', { hasText: 'TikTok-US-01' }).first()
    badges.push(`${m}:${(await row.innerText()).includes('新渠道') ? '新渠道' : '常规'}`)
  }
  eq(badges, MONTHS.map((m) => `${m}:${m === '2028-03' ? '常规' : '新渠道'}`), 'TikTok-US-01 在 2027-03 至 2028-02 各月显示「新渠道」徽章，2028-03 起为常规渠道')
})
