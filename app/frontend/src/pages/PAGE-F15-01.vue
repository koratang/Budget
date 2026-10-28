<script setup lang="ts">
/**
 * 经营总览驾驶舱 PAGE-F15-01：由原工作台 viewDashboard（含 kpiCard / momYoyCell / blkBiz）原样移植。
 * 全部数字由引擎按当前维度（年度累计 / 月度）实时计算，切换维度后自动刷新。
 */
import { computed } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import { comboChart, donutChart, lineChart, txt } from '@/bizfin/charts'
import {
  C, MONTHS9, NAV, PAL, S, deptOf, find, fmt, hasData, jsNum, l2, momYoyOf, pct, rate, rateText, validations,
  type Indicator,
} from '@/bizfin/engine'

const desc = NAV.find((n) => n.id === 'dashboard')?.sub

/** 取指标；示例与正式数据都含这些编码，缺失说明数据损坏，直接报错 */
function need(code: string): Indicator {
  const i = find(code)
  if (!i) throw new Error('缺少指标 ' + code)
  return i
}

/** 达成率分档（同原 healthColor：≥100 优、≥90 良、≥80 预警、其余不达标） */
function tier(r: number): string {
  return r >= 100 ? 't-good' : r >= 90 ? 't-info' : r >= 80 ? 't-warn' : 't-bad'
}

/* ---------- KPI 卡（原 kpiCard / momYoyCell） ---------- */
interface Delta { lab: string; text: string; cls: string }
function deltaOf(ind: Indicator, v: number | null, lab: string): Delta {
  if (v === null || isNaN(v)) return { lab, text: lab + ' —', cls: 'muted' }
  const good = ind.dir === 1 ? v >= 0 : v <= 0
  /* 原工具：有利变动标红（up）、不利标绿（down） */
  return { lab, text: lab + ' ' + (v >= 0 ? '+' : '') + fmt(v, 1) + '%', cls: good ? 'up' : 'down' }
}
interface Kpi { label: string; ind: Indicator; blank: boolean; cls: string; val: string; deltas: Delta[] }
function kpiCard(label: string, ind: Indicator, dec: number): Kpi {
  const blank = !hasData(ind)
  const r = rate(ind)
  const cls = blank ? '' : (r >= 100 ? 'good' : r >= 90 ? '' : r >= 80 ? 'warn' : 'bad')
  const my = blank ? { mom: null, yoy: null } : momYoyOf(ind)
  return {
    label, ind, blank, cls,
    val: blank ? '—' : fmt(ind.actual, dec),
    deltas: blank ? [] : [deltaOf(ind, my.mom, '环比'), deltaOf(ind, my.yoy, '同比')],
  }
}

/* 业务指标占位文本：已填报则显示实际值，未填报显示「待填报」 */
function blkBiz(code: string): string {
  const i = find(code)
  if (!i) return '指标缺失'
  if (!hasData(i)) return '待填报'
  return '实际 ' + fmt(i.actual) + ' ' + i.unit + ' / 目标 ' + fmt(i.target) + ' ' + i.unit
}

const CH_CODES = ['F1.1', 'F1.2', 'F1.3', 'F1.4', 'F1.5']

/** 带符号金额文本（正数补「+」，负数自带「−」） */
const signed = (n: number, d: number): string => (n >= 0 ? '+' : '') + fmt(n, d)
/** 涨红跌绿：正 = up（红）、负 = down（绿），与指标好坏无关 */
const toneOf = (n: number): string => n > 0 ? 'up' : n < 0 ? 'down' : ''

/* ---------- 渠道毛利率小图 ----------
   viewBox 宽 480（原 640）：半宽卡片里按约 1:1 缩放，字号与页面其他图一致，不再缩到约 7px。
   lineChart 的 endLabel 会给每条线各标一次末值，多条线数值相同时标签叠成一团；
   这里关掉 endLabel，按末值（1 位小数）分组，每组只在末点上方标一次。
   坐标与 lineChart（endLabel=false）同口径：pad 左 56 右 20 上 20 下 40，纵轴 [min − 20%·跨度, max + 26%·跨度] */
