<script setup lang="ts">
/**
 * 用户分析（原 viewUserAnalysis）：不同渠道的新客和老客占比、客单价差异。
 * 数据来自引擎 channelModel（新客占比按渠道获客属性基准推算，属示例数据）。
 */
import { computed } from 'vue'
import { channelModel, fmt } from '@/bizfin/engine'
import { hiLo } from './AnaKit'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitNote from './AnaKitNote.vue'

const cm = computed(() => channelModel())
const rows = computed(() => cm.value.rows.slice().sort((a, b) => b.newShare - a.newShare))
const sum = computed(() =>
  cm.value.rows.reduce(
    (a, r) => {
      a.nord += r.newOrders; a.oord += r.oldOrders; a.nrev += r.newRevenue; a.orev += r.oldRevenue
      return a
    },
    { nord: 0, oord: 0, nrev: 0, orev: 0 },
  ),
)
const newRevSh = computed(() => (cm.value.revenue > 0 ? cm.value.newRevenue / cm.value.revenue * 100 : 0))
const aovNew = computed(() => cm.value.newRevenue * 10000 / (sum.value.nord || 1))
const aovOld = computed(() => (cm.value.revenue - cm.value.newRevenue) * 10000 / (sum.value.oord || 1))
const topNew = computed(() => rows.value[0])
const topTwo = computed(() => rows.value.slice(0, 2).map((r) => r.channel).join(' / '))
</script>

<template>
  <div class="ana-user">
    <AnaKitNote title="用户分析口径：">各渠道新客占比以渠道获客属性为基准（独立站 / Amazon 以新客为主，Home Depot / Lowe's 商超渠道以复购老客为主），叠加月度新客趋势指数后，<b>新客订单 + 老客订单 ≡ 渠道订单量</b>、<b>新客收入 + 老客收入 ≡ 渠道收入</b>；老客客单价 = 新客客单价 × 1.12（复购连带率更高的经验系数）。新客占比高说明渠道处于拉新期，老客占比高说明复购与用户资产更健康。</AnaKitNote>

    <div class="grid-4 kpis">
      <AnaKitKpi data-kpi="newShare" label="新客订单占比" :value="fmt(cm.newShare, 1)" unit="%" :foot="`新客订单 ${fmt(sum.nord, 0)} 单`" />
      <AnaKitKpi data-kpi="newRev" label="新客收入贡献" :value="fmt(newRevSh, 1)" unit="%" tone="biz"
        :foot="`${fmt(cm.newRevenue, 0)} 万元 / 合计 ${fmt(cm.revenue, 0)} 万元`" />
      <AnaKitKpi data-kpi="aovNew" label="新客客单价" :value="fmt(aovNew, 0)" unit="元" :foot="`老客客单价 ${fmt(aovOld, 0)} 元（+12%）`" />
      <AnaKitKpi data-kpi="topNew" label="新客占比最高渠道" :value="topNew.channel" tone="up" compact
        :foot="`新客占比 ${fmt(topNew.newShare, 1)}%，客单价 ${fmt(topNew.aov, 0)} 元`" />
    </div>

    <AnaKitCard title="渠道新客 / 老客结构" desc="金额：万元 ｜ 客单价：元">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>渠道</th><th class="num">新客占比</th><th class="num">老客占比</th>
              <th class="num">新客订单</th><th class="num">老客订单</th>
              <th class="num">新客收入</th><th class="num">老客收入</th>
              <th class="num">新客客单价</th><th class="num">老客客单价</th><th class="num">渠道客单价</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.channel">
              <td class="strong">{{ r.channel }}</td>
              <td class="num" :style="hiLo(r.newShare >= cm.newShare)">{{ fmt(r.newShare, 1) }}%</td>
              <td class="num">{{ fmt(r.oldShare, 1) }}%</td>
              <td class="num">{{ fmt(r.newOrders, 0) }}</td>
              <td class="num">{{ fmt(r.oldOrders, 0) }}</td>
              <td class="num">{{ fmt(r.newRevenue, 0) }}</td>
              <td class="num">{{ fmt(r.oldRevenue, 0) }}</td>
              <td class="num">{{ fmt(r.aovNew, 0) }}</td>
              <td class="num">{{ fmt(r.aovOld, 0) }}</td>
              <td class="num strong">{{ fmt(r.aov, 0) }}</td>
            </tr>
            <tr class="total" data-test="total">
              <td>合计</td>
              <td class="num">{{ fmt(cm.newShare, 1) }}%</td><td class="num">{{ fmt(100 - cm.newShare, 1) }}%</td>
              <td class="num">{{ fmt(sum.nord, 0) }}</td><td class="num">{{ fmt(sum.oord, 0) }}</td>
              <td class="num">{{ fmt(sum.nrev, 0) }}</td><td class="num">{{ fmt(sum.orev, 0) }}</td>
              <td class="num">{{ fmt(aovNew, 0) }}</td><td class="num">{{ fmt(aovOld, 0) }}</td>
              <td class="num">{{ fmt(cm.revenue * 10000 / (cm.orders || 1), 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>
        老客客单价普遍高于新客 12%，说明复购客户存在明确的连带购买与升级行为。对新客占比过高的渠道（{{ topTwo }}），应把次购转化率作为下一阶段核心考核项；对老客占比高的商超渠道，重点是通过上新与组合促销提升客单价。
      </AnaKitChartNote>
    </AnaKitCard>
  </div>
</template>

<style scoped>
.kpis { margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
</style>
