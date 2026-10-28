<script setup lang="ts">
/**
 * 数据分析 · 尾程物流分析（原 viewLogiPostAnalysis）：服务商尾程发货量 / 单位成本月度趋势 ｜ 渠道尾程成本占比月度趋势。
 * 费用池取 costPools().logiPost；发货量与「订单分析」同源（orderModel）；KPI 口径随维度切换。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import { lineChart, type LineSeries } from '@/bizfin/charts'
import {
  CHANNELS, CH_COLOR, MONTHS9, S, channelRowsAt, costPools, fmt, mSeries, orderModel, provColor, providerCost, provShares,
  type Provider,
} from '@/bizfin/engine'

/* 尾程服务商（6 家，按单计价：元 / 单） */
const POST_PROVIDERS: Provider[] = [
  { name: 'UPS（美线快运）', cost: 28.5, share: 0.30 },
  { name: 'FedEx（美线经济）', cost: 24.8, share: 0.24 },
  { name: 'USPS（小包直发）', cost: 12.6, share: 0.16 },
  { name: 'DPD（欧洲配送）', cost: 18.9, share: 0.14 },
  { name: 'Evri（英国配送）', cost: 11.2, share: 0.10 },
  { name: '专线卡车（商超直送）', cost: 9.8, share: 0.06 },
]
const POST_IDX = [0.98, 0.97, 0.99, 1.00, 1.01, 1.02, 1.03, 1.04, 1.05]

/* 服务商份额加权单位成本（元 / 单）；m = null 为年度加权 */
function weightedUc(m: number | null): number {
  const sh = provShares(POST_PROVIDERS, m)
  let tot = 0
  POST_PROVIDERS.forEach(function (pr, i) { tot += sh[i] * providerCost(pr.cost, POST_IDX, 'pp-' + pr.name, m) })
  return tot
}

const v = computed(() => {
  const p = costPools()
  const postByM = mSeries((m) => costPools(m).logiPost)
  const revByM = mSeries((m) => costPools(m).rev)
  const ordByM = mSeries((m) => orderModel(m).total)
  const mN = S.curM || 9
  const mLabels = MONTHS9.slice(0, mN)
  const unitCostByM = mSeries((m) => weightedUc(m))

  /* 图 1：服务商尾程发货量月度趋势（单） */
  const qtySeries: LineSeries[] = POST_PROVIDERS.map(function (pr, i) {
    return { name: pr.name.replace(/（.*?）/g, ''), color: provColor(i), values: mSeries((m) => ordByM[m] * provShares(POST_PROVIDERS, m)[i]) }
  })
  /* 图 2：服务商单位成本月度趋势（元 / 单） */
  const costSeries: LineSeries[] = POST_PROVIDERS.map(function (pr, i) {
    return { name: pr.name.replace(/（.*?）/g, ''), color: provColor(i), values: mSeries((m) => providerCost(pr.cost, POST_IDX, 'pp-' + pr.name, m)) }
  })
  /* 图 3：渠道尾程成本占比月度趋势（占该渠道收入 %） */
  const chRateSeries: LineSeries[] = CHANNELS.map(function (c) {
    return {
      name: c, color: CH_COLOR[c], values: mSeries(function (m) {
        const r = channelRowsAt(m).filter((x) => x.key === c)[0]
        return (r && r.revenue > 0) ? r.logiPost / r.revenue * 100 : 0
      }),
    }
  })

  /* KPI 口径随维度切换：年度 = 全年累计；月度 = 当月值（原代码另算的年度加权单价 ucYear 未被使用，不再计算） */
  const curIdx = Math.min((S.curM || 9) - 1, 8)
  const isMonth = S.dim === 'month'
  const costNow = isMonth ? (postByM[curIdx] || 0) : p.logiPost
  const ordNow = isMonth ? (ordByM[curIdx] || 0) : orderModel().total
  const revNow = isMonth ? (revByM[curIdx] || 0) : p.rev
  const ucNow = ordNow > 0 ? costNow * 10000 / ordNow : 0
  const postRate = revNow > 0 ? costNow / revNow * 100 : 0
  const ucIdxNow = unitCostByM[unitCostByM.length - 1] || 0

  const legend = (ss: LineSeries[]): { name: string; color: string }[] => ss.map((s) => ({ name: s.name ?? '', color: s.color }))
  return {
    isMonth, costNow, ordNow, ucNow, postRate, ucIdxNow,
    pill: '月度（' + mLabels[0] + ' ~ ' + mLabels[mLabels.length - 1] + '）',
    qtySvg: lineChart(mLabels, qtySeries, { w: 860, h: 280, endLabel: false, dec: 0 }), qtyLegend: legend(qtySeries),
    costSvg: lineChart(mLabels, costSeries, { w: 860, h: 280, endLabel: false, dec: 2 }), costLegend: legend(costSeries),
    chSvg: lineChart(mLabels, chRateSeries, { w: 860, h: 280, endLabel: true, dec: 2 }), chLegend: legend(chRateSeries),
  }
})
</script>