const GM_W = 480, GM_H = 290
interface GmSeries { name: string; color: string; values: number[] }
interface GmGroup { names: string[]; color: string; last: number; text: string; whole: boolean }
function gmGroups(series: GmSeries[]): GmGroup[] {
  const map = new Map<string, GmSeries[]>()
  series.forEach((s) => {
    const k = fmt(s.values[s.values.length - 1], 1)
    map.set(k, (map.get(k) || []).concat(s))
  })
  return [...map.entries()].map(([k, list]) => ({
    names: list.map((s) => s.name),
    color: list.length > 1 ? C.text2 : list[0].color,
    last: list[0].values[list[0].values.length - 1],
    text: k + '%' + (list.length > 1 ? '（' + list.length + ' 线重合）' : ''),
    /* 整段曲线逐月相同 → 完全重合 */
    whole: list.every((s) => s.values.every((v, i) => fmt(v, 1) === fmt(list[0].values[i], 1))),
  }))
}
function gmChartSvg(labels: string[], series: GmSeries[], groups: GmGroup[]): string {
  const base = lineChart(labels, series, { w: GM_W, h: GM_H, dec: 1 })
  const all = series.flatMap((s) => s.values)
  if (!all.length) return base
  const mn = Math.min(...all), mx = Math.max(...all)
  const sp = (mx - mn) || Math.abs(mx) || 1
  const lo = mn - sp * 0.20, hi = mx + sp * 0.26
  const ih = GM_H - 20 - 40
  const Y = (v: number): number => 20 + ih - ih * (v - lo) / ((hi - lo) || 1)
  /* 末点上方 9px 起标；相邻两组标签小于 13px 时依次上推，避免互相压住 */
  const pos = groups.map((g) => ({ g, y: Y(g.last) - 9 })).sort((a, b) => b.y - a.y)
  for (let i = 1; i < pos.length; i++) if (pos[i - 1].y - pos[i].y < 13) pos[i].y = pos[i - 1].y - 13
  const labelsSvg = pos.map((p) => txt(GM_W - 20, Math.max(12, p.y), p.g.text, { anchor: 'end', size: 10.5, weight: 700, fill: p.g.color })).join('')
  const at = base.lastIndexOf('</svg>')
  return base.slice(0, at) + labelsSvg + base.slice(at)
}

