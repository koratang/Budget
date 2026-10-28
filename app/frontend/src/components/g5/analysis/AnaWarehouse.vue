<script setup lang="ts">
/**
 * 数据分析 · 仓储分析（原 viewWarehouseAnalysis）：海外仓仓储成本总额月度趋势 ｜ 渠道仓储成本占比月度趋势 ｜ 海外仓库存数据。
 * 仓储费用池取 costPools().warehouse（F1 × F4.5），× (1 + 代发系数 0.35) 为含代发口径；
 * 库存流水：出库 ≡ 订单量（件单比 1.00），入库 = 出库 × 前置备货系数；KPI 与库存表随维度切换。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import { lineChart, type LineSeries } from '@/bizfin/charts'
import {
  CHANNELS, CH_COLOR, MONTHS9, S, WH_PROVIDERS, channelRowsAt, costPools, fmt, mSeries, orderModel, provColor, wave, whChShares,
  type Provider,
} from '@/bizfin/engine'

/* 海外仓 4 座（自有仓广州为国内集货仓，不计入海外仓口径）；HANDLING = 代发费用系数 */
const WH_HANDLING = 0.35
const WH_OVERSEAS = WH_PROVIDERS.filter((pr) => pr.name.indexOf('自有仓') < 0)
const whName = (pr: Provider): string => pr.name.replace(/（/g, '·').replace(/）/g, '')
const ovShareBase = WH_OVERSEAS.reduce((a, pr) => a + pr.share, 0)
/* 前置备货系数（入库 = 出库 × 系数） */
const STOCK_IN_IDX = [1.28, 1.22, 1.15, 1.10, 1.08, 1.12, 1.18, 1.15, 1.12]
const sum = (arr: number[]): number => arr.reduce((a, b) => a + b, 0)
/* 最大余数法：把整数 total 按份额拆成整数，且各份之和恰好等于 total */
function allocInt(total: number, shares: number[]): number[] {
  const tot = sum(shares) || 1
  const raw = shares.map((sh) => total * sh / tot)
  const out = raw.map((x) => Math.floor(x))
  let rest = total - sum(out)
  raw.map((x, i) => ({ i, frac: x - Math.floor(x) })).sort((a, b) => b.frac - a.frac).forEach((r) => {
    if (rest > 0) { out[r.i] += 1; rest -= 1 }
  })
  return out
}

