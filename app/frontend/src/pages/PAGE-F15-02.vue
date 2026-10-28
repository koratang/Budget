<script setup lang="ts">
/**
 * 财务指标 PAGE-F15-02：由原工作台 viewFinance + indicatorTable('fin') + renderFinRow 原样移植。
 * 实际值单元格可直接编辑（年度维度写年度累计；月度维度写当月覆盖并反算年度累计），改后保存「财务与业务指标」部分。
 */
import { computed, ref } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { useToast } from '@/components/g1/useToast'
import {
  NAV, S, children, deptOf, editCell, find, fmt, hasData, isBlankBiz, jsNum, l1, l2, momYoyOf, pct, periodLabel,
  rate, yearOf, type Indicator,
} from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

const desc = NAV.find((n) => n.id === 'finance')?.sub
const { toast, show } = useToast()

type Filter = 'all' | 'l1' | 'l2'
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: '全部' }, { id: 'l1', label: '仅一级' }, { id: 'l2', label: '仅二级' },
]
const finFilter = ref<Filter>('all')
const finSearch = ref('')

function need(code: string): Indicator {
  const i = find(code)
  if (!i) throw new Error('缺少指标 ' + code)
  return i
}

/* 环比 / 同比单元格：有利变动标红（up）、不利标绿（down），同原工具 */
interface Delta { text: string; cls: string }
function deltaOf(i: Indicator, v: number | null): Delta {
  if (v === null || isNaN(v)) return { text: '—', cls: 'muted' }
  const good = i.dir === 1 ? v >= 0 : v <= 0
  return { text: (v >= 0 ? '+' : '') + fmt(v, 1) + '%', cls: good ? 'up' : 'down' }
}

/* ---------- KPI（F1-F7） ---------- */
const kpis = computed(() => ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7'].map((c) => {
  const i = need(c)
  const blank = !hasData(i)
  const my = blank ? { mom: null, yoy: null } : momYoyOf(i)
  const cell = (v: number | null, lab: string): Delta => {
    const d = deltaOf(i, v)
    return { text: lab + ' ' + d.text, cls: d.cls }
  }
  return {
    i,
    val: blank ? '—' : fmt(i.actual, (i.unit === '%' || i.unit === '天') ? 1 : 0),
    mom: cell(my.mom, '环比'),
    yoy: cell(my.yoy, '同比'),
  }
}))

/* ---------- 明细表（原 indicatorTable('fin') + renderFinRow） ---------- */
/* recompute 每次都会按公式覆盖的财务派生指标（F4.9 期间费用合计、F7.3 应收、F7.5 存货、F7.7 应付），手工改了也会被重算 */
const ENGINE_DERIVED = new Set(['F4.9', 'F7.3', 'F7.5', 'F7.7'])
/** 千分位显示，保留原始小数位（输入框内仍为原始数值便于编辑） */
function thou(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(v)) return '—'
  const dec = (String(v).split('.')[1] || '').length
  return fmt(v, dec)
}
interface Row {
  i: Indicator
  blank: boolean
  hasOv: boolean
  /** 派生值（维度聚合 / 渠道毛利标记 / 引擎公式），同原工具 readonly，不给输入框 */
  derived: boolean
  value: string
  shown: string
  mom: Delta
  yoy: Delta
}
function finRow(i: Indicator): Row {
  const src = yearOf(i)
  const m = S.curM - 1
  const hasOv = S.dim === 'month' && ((src._ova !== undefined && src._ova[m] !== undefined) || (src._ovt !== undefined && src._ovt[m] !== undefined))
  const my = momYoyOf(i)
  return {
    i, hasOv,
    blank: isBlankBiz(i),
    derived: !!src._dimAgg || !!src._chanEdited || ENGINE_DERIVED.has(i.code),
    value: i.actual === null || i.actual === undefined ? '' : String(i.actual),
    shown: thou(i.actual),
    mom: deltaOf(i, my.mom),
    yoy: deltaOf(i, my.yoy),
  }
}
const rows = computed<Row[]>(() => {
  const q = finSearch.value.trim().toLowerCase()
  const hit = (i: Indicator): boolean => !q || i.name.toLowerCase().includes(q) || i.code.toLowerCase().includes(q) ||
    deptOf(i).toLowerCase().includes(q)
  const out: Row[] = []
  l1('fin').forEach((p) => {
    const kidsHit = children(p.code).filter(hit)
    const pHit = hit(p)
    if (finFilter.value === 'l2') { kidsHit.forEach((c) => out.push(finRow(c))); return }
    if (finFilter.value === 'l1') { if (pHit) out.push(finRow(p)); return }
    if (pHit || kidsHit.length) {
      out.push(finRow(p))
      kidsHit.forEach((c) => out.push(finRow(c)))
    }
  })
  return out
})
const counts = computed(() => ({ l1: l1('fin').length, l2: l2('fin').length }))
const monthTitle = computed(() => S.dim === 'month' ? periodLabel() + ' 月度实际（可直接编辑）' : '年度累计实际（可直接编辑）')

