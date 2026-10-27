// FLOW-32 Excel 导出（CMP-F14-01 / API-F14-01）：真实浏览器点击「导出 Excel」，校验下载文件名并解析 .xlsx：
// 表头列 = 页面当前显示列（含隐藏拆分列时同样不导出）；行范围按用户；金额与页面显示值逐格相同、保留 2 位小数。期望值取自契约 FLOW-32。
import { mkdirSync } from 'node:fs'
import { BASE, check, eq, loginAs, py, run } from './_e3_harness.mjs'

const OUT = '/tmp/e3_acc/downloads'
mkdirSync(OUT, { recursive: true })

/** 页面表格 → { header: 叶子表头, rows: 展开 colspan 后的单元格文字 } */
async function pageTable(locator) {
  return locator.evaluate((t) => {
    const grid = []
    const headRows = [...t.tHead.rows]
    headRows.forEach((tr, r) => {
      grid[r] = grid[r] || []
      let c = 0
      for (const cell of tr.cells) {
        while (grid[r][c] !== undefined) c++
        for (let dr = 0; dr < cell.rowSpan; dr++) {
          grid[r + dr] = grid[r + dr] || []
          for (let dc = 0; dc < cell.colSpan; dc++) grid[r + dr][c + dc] = { text: cell.textContent.trim(), leaf: dr === cell.rowSpan - 1 }
        }
        c += cell.colSpan
      }
    })
    const header = grid[grid.length - 1].map((x) => x.text)
    const rows = [...t.tBodies[0].rows].filter((tr) => !tr.classList.contains('detail')).map((tr) => {
      const out = []
      for (const cell of tr.cells) for (let i = 0; i < cell.colSpan; i++) out.push(cell.textContent.replace(/\s+/g, ' ').trim())
      return out
    })
    return { header, rows }
  })
}

function fmtCell(cell) {
  if (!cell || cell.v === null) return ''
  const f = cell.f || 'General'
  const n = Number(cell.v)
  if (f === 'General' || Number.isNaN(n)) return String(cell.v)
  const sec = f.split(';')[0]
  const dec = (sec.split('.')[1] || '').replace(/[^0]/g, '').length
  const pct = sec.includes('%')
  const val = pct ? n * 100 : n
  const abs = Math.abs(val).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec, useGrouping: sec.includes(',') })
  return `${val < 0 && Number(abs.replace(/,/g, '')) !== 0 ? '−' : ''}${abs}${pct ? '%' : ''}`
}

const NUM = /^[+−-]?(¥ )?[\d,]+(\.\d+)?%?$/
const norm = (s) => s.replace(/^\+/, '').replace(/^¥ /, '').replace(/^−¥ /, '−').replace(/^-/, '−')

/** 逐格比对：按首列名称对齐页面行与导出行，比较页面上的全部数值格 */
function compareRows(label, page, sheetRows, keyCols = 1) {
  const key = (r) => r.slice(0, keyCols).join('|')
  const byKey = new Map(sheetRows.map((r) => [key(r.map(fmtCell)), r]))
  let compared = 0
  const bad = []
  for (const pr of page.rows) {
    const sr = byKey.get(key(pr))
    if (!sr) continue
    pr.forEach((text, i) => {
      if (!NUM.test(text)) return
      compared++
      const got = fmtCell(sr[i])
      if (norm(got) !== norm(text)) bad.push(`${key(pr)}#${page.header[i]}: 页面 ${text} / 导出 ${got}`)
    })
  }
  check(compared > 0 && bad.length === 0, `${label}：导出金额与页面显示值逐格相同（比对 ${compared} 格${bad.length ? '；不一致 ' + bad.slice(0, 5).join('；') : ''}）`)
}

async function exportFrom(page, pageId, name) {
  const btn = page.locator(`[data-page-id="${pageId}"] [data-cmp="CMP-F14-01"]`).first()
  await btn.waitFor()
  const [dl] = await Promise.all([page.waitForEvent('download'), btn.click()])
  const file = `${OUT}/${name}-${dl.suggestedFilename()}`
  await dl.saveAs(file)
  const sheets = py('xlsx', file)
  return { filename: dl.suggestedFilename(), sheets }
}

