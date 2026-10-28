<script setup lang="ts">
/**
 * 数据分析 · 管理费用分析（原 viewAdminAnalysis）：各部门月度费用发生额 × 费用类型。
 * 口径：管理费用池 = 营业收入 F1 × F4.7 管理费用率；部门 / 费用类型仅提供分摊权重，Σ部门 ≡ Σ类型 ≡ 管理费用池；
 * 月度拆分按「当月收入 × 当月费率」并整体归一校准，1-9 月合计精确等于年度池（逐月勾稽）。计算全部取引擎 adminMatrix 等。
 */
import { computed } from 'vue'
import SvgChart from '@/components/g5/SvgChart.vue'
import AnaKitCard from './AnaKitCard.vue'
import AnaKitChartNote from './AnaKitChartNote.vue'
import AnaKitCode from './AnaKitCode.vue'
import AnaKitKpi from './AnaKitKpi.vue'
import AnaKitLegend from './AnaKitLegend.vue'
import AnaKitNote from './AnaKitNote.vue'
import { COMBO_BAR_COLOR, HALF_W, comboChart, hBarChart, lineChart, stack100 } from '@/bizfin/charts'
import {
  ADMIN_DEPTS, ADMIN_D_COLOR, ADMIN_TYPES, ADMIN_T_COLOR, C, MONTHS9, S, YEAR_LABEL,
  adminAnnualPool, adminMatrix, adminMatrixNow, adminPoolByM, find, fmt, iv, jsNum, mSeries, periodLabel,
  type AdminRow,
} from '@/bizfin/engine'

const sum = (arr: number[]): number => arr.reduce((a, b) => a + b, 0)
/* 部门的主导费用类型（发生额最大的类型） */
const mainTypeOf = (row: AdminRow): string => ADMIN_TYPES[row.types.indexOf(Math.max(...row.types))].name
/* 柱色：同一常量既传给 comboChart 也用于图例，保证一致 */
const BAR_COLOR = COMBO_BAR_COLOR

const v = computed(() => {
  const poolM = adminPoolByM()
  const mm = mSeries((m) => adminMatrix(m)) /* 月度矩阵序列 */
  const annual = adminMatrix(null) /* 年度累计矩阵 */
  const snap = adminMatrixNow() /* 当前维度快照 */
  const poolAnnual = adminAnnualPool()
  const poolNow = sum(snap.map((r) => r.total))
  const f43 = find('F4.7')
  const f43Actual = jsNum(f43?.actual), f43Target = jsNum(f43?.target)
  const rateM = mSeries((m) => jsNum(iv('F4.7', m)))
  const isMonth = S.dim === 'month'

  /* 部门月度发生额：deptByM[dept].byM[m] */
  const deptByM = ADMIN_DEPTS.map((d, i) => ({ dept: d.name, byM: mm.map((mt) => mt[i].total) }))
  /* 费用类型月度发生额：typeByM[t].byM[m] = Σ各部门 */
  const typeByM = ADMIN_TYPES.map((t, ti) => ({ type: t.name, byM: mm.map((mt) => sum(mt.map((r) => r.types[ti]))) }))
  /* 年度累计的类型合计与部门合计 */
  const typeAnnual = ADMIN_TYPES.map((_t, ti) => sum(annual.map((r) => r.types[ti])))
  const topTypeIdx = typeAnnual.indexOf(Math.max(...typeAnnual))
  const deptAnnualTot = annual.map((r) => r.total)
  const topDeptIdx = deptAnnualTot.indexOf(Math.max(...deptAnnualTot))
  const typeSnap = ADMIN_TYPES.map((_t, ti) => sum(snap.map((r) => r.types[ti])))

  const rateGap = f43Actual - f43Target /* 逆向指标：低于目标为优 */

  /* 主要部门（发生额最大的 5 个）月度趋势 */
  const topDepts = annual
    .map((r, i) => ({ name: r.dept, color: ADMIN_D_COLOR[r.dept], values: deptByM[i].byM, dec: 1 }))
    .sort((a, b) => sum(b.values) - sum(a.values))
    .slice(0, 5)

  return {
    isMonth, poolM, annual, snap, poolAnnual, poolNow, f43Actual, f43Target, rateGap, rateM,
    deptByM, typeByM, typeAnnual, topTypeIdx, deptAnnualTot, topDeptIdx, typeSnap, topDepts,
    /* 4 张图都在半宽卡片里：画布宽 HALF_W，字号按画布宽度放大（见 charts.ts fontScale），渲染后不小于 11px */
    comboSvg: comboChart(MONTHS9, poolM, [{ color: C.fin, values: rateM }], { w: HALF_W, h: 260, barColor: BAR_COLOR }),
    stackSvg: stack100(MONTHS9, ADMIN_TYPES.map((t, ti) => ({ name: t.name, color: ADMIN_T_COLOR[t.name], values: typeByM[ti].byM })), { w: HALF_W, h: 260 }),
    hbarSvg: hBarChart(annual.map((r) => ({
      label: r.dept, value: r.total, color: ADMIN_D_COLOR[r.dept],
      text: fmt(r.total, 1) + ' · ' + mainTypeOf(r) + ' ' + fmt(Math.max(...r.types) / r.total * 100, 0) + '%',
    })).sort((a, b) => b.value - a.value), { w: HALF_W, labelW: 96, rowH: 30, rightW: 176 }),
    lineSvg: lineChart(MONTHS9, topDepts, { w: HALF_W, h: 260, dec: 1, dots: false, endLabel: true }),
  }
})

