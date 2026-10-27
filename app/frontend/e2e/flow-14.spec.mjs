// FLOW-14 浏览器 E2E：王浩 / 蒋帆在填报页点「下载填报模板」并解析下载的 .xlsx；王浩上传含 3 处错误的模板 → 错误清单 3 条、页面与数据库不变；
// 修正后上传成功并刷新合计。期望值逐字取自 TDD验收契约.md FLOW-14。
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { setup, startSystem, setClock, as, gotoGrid, cellText, run, ok, eq, xlsx, dumpStore, gridRows } from './e2_lib.mjs'

const SCRATCH = process.env.E2_TMP || fs.mkdtempSync(path.join(os.tmpdir(), 'budget-e2-'))
const DRIVERS = ['SPU 数量', '单 SPU 平均销量', '平均单价（USD）', '折扣率（%）', '退款率（%）', '广告费率（%）', '佣金率（%）']

async function downloadTemplate(page, name) {
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: '下载填报模板' }).click()])
  const file = path.join(SCRATCH, `${Date.now()}_${name}.xlsx`)
  await dl.saveAs(file)
  return file
}
async function uploadFile(page, file) {
  const resp = page.waitForResponse((r) => r.url().includes('/template-upload'))
  await page.locator('input[type=file]').setInputFiles(file)
  return (await resp).json()
}

await run('FLOW-14', async (browser) => {
  const s = setup('flow_14')
  await startSystem()
  await setClock('2026-12-15 10:00')

  const wang = await as(browser, s.users, 'wanghao')
  await gotoGrid(wang, `/filling/platform/${s.unit}`)
  const file = await downloadTemplate(wang, 'amazon')
  const sheet = Object.values(xlsx(file).sheets)[0]
  eq(sheet[0], ['店铺', '站点', '品类', '新老品', '月份', ...DRIVERS], '王浩模板：维度 + 7 个驱动列')
  eq(new Set(sheet.slice(1).map((r) => r[0])), new Set(['Amazon-US-01']), '只含 Amazon-US-01')
  const hit = sheet.find((r) => r[2] === '浴室柜' && r[3] === '新品' && r[4] === '2027-03')
  ok(hit && hit[5] === '10' && hit[7] === '80.00', `已保存值预填（SPU 10、单价 80.00）：${JSON.stringify(hit)}`)

  const jiang = await as(browser, s.users, 'jiangfan')
  await gotoGrid(jiang, `/filling/logistics/${s.logistics}`)
  const lfile = await downloadTemplate(jiang, 'logistics')
  for (const [name, rows] of Object.entries(xlsx(lfile).sheets)) {
    const header = rows[0].map(String)
    eq(header.filter((h) => h.includes('率')), ['头程费率（%）', '尾程费率（%）', '仓储费率（%）', '关税率（%）'], `蒋帆模板 ${name} 只含四项比例列`)
    ok(!header.some((h) => /收入|销量|利润/.test(h)), `蒋帆模板 ${name} 无收入、销量、利润列`)
  }

  // 第 5 行 SPU 数量 −1、第 9 行折扣率 130、第 12 行店铺「Amazon-JP-01」，其余行合法（第 3 行改为合法新值）
  const before = dumpStore(s.store_id)
  const rowsBefore = JSON.stringify(await gridRows(wang))
  const bad = xlsx(file, 'F5=-1', 'I9=130', 'A12=Amazon-JP-01', 'F3=7', 'G3=5').saved
  const res = await uploadFile(wang, bad)
  eq(res.status, 'failed', '整份校验未通过')
  const modal = wang.locator('.modal, [role=dialog]').filter({ hasText: '校验未通过' })
  await modal.waitFor()
  const items = await modal.locator('li').allInnerTexts()
  eq(items.length, 3, `错误清单 3 条：${items.join(' | ')}`)
  ok(items[0].includes('第 5 行') && items[0].includes('SPU 数量'), items[0])
  ok(items.some((t) => t.includes('第 9 行') && t.includes('折扣率')), '第 9 行折扣率')
  ok(items.some((t) => t.includes('第 12 行') && t.includes('店铺') && t.includes('Amazon-JP-01')), '第 12 行店铺')
  ok(items.every((t) => t.split('·').length >= 3), '各含行号、字段与原因')
  await modal.getByRole('button', { name: '知道了' }).click()
  eq(dumpStore(s.store_id), before, '数据库值未变化')
  await gotoGrid(wang, `/filling/platform/${s.unit}`)
  const rowsAfter = await gridRows(wang)
  const diff = []
  for (const r of rowsAfter) {
    const b = JSON.parse(rowsBefore).find((x) => x.__rowKey === r.__rowKey)
    for (const k of Object.keys(r)) if (!b || b[k] !== r[k]) diff.push(`${r.__rowKey}.${k}: ${b?.[k]} → ${r[k]}`)
  }
  eq(diff, [], '页面数据未变化')

  // 修正后上传成功并刷新合计
  const m3 = sheet[2][4] // 第 3 行（Excel 行号）对应月份：SPU 7 × 平均销量 5 = 35
  const totalBefore = await cellText(wang, 'total|sales_qty', m3)
  const fixed = xlsx(file, 'F5=0', 'I9=0', 'F3=7', 'G3=5').saved
  const res2 = await uploadFile(wang, fixed)
  eq(res2.status, 'imported', '修正后上传成功')
  await wang.waitForTimeout(800)
  const totalAfter = await cellText(wang, 'total|sales_qty', m3)
  ok(totalAfter !== totalBefore && totalAfter === '35', `合计已刷新：${totalBefore} → ${totalAfter}`)
  ok(dumpStore(s.store_id).sha256 !== before.sha256, '数据库已写入')
})
