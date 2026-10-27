// FLOW-05 浏览器 E2E：期望值逐字取自 TDD验收契约 FLOW-05。
import { mkdirSync } from 'node:fs'
import { run, loginAs, BASE, check, eq, writeXlsx } from './e1_harness.mjs'

const DIR = '/tmp/e1_acc_files/flow05'
mkdirSync(DIR, { recursive: true })
const H = ['SKU', 'SPU 编码', '品类', '首次上架日期']

function rows(fixed) {
  const out = []
  for (let r = 2; r <= 210; r++) {
    if (r === 17) out.push(['FM-2416-BK', 'SPU-FM-2416', '框镜', '2026-03-15'])
    else if (r === 18) out.push(['FM-2416-WH', 'SPU-FM-2416', fixed ? '框镜' : null, '2026-04-02'])
    else if (r === 19) out.push(['MC-3026-GY', 'SPU-MC-3026', '镜柜', '2026-03-31'])
    else if (r === 203) out.push(['LM-4032-LED', 'SPU-LM-4032', '灯镜', fixed ? '2026-05-20' : null])
    else out.push([`BC-${String(r).padStart(4, '0')}-WH`, `SPU-BC-${String(Math.floor(r / 4)).padStart(3, '0')}`, '浴室柜', '2025-06-01'])
  }
  return out
}

async function verdict(page, month, spu) {
  await page.locator('#month').fill(month)
  await page.getByLabel('搜索 SKU 或 SPU 编码').fill(spu)
  await page.waitForResponse((r) => r.url().includes('/api/master/sku-mapping') && r.url().includes(encodeURIComponent(spu)) && r.url().includes(month))
  await page.waitForTimeout(300)
  const cells = await page.locator('tbody tr', { hasText: spu }).evaluateAll((trs) => trs.map((tr) => tr.lastElementChild.textContent.trim()))
  const set = [...new Set(cells)]
  return set.length === 1 ? set[0] : set.join('/')
}

await run('FLOW-05', 'default', async (env) => {
  const bp = await env.newPage()
  await loginAs(bp, '陈思雨')
  await bp.goto(`${BASE}/master/sku`)
  await bp.getByRole('button', { name: '上传对照表' }).first().click()
  await bp.locator('#sku-file').setInputFiles(writeXlsx(`${DIR}/SKU对照表_2027-05.xlsx`, H, rows(false)))
  const alert = bp.getByRole('dialog').getByRole('alert')
  await alert.getByText('校验未通过').waitFor()
  const list = await bp.getByRole('dialog').locator('tbody tr').evaluateAll((trs) => trs.map((tr) => {
    const td = tr.querySelectorAll('td'); return `${td[0].textContent.trim()} · ${td[2].textContent.trim()}`
  }))
  eq(list, ['18 · 缺少品类', '203 · 缺少首次上架日期'], '首次上传清单列出「18 · 缺少品类」「203 · 缺少首次上架日期」')
  check((await alert.innerText()).includes('整份文件未写入'), '提示整份文件未写入')
  await bp.getByRole('dialog').getByRole('button', { name: '取消' }).click()
  const api1 = await (await bp.request.get(`${BASE}/api/master/sku-mapping`)).json()
  eq(api1.summary.sku_count, 0, '对照表行数与上传前相同（0）')

  await bp.getByRole('button', { name: '上传对照表' }).first().click()
  await bp.locator('#sku-file').setInputFiles(writeXlsx(`${DIR}/SKU对照表_2027-05_修正.xlsx`, H, rows(true)))
  await bp.getByRole('button', { name: '确认写入' }).click()
  await bp.getByRole('button', { name: '确认写入' }).waitFor({ state: 'detached' })
  await bp.locator('#month').waitFor()
  const sum = await bp.locator('.summary').innerText()
  check(sum.includes('209'), `修正后写入成功：${sum.replace(/\s+/g, ' ')}`)
  eq(await verdict(bp, '2027-02', 'SPU-FM-2416'), '新品', 'SPU-FM-2416 在 2027-02 为新品')
  eq(await verdict(bp, '2027-03', 'SPU-FM-2416'), '老品', 'SPU-FM-2416 在 2027-03 为老品')
  const fm = await bp.locator('tbody tr', { hasText: 'SPU-FM-2416' }).first().innerText()
  check(fm.includes('2026-03-15'), 'SPU-FM-2416 首次上架日期 2026-03-15')
  eq(await verdict(bp, '2027-03', 'SPU-MC-3026'), '老品', 'SPU-MC-3026 在 2027-03 为老品')
  const mc = await bp.locator('tbody tr', { hasText: 'SPU-MC-3026' }).first().innerText()
  check(mc.includes('2026-03-31'), 'SPU-MC-3026 首次上架日期 2026-03-31')
})