const typeLegend = ADMIN_TYPES.map((t) => ({ name: t.name, color: ADMIN_T_COLOR[t.name] }))
const comboLegend = [{ name: '管理费用（万元）', color: BAR_COLOR }, { name: '管理费用率（%）', color: C.fin }]
const share = (x: number, base: number): string => fmt(base > 0 ? x / base * 100 : 0, 1) + '%'
</script>

<template>
  <div data-ana-view="anaAdmin">
    <AnaKitNote title="管理费用分析口径：">
      管理费用池 = 营业收入 <AnaKitCode code="F1" /> × 管理费用占比 <AnaKitCode code="F4.7" />，部门与费用类型仅提供<b>分摊权重</b>，因此 <b>Σ部门发生额 ≡ Σ费用类型发生额 ≡ 管理费用池</b>。月度拆分按「当月收入 × 当月费率」计算并整体归一校准，使 1-9 月合计<b>精确等于</b>年度池；月度维度下本页部门 × 费用类型矩阵取选中月份，与月度发生额表同一列数字完全一致。
    </AnaKitNote>

    <div class="kpi-grid">
      <AnaKitKpi
        label="管理费用池" :value="fmt(v.poolNow, 1)" unit="万元" tone="fin" data-kpi="pool"
        :foot="v.isMonth ? periodLabel() + '发生额' : '年度累计 · 占收入 ' + fmt(v.f43Actual, 2) + '%'"
      />
      <AnaKitKpi
        label="管理费用率" :value="fmt(v.f43Actual, 2)" unit="%" :tone="v.rateGap <= 0 ? 'good' : 'bad'" data-kpi="rate"
        :foot="'目标 ' + fmt(v.f43Target, 1) + '% · ' + (v.rateGap <= 0 ? '优于目标 ' : '超出目标 ') + fmt(Math.abs(v.rateGap), 2) + 'pt'"
      />
      <AnaKitKpi
        label="发生额最高部门" :value="ADMIN_DEPTS[v.topDeptIdx].name" compact data-kpi="top-dept"
        :foot="fmt(v.deptAnnualTot[v.topDeptIdx], 1) + ' 万元 · 占比 ' + share(v.deptAnnualTot[v.topDeptIdx], v.poolAnnual)"
      />
      <AnaKitKpi
        label="占比最高费用类型" :value="ADMIN_TYPES[v.topTypeIdx].name" compact tone="warn" data-kpi="top-type"
        :foot="fmt(v.typeAnnual[v.topTypeIdx], 1) + ' 万元 · 占比 ' + share(v.typeAnnual[v.topTypeIdx], v.poolAnnual)"
      />
    </div>

    <AnaKitCard title="各部门月度费用发生额" desc="单位：万元 ｜ 年累计 = 1-9 月合计">
      <div class="table-wrap">
        <table class="table" data-testid="dept-month-table">
          <thead>
            <tr>
              <th>部门</th><th v-for="m in MONTHS9" :key="m" class="num">{{ m }}</th>
              <th class="num">年累计</th><th class="num">占比</th><th>主导费用类型</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(d, i) in v.deptByM" :key="d.dept">
              <td class="strong">{{ d.dept }}</td>
              <td v-for="(x, m) in d.byM" :key="m" class="num">{{ fmt(x, 1) }}</td>
              <td class="num strong">{{ fmt(v.annual[i].total, 1) }}</td>
              <td class="num">{{ share(v.annual[i].total, v.poolAnnual) }}</td>
              <td class="small">{{ mainTypeOf(v.annual[i]) }}</td>
            </tr>
            <tr class="total">
              <td>合计</td>
              <td v-for="(x, m) in v.poolM" :key="m" class="num">{{ fmt(x, 1) }}</td>
              <td class="num">{{ fmt(v.poolAnnual, 1) }}</td><td class="num">100.0%</td><td>—</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>合计行 = 管理费用池 = <AnaKitCode code="F1" /> × <AnaKitCode code="F4.7" /> = {{ fmt(v.poolAnnual, 1) }} 万元；月度合计已归一校准，与年度池逐分勾稽。人力薪酬类费用占比高的部门月度波动小，测试与合规费受认证周期影响集中在二、三季度。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="各费用类型月度发生额" desc="单位：万元 ｜ 行 = 费用类型，列 = 月份">
      <div class="table-wrap">
        <table class="table" data-testid="type-month-table">
          <thead>
            <tr>
              <th>费用类型</th><th v-for="m in MONTHS9" :key="m" class="num">{{ m }}</th>
              <th class="num">年累计</th><th class="num">占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(t, i) in v.typeByM" :key="t.type">
              <td class="strong"><span class="dot" :style="{ background: ADMIN_T_COLOR[t.type] }" />{{ t.type }}</td>
              <td v-for="(x, m) in t.byM" :key="m" class="num">{{ fmt(x, 1) }}</td>
              <td class="num strong">{{ fmt(v.typeAnnual[i], 1) }}</td>
              <td class="num">{{ share(v.typeAnnual[i], v.poolAnnual) }}</td>
            </tr>
            <tr class="total">
              <td>合计</td>
              <td v-for="(x, m) in v.poolM" :key="m" class="num">{{ fmt(x, 1) }}</td>
              <td class="num">{{ fmt(v.poolAnnual, 1) }}</td><td class="num">100.0%</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>费用类型列合计恒等于管理费用池；职工薪酬及社保为最大类型，属刚性支出；中介服务费（审计 / 法务 / 咨询）集中在财务部，测试与合规费与「政策环境」模块的欧盟合规投入同源。</AnaKitChartNote>
    </AnaKitCard>

    <AnaKitCard title="部门 × 费用类型发生额矩阵" :desc="'单位：万元 ｜ ' + (v.isMonth ? periodLabel() : YEAR_LABEL)">
      <div class="table-wrap">
        <table class="table" data-testid="matrix-table">
          <thead>
            <tr>
              <th>部门</th><th v-for="t in ADMIN_TYPES" :key="t.name" class="num">{{ t.name }}</th>
              <th class="num">合计</th><th class="num">占比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in v.snap" :key="r.dept">
              <td class="strong">{{ r.dept }}</td>
              <td v-for="(x, ti) in r.types" :key="ti" class="num">{{ fmt(x, 1) }}</td>
              <td class="num strong">{{ fmt(r.total, 1) }}</td>
              <td class="num">{{ share(r.total, v.poolNow) }}</td>
            </tr>
            <tr class="total">
              <td>合计</td>
              <td v-for="(x, ti) in v.typeSnap" :key="ti" class="num">{{ fmt(x, 1) }}</td>
              <td class="num">{{ fmt(v.poolNow, 1) }}</td><td class="num">100.0%</td>
            </tr>
          </tbody>
        </table>
      </div>
      <AnaKitChartNote>横向读：部门的费用类型结构（行合计 = 部门发生额）；纵向读：某费用类型在各部门的分布（列合计 = 类型发生额）。行合计与列合计的总额相等，均等于当期管理费用池 {{ fmt(v.poolNow, 1) }} 万元。</AnaKitChartNote>
    </AnaKitCard>

    <div class="grid-2">
      <AnaKitCard title="管理费用发生额与费用率月度趋势" desc="柱：发生额（万元）｜ 线：管理费用率（%）">
        <AnaKitLegend :items="comboLegend" />
        <SvgChart :svg="v.comboSvg" label="管理费用发生额与费用率月度趋势" />
        <AnaKitChartNote>管理费用率全年运行在 {{ fmt(Math.min(...v.rateM), 2) }}% ~ {{ fmt(Math.max(...v.rateM), 2) }}% 区间，低于目标 {{ fmt(v.f43Target, 1) }}%；发生额随收入季节性波动，费用率本身保持平稳，说明管理费用以固定成本为主。</AnaKitChartNote>
      </AnaKitCard>
      <AnaKitCard title="费用类型结构月度趋势" desc="每根 100%（分母 = 当月管理费用池）">
        <AnaKitLegend :items="typeLegend" />
        <SvgChart :svg="v.stackSvg" label="费用类型结构月度趋势" />
        <AnaKitChartNote>结构全年基本稳定：薪酬类占比 {{ fmt(v.typeAnnual[0] / v.poolAnnual * 100, 0) }}% 左右小幅波动，测试与合规费在三季度占比略有抬升（对应欧盟合规项目的集中投入）。</AnaKitChartNote>
      </AnaKitCard>
    </div>

    <div class="grid-2">
      <AnaKitCard title="部门管理费用年累计排序" desc="单位：万元">
        <SvgChart :svg="v.hbarSvg" label="部门管理费用年累计排序" />
        <AnaKitChartNote>人力资源部、财务部、总经办合计占 {{ fmt((v.deptAnnualTot[1] + v.deptAnnualTot[2] + v.deptAnnualTot[0]) / v.poolAnnual * 100, 1) }}%，是管理费用的主要发生部门；客服人效（<AnaKitCode code="S1.12" />）与视觉人效（<AnaKitCode code="S1.13" />）提升是摊薄固定管理费用的关键路径。</AnaKitChartNote>
      </AnaKitCard>
      <AnaKitCard title="主要部门月度发生额趋势" desc="发生额最大的 5 个部门，单位：万元">
        <AnaKitLegend :items="v.topDepts" />
        <SvgChart :svg="v.lineSvg" label="主要部门月度发生额趋势" />
        <AnaKitChartNote>各部门发生额形态与收入季节性一致但弹性更低：费用基数大的部门（人力资源部）曲线更平，差旅与合规类占比高的部门（供应中心、产品作战部）随项目节奏波动更明显。</AnaKitChartNote>
      </AnaKitCard>
    </div>
  </div>
</template>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: var(--space-3); margin-bottom: var(--space-4); }
.strong { font-weight: 700; }
.dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
</style>