const v = computed(() => {
  const p = costPools()
  const whByM = mSeries((m) => costPools(m).warehouse)
  const revByM = mSeries((m) => costPools(m).rev)
  const ordByM = mSeries((m) => orderModel(m).total)
  const mN = S.curM || 9
  const mLabels = MONTHS9.slice(0, mN)

  /* ---- 库存流水模型（件）：出库 = 订单量（件单比 1.00）｜入库 = 出库 × 前置备货系数 ---- */
  const inByM = ordByM.map((x, m) => Math.round(x * STOCK_IN_IDX[m]))
  const outByM = ordByM.map((x) => Math.round(x))
  const openByM: number[] = [], closeByM: number[] = []
  let opening = 22000
  for (let m = 0; m < 9; m++) {
    openByM.push(opening)
    opening = opening + inByM[m] - outByM[m]
    closeByM.push(opening)
  }

  /* 海外仓份额（月度确定性波动后重归一，仅 4 座海外仓） */
  const ovSharesByM = mSeries(function (m) {
    const js = WH_OVERSEAS.map((pr) => pr.share * wave('ps-' + pr.name, 0.08)(m))
    const tot = sum(js) || 1
    return js.map((x) => x / tot)
  })
  /* 海外仓月度仓储成本总额（含代发，万元）= 月度仓储池 × (1+代发系数) × 海外仓份额 ÷ 海外仓基础份额占比 */
  const whCostSeries: LineSeries[] = WH_OVERSEAS.map(function (pr, i) {
    return { name: whName(pr), color: provColor(i), values: mSeries((m) => whByM[m] * (1 + WH_HANDLING) * ovSharesByM[m][i] / ovShareBase) }
  })

  /* 渠道仓储成本占比（占该渠道收入 %） */
  const chRateSeries: LineSeries[] = CHANNELS.map(function (c) {
    return {
      name: c, color: CH_COLOR[c], values: mSeries(function (m) {
        const r = channelRowsAt(m).filter((x) => x.key === c)[0]
        const wh = whByM[m] * (1 + WH_HANDLING) * (whChShares(m)[c] || 0)
        return (r && r.revenue > 0) ? wh / r.revenue * 100 : 0
      }),
    }
  })

  /* ---- KPI 与库存表（维度感知）：年度 = 年初期初 + 1~curM 月累计入/出库 + curM 月末期末；月度 = 当月流水 ---- */
  const curIdx = Math.min((S.curM || 9) - 1, 8)
  const isMonth = S.dim === 'month'
  const whCostNow = isMonth ? whByM[curIdx] * (1 + WH_HANDLING) : p.warehouse * (1 + WH_HANDLING)
  const revRef = isMonth ? revByM[curIdx] : p.rev
  const whRateNow = revRef > 0 ? whCostNow / revRef * 100 : 0
  const kOpen = isMonth ? openByM[curIdx] : openByM[0]
  const kIn = isMonth ? inByM[curIdx] : sum(inByM.slice(0, mN))
  const kOut = isMonth ? outByM[curIdx] : sum(outByM.slice(0, mN))
  const kClose = closeByM[curIdx]

  /* 海外仓库存数据表（期初 / 入库 / 出库 / 期末，各仓按当月份额拆分）
     取整口径与 KPI 一致：先取 KPI 的合计整数，再用最大余数法拆到各仓（各仓之和 ≡ KPI，不再出现 22,000 对 21,999 的取整差）；
     各仓期末 = 期初 + 入库 − 出库，因此逐行勾稽成立，且期末合计 ≡ KPI 期末。 */
  const shRef = ovSharesByM[curIdx]
  const openSp = allocInt(kOpen, shRef), inSp = allocInt(kIn, shRef), outSp = allocInt(kOut, shRef)
  const stockRows = WH_OVERSEAS.map((pr, i) => ({
    name: whName(pr),
    open: openSp[i],
    in: inSp[i],
    out: outSp[i],
    close: openSp[i] + inSp[i] - outSp[i],
  }))
  const stockSum = stockRows.reduce(function (a, r) {
    a.open += r.open; a.in += r.in; a.out += r.out; a.close += r.close; return a
  }, { open: 0, in: 0, out: 0, close: 0 })

  const legend = (ss: LineSeries[]): { name: string; color: string }[] => ss.map((s) => ({ name: s.name ?? '', color: s.color }))
  return {
    isMonth, whCostNow, whRateNow, kOpen, kIn, kOut, kClose, stockRows, stockSum,
    mLabel: S.curM || 9,
    period: isMonth ? '当月（' + MONTHS9[curIdx] + '）' : '年初至 ' + MONTHS9[curIdx] + '末累计',
    whSvg: lineChart(mLabels, whCostSeries, { w: 540, h: 240, endLabel: false, dec: 1 }), whLegend: legend(whCostSeries),
    chSvg: lineChart(mLabels, chRateSeries, { w: 540, h: 240, endLabel: true, dec: 2 }), chLegend: legend(chRateSeries),
  }
})
</script>

