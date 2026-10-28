<script setup lang="ts">
/**
 * 品类分析（原 viewCategoryAnalysis）：品类的在售 SPU / 销量 / 品效 ｜ 年度上新销售占比 ｜ SPU 毛利 TOP / Bottom 10。
 * 数据来自引擎 catModel / yearMixRows / buildSpuTable（SPU、件均价、上市年份结构为推算示例数据）。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import {
  C, CATEGORIES, CAT_COLOR, MONTHS9, NEW_YEARS, PROV_COLOR, buildSpuTable, catModel, fmt, mSeries, orderModel, yearMixRows,
  type CatModelRow, type SpuRow,
} from '@/bizfin/engine'
import { lineChart, stack100 } from '@/bizfin/charts'
import { TREND_COLOR, hiLo, signTrend, trendStyle, type Trend } from './AnaKit'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import AnaKitNote from './AnaKitNote.vue'

type CatField = 'spu' | 'qty' | 'perSpu'
const isNewYear = (label: string): boolean => label.indexOf('2025') >= 0 || label.indexOf('2026') >= 0

const catM = computed(() => mSeries((m) => catModel(m)))
const cat = computed(() => catModel())
const ym = computed(() => yearMixRows())
const ymByM = computed(() => mSeries((m) => yearMixRows(m)))
const totalSpu = computed(() => cat.value.reduce((a, r) => a + r.spu, 0))
const totalQty = computed(() => cat.value.reduce((a, r) => a + r.qty, 0))
const totalRev = computed(() => cat.value.reduce((a, r) => a + r.revenue, 0))
const totalGross = computed(() => cat.value.reduce((a, r) => a + r.gross, 0))
const orders = computed(() => orderModel().total)
const topPer = computed(() => cat.value.slice().sort((a, b) => b.perSpu - a.perSpu)[0])
const newShareNow = computed(() => ym.value.filter((r) => isNewYear(r.label)).reduce((a, r) => a + r.share, 0))
const avgPer = computed(() => totalRev.value / (totalSpu.value || 1))
const sorted = computed(() => cat.value.slice().sort((a, b) => b.revenue - a.revenue))

const catLegend = CATEGORIES.map((c) => ({ name: c, color: CAT_COLOR[c] }))
function catLine(field: CatField, dec: number): string {
  return lineChart(
    MONTHS9,
    CATEGORIES.map((c) => ({
      name: c,
      color: CAT_COLOR[c],
      values: catM.value.map((rs) => {
        const r: CatModelRow | undefined = rs.find((x) => x.cat === c)
        return r ? r[field] : 0
      }),
      dec,
    })),
    { w: 600, h: 266, dots: false, endLabel: true, dec },
  )
}
const spuSvg = computed(() => catLine('spu', 0))
const qtySvg = computed(() => catLine('qty', 0))
const perSvg = computed(() => catLine('perSpu', 1))

/* 月度新品 / 老品收入占比（新品 = 2025/2026 上新；老品 = 2024 年及以前） */
/* 新品 / 老品是分类，不用红绿（避免与涨跌语义冲突） */
const newOldLegend = [{ name: '新品（滚动）', color: C.biz }, { name: '老品', color: C.text3 }]
const newOldSvg = computed(() => {
  const byM = ymByM.value.map((rows) => {
    const nw = rows.filter((r) => isNewYear(r.label)).reduce((a, r) => a + r.share, 0)
    return { nw, old: 100 - nw }
  })
  return stack100(MONTHS9, [
    { name: '新品（滚动）', color: C.biz, values: byM.map((x) => x.nw) },
    { name: '老品', color: C.text3, values: byM.map((x) => x.old) },
  ], { w: 600, h: 266, bw: 34 })
})
const yearLegend = NEW_YEARS.map((y, i) => ({ name: y, color: PROV_COLOR[i % PROV_COLOR.length] }))
const yearSvg = computed(() =>
  stack100(MONTHS9, NEW_YEARS.map((y, i) => ({
    name: y, color: PROV_COLOR[i % PROV_COLOR.length], values: ymByM.value.map((rs) => rs[i].money),
  })), { w: 880, h: 252 }),
)

/* SPU 粒度：TOP 10 / Bottom 10（自原「产品效益」板块并入，按毛利率排序） */
const spus = computed(() => buildSpuTable())
const topN = computed(() => spus.value.slice(0, 10))
const botN = computed(() => spus.value.slice(-10).reverse())
/* 涨红跌绿口径（与渠道效益同档）：SPU 毛利率 ≥25% 高档红 / 15–25% 中性 / <15% 低档绿，TOP / Bottom 两表同一规则 */
function spuTrend(r: SpuRow): Trend {
  return r.grossRate >= 0.25 ? 'up' : r.grossRate >= 0.15 ? 'flat' : 'down'
}
</script>