const v = computed(() => {
  const rev = need('F1'), gm = need('F3'), net = need('F4'), cf = need('F7')
  const inv = need('F7.6'), f41 = need('F4.1')
  const revA = jsNum(rev.actual)

  /* 业务指标未填报时（达成率无意义）不计入预警，避免整屏「0%」噪音 */
  const highRisk = l2('fin').concat(l2('biz'))
    .filter((i) => hasData(i) && i.target && rate(i) < 80)
    .sort((a, b) => rate(a) - rate(b))

  const chItems = CH_CODES.map((c, idx) => {
    const i = need(c)
    return { label: i.name.replace(' 渠道收入', '').replace('渠道收入', '').replace('收入', ''), value: jsNum(i.actual), color: PAL[idx] }
  })
  const share = (x: number): number => x / (revA || 1) * 100

  /* 月度趋势（本年 1 月至当月） */
  const mN = Math.max(2, Math.min(S.curM || 9, 9))
  const yMonths = MONTHS9.slice(0, mN)
  const maOf = (c: string): number[] => {
    const i = find(c)
    if (!i || !i._ma) return yMonths.map(() => 0)
    return i._ma.slice(0, mN)
  }
  const yRev = maOf('F1'), yGross = maOf('F3'), yNet = maOf('F5')

  /* 渠道毛利率序列（F3.1-F3.5 与 F1.1-F1.5 渠道一一对应） */
  const gmSeries = CH_CODES.map((c, idx) => {
    const i = find('F3.' + (idx + 1))
    const ch = find(c)
    return { name: ch ? ch.name : ('F3.' + (idx + 1)), color: PAL[idx], values: (i && i._ma) ? i._ma.slice(0, mN) : yMonths.map(() => 0) }
  })
  const gmLast = gmSeries.map((s) => s.values[s.values.length - 1])
  const gmG = gmGroups(gmSeries)
  const bestIdx = gmLast.indexOf(Math.max(...gmLast))
  const worstIdx = gmLast.indexOf(Math.min(...gmLast))

  const f41A = jsNum(f41.actual), f41T = jsNum(f41.target)
  const gmA = jsNum(gm.actual), gmT = jsNum(gm.target)
  const invA = jsNum(inv.actual), invT = jsNum(inv.target)
  const chain = [
    /* --- 财务口径链（真实数字，随时可算） --- */
    /* 结果金额按涨红跌绿着色（正数红、负数绿），与全站口径一致 */
    { b: '销售费用率↓（' + pct(f41.actual) + ' → ' + pct(f41.target) + '）', m: '期间费用率 ' + fmt(f41A - f41T, 1) + 'pt',
      f: '净利润 ' + signed(revA * (f41A - f41T) / 100, 0) + ' 万元', tone: toneOf(revA * (f41A - f41T) / 100) },
    { b: '毛利率↑（' + pct(gm.actual) + ' → ' + pct(gm.target) + '）', m: '毛利额 ' + fmt(gmT - gmA, 1) + 'pt',
      f: '毛利额 ' + signed(revA * (gmT - gmA) / 100, 0) + ' 万元', tone: toneOf(revA * (gmT - gmA) / 100) },
    { b: '存货周转天数↓（' + fmt(inv.actual, 0) + ' → ' + fmt(inv.target, 0) + ' 天）', m: '释放占用资金 ' + fmt(Math.max(0, invA - invT), 0) + ' 天',
      f: '经营现金流 ' + signed(Math.max(0, invA - invT) * revA * 0.67 / 365, 0) + ' 万元', tone: toneOf(Math.max(0, invA - invT) * revA * 0.67 / 365) },
    /* --- 业务口径链（分维度数据填报后自动出数） --- */
    { b: '品效↑ / 单位广告成本↓（营销板块 ' + blkBiz('S1.5') + '）', m: '按投放费用 = 归因销售额 62% ÷ 品效 测算',
      f: '营销费用率 ' + fmt(f41.actual || 0, 2) + 'pt 由 F4.1 直接取数，品效提升直接压降该池', tone: '' },
    { b: '降本率↑（供应链板块 ' + blkBiz('S3.3') + '）', m: '采购降本 1pt 近似等额转毛利',
      f: '按营业成本占收入 67% 测算，每 1pt 降幅 ≈ 毛利 +' + fmt(revA * 0.67 / 100, 0) + ' 万元', tone: '' },
    { b: '有货率↑（仓配履约板块 ' + blkBiz('S4.8') + '）', m: '断货销售机会损失减少',
      f: '按每 1pt 有货率 ≈ 收入 ' + fmt(revA / 100 * 0.5, 0) + ' 万元 估算', tone: '' },
  ]

  return {
    kpis: [kpiCard('营业收入', rev, 0), kpiCard('毛利率', gm, 1), kpiCard('净利润', net, 1), kpiCard('经营性现金流净额', cf, 0)],
    yMonths, mN,
    combo: comboChart(yMonths, yRev, [{ color: C.fin, values: yGross }, { color: '#7c3aed', values: yNet }], { h: 290 }),
    revMin: fmt(Math.min(...yRev), 0), revMax: fmt(Math.max(...yRev), 0),
    grossMin: pct(Math.min(...yGross)), grossMax: pct(Math.max(...yGross)),
    grossDelta: (yGross[mN - 1] - yGross[0] >= 0 ? '+' : '') + fmt(yGross[mN - 1] - yGross[0], 1),
    netLast: pct(yNet[mN - 1]),
    donut: donutChart(chItems.map((c) => ({ label: c.label, value: c.value, color: c.color })), { size: 196, centerTop: '总收入', centerVal: fmt(rev.actual, 0) }),
    chRows: chItems.map((c) => ({ label: c.label, color: c.color, share: fmt(share(c.value), 1) + '%' })),
    amazonShare: fmt(share(chItems[0].value), 1), cr1: pct(share(chItems[0].value), 1),
    gmChart: gmChartSvg(yMonths, gmSeries, gmG),
    gmSeries,
    /* 重合说明：如「Amazon / Wayfair / HomeDepot / Lowe's 均为 29.2%」 */
    gmOverlap: gmG.filter((g) => g.names.length > 1)
      .map((g) => g.names.join(' / ') + ' 均为 ' + fmt(g.last, 1) + '%' + (g.whole ? '（各月数值相同，曲线完全重合）' : '（末月重合）')),
    gmBest: gmSeries[bestIdx].name + '（' + pct(gmLast[bestIdx], 1) + '）',
    gmWorst: gmSeries[worstIdx].name + '（' + pct(gmLast[worstIdx], 1) + '）',
    gmIndep: pct(gmLast[4], 1),
    chain,
    val: validations(),
    highRisk,
  }
})
</script>