<template>
  <div data-ana-view="anaWarehouse">
    <!-- 6 张 KPI 用 g5.css 的 grid-3 排成整齐的 3×2（窄屏自动降为 2 列 / 1 列） -->
    <div class="grid-3 kpi-grid">
      <AnaKitKpi
        label="仓储成本总额" :value="fmt(v.whCostNow, 1)" unit="万元" tone="fin" data-kpi="cost"
        :foot="(v.isMonth ? '当月 · ' : '全年累计 · ') + '仓储 ' + fmt(v.whCostNow / (1 + WH_HANDLING), 1) + ' + 代发 ' + fmt(v.whCostNow * WH_HANDLING / (1 + WH_HANDLING), 1)"
      />
      <AnaKitKpi label="仓储成本占比" :value="fmt(v.whRateNow, 2)" unit="%" foot="仓储成本（含代发）÷ 营业收入" data-kpi="rate" />
      <AnaKitKpi label="期初库存数量" :value="fmt(v.kOpen, 0)" unit="件" :foot="v.isMonth ? '当月月初 4 仓合计' : '年初库存 4 仓合计'" tone="biz" data-kpi="open" />
      <AnaKitKpi label="入库数量" :value="fmt(v.kIn, 0)" unit="件" :foot="(v.isMonth ? '当月入库' : '1-' + v.mLabel + ' 月累计入库') + ' · 含前置备货'" data-kpi="in" />
      <AnaKitKpi label="出库数量" :value="fmt(v.kOut, 0)" unit="件" :foot="(v.isMonth ? '当月出库' : '1-' + v.mLabel + ' 月累计出库') + ' · ≡ 订单量（件单比 1.00）'" data-kpi="out" />
      <AnaKitKpi label="期末库存数量" :value="fmt(v.kClose, 0)" unit="件" foot="期初 + 入库 − 出库 · 4 仓合计" tone="warn" data-kpi="close" />
    </div>

    <div class="grid-2">
      <AnaKitCard title="海外仓仓储成本总额月度趋势" desc="单位：万元 ｜ 含仓储费用 + 代发费用（代发系数 0.35）">
        <SvgChart :svg="v.whSvg" label="海外仓仓储成本总额月度趋势" />
        <AnaKitLegend :items="v.whLegend" />
        <AnaKitChartNote>万邑通（美西仓）体量最大且单价最优；成本上行主要来自前置库存量增加而非单价上涨。</AnaKitChartNote>
      </AnaKitCard>
      <AnaKitCard title="渠道仓储成本占比月度趋势" desc="各渠道仓储成本（含代发）÷ 该渠道收入（%）">
        <SvgChart :svg="v.chSvg" label="渠道仓储成本占比月度趋势" />
        <AnaKitLegend :items="v.chLegend" />
        <AnaKitChartNote>仓储占比越高说明该渠道越依赖海外仓前置备货；需与尾程费率联动看——前置库存抬高仓储但压低尾程，决策依据应为「仓储 + 尾程」合计费率。</AnaKitChartNote>
      </AnaKitCard>
    </div>

    <AnaKitCard title="海外仓库存数据" :desc="'单位：件 ｜ ' + v.period + ' ｜ 4 座海外仓'">
      <div class="table-wrap">
        <table class="table" data-testid="stock-table">
          <thead>
            <tr>
              <th>海外仓</th><th class="num">期初库存数量</th><th class="num">入库数量</th><th class="num">出库数量</th><th class="num">期末库存数量</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in v.stockRows" :key="r.name">
              <td class="strong">{{ r.name }}</td>
              <td class="num">{{ fmt(r.open, 0) }}</td>
              <td class="num">{{ fmt(r.in, 0) }}</td>
              <td class="num">{{ fmt(r.out, 0) }}</td>
              <td class="num strong">{{ fmt(r.close, 0) }}</td>
            </tr>
            <tr class="total">
              <td>合计</td>
              <td class="num">{{ fmt(v.stockSum.open, 0) }}</td>
              <td class="num">{{ fmt(v.stockSum.in, 0) }}</td>
              <td class="num">{{ fmt(v.stockSum.out, 0) }}</td>
              <td class="num">{{ fmt(v.stockSum.close, 0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>勾稽：期初 + 入库 − 出库 = 期末，逐行与合计均成立。出库 ≡ 订单量（件单比 1.00），入库 = 出库 × 前置备货系数（1.08 ~ 1.28），旺季前主动加大补货；切到月度维度可看各仓单月流水。</AnaKitChartNote>
    </AnaKitCard>
  </div>
</template>

<style scoped>
.kpi-grid { gap: var(--space-3); margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
</style>
