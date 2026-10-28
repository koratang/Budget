<script setup lang="ts">
/**
 * 渠道效益分析（原 viewChannelEffect）：渠道 × 九项费用结构矩阵、收入规模 / 毛利率横条、单渠道成本结构月度趋势。
 * 口径：财务指标为唯一真源，费用池由 F1 / F2 / F4.x 决定，渠道权重仅做池内分摊 ⇒ 贡献毛利额合计 ≡ F4 净利润。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import { C, COST_LINES, MONTHS9, PAL, S, channelEffectAll, channelRowsAt, fmt, iv, type EffRow } from '@/bizfin/engine'
import { hBarChart, lineChart } from '@/bizfin/charts'
import { TREND_COLOR, signTrend, trendStyle, type Trend } from './AnaKit'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import AnaKitNote from './AnaKitNote.vue'

/** 按 COST_LINES 的 key 取渠道行数值 */
function lineVal(r: EffRow, key: string): number {
  const v: unknown = Reflect.get(r, key)
  return typeof v === 'number' ? v : 0
}
/* 涨红跌绿口径：毛利率 ≥25% 高档红 / 15–25% 中性 / <15% 低档绿；表格、条形图、图例共用 */
function rateTrend(rate: number): Trend {
  return rate >= 0.25 ? 'up' : rate >= 0.15 ? 'flat' : 'down'
}
const RATE_BAR: Record<Trend, string> = { up: C.up, flat: C.text3, down: C.down }

const rows = computed(() => channelEffectAll())
const totalRev = computed(() => rows.value.reduce((a, b) => a + b.revenue, 0))
const totalGross = computed(() => rows.value.reduce((a, b) => a + b.gross, 0))
const blendedRate = computed(() => (totalRev.value > 0 ? totalGross.value / totalRev.value : 0))
const top = computed(() => rows.value.slice().sort((a, b) => b.gross - a.gross)[0])
const bot = computed(() => rows.value.slice().sort((a, b) => a.gross - b.gross)[0])
const hhi = computed(() => rows.value.reduce((a, b) => a + b.share * b.share * 10000, 0))
const colTotal = (key: string): number => rows.value.reduce((a, b) => a + lineVal(b, key), 0)

/* 勾稽：贡献毛利额合计 ≡ F4 净利润；贡献毛利率合计 ≡ F5 净利润率 */
const netProfit = computed(() => iv('F4'))
const netRate = computed(() => iv('F5'))
const tieDiff = computed(() => totalGross.value - (netProfit.value ?? 0))
const tieOk = computed(() => netProfit.value !== null && Math.abs(tieDiff.value) < 0.5)

const revSvg = computed(() =>
  hBarChart(
    rows.value.slice().sort((a, b) => b.revenue - a.revenue).map((r) => ({
      label: r.key, value: r.revenue, color: C.biz, text: fmt(r.revenue, 0) + ' 万 (' + fmt(r.share * 100, 1) + '%)',
    })),
    { w: 540, labelW: 108, rowH: 30, rightW: 140 },
  ),
)
const rateSvg = computed(() =>
  hBarChart(
    rows.value.slice().sort((a, b) => b.grossRate - a.grossRate).map((r) => ({
      label: r.key,
      value: r.grossRate * 100,
      color: RATE_BAR[rateTrend(r.grossRate)],
      text: fmt(r.grossRate * 100, 1) + '% 毛利 ' + fmt(r.gross, 0) + '万',
    })),
    { w: 540, labelW: 108, rowH: 30, rightW: 170 },
  ),
)

