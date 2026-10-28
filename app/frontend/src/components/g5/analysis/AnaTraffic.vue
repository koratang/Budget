<script setup lang="ts">
/**
 * 流量分析（原 viewTrafficAnalysis）：不同渠道的 UV、转化率、非付费流量占比、单位广告成本 CPC。
 * 数据来自引擎 channelModel（UV 由订单量 ÷ 转化率反推，属推算示例数据）。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import { CHANNELS, CH_COLOR, MONTHS9, S, channelModel, find, fmt, hasData, mSeries, type ChannelModelRow } from '@/bizfin/engine'
import { lineChart } from '@/bizfin/charts'
import { hiLo } from './AnaKit'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import AnaKitNote from './AnaKitNote.vue'

type TrendField = 'uv' | 'cvr' | 'organic' | 'cpc'

const cm = computed(() => channelModel())
const mm = computed(() => mSeries((m) => channelModel(m)))
const rows = computed(() => cm.value.rows.slice().sort((a, b) => b.uv - a.uv))
const totalUv = computed(() => cm.value.uv || 1)
const best = computed(() => rows.value.slice().sort((a, b) => a.cpc - b.cpc)[0])
const worst = computed(() => rows.value.slice().sort((a, b) => b.cpc - a.cpc)[0])
const cvrFilled = computed(() => hasData(find('S1.2')))
const T = computed(() =>
  cm.value.rows.reduce(
    (a, r) => {
      a.uv += r.uv; a.paid += r.paidUv; a.ord += r.orders; a.mkt += r.mkt; a.rev += r.revenue
      return a
    },
    { uv: 0, paid: 0, ord: 0, mkt: 0, rev: 0 },
  ),
)

/* 渠道维度月度趋势：4 张折线图（UV / 转化率 / 非付费占比 / CPC），每张图正下方各带渠道图例 */
const mLabels = computed(() => MONTHS9.slice(0, S.curM || 9))
const chLegend = CHANNELS.map((c) => ({ name: c, color: CH_COLOR[c] }))
function chSeries(field: TrendField, div?: number): { name: string; color: string; values: number[] }[] {
  const mmT = mm.value.slice(0, mLabels.value.length)
  return CHANNELS.map((c) => ({
    name: c,
    color: CH_COLOR[c],
    values: mmT.map((x) => {
      const r: ChannelModelRow | undefined = x.rows.find((y) => y.channel === c)
      return r ? (div ? r[field] / div : r[field]) : 0
    }),
  }))
}
const trendDefs = computed(() => {
  const labels = mLabels.value
  const defs = [
    { title: '渠道 UV 月度趋势', desc: '各渠道 UV（万）', series: chSeries('uv', 10000), dec: 1,
      note: 'UV 月度差值反映投放节奏与季节波动，关注环比拐点与渠道结构变化。' },
    { title: '渠道转化率月度趋势', desc: '各渠道转化率（%）', series: chSeries('cvr'), dec: 2,
      note: '转化率提升来自详情页与定价优化；下降需排查流量精准度与库存可售率。' },
    { title: '渠道非付费流量占比月度趋势', desc: '各渠道非付费流量占比（%）', series: chSeries('organic'), dec: 1,
      note: '非付费占比上升说明自然流量与品牌心智在积累，对应营销费用的摊薄空间。' },
    { title: '渠道 CPC 月度趋势', desc: '各渠道单位广告成本（元 / 付费 UV）', series: chSeries('cpc'), dec: 2,
      note: 'CPC 走高需结合转化率一并判断：CVR 同步提升时获客成本可能仍在改善区间。' },
  ]
  return defs.map((d) => ({
    title: d.title,
    desc: d.desc + ' ｜ ' + labels[0] + ' ~ ' + labels[labels.length - 1],
    note: d.note,
    svg: lineChart(labels, d.series, { w: 540, h: 230, endLabel: true, dec: d.dec }),
  }))
})
</script>

