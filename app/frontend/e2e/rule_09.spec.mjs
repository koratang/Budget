// RULE-09 导入校验性能（NFR-002）：陈思雨在实际数导入页（PAGE-F09-01）依次上传 5 万行金蝶与 BI 文件（各一份合法版与末行
// 出错版），记录「上传完成 → 页面显示校验结果」耗时；同时读取 import_batch 的 uploaded_at → validated_at；校验期间另一用户
// （王浩）持续请求其他页面接口，记录状态与耗时。
// 前置：.venv/bin/python -m tests.acceptance.e4_env reset rule09；
//       .venv/bin/python -m tests.acceptance.e4_env gen09 <E4_OUT>/rule09；后端 8014（e4_server）已启动。
import { execFileSync } from 'node:child_process'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { chromium, BASE, loginAs, check, finish } from './e4_harness.mjs'

const OUT = process.env.E4_OUT || '/tmp/claude-0/-home-user/001a2709-c0f1-57ab-bb23-2c886d9a31b8/scratchpad'
const DIR = path.join(OUT, 'rule09')
const results = []
const browser = await chromium.launch()
const page = await (await browser.newContext({ viewport: { width: 1440, height: 1000 } })).newPage()
await loginAs(page, 'chensiyu')
const other = await (await browser.newContext()).newPage()
await loginAs(other, 'wanghao')

const cases = [
  ['kingdee', '金蝶月度', '金蝶_5万行_合法.xlsx', 'pass'],
  ['kingdee', '金蝶月度', '金蝶_5万行_末行出错.xlsx', 'fail'],
  ['bi', 'BI 双月', 'BI_5万行_合法.xlsx', 'pass'],
  ['bi', 'BI 双月', 'BI_5万行_末行出错.xlsx', 'fail'],
]
const report = []
for (const [, tabLabel, file, expect] of cases) {
  await page.goto(`${BASE}/actuals/import`)
  await page.locator('[data-page-id="PAGE-F09-01"] .tabs').waitFor()
  await page.getByRole('tab', { name: tabLabel, exact: true }).click()
  await page.waitForLoadState('networkidle')
  await page.waitForTimeout(500)
  // 以文件内容设置（本机 Playwright 对含中文的路径参数取不到文件）
  await page.locator('input[type="file"]').setInputFiles({ name: file, buffer: readFileSync(path.join(DIR, file)),
    mimeType: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
  const upResp = page.waitForResponse((r) => r.url().endsWith('/api/imports') && r.request().method() === 'POST',
    { timeout: 120000 })
  const tClick = Date.now()
  await page.getByRole('button', { name: '上传并校验' }).click()
  const resp = await upResp
  const tUploaded = Date.now()
  const batchId = (await resp.json()).id
  // 校验期间其他页面请求
  const probes = []
  let done = false
  const prober = (async () => {
    const urls = ['/api/workbench', '/api/filling-units', '/api/me', '/api/alerts']
    for (let k = 0; !done; k++) {
      const t = Date.now()
      const r = await other.request.get(`${BASE}${urls[k % urls.length]}`)
      probes.push({ url: urls[k % urls.length], status: r.status(), ms: Date.now() - t })
      await new Promise((res) => setTimeout(res, 300))
    }
  })()
  const sel = expect === 'pass' ? '#pass-t' : '#fail-t'
  await page.locator(sel).waitFor({ timeout: 120000 })
  const tShown = Date.now()
  done = true
  await prober
  const batch = await (await page.request.get(`${BASE}/api/imports/${batchId}`)).json()
  const db = execFileSync('psql', ['postgresql://budget:budget@127.0.0.1:5432/budget_acc4', '-Atc',
    `SELECT extract(epoch FROM validated_at - uploaded_at) FROM import_batch WHERE id = ${batchId}`], { encoding: 'utf8' }).trim()
  const rowsShown = expect === 'fail' ? await page.locator('section[aria-labelledby="fail-t"] tbody tr').allInnerTexts() : []
  const shownSec = (tShown - tUploaded) / 1000
  const maxProbe = Math.max(...probes.map((p) => p.ms))
  const badProbe = probes.filter((p) => p.status !== 200)
  report.push({ file, upload_request_s: (tUploaded - tClick) / 1000, shown_s: shownSec, db_s: Number(db),
    status: batch.status, issues: batch.issues.length, row_count: batch.row_count, rowsShown,
    probes: probes.length, probe_max_ms: maxProbe, probe_non200: badProbe.length })
  check(results, `${file}：上传完成 → 页面显示校验结果 ${shownSec.toFixed(1)} 秒 ≤ 60`, shownSec <= 60)
  check(results, `${file}：uploaded_at → validated_at ${Number(db).toFixed(1)} 秒 ≤ 60`, Number(db) <= 60)
  if (expect === 'pass') {
    check(results, `${file}：校验通过，5 万行`, batch.status === 'passed' && batch.row_count === 50000,
      `${batch.status} ${batch.row_count}`)
  } else {
    check(results, `${file}：出错版列出全部错误（末行第 50,001 行）`,
      batch.status === 'failed' && batch.issues.length === 1 && rowsShown.length === 1 && rowsShown[0].includes('50,001'),
      rowsShown.join(' | '))
  }
  check(results, `${file}：校验期间其他页面请求 ${probes.length} 次全部 200，最长 ${maxProbe} ms`,
    probes.length > 0 && badProbe.length === 0 && maxProbe < 3000)
  await page.screenshot({ path: path.join(OUT, `rule09_${file.replace(/\W+/g, '_')}.png`) })
}
writeFileSync(path.join(OUT, 'rule09_report.json'), JSON.stringify(report, null, 1))
console.log(JSON.stringify(report.map(({ rowsShown, ...r }) => r)))
await browser.close()
finish(results)