/* 单渠道成本结构月度趋势：每费用项一张折线图，5 渠道各一条线，1 月至当月 */
const mLabels = computed(() => MONTHS9.slice(0, S.curM || 9))
const legend = computed(() => rows.value.map((r, idx) => ({ name: r.key, color: PAL[idx] })))
const trendCharts = computed(() => {
  const monthRows: EffRow[][] = []
  for (let m = 0; m < mLabels.value.length; m++) monthRows.push(channelRowsAt(m))
  return COST_LINES.filter((c) => c.type === 'cost' || c.key === 'gross').map((line) => ({
    key: line.key,
    title: line.name + (line.key === 'gross' ? ' (毛利)' : ''),
    svg: lineChart(
      mLabels.value,
      rows.value.map((r, idx) => ({
        name: r.key,
        color: PAL[idx],
        values: monthRows.map((rs) => {
          const rr = rs.find((x) => x.key === r.key)
          return rr ? lineVal(rr, line.key) : 0
        }),
      })),
      { w: 540, h: 220, endLabel: true, dec: 0 },
    ),
  }))
})
</script>

<template>
  <div class="ana-channel">
    <div class="grid-4 kpis">
      <AnaKitKpi data-kpi="gross" label="渠道总毛利额" :value="fmt(totalGross, 0)" unit="万" tone="biz"
        :foot="`收入 ${fmt(totalRev, 0)} 万 × 综合毛利率 ${fmt(blendedRate * 100, 1)}%`" />
      <AnaKitKpi data-kpi="top" label="毛利最高渠道" :value="top.key" tone="up" compact
        :foot="`${fmt(top.gross, 0)} 万 · 毛利率 ${fmt(top.grossRate * 100, 1)}%`" />
      <AnaKitKpi data-kpi="bot" label="毛利最低渠道" :value="bot.key" tone="down" compact
        :foot="`${fmt(bot.gross, 0)} 万 · 毛利率 ${fmt(bot.grossRate * 100, 1)}%`" />
      <AnaKitKpi data-kpi="hhi" label="渠道集中度（HHI）" :value="fmt(hhi, 0)" tone="fin"
        foot="数值越大说明渠道越集中，< 1500 为分散、1500-2500 为中等、>2500 为高集中度" />
    </div>

    <AnaKitCard title="渠道 × 费用结构 矩阵" desc="单位：万元 ｜ 毛利率单元格为占比，金额单元格为万元">
      <div class="table-wrap">
        <table class="table matrix" data-test="matrix">
          <thead>
            <tr>
              <th>渠道</th>
              <th v-for="c in COST_LINES" :key="c.key" class="num">{{ c.name }}{{ c.key === 'grossRate' ? ' (%)' : '' }}</th>
              <th class="num">收入占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.key">
              <td class="strong">{{ r.key }}</td>
              <template v-for="c in COST_LINES" :key="c.key">
                <td v-if="c.key === 'grossRate'" class="num" :style="trendStyle(rateTrend(r.grossRate))">{{ fmt(r.grossRate * 100, 1) }}%</td>
                <td v-else-if="c.type === 'income'" class="num income">{{ fmt(lineVal(r, c.key), 0) }}</td>
                <td v-else-if="c.key === 'gross'" class="num" :style="trendStyle(signTrend(r.gross))">{{ r.gross >= 0 ? '+' : '' }}{{ fmt(r.gross, 0) }}</td>
                <td v-else class="num">{{ fmt(lineVal(r, c.key), 0) }}</td>
              </template>
              <td class="num muted">{{ fmt(r.share * 100, 1) }}%</td>
            </tr>
            <tr class="total" data-test="matrix-total">
              <td>合计</td>
              <template v-for="c in COST_LINES" :key="c.key">
                <td v-if="c.key === 'grossRate'" class="num" :style="{ color: TREND_COLOR[rateTrend(blendedRate)] }">{{ fmt(blendedRate * 100, 1) }}%</td>
                <td v-else-if="c.key === 'gross'" class="num" :style="{ color: TREND_COLOR[signTrend(totalGross)] }">{{ totalGross >= 0 ? '+' : '' }}{{ fmt(totalGross, 0) }}</td>
                <td v-else class="num">{{ fmt(colTotal(c.key), 0) }}</td>
              </template>
              <td class="num">100.0%</td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="tie small" data-test="tie">
        <span class="badge" :class="tieOk ? 'badge-good' : 'badge-warn'">{{ tieOk ? '勾稽一致' : '勾稽差异' }}</span>
        贡献毛利额合计 <b>{{ fmt(totalGross, 1) }}</b> 万元 ≡ <AnaKitCode code="F4" /> 净利润 <b>{{ fmt(netProfit, 1) }}</b> 万元（差额 {{ fmt(tieDiff, 1) }}）；
        贡献毛利率合计 <b>{{ fmt(blendedRate * 100, 2) }}%</b> ≡ <AnaKitCode code="F5" /> 净利润率 <b>{{ fmt(netRate, 2) }}%</b>
      </p>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard title="渠道收入规模（万元）" desc="按本期收入降序">
        <SvgChart :svg="revSvg" label="渠道收入规模" />
      </AnaKitCard>
      <AnaKitCard title="渠道毛利率（%）" desc="颜色（高红低绿）：红 ≥25% / 灰 15–25% / 绿 <15%">
        <SvgChart :svg="rateSvg" label="渠道毛利率" />
      </AnaKitCard>
    </div>

    <AnaKitCard title="单渠道成本结构月度趋势" desc="各渠道 1 月至当月发生额（万元）线性趋势，按费用项分图"
      :pill="`月度（${mLabels[0]} ~ ${mLabels[mLabels.length - 1]}）`">
      <div class="grid-2">
        <div v-for="t in trendCharts" :key="t.key">
          <div class="trend-title">{{ t.title }}</div>
          <SvgChart :svg="t.svg" :label="`${t.title} 月度趋势`" />
          <AnaKitLegend :items="legend" />
        </div>
      </div>
      <AnaKitChartNote>
        毛利率的差异主要来自渠道佣金结构（Amazon 15%、Wayfair 22% vs Home Depot/Lowe's 3%）与产品成本率，各费用项的月度波动可直接定位成本异常月份；建议针对 Wayfair / Amazon 高佣金渠道同步推进降本与提价，把单渠道毛利率提升到 25% 以上。
      </AnaKitChartNote>
    </AnaKitCard>

    <AnaKitNote title="渠道效益分析说明：">本表以<b>财务指标为唯一真源</b>：净销售额口径取自渠道二级 <AnaKitCode code="F1.1~F1.5" />（与订单分析的渠道集中度 CR1 同源），费用池由 <AnaKitCode code="F1" /> / <AnaKitCode code="F2" /> / <AnaKitCode code="F4.1" /> / <AnaKitCode code="F4.2" /> / <AnaKitCode code="F4" /> 直接决定，渠道结构权重仅用于<b>池内分摊</b>。因此 <b>贡献毛利额合计 ≡ <AnaKitCode code="F4" /> 净利润</b>、<b>贡献毛利率合计 ≡ <AnaKitCode code="F5" /> 净利润率</b>，九项结构在渠道维度加总后可与管理报表逐项对账。可在「数据管理」导入分渠道佣金单 / FBA 账单后，用真实台账替换分摊权重，勾稽关系保持不变。毛利率 + 收入规模 双轴交叉 = 渠道优先级矩阵：低毛利 + 低规模（及时止损）、低毛利 + 高规模（重点改进）、高毛利 + 低规模（放量）、高毛利 + 高规模（守住）。</AnaKitNote>
  </div>
</template>

<style scoped>
.kpis { margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
.income { color: var(--fg); font-weight: 600; }
.matrix th, .matrix td { font-size: var(--text-xs); }
.tie { margin: var(--space-3) 0 0; color: var(--fg-2); display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-1); }
.trend-title { font-size: var(--text-sm); font-weight: 600; color: var(--fg-2); margin-bottom: var(--space-2); }
</style>
