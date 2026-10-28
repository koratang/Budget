<script setup lang="ts">
/**
 * 订单分析（原 viewOrderAnalysis）：不同渠道的订单量和客单价、渠道集中度 CR1。
 * 数据来自引擎 orderModel（订单量 = 渠道收入 × 10000 ÷ 渠道客单价）。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import { CHANNELS, CH_COLOR, MONTHS9, S, fmt, mSeries, orderModel } from '@/bizfin/engine'
import { hBarChart, lineChart } from '@/bizfin/charts'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import AnaKitNote from './AnaKitNote.vue'

const om = computed(() => orderModel())
const mm = computed(() => mSeries((m) => orderModel(m)))
const list = computed(() =>
  CHANNELS.map((c) => ({ channel: c, orders: om.value.orders[c], revenue: om.value.revenueByChannel[c], aov: om.value.aov[c] }))
    .sort((a, b) => b.orders - a.orders),
)
const topOrd = computed(() => list.value[0])
const topAov = computed(() => list.value.slice().sort((a, b) => b.aov - a.aov)[0])
/* 渠道集中度 CR1：收入占比最高的单一渠道（口径 = 财务渠道二级 F1.1~F1.5） */
const cr1Row = computed(() => list.value.slice().sort((a, b) => b.revenue - a.revenue)[0])
const cr1 = computed(() => (om.value.revenue > 0 ? cr1Row.value.revenue / om.value.revenue * 100 : 0))

const mLabels = computed(() => MONTHS9.slice(0, S.curM || 9))
const legend = CHANNELS.map((c) => ({ name: c, color: CH_COLOR[c] }))
const trendSvg = computed(() =>
  lineChart(
    mLabels.value,
    CHANNELS.map((c) => ({
      name: c,
      color: CH_COLOR[c],
      values: mm.value.slice(0, mLabels.value.length).map((x) => {
        const v = x.orders[c]
        return v === null || v === undefined || isNaN(v) ? 0 : v
      }),
    })),
    { w: 860, h: 272, endLabel: true, dec: 0 },
  ),
)
const ordSvg = computed(() =>
  hBarChart(
    list.value.slice().sort((a, b) => b.orders - a.orders).map((r) => ({
      label: r.channel, value: r.orders, color: CH_COLOR[r.channel],
      text: fmt(r.orders, 0) + ' 单 (' + fmt(r.orders / (om.value.total || 1) * 100, 1) + '%)',
    })),
    { w: 520, labelW: 104, rowH: 30, rightW: 158 },
  ),
)
const aovSvg = computed(() =>
  hBarChart(
    list.value.slice().sort((a, b) => b.aov - a.aov).map((r) => ({
      label: r.channel, value: r.aov, color: CH_COLOR[r.channel],
      text: fmt(r.aov, 0) + ' 元 (' + (r.aov >= om.value.blendedAov ? '+' : '') + fmt(r.aov - om.value.blendedAov, 0) + ')',
    })),
    { w: 520, labelW: 104, rowH: 30, rightW: 158 },
  ),
)
</script>

<template>
  <div class="ana-order">
    <AnaKitNote title="订单分析口径：">订单量按 <b>订单量 = 渠道收入 × 10000 ÷ 渠道客单价</b> 逐渠道计算，各渠道合计即为总订单量。客单价优先取营销板块 <AnaKitCode code="S1.3" />「客单价」分渠道填报值，未填报回落渠道结构基准（Amazon 1065 元 / Wayfair 2010 元 / Home Depot 2470 元 / Lowe's 2330 元 / 独立站 1340 元）。订单量与客单价共同决定收入，两者需交叉判断渠道健康度。</AnaKitNote>

    <div class="grid-4 kpis">
      <AnaKitKpi data-kpi="total" label="总订单量" :value="fmt(om.total, 0)" unit="单"
        :foot="`收入 ${fmt(om.revenue, 0)} 万元 ÷ 综合客单价 ${fmt(om.blendedAov, 0)} 元`" />
      <AnaKitKpi data-kpi="aov" label="综合客单价" :value="fmt(om.blendedAov, 0)" unit="元" tone="biz"
        :foot="`收入 ${fmt(om.revenue, 0)} 万元 ÷ ${fmt(om.total, 0)} 单`" />
      <AnaKitKpi data-kpi="topOrd" label="订单量最大渠道" :value="topOrd.channel" compact
        :foot="`${fmt(topOrd.orders, 0)} 单 · 占 ${fmt(topOrd.orders / (om.total || 1) * 100, 1)}%`" />
      <AnaKitKpi data-kpi="topAov" label="客单价最高渠道" :value="topAov.channel" tone="fin" compact
        :foot="`${fmt(topAov.aov, 0)} 元 · 收入 ${fmt(topAov.revenue, 0)} 万元`" />
    </div>

    <AnaKitCard title="渠道订单量与客单价" desc="订单量：单 ｜ 金额：万元 ｜ 客单价：元">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>渠道</th><th class="num">订单量</th><th class="num">订单占比</th><th class="num">收入</th>
              <th class="num">收入占比</th><th class="num">客单价</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in list" :key="r.channel">
              <td class="strong">{{ r.channel }}</td>
              <td class="num">{{ fmt(r.orders, 0) }}</td>
              <td class="num">{{ fmt(r.orders / (om.total || 1) * 100, 1) }}%</td>
              <td class="num">{{ fmt(r.revenue, 0) }}</td>
              <td class="num">{{ fmt(r.revenue / (om.revenue || 1) * 100, 1) }}%</td>
              <td class="num strong">{{ fmt(r.aov, 0) }}</td>
            </tr>
            <tr class="total" data-test="total">
              <td>合计</td>
              <td class="num">{{ fmt(om.total, 0) }}</td><td class="num">100.0%</td>
              <td class="num">{{ fmt(om.revenue, 0) }}</td><td class="num">100.0%</td>
              <td class="num">{{ fmt(om.blendedAov, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>
        商超渠道（Home Depot / Lowe's）订单量占比低但客单价高，是"低频高客单"结构；Amazon 反向，为"高频低客单"。两者结合使收入结构相对均衡，避免单一渠道集中度过高（当前 CR1 = {{ fmt(cr1, 1) }}%（{{ cr1Row.channel }}，由 <AnaKitCode code="F1.1" /> ~ <AnaKitCode code="F1.5" /> 渠道收入结构实时计算）。
      </AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="渠道订单量月度趋势" desc="各渠道 1 月至当月订单量（单）线性趋势"
      :pill="`月度（${mLabels[0]} ~ ${mLabels[mLabels.length - 1]}）`">
      <SvgChart :svg="trendSvg" label="渠道订单量月度趋势" />
      <AnaKitLegend :items="legend" />
      <AnaKitChartNote>各渠道订单量按月对比，可直接看出渠道放量节奏与季节性差异；订单量增长若伴随客单价下滑，说明增长依赖低价引流，需警惕毛利被稀释。</AnaKitChartNote>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard title="渠道订单量分布" desc="单位：单">
        <SvgChart :svg="ordSvg" label="渠道订单量分布" />
      </AnaKitCard>
      <AnaKitCard title="渠道客单价分布" desc="单位：元">
        <SvgChart :svg="aovSvg" label="渠道客单价分布" />
      </AnaKitCard>
    </div>
  </div>
</template>

<style scoped>
.kpis { margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
</style>