<template>
  <div class="ana-traffic">
    <AnaKitNote title="流量分析口径：">各渠道 UV 由「渠道订单量 ÷ 渠道转化率」反推：转化率优先取营销板块 <AnaKitCode code="S1.2" />「转化率」分渠道填报值，未填报回落渠道结构基准；因此 <b>UV × 转化率 ≡ 订单量</b>。付费 UV = UV ×（1 − 非付费流量占比），非付费流量占比优先取 <AnaKitCode code="S1.8" /> 分渠道填报值。单位广告成本 <b>CPC = 营销费用 ÷ 付费 UV</b>，<AnaKitCode code="F4.1" /> 营销费用率按渠道反比于流量效率分摊，与「渠道效益分析」的营销费用列逐渠道一致。转化率越高、非付费占比越高、CPC 越低，说明该渠道的流量效率越好。</AnaKitNote>

    <div class="grid-4 kpis">
      <AnaKitKpi data-kpi="uv" label="渠道总 UV" :value="fmt(cm.uv / 10000, 1)" unit="万" :foot="`覆盖 ${CHANNELS.length} 个渠道`" />
      <AnaKitKpi data-kpi="cvr" label="综合转化率 CVR" :value="fmt(cm.cvr, 2)" unit="%">
        <template #foot>
          <template v-if="cvrFilled">营销板块 <AnaKitCode code="S1.2" /> 填报值（分渠道加权）</template>
          <template v-else>结构基准（<AnaKitCode code="S1.2" /> 待填报）</template>
        </template>
      </AnaKitKpi>
      <AnaKitKpi data-kpi="organic" label="非付费流量占比" :value="fmt(cm.organic, 1)" unit="%" :foot="`付费 UV ${fmt(cm.paidUv / 10000, 1)} 万`" />
      <AnaKitKpi data-kpi="cpc" label="综合 CPC" :value="fmt(cm.cpc, 2)" unit="元" tone="fin" :foot="`营销费用 ${fmt(cm.mkt, 0)} 万元`" />
    </div>

    <AnaKitCard title="渠道流量与转化结构" desc="UV：万 ｜ 营销费用：万元 ｜ CPC：元">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>渠道</th><th class="num">UV</th><th class="num">UV 占比</th><th class="num">付费 UV</th>
              <th class="num">非付费占比</th><th class="num">订单量</th><th class="num">转化率</th>
              <th class="num">营销费用</th><th class="num">CPC</th><th class="num">营销费用率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.channel">
              <td class="strong">{{ r.channel }}</td>
              <td class="num">{{ fmt(r.uv / 10000, 1) }}</td>
              <td class="num">{{ fmt(r.uv / totalUv * 100, 1) }}%</td>
              <td class="num">{{ fmt(r.paidUv / 10000, 1) }}</td>
              <td class="num" :style="hiLo(r.organic >= cm.organic)">{{ fmt(r.organic, 1) }}%</td>
              <td class="num">{{ fmt(r.orders, 0) }}</td>
              <td class="num" :style="hiLo(r.cvr >= cm.cvr)">{{ fmt(r.cvr, 2) }}%</td>
              <td class="num">{{ fmt(r.mkt, 0) }}</td>
              <td class="num" :style="hiLo(r.cpc > cm.cpc)">{{ fmt(r.cpc, 2) }}</td>
              <td class="num">{{ fmt(r.mktRate, 1) }}%</td>
            </tr>
            <tr class="total" data-test="total">
              <td>合计</td>
              <td class="num">{{ fmt(T.uv / 10000, 1) }}</td><td class="num">100.0%</td>
              <td class="num">{{ fmt(T.paid / 10000, 1) }}</td>
              <td class="num">{{ fmt(cm.organic, 1) }}%</td>
              <td class="num">{{ fmt(T.ord, 0) }}</td><td class="num">{{ fmt(cm.cvr, 2) }}%</td>
              <td class="num">{{ fmt(T.mkt, 0) }}</td>
              <td class="num">{{ fmt(cm.cpc, 2) }}</td>
              <td class="num">{{ fmt(T.rev > 0 ? T.mkt / T.rev * 100 : 0, 1) }}%</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>
        CPC 最低渠道为 <b>{{ best.channel }}</b>（{{ fmt(best.cpc, 2) }} 元，非付费占比 {{ fmt(best.organic, 1) }}%），最高为 <b>{{ worst.channel }}</b>（{{ fmt(worst.cpc, 2) }} 元，非付费占比 {{ fmt(worst.organic, 1) }}%），两者相差 {{ fmt(worst.cpc / (best.cpc || 1), 1) }} 倍。CPC 高的渠道应优先做详情页转化优化（提高 CVR）与自然流量占比提升，而非单纯压缩投放预算。
      </AnaKitChartNote>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard v-for="d in trendDefs" :key="d.title" :title="d.title" :desc="d.desc">
        <SvgChart :svg="d.svg" :label="d.title" />
        <AnaKitLegend :items="chLegend" />
        <AnaKitChartNote>{{ d.note }}</AnaKitChartNote>
      </AnaKitCard>
    </div>
  </div>
</template>

<style scoped>
.kpis { margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
</style>