/* 实际值单元格编辑（原 document change 事件委托） */
function onEdit(e: Event, code: string): void {
  const el = e.target as HTMLInputElement
  const it = find(code)
  if (!it || !store.canEdit) return
  try {
    editCell(code, 'actual', el.value)
  } catch (err) {
    el.value = it.actual === null || it.actual === undefined ? '' : String(it.actual)
    show(err instanceof Error ? err.message : String(err))
    return
  }
  commit('indicators')
  show(S.dim === 'month'
    ? code + ' 的 ' + periodLabel() + ' 月度实际值已更新，年度累计值已同步反算，其余月份保持不变'
    : code + ' 实际值 已更新，相关指标与建议已重新计算')
}

/* ---------- 财务视角关键提示 ---------- */
const hints = computed(() => {
  const F1 = need('F1'), F3 = need('F3'), F4 = need('F4'), F7 = need('F7'), F49 = need('F4.9')
  const F41 = need('F4.1'), F74 = need('F7.4'), F76 = need('F7.6')
  const a = (i: Indicator): number => jsNum(i.actual)
  const t = (i: Indicator): number => jsNum(i.target)
  return [
    { st: rate(F3) >= 95 ? 'ok' : 'warn', ic: '!', t: '毛利率缺口 ' + fmt(t(F3) - a(F3), 1) + 'pt',
      d: '对应毛利损失约 ' + fmt(a(F1) * (t(F3) - a(F3)) / 100, 1) + ' 万元，需供应中心与产品作战部联合改善。' },
    /* 修正：原工具这里用 F4（净利润，万元）的实际 − 目标当作期间费用率偏差，得出「超标 −766.1pt」这类无意义数字；
       期间费用率是 F4.9（期间费用率合计，%，逆向指标），超标 = 实际 − 目标，达成率也按 F4.9 判断 */
    { st: rate(F49) >= 95 ? 'ok' : 'err', ic: '×', t: '期间费用率超标 ' + fmt(a(F49) - t(F49), 1) + 'pt',
      d: '主要来自营销费用率（' + pct(F41.actual) + ' vs 目标 ' + pct(F41.target) + '），核心驱动是广告 ACOS 偏高。' },
    { st: rate(F76) >= 90 ? 'ok' : 'warn', ic: '!', t: '存货周转天数超目标 ' + fmt(a(F76) - t(F76), 0) + ' 天',
      d: '占用资金约 ' + fmt((a(F76) - t(F76)) * (a(F1) * (1 - a(F3) / 100)) / 365, 0) + ' 万元，直接压制经营净现金流。' },
    { st: rate(F4) >= 80 ? 'ok' : 'err', ic: '×', t: '净利润达成率仅 ' + fmt(rate(F4), 0) + '%',
      d: '收入完成 ' + fmt(rate(F1), 0) + '%、利润完成 ' + fmt(rate(F4), 0) + '%，呈"增收不增利"特征，成本与费用端需专项治理。' },
    { st: rate(F74) >= 90 ? 'ok' : 'warn', ic: '!', t: '应收账期超目标 ' + fmt(a(F74) - t(F74), 0) + ' 天',
      d: '建议对分销客户设置信用额度红线，超期停单，并把资金成本计入长账期报价。' },
    { st: rate(F7) >= 90 ? 'ok' : 'warn', ic: '!', t: '经营净现金流达成率 ' + fmt(rate(F7), 0) + '%',
      d: '利润含金量不足，需同步压降存货与应收两端营运资本占用。' },
  ]
})
</script>