<template>
  <BizfinPage page-id="PAGE-F15-01" :sections="['indicators', 'biz_dim']" title="经营总览驾驶舱" :desc="desc">
    <div class="kpi-grid section">
      <div v-for="k in v.kpis" :key="k.ind.code" class="card kpi" :class="k.cls" :data-kpi="k.ind.code">
        <div class="kpi-label">{{ k.label }} <span class="code-tag">{{ k.ind.code }}</span></div>
        <div class="kpi-val">{{ k.val }}<span class="u">{{ k.ind.unit }}</span></div>
        <div class="kpi-foot">
          <template v-if="k.blank"><span class="muted">环比 — ｜ 同比 —</span><span>待填报</span></template>
          <span v-for="d in k.deltas" v-else :key="d.lab" :class="d.cls" :title="d.lab">{{ d.text }}</span>
        </div>
      </div>
    </div>

    <section class="card section">
      <div class="card-title">
        <span>收入与盈利能力趋势 <span class="small muted sub">柱：营业收入（万元）｜ 线：毛利率 / 净利率（%）</span></span>
        <span class="badge">月度（{{ v.yMonths[0] }} ~ {{ v.yMonths[v.mN - 1] }}）</span>
      </div>
      <SvgChart :svg="v.combo" label="收入与盈利能力趋势" />
      <div class="legend">
        <span><i class="sw-rev"></i>营业收入（万元）</span>
        <span><i :style="{ background: C.fin }"></i>毛利率（%）</span>
        <span><i style="background: #7c3aed"></i>净利率（%）</span>
      </div>
      <p class="note">
        {{ v.mN }} 个月收入在 <b>{{ v.revMin }} ~ {{ v.revMax }} 万元</b>区间；毛利率区间 {{ v.grossMin }} ~ {{ v.grossMax }}，累计净变化
        <b>{{ v.grossDelta }}pt</b>；净利率收于 {{ v.netLast }}。
      </p>
    </section>

    <div class="grid-2 section">
      <section class="card">
        <div class="card-title"><span>渠道收入结构</span><span class="small muted">单位：万元</span></div>
        <div class="donut-row">
          <div class="donut"><SvgChart :svg="v.donut" label="渠道收入结构" /></div>
          <div class="donut-list">
            <div v-for="c in v.chRows" :key="c.label" class="score-row">
              <span class="dot" :style="{ background: c.color }"></span>
              <span class="grow">{{ c.label }}</span>
              <b class="num">{{ c.share }}</b>
            </div>
          </div>
        </div>
        <p class="note">
          Amazon 占比 {{ v.amazonShare }}%，为第一大渠道；渠道集中度 CR1（第一大渠道收入 ÷ 总收入）<b>{{ v.cr1 }}</b>，存在单一渠道依赖风险，需持续加大独立站与 Wayfair 投入。该口径与财务指标
          <code>F1.1</code> / <code>F1</code> 直接勾稽。
        </p>
      </section>

      <section class="card">
        <div class="card-title">
          <span>渠道毛利率</span>
          <span class="small muted">各渠道月度毛利率（%）线性趋势 ｜ {{ v.yMonths[0] }} ~ {{ v.yMonths[v.mN - 1] }}</span>
        </div>
        <SvgChart :svg="v.gmChart" label="渠道毛利率趋势" />
        <div class="legend">
          <span v-for="s in v.gmSeries" :key="s.name"><i :style="{ background: s.color }"></i>{{ s.name }}</span>
        </div>
        <p v-for="t in v.gmOverlap" :key="t" class="note overlap" data-gm-overlap>{{ t }}</p>
        <p class="note">
          当月毛利率最高为 <b>{{ v.gmBest }}</b>，最低为 {{ v.gmWorst }}；平台渠道（Amazon / Wayfair / Home Depot / Lowe's）毛利率与独立站（{{ v.gmIndep }}）的差距反映渠道结构对整体毛利的影响，对应财务指标 F3.1-F3.5。
        </p>
      </section>
    </div>

    <section class="card section">
      <div class="card-title">
        <span>业财联动核心传导链 <span class="small muted sub">业务动作 → 财务结果的量化路径</span></span>
        <RouterLink class="btn" :to="{ name: 'bizfin-linkage' }">查看完整联动图谱 →</RouterLink>
      </div>
      <ol class="stack-list" data-chain>
        <li v-for="(s, i) in v.chain" :key="i" class="stack-item">
          <span class="n">{{ i + 1 }}</span>
          <div class="c"><b>{{ s.b }}</b> <span class="muted">→</span> {{ s.m }} <span class="muted">→</span> <span class="fin" :class="s.tone">{{ s.f }}</span></div>
        </li>
      </ol>
      <p class="note">前 3 条为财务口径链（数字实时可算）；后 3 条为业务口径链，需在「业务指标」页或数据管理页填报分渠道 / 分品类 / 分线路 / 分服务商数据后自动出数。</p>
    </section>

    <div class="grid-2 section top-align">
      <section class="card">
        <div class="card-title"><span>数据一致性校验</span><span class="small muted">一级指标与二级明细勾稽</span></div>
        <div class="chk-list">
          <div v-for="(c, i) in v.val" :key="i" class="chk" :class="c.state">
            <span class="ic" aria-hidden="true">{{ c.state === 'ok' ? '✓' : '!' }}</span>
            <div><div class="t">{{ c.title }}</div><div class="d">{{ c.detail }}</div></div>
          </div>
        </div>
      </section>

      <section class="card">
        <div class="card-title">
          <span>达成率预警（低于 80%） <span class="small muted sub">共 {{ v.highRisk.length }} 项</span></span>
          <RouterLink class="btn" :to="{ name: 'bizfin-advice' }">查看经营建议 →</RouterLink>
        </div>
        <div class="table-wrap">
          <table class="table risk-table" data-testid="risk-table">
            <thead>
              <tr><th>编码</th><th>指标名称</th><th>责任部门</th><th class="num">实际</th><th class="num">目标</th><th class="num">达成率</th></tr>
            </thead>
            <tbody>
              <tr v-for="i in v.highRisk" :key="i.code">
                <td class="code-tag">{{ i.code }}</td>
                <td class="nm"><span class="badge" :class="i.kind === 'fin' ? 'badge-good' : 'badge-info'">{{ i.kind === 'fin' ? '财务' : '业务' }}</span> {{ i.name }}</td>
                <td class="small muted dept">{{ deptOf(i) }}</td>
                <td class="num">{{ fmt(i.actual) }}</td>
                <td class="num muted">{{ fmt(i.target) }}</td>
                <td class="num"><b :class="tier(rate(i))">{{ rateText(i) }}</b></td>
              </tr>
              <tr v-if="!v.highRisk.length"><td colspan="6" class="empty">暂无低于 80% 的二级指标</td></tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </BizfinPage>
