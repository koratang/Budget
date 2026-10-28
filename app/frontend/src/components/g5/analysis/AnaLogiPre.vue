<script setup lang="ts">
/**
 * 数据分析 · 头程物流分析（原 viewLogiPreAnalysis）：服务商-线路发货量 / 单位成本月度趋势 ｜ 渠道头程成本占比月度趋势。
 * 费用池取 costPools().logiPre（F1 × F4.3）；发货量按服务商份额加权单位成本反推；KPI 口径随维度切换。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import { lineLegend, overlapNote } from './AnaKit'
import { lineChart, type LineSeries } from '@/bizfin/charts'
import {
  CHANNELS, CH_COLOR, FREIGHT_IDX, LOGI_PROVIDERS, MONTHS9, PAL, S,
  channelRowsAt, costPools, fmt, mSeries, providerCost, provShares,
} from '@/bizfin/engine'

/* 服务商 × 线路 组合（9 条，覆盖主要发货路径；w = 该服务商内部线路分配权重） */
const LANE_IDX_PRE: Record<string, number> = { '美东': 1.06, '美西': 1.00, '英国': 1.12, '欧洲': 1.15 }
const PROV_LANES = [
  { prov: '美森快船（海运快线）', lane: '美西', w: 0.62 },
  { prov: '美森快船（海运快线）', lane: '美东', w: 0.38 },
  { prov: '中远海运（普船）', lane: '美西', w: 0.45 },
  { prov: '中远海运（普船）', lane: '欧洲', w: 0.30 },
  { prov: '中远海运（普船）', lane: '英国', w: 0.25 },
  { prov: '燕文物流', lane: '英国', w: 0.55 },
  { prov: '燕文物流', lane: '欧洲', w: 0.45 },
  { prov: '递四方', lane: '美东', w: 1.00 },
  { prov: '万邑通（头程集运）', lane: '美西', w: 1.00 },
]
const provIdx: Record<string, number> = {}
LOGI_PROVIDERS.forEach(function (pr, i) { provIdx[pr.name] = i })
const cmbName = (pl: { prov: string; lane: string }): string => pl.prov.replace(/（.*?）/g, '') + '·' + pl.lane
/* 9 条线的区分：颜色按服务商（5 个色相拉开，避开红 / 绿以免与涨跌语义混淆），线型按线路；图例画同样的线型 */
const PROV_LINE_COLOR: Record<string, string> = {
  '美森快船（海运快线）': PAL[0], /* 蓝 */
  '中远海运（普船）': PAL[3], /* 橙 */
  '燕文物流': PAL[2], /* 紫 */
  '递四方': PAL[7], /* 品红 */
  '万邑通（头程集运）': PAL[8], /* 青 */
}
const LANE_DASH: Record<string, string> = { '美西': '', '美东': '8 4', '欧洲': '2 3', '英国': '10 3 2 3' }
const laneStyle = (pl: { prov: string; lane: string }): { name: string; color: string; dash?: string } => {
  const dash = LANE_DASH[pl.lane]
  return { name: cmbName(pl), color: PROV_LINE_COLOR[pl.prov], ...(dash ? { dash } : {}) }
}

/* 服务商份额加权单位成本（元/kg）；m = null 为年度加权 */
function weightedUc(m: number | null): number {
  const sh = provShares(LOGI_PROVIDERS, m)
  let tot = 0
  LOGI_PROVIDERS.forEach(function (pr, i) { tot += sh[i] * providerCost(pr.cost, FREIGHT_IDX, 'pc-' + pr.name, m) })
  return tot
}