<template>
  <div class="ana-category">
    <AnaKitNote title="品类分析口径：">件均价 = 综合客单价 × 品类相对价指数（按渠道口径近似），<AnaKitCode code="F2.1" />~<AnaKitCode code="F2.5" /> 的品类收入结构经校准满足 <b>Σ（收入份额 ÷ 相对价）= 1</b>，因此 <b>销量合计 ≡ 订单量</b>（件单比 1.00），且销量加权件均价 ≡ 客单价。在售 SPU 按「基础 SKU + 年内上新 SKU − 结构性下架」逐月演进；<b>品效 = 品类收入 ÷ 在售 SPU 数</b>，衡量单个 SKU 的产出效率。上市年份销售占比按各品类的年份结构矩阵 （2023 年及以前 / 2024 / 2025 / 2026 上新）加权得到，合计恒为 100%。</AnaKitNote>

    <div class="grid-4 kpis">
      <AnaKitKpi data-kpi="spu" label="在售 SPU 合计" :value="fmt(totalSpu, 0)" unit="个" :foot="`${CATEGORIES.length} 个品类 · 日均在架结构`" />
      <AnaKitKpi data-kpi="qty" label="销量合计" :value="fmt(totalQty / 10000, 2)" unit="万件"
        :foot="`件单比 ${fmt(totalQty / (orders || 1), 2)}（1 单 1 件）`" />
      <AnaKitKpi data-kpi="topPer" label="品效最高品类" :value="topPer.cat" tone="up" compact
        :foot="`${fmt(topPer.perSpu, 1)} 万元 / SPU · 在售 ${fmt(topPer.spu, 0)} 个`" />
      <AnaKitKpi data-kpi="newShare" label="2025/2026 新品销售占比" :value="fmt(newShareNow, 1)" unit="%" tone="biz" foot="新品驱动型增长结构" />
    </div>

    <AnaKitCard title="品类经营明细" desc="收入：万元 ｜ 件均价：元 ｜ 品效：万元/SPU">
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr>
              <th>品类</th><th class="num">在售 SPU</th><th class="num">销量（件）</th><th class="num">件均价</th>
              <th class="num">收入</th><th class="num">收入占比</th><th class="num">品效</th>
              <th class="num">贡献毛利率</th><th class="num">贡献毛利额</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in sorted" :key="r.cat">
              <td class="strong">{{ r.cat }}</td>
              <td class="num">{{ fmt(r.spu, 0) }}</td>
              <td class="num">{{ fmt(r.qty, 0) }}</td>
              <td class="num">{{ fmt(r.price, 0) }}</td>
              <td class="num">{{ fmt(r.revenue, 0) }}</td>
              <td class="num">{{ fmt(r.share, 1) }}%</td>
              <td class="num" :style="hiLo(r.perSpu >= avgPer)">{{ fmt(r.perSpu, 1) }}</td>
              <td class="num" :style="hiLo(r.grossRate >= 5)">{{ fmt(r.grossRate, 1) }}%</td>
              <td class="num" :style="trendStyle(signTrend(r.gross))">{{ r.gross >= 0 ? '+' : '' }}{{ fmt(r.gross, 0) }}</td>
            </tr>
            <tr class="total" data-test="total">
              <td>合计</td>
              <td class="num">{{ fmt(totalSpu, 0) }}</td><td class="num">{{ fmt(totalQty, 0) }}</td>
              <td class="num">{{ fmt(totalQty > 0 ? totalRev * 10000 / totalQty : 0, 0) }}</td>
              <td class="num">{{ fmt(totalRev, 0) }}</td><td class="num">100.0%</td>
              <td class="num">{{ fmt(avgPer, 1) }}</td>
              <td class="num">{{ fmt(totalRev > 0 ? totalGross / totalRev * 100 : 0, 1) }}%</td>
              <td class="num" :style="{ color: TREND_COLOR[signTrend(totalGross)] }">{{ totalGross >= 0 ? '+' : '' }}{{ fmt(totalGross, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>
        品效高于均值（{{ fmt(avgPer, 1) }} 万元/SPU）的品类应在 SKU 拓展与资源投放上优先倾斜；品效低但毛利率高的品类（如浴室柜）应通过精简 SKU、聚焦畅销型号来提升单 SKU 产出。
      </AnaKitChartNote>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard title="各品类每月在售 SPU 数量" desc="单位：个">
        <AnaKitLegend :items="catLegend" />
        <SvgChart :svg="spuSvg" label="各品类每月在售 SPU 数量" />
        <AnaKitChartNote>年内上新 SKU 逐步上架、结构性长尾 SKU 逐步下架，在售 SPU 数量呈"先升后稳"的演进曲线。</AnaKitChartNote>
      </AnaKitCard>
      <AnaKitCard title="各品类每月销量" desc="单位：件">
        <AnaKitLegend :items="catLegend" />
        <SvgChart :svg="qtySvg" label="各品类每月销量" />
        <AnaKitChartNote>销量与件均价反向变动：大促月份（件均价指数下行）销量抬升，是"以价换量"的直接体现。</AnaKitChartNote>
      </AnaKitCard>
    </div>

    <div class="grid-2">
      <AnaKitCard title="各品类月度品效趋势" desc="品效 = 当月收入 ÷ 在售 SPU（万元 / SPU）">
        <AnaKitLegend :items="catLegend" />
        <SvgChart :svg="perSvg" label="各品类月度品效趋势" />
        <AnaKitChartNote>品效 = 单品产出效率，是"精简 SKU + 聚焦爆款"策略的量化依据；大促月份收入抬升带动品效上行，需结合在售 SPU 数量同步解读。</AnaKitChartNote>
      </AnaKitCard>
      <AnaKitCard title="月度新品与老品收入占比" desc="每根 100% ｜ 新品（滚动）vs 老品">
        <AnaKitLegend :items="newOldLegend" />
        <SvgChart :svg="newOldSvg" label="月度新品与老品收入占比" />
        <AnaKitChartNote>新品合计贡献 {{ fmt(newShareNow, 1) }}% 的收入，是收入增量的主要来源；老品占比随新品替代节奏逐月变化，需通过换代升级与老品清仓策略控制占比与库存风险。</AnaKitChartNote>
      </AnaKitCard>
    </div>

    <AnaKitCard title="年度上新销售占比月度趋势" desc="每根 100%，观察新品对收入的替代节奏">
      <AnaKitLegend :items="yearLegend" />
      <SvgChart :svg="yearSvg" label="年度上新销售占比月度趋势" />
      <AnaKitChartNote>新品占比逐月上行说明产品迭代有效；若老品占比长期高企，则意味着产品线老化、需加快新品导入与老品汰换节奏。</AnaKitChartNote>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard title="TOP 10 最高毛利 SPU" :desc="`按毛利率降序 ｜ 净收入万元 ｜ 共 ${spus.length} 个 SPU`">
        <div class="table-wrap">
          <table class="table" data-test="spu-top">
            <thead><tr><th>SPU 编码</th><th>品类</th><th class="num">净收入（万元）</th><th class="num">毛利率</th></tr></thead>
            <tbody>
              <tr v-for="r in topN" :key="r.code">
                <td class="strong">{{ r.code }}</td><td>{{ r.cat }}</td>
                <td class="num">{{ fmt(r.revenue, 0) }}</td>
                <td class="num" :style="trendStyle(spuTrend(r))">{{ fmt(r.grossRate * 100, 1) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </AnaKitCard>
      <AnaKitCard title="Bottom 10 最低毛利 SPU" desc="按毛利率升序 ｜ 净收入万元">
        <div class="table-wrap">
          <table class="table" data-test="spu-bottom">
            <thead><tr><th>SPU 编码</th><th>品类</th><th class="num">净收入（万元）</th><th class="num">毛利率</th></tr></thead>
            <tbody>
              <tr v-for="r in botN" :key="r.code">
                <td class="strong">{{ r.code }}</td><td>{{ r.cat }}</td>
                <td class="num">{{ fmt(r.revenue, 0) }}</td>
                <td class="num" :style="trendStyle(spuTrend(r))">{{ fmt(r.grossRate * 100, 1) }}%</td>
              </tr>
            </tbody>
          </table>
        </div>
      </AnaKitCard>
    </div>

    <AnaKitNote title="SPU 效益说明：">SPU 粒度毛利率在品类毛利率基线（财务 F1/F2/F3 按产品板块结构权重分摊）上叠加确定性扰动派生，与品类整体毛利率保持量级一致；TOP / Bottom 仅看毛利率维度，可结合上方「品类经营明细」中的品效与销量权重交叉印证。</AnaKitNote>
  </div>
</template>

<style scoped>
.kpis { margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
</style>