<template>
  <BizfinPage page-id="PAGE-F15-02" :sections="['indicators']" title="财务指标" :desc="desc">
    <div class="kpi-grid section">
      <div v-for="k in kpis" :key="k.i.code" class="card kpi" :data-kpi="k.i.code">
        <div class="kpi-label">{{ k.i.name }} <span class="code-tag">{{ k.i.code }}</span></div>
        <div class="kpi-val">{{ k.val }}<span class="u">{{ k.i.unit }}</span></div>
        <div class="kpi-foot"><span :class="k.mom.cls">{{ k.mom.text }}</span><span :class="k.yoy.cls">{{ k.yoy.text }}</span></div>
      </div>
    </div>

    <section class="card section">
      <div class="card-title head-wrap">
        <span>财务指标体系明细
          <span class="small muted sub">{{ counts.l1 }} 个一级 · {{ counts.l2 }} 个二级 ｜ 实际值单元格可直接点击编辑 ｜ 环比 / 同比自动计算（年度维度：同比 vs 去年；月度维度：环比 vs 上月、同比 vs 去年同月）</span>
        </span>
        <span class="tools">
          <span class="seg" role="group" aria-label="层级筛选">
            <button v-for="f in FILTERS" :key="f.id" type="button" :aria-pressed="finFilter === f.id" @click="finFilter = f.id">{{ f.label }}</button>
          </span>
          <input v-model="finSearch" class="input" placeholder="搜索指标 / 部门" aria-label="搜索指标 / 部门">
        </span>
      </div>
      <div v-if="rows.length" class="table-wrap">
        <table class="table" data-testid="fin-table">
          <thead>
            <tr>
              <th style="width: 34px">层级</th><th style="width: 56px">编码</th><th>指标名称</th>
              <th style="width: 110px" class="num">实际值</th><th style="width: 70px" class="num">环比</th>
              <th style="width: 70px" class="num">同比</th><th style="width: 58px">单位</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.i.code" :class="{ lv1: r.i.level === 1 }" :data-code="r.i.code">
              <td><span class="badge" :class="r.i.level === 1 ? 'badge-info' : ''">{{ r.i.level === 1 ? '一级' : '二级' }}</span></td>
              <td class="code-tag">{{ r.i.code }}</td>
              <td class="name">
                {{ r.i.name }}
                <span v-if="r.i.dir === -1" class="badge" title="逆向指标：越低越好">逆向</span>
                <span v-if="r.derived" class="badge badge-info" data-derived title="该值由派生公式自动计算">派生</span>
                <span v-if="r.blank" class="badge" title="真实台账填报前不参与达成率计算">待填报</span>
                <span v-if="S.dim === 'month'" class="badge badge-info" :title="`该值为 ${periodLabel()} 的月度口径`">月度</span>
                <span v-if="r.hasOv" class="badge badge-bad" title="该月为手工填报值，已参与年度累计反算">手工填报</span>
              </td>
              <td class="num">
                <input
                  v-if="store.canEdit && !r.derived"
                  class="cell-input"
                  :value="r.value"
                  placeholder="—"
                  :title="monthTitle"
                  :aria-label="`${r.i.code} ${r.i.name} 实际值`"
                  :data-c="r.i.code"
                  data-f="actual"
                  @change="onEdit($event, r.i.code)"
                >
                <span v-else class="cell-text" :class="{ derived: r.derived }">{{ r.shown }}</span>
              </td>
              <td class="num"><b :class="r.mom.cls">{{ r.mom.text }}</b></td>
              <td class="num"><b :class="r.yoy.cls">{{ r.yoy.text }}</b></td>
              <td class="small muted">{{ r.i.unit }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty">没有匹配的指标，请调整筛选条件或搜索关键词。</div>
    </section>

    <section class="card section">
      <div class="card-title"><span>财务视角关键提示 <span class="small muted sub">基于当前指标偏差自动生成</span></span></div>
      <div class="chk-list">
        <div v-for="(h, n) in hints" :key="n" class="chk" :class="h.st">
          <span class="ic" aria-hidden="true">{{ h.ic }}</span>
          <div><div class="t">{{ h.t }}</div><div class="d">{{ h.d }}</div></div>
        </div>
      </div>
    </section>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </BizfinPage>
</template>

<style scoped>
.kpi-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(178px, 1fr)); gap: var(--space-4); }
.kpi { border-top: 3px solid var(--success); }
.kpi-val { font-size: var(--text-2xl); font-weight: 700; margin-top: var(--space-1); font-variant-numeric: tabular-nums; }
.kpi-val .u { font-size: var(--text-xs); font-weight: 400; color: var(--muted); margin-left: 3px; }
.kpi-foot { display: flex; gap: var(--space-2); flex-wrap: wrap; margin-top: var(--space-2); font-size: var(--text-xs); color: var(--muted); font-weight: 600; }
.sub { font-weight: 400; margin-left: var(--space-2); }
.head-wrap { flex-wrap: wrap; }
.tools { display: flex; gap: var(--space-2); align-items: center; }
tr.lv1 td { background: var(--surface-warm); font-weight: 600; }
td.name { white-space: normal; }
td.name .badge { margin-left: var(--space-1); height: 18px; }
/* 可编辑单元格常显细边框 + 浅底，与派生 / 只读纯文本一眼可分 */
.cell-input { width: 100px; height: 26px; border: 1px solid var(--border); background: color-mix(in oklab, var(--accent), white 96%); border-radius: var(--radius-md); padding: 0 6px; font: inherit; text-align: right; font-variant-numeric: tabular-nums; color: var(--fg); cursor: text; transition: border-color var(--motion-fast) var(--ease-standard), background var(--motion-fast) var(--ease-standard); }
.cell-input:hover { border-color: var(--muted); background: var(--surface); }
.cell-input:focus-visible { outline: none; border-color: var(--accent); background: var(--surface); box-shadow: var(--focus-ring); }
.cell-text { display: inline-block; padding: 0 7px; font-variant-numeric: tabular-nums; }
.cell-text.derived { color: var(--fg-2); }
.empty { text-align: center; color: var(--muted); padding: var(--space-6) var(--space-4); }
.chk-list { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: var(--space-2); }
.chk { display: flex; align-items: flex-start; gap: var(--space-2); padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); }
.chk .ic { width: 17px; height: 17px; border-radius: 50%; flex: 0 0 17px; display: flex; align-items: center; justify-content: center; font-size: 10px; font-weight: 800; color: var(--accent-on); margin-top: 2px; }
.chk.ok .ic { background: var(--success); }
.chk.warn .ic { background: var(--warn); }
.chk.err .ic { background: var(--danger); }
.chk .t { font-size: var(--text-sm); font-weight: 600; }
.chk .d { font-size: var(--text-xs); color: var(--fg-2); line-height: 1.65; }
</style>