const v = computed(() => {
  const p = costPools()
  const preByM = mSeries((m) => costPools(m).logiPre)
  const revByM = mSeries((m) => costPools(m).rev)
  const mN = S.curM || 9
  const mLabels = MONTHS9.slice(0, mN)
  const unitCostByM = mSeries((m) => weightedUc(m))

  /* 图 1：服务商-线路 发货量月度趋势（吨） */
  const qtySeries: LineSeries[] = PROV_LANES.map(function (pl) {
    const pi = provIdx[pl.prov]
    return {
      ...laneStyle(pl), values: mSeries(function (m) {
        const sh = provShares(LOGI_PROVIDERS, m)[pi]
        const uc = unitCostByM[m]
        const tot = uc > 0 ? costPools(m).logiPre * 10000 / uc / 1000 : 0
        return tot * sh * pl.w
      }),
    }
  })
  /* 图 2：服务商-线路 单位成本月度趋势（元/kg） */
  const costSeries: LineSeries[] = PROV_LANES.map(function (pl) {
    const pr = LOGI_PROVIDERS[provIdx[pl.prov]]
    return {
      ...laneStyle(pl),
      values: mSeries((m) => providerCost(pr.cost, FREIGHT_IDX, 'pc-' + pr.name, m) * LANE_IDX_PRE[pl.lane]),
    }
  })
  /* 图 3：渠道头程成本占比月度趋势（占该渠道收入 %） */
  const chRateSeries: LineSeries[] = CHANNELS.map(function (c) {
    return {
      name: c, color: CH_COLOR[c], values: mSeries(function (m) {
        const r = channelRowsAt(m).filter((x) => x.key === c)[0]
        return (r && r.revenue > 0) ? r.logiPre / r.revenue * 100 : 0
      }),
    }
  })

  /* KPI 口径随维度切换：年度 = 全年累计 + 年度加权单价；月度 = 当月值 */
  const ucYear = weightedUc(null)
  const curIdx = Math.min((S.curM || 9) - 1, 8)
  const isMonth = S.dim === 'month'
  const costNow = isMonth ? (preByM[curIdx] || 0) : p.logiPre
  const ucNow = isMonth ? (unitCostByM[curIdx] || 0) : ucYear
  const qtyNow = ucNow > 0 ? costNow * 10000 / ucNow / 1000 : 0
  const revNow = isMonth ? (revByM[curIdx] || 0) : p.rev
  const preRate = revNow > 0 ? costNow / revNow * 100 : 0
  const ucJan = unitCostByM[0] || 0

  return {
    isMonth, costNow, qtyNow, ucNow, preRate, ucJan,
    pill: '月度（' + mLabels[0] + ' ~ ' + mLabels[mLabels.length - 1] + '）',
    qtySvg: lineChart(mLabels, qtySeries, { w: 860, h: 280, endLabel: false, dec: 0 }), qtyLegend: lineLegend(qtySeries),
    costSvg: lineChart(mLabels, costSeries, { w: 860, h: 280, endLabel: false, dec: 2 }), costLegend: lineLegend(costSeries),
    chSvg: lineChart(mLabels, chRateSeries, { w: 860, h: 280, endLabel: true, dec: 2, endUnit: '%' }), chLegend: lineLegend(chRateSeries),
    chOverlap: overlapNote(chRateSeries, 2, '%'),
  }
})
</script>

<template>
  <div data-ana-view="anaLogiPre">
    <div class="kpi-grid">
      <AnaKitKpi label="头程成本总额" :value="fmt(v.costNow, 1)" unit="万元" data-kpi="cost">
        <template #foot>{{ v.isMonth ? '当月 · ' : '全年累计 · ' }}对应 <AnaKitCode code="F4.3" /> 头程成本占比</template>
      </AnaKitKpi>
      <AnaKitKpi label="头程发货量" :value="fmt(v.qtyNow, 0)" unit="吨" foot="按加权单位成本反推（费用 ÷ 单价）" tone="biz" data-kpi="qty" />
      <AnaKitKpi label="单位成本" :value="fmt(v.ucNow, 2)" unit="元/kg" :foot="'5 服务商份额加权 · 年初 ' + fmt(v.ucJan, 2)" tone="warn" data-kpi="uc" />
      <AnaKitKpi label="头程成本占比" :value="fmt(v.preRate, 2)" unit="%" foot="头程费用 ÷ 营业收入" tone="fin" data-kpi="rate" />
    </div>

    <AnaKitCard title="服务商-线路 头程发货量月度趋势" desc="单位：吨 ｜ 各服务商按线路分配权重拆分" :pill="v.pill">
      <SvgChart :svg="v.qtySvg" label="服务商-线路 头程发货量月度趋势" />
      <AnaKitLegend :items="v.qtyLegend" />
      <AnaKitChartNote>快船（美森）承担美线主量，普船（中远）覆盖欧洲与英国；发货量在旺季前置备货期抬升，可对照「采购周期」与「库存周转」判断是否为主动备货而非被动压货。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="服务商-线路 单位成本月度趋势" desc="单位：元 / kg ｜ 线路系数：美西 1.00 / 美东 1.06 / 英国 1.12 / 欧洲 1.15">
      <SvgChart :svg="v.costSvg" label="服务商-线路 单位成本月度趋势" />
      <AnaKitLegend :items="v.costLegend" />
      <AnaKitChartNote>快船与普船的单价差是「时效 — 成本」权衡的核心；远洋线路（英国 / 欧洲）因运输距离与清关成本，单位成本显著高于美西。提高普船占比、放大集运比例可摊薄加权单位成本。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="渠道头程成本占比月度趋势" desc="各渠道头程成本 ÷ 该渠道收入（%）">
      <SvgChart :svg="v.chSvg" label="渠道头程成本占比月度趋势" />
      <AnaKitLegend :items="v.chLegend" />
      <AnaKitChartNote>
        头程占比高的渠道说明其收入对运价更敏感：大件直发比例高的渠道需优先推进包装减负与集拼，占比上行时应同步评估提价或调整履约线路。
        <template v-if="v.chOverlap"><br><span data-test="overlap-note">注：{{ v.chOverlap }}。</span></template>
      </AnaKitChartNote>
    </AnaKitCard>
  </div>
</template>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: var(--space-3); margin-bottom: var(--space-4); }
</style>