const sheetBy = (sheets, title) => sheets.find((s) => s.title === title) ?? sheets[0]
const texts = (row) => row.map(fmtCell)

await run('FLOW-32', 'flow32', '2027-05-20 10:00', async (env) => {
  const page = await env.newPage()
  await loginAs(page, '林晓')

  // 公司汇总
  await page.goto(`${BASE}/reports/company`)
  await page.locator('[data-page-id="PAGE-F10-01"] [data-testid="kpi-original"]').waitFor()
  let ex = await exportFrom(page, 'PAGE-F10-01', 'linxiao-company')
  check(ex.filename.endsWith('.xlsx') && ex.filename.startsWith('公司汇总'), `公司汇总下载文件名：${ex.filename}`)
  let pt = await pageTable(page.locator('section[aria-labelledby="t-np"] table'))
  let sh = sheetBy(ex.sheets, '净利润')
  eq(texts(sh.rows[0]), pt.header, '公司汇总：表头列与页面一致')
  compareRows('公司汇总', pt, sh.rows.slice(1))

  // 渠道×站点偏差（2027-04）
  await page.goto(`${BASE}/reports/channel?month=2027-04`)
  const ct = page.locator('[data-testid="channel-table"]')
  await ct.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  ex = await exportFrom(page, 'PAGE-F10-02', 'linxiao-channel')
  eq(ex.filename, '渠道站点偏差_2027-04_最新调整后目标.xlsx', '渠道×站点偏差下载文件名')
  pt = await pageTable(ct)
  sh = sheetBy(ex.sheets, '渠道站点偏差')
  eq(texts(sh.rows[1]), pt.header, '渠道×站点偏差：表头列与页面当前显示列一致')
  const names = sh.rows.slice(2).map((r) => fmtCell(r[0]))
  console.log('  林晓导出行：', JSON.stringify(names))
  check(['Amazon-US-01', 'Amazon-CA-01', 'Ferguson', '未归属渠道'].every((n) => names.includes(n)) && names.includes('B 端（按客户）'), '林晓文件含全部店铺、B 端与未归属渠道行')
  compareRows('渠道×站点偏差', pt, sh.rows.slice(2))

  // BI 未到（2027-05）：页面隐藏拆分列，导出同样不含
  await page.goto(`${BASE}/reports/channel?month=2027-05`)
  await ct.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  ex = await exportFrom(page, 'PAGE-F10-02', 'linxiao-channel-05')
  pt = await pageTable(ct)
  sh = sheetBy(ex.sheets, '渠道站点偏差')
  eq(texts(sh.rows[1]), pt.header, '隐藏拆分列时导出表头同样不含拆分列')
  check(!texts(sh.rows[1]).includes('量差'), '2027-05 导出无量差等拆分列')

  // 品类报告
  await page.goto(`${BASE}/reports/category?month=2027-04`)
  const cat = page.locator('[data-testid="category-table"]')
  await cat.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  ex = await exportFrom(page, 'PAGE-F10-03', 'linxiao-category')
  eq(ex.filename, '品类新老品偏差_2027-04.xlsx', '品类报告下载文件名')
  pt = await pageTable(cat)
  sh = ex.sheets[0]
  eq(texts(sh.rows[1]), pt.header, '品类报告：表头列与页面一致')
  compareRows('品类报告', pt, sh.rows.slice(2), 2)

  // 部门费用报告
  await page.goto(`${BASE}/reports/dept`)
  const dt = page.locator('[data-testid="dept-table"]')
  await dt.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  ex = await exportFrom(page, 'PAGE-F10-04', 'linxiao-dept')
  check(ex.filename.startsWith('部门费用报告') && ex.filename.endsWith('.xlsx'), `部门费用报告下载文件名：${ex.filename}`)
  pt = await pageTable(dt)
  sh = ex.sheets[0]
  eq(texts(sh.rows[0]), pt.header, '部门费用报告：表头列与页面一致')
  const prow = pt.rows.find((r) => r.includes('培训费'))
  const srow = sh.rows.find((r) => texts(r).includes('培训费'))
  const pi = prow.indexOf('培训费')
  check(norm(fmtCell(srow[pi + 1])) === norm(prow[pi + 1]) && norm(fmtCell(srow[pi + 2])) === norm(prow[pi + 2]), `部门费用报告培训费金额与页面一致（${prow[pi + 1]} / ${prow[pi + 2]}）`)
  eq(fmtCell(srow[pi + 2]), '123,456.79', '累计实际 123,456.785 → 123,456.79（四舍五入 2 位）')

  // 预算表（PAGE-F04-02）
  const unit = env.seeded.unit
  await page.goto(`${BASE}/filling/platform/${unit}`)
  await page.locator('[data-page-id="PAGE-F04-02"] [data-cmp="CMP-F14-01"]').waitFor()
  await page.waitForTimeout(800)
  ex = await exportFrom(page, 'PAGE-F04-02', 'linxiao-budget')
  eq(ex.filename, '预算表_Amazon-US-01_2027 年度预算编制.xlsx', '预算表下载文件名')
  const grid = await (await page.request.get(`${BASE}/api/filling-units/${unit}/grid`)).json()
  sh = ex.sheets[0]
  eq(texts(sh.rows[0]), grid.columns.map((c) => c.label), '预算表：表头列与填报表格当前显示列一致')
  // RevoGrid 横向虚拟滚动：逐段滚动收集页面上实际渲染过的表头与单元格文字
  let domHeaders = ''
  for (const frac of [0, 0.5, 1]) {
    domHeaders += await page.locator('[data-page-id="PAGE-F04-02"] revo-grid').evaluate(async (g, f) => {
      for (const el of g.querySelectorAll('*')) if (el.scrollWidth > el.clientWidth + 5) el.scrollLeft = (el.scrollWidth - el.clientWidth) * f
      await new Promise((r) => setTimeout(r, 400))
      return g.textContent
    }, frac)
  }
  const missing = ['品类', '新/老品', '项目', '1 月', '12 月', '全年'].filter((h) => !domHeaders.includes(h))
  check(missing.length === 0, `填报表格页面显示同一组列${missing.length ? '（DOM 未见：' + missing.join('、') + '）' : ''}`)
  let compared = 0
  const badCells = []
  for (const row of grid.rows) {
    const v = row.values
    const sr = sh.rows.find((r) => fmtCell(r[0]) === v.category && (fmtCell(r[1]) === (v.is_new || '—')) && fmtCell(r[2]) === v.item)
    if (!sr) { badCells.push(`缺行 ${v.category}/${v.item}`); continue }
    grid.columns.slice(3).forEach((c, i) => {
      if (v[c.key] == null) return
      compared++
      if (fmtCell(sr[i + 3]) !== v[c.key]) badCells.push(`${v.category}/${v.item}/${c.label}: 页面 ${v[c.key]} / 导出 ${fmtCell(sr[i + 3])}`)
    })
  }
  check(compared > 0 && badCells.length === 0, `预算表逐格与页面相同（比对 ${compared} 格${badCells.length ? '；' + badCells.slice(0, 5).join('；') : ''}）`)
  check(domHeaders.includes('615,168.00'), '页面表格显示 4 月收入（人民币）615,168.00')

  // 王浩在渠道×站点偏差导出
  await page.context().clearCookies()
  await loginAs(page, '王浩')
  await page.goto(`${BASE}/reports/channel?month=2027-04`)
  await ct.locator('tbody tr').first().waitFor()
  await page.waitForTimeout(500)
  ex = await exportFrom(page, 'PAGE-F10-02', 'wanghao-channel')
  sh = sheetBy(ex.sheets, '渠道站点偏差')
  const wn = sh.rows.slice(2).map((r) => fmtCell(r[0]))
  console.log('  王浩导出行：', JSON.stringify(wn))
  eq(wn.filter((n) => !n.startsWith('合计')), ['Amazon-US-01'], '王浩文件只含 Amazon-US-01 行，不含其他店铺、B 端与未归属渠道')
  const detail = ex.sheets.find((s) => s.title === '明细')
  check(!!detail && detail.rows.slice(1).every((r) => fmtCell(r[0]) === 'Amazon-US-01'), '王浩明细表只含 Amazon-US-01')
  compareRows('王浩渠道×站点偏差', await pageTable(ct), sh.rows.slice(2))
})