</template>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: var(--space-4); }
.kpi { border-top: 3px solid var(--accent); }
.kpi.good { border-top-color: var(--success); }
.kpi.warn { border-top-color: var(--warn); }
.kpi.bad { border-top-color: var(--danger); }
.kpi-val { font-size: var(--text-2xl); font-weight: 700; margin-top: var(--space-1); font-variant-numeric: tabular-nums; }
.kpi-val .u { font-size: var(--text-xs); font-weight: 400; color: var(--muted); margin-left: 3px; }
.kpi-foot { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-2); font-size: var(--text-xs); color: var(--muted); font-weight: 600; }
.sub { font-weight: 400; margin-left: var(--space-2); }
.note { font-size: var(--text-xs); color: var(--muted); line-height: 1.75; margin: var(--space-2) 0 0; }
.note b { color: var(--fg); }
.sw-rev { background: #bfd5fb; }
.donut-row { display: flex; align-items: center; gap: var(--space-2); }
.donut { flex: 0 0 196px; }
.donut-list { flex: 1; }
.score-row { display: flex; align-items: center; gap: var(--space-2); padding: 5px 0; border-bottom: 1px dashed var(--border-soft); font-size: var(--text-xs); }
.score-row:last-child { border-bottom: none; }
.score-row .grow { flex: 1; }
.dot { width: 6px; height: 6px; border-radius: 50%; flex: 0 0 6px; }
.stack-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.stack-item { display: flex; gap: var(--space-3); align-items: flex-start; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); }
.stack-item .n { width: 20px; height: 20px; border-radius: var(--radius-md); background: color-mix(in oklab, var(--accent), white 88%); color: var(--accent); font-size: var(--text-xs); font-weight: 700; display: flex; align-items: center; justify-content: center; flex: 0 0 20px; }
.stack-item .c { font-size: var(--text-sm); color: var(--fg-2); line-height: 1.75; }
.stack-item .c b { color: var(--fg); }
.stack-item .fin { color: var(--fg); font-weight: 700; }
.stack-item .fin.up { color: var(--danger); }
.stack-item .fin.down { color: var(--success); }
.overlap { margin-top: var(--space-1); color: var(--fg-2); }
.chk-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: var(--space-2); }
.chk { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); }
.chk .ic { width: 17px; height: 17px; border-radius: 50%; flex: 0 0 17px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; color: var(--accent-on); margin-top: 2px; }
.chk.ok .ic { background: var(--success); }
.chk.warn .ic { background: var(--warn); }
.chk .t { font-size: var(--text-sm); font-weight: 600; }
.chk .d { font-size: var(--text-xs); color: var(--fg-2); line-height: 1.65; }
/* 预警表完整显示（不再限高 330px 内滚动）；卡片顶对齐，不被左侧校验列表拉出大片空白 */
.top-align { align-items: start; }
.risk-table td, .risk-table th { padding: 0 8px; }
.risk-table td.dept, .risk-table td.nm { white-space: normal; line-height: 1.4; padding-top: 4px; padding-bottom: 4px; }
.risk-table td.dept { min-width: 72px; }
.empty { text-align: center; color: var(--muted); padding: var(--space-6) var(--space-4); }
.t-good { color: var(--success); }
.t-info { color: var(--accent); }
.t-warn { color: var(--warn); }
.t-bad { color: var(--danger); }
</style>