<template>
  <div data-ana-view="anaLogiPost">
    <div class="kpi-grid">
      <AnaKitKpi label="尾程成本总额" :value="fmt(v.costNow, 1)" unit="万元" data-kpi="cost">
        <template #foot>{{ v.isMonth ? '当月 · ' : '全年累计 · ' }}对应 <AnaKitCode code="F4.4" /> 尾程成本占比</template>
      </AnaKitKpi>
      <AnaKitKpi label="尾程发货订单量" :value="fmt(v.ordNow, 0)" unit="单" foot="尾程按订单履约，与「订单分析」同源" tone="biz" data-kpi="orders" />
      <AnaKitKpi label="单位成本" :value="fmt(v.ucNow, 1)" unit="元/单" :foot="'尾程费用 ÷ 发货订单量 · 服务商加权参考 ' + fmt(v.ucIdxNow, 1)" tone="warn" data-kpi="uc" />
      <AnaKitKpi label="尾程成本占比" :value="fmt(v.postRate, 2)" unit="%" foot="尾程费用 ÷ 营业收入" tone="fin" data-kpi="rate" />
    </div>

    <AnaKitCard title="服务商尾程发货量月度趋势" desc="单位：单 ｜ 按服务商份额拆分月度总订单" :pill="v.pill">
      <SvgChart :svg="v.qtySvg" label="服务商尾程发货量月度趋势" />
      <AnaKitLegend :items="v.qtyLegend" />
      <AnaKitChartNote>商超渠道整柜直送由专线卡车承担，小包直发由 USPS / Evri 承担；发货量随订单量与渠道结构同步波动，旺季附加费时段可对照单位成本图判断履约成本压力。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="服务商单位成本月度趋势" desc="单位：元 / 单">
      <SvgChart :svg="v.costSvg" label="服务商单位成本月度趋势" />
      <AnaKitLegend :items="v.costLegend" />
      <AnaKitChartNote>专线卡车（商超直送）单价最低但覆盖有限，USPS / Evri 主打小包轻量件，UPS / FedEx 覆盖美线主流履约。可通过调整服务商份额组合摊薄加权单均成本。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="渠道尾程成本占比月度趋势" desc="各渠道尾程成本 ÷ 该渠道收入（%）">
      <SvgChart :svg="v.chSvg" label="渠道尾程成本占比月度趋势" />
      <AnaKitLegend :items="v.chLegend" />
      <AnaKitChartNote>小包直发为主的渠道尾程费率显著高于整柜直送的商超渠道；优化方向是把高频订单向海外仓前置库存迁移，用仓储成本换取尾程费率下降。</AnaKitChartNote>
    </AnaKitCard>
  </div>
</template>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: var(--space-3); margin-bottom: var(--space-4); }
</style>
