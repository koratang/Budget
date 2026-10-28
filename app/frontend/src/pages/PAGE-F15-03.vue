<script setup lang="ts">
/**
 * 业务指标 PAGE-F15-03（原工具 viewBusiness → viewBusinessOverview）
 * 逐板块：二级指标明细表（实际值可编辑）+ 分维度填报矩阵（渠道 / 品类 / 线路），末尾为业财联动摘要。
 * 编辑沿用原「表格编辑」事件委托：维度单元格 → editDimCell；指标实际值 → editCell（月度维度下写月度覆盖）。
 */
import { computed } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { useToast } from '@/components/g1/useToast'
import {
  BIZ_DIMS, BIZ_DIM_ORDER, DIM_SKIP_MAP, LINKAGE, S,
  bizDimAgg, bizDimFilled, bizDimOf, bizFilledStat, children, decOf, editCell, editDimCell,
  find, fmt, hasData, l1, l2, periodLabel, yearOf,
  type Indicator, type ValueField,
} from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

const { toast, show } = useToast()

/** 达成率分档（同引擎 healthColor：≥100 优 / ≥90 良 / ≥80 预警 / 其余 落后）→ 平台令牌色 */
function tone(r: number): string {
  return r >= 100 ? 't-good' : r >= 90 ? 't-info' : r >= 80 ? 't-warn' : 't-bad'
}

/* ---------------- 体系与数据状态 ---------------- */
const stat = computed(() => {
  const l2All = l2('biz')
  const dimInds = l2All.filter((i) => (i.dims || []).length)
  let dimTotal = 0, dimFilled = 0
  dimInds.forEach((i) => {
    ;(i.dims || []).forEach((dk) => {
      const D = BIZ_DIMS[dk]
      if (!D) return
      dimTotal += D.members.length
      dimFilled += bizDimFilled(i.code)
    })
  })
  return { filled: l2All.filter(hasData).length, total: l2All.length, dimFilled, dimTotal }
})

/* ---------------- 板块：明细表 + 维度矩阵 ---------------- */
interface Matrix { dimKey: string; label: string; members: string[]; actualOnly: boolean; inds: Indicator[] }
interface Board { p: Indicator; kids: Indicator[]; fill: { filled: number; total: number }; matrices: Matrix[] }

const boards = computed<Board[]>(() =>
  l1('biz').map((p) => {
    const kids = children(p.code)
    const skip = DIM_SKIP_MAP[p.code]
    const matrices: Matrix[] = []
    BIZ_DIM_ORDER.forEach((dk) => {
      const inds = kids.filter((i) => (i.dims || []).indexOf(dk) >= 0)
      const D = BIZ_DIMS[dk]
      if (!inds.length || !D || (skip && skip.has(dk))) return
      const actualOnly = (p.code === 'S1' && dk === 'channel') || (p.code === 'S2' && dk === 'category') || (p.code === 'S4' && dk === 'lane')
      matrices.push({ dimKey: dk, label: D.label, members: D.members, actualOnly, inds })
    })
    return { p, kids, fill: bizFilledStat(p.code), matrices }
  }),
)

/** 填报状态徽标（原 bizFillPill） */
function fillBadge(st: { filled: number; total: number }): { cls: string; text: string } {
  if (!st.total) return { cls: '', text: '—' }
  if (!st.filled) return { cls: 'badge-bad', text: `待填报 0/${st.total}` }
  if (st.filled >= st.total) return { cls: 'badge-good', text: `已填报 ${st.filled}/${st.total}` }
  return { cls: 'badge-warn', text: `填报中 ${st.filled}/${st.total}` }
}

function matrixDesc(m: Matrix): string {
  const head = `行 = ${m.label}（${m.members.join(' / ')}）｜ 列 = 指标 ｜ `
  return head + (m.actualOnly ? '填实际值即可，留空即「待填报」' : '单元格上格填目标值、下格填实际值，留空即「待填报」')
}

/** 矩阵单元格的填报字段：仅实际值矩阵只有下格 */
const fieldsOf = (m: Matrix): ValueField[] => (m.actualOnly ? ['actual'] : ['target', 'actual'])

const cellVal = (code: string, dk: string, mb: string, f: ValueField): string => {
  const v = bizDimOf(code, dk, mb)[f]
  return v === null || v === undefined ? '' : String(v)
}

/** 单个维度单元格的达成率（原 dimCellRate） */
function cellRate(i: Indicator, dk: string, mb: string): { text: string; cls: string; title?: string } {
  const c = bizDimOf(i.code, dk, mb)
  if (c.actual === null || c.actual === undefined) return { text: '—', cls: 'muted' }
  if (c.target === null || c.target === undefined || !c.target) return { text: '待设目标', cls: 'muted', title: '目标值未填报，无法计算达成率' }
  let r = i.dir === -1 ? (c.actual > 0 ? c.target / c.actual * 100 : 0) : c.actual / c.target * 100
  r = Math.min(130, Math.max(0, r))
  return { text: fmt(r, 0) + '%', cls: tone(r) + ' strong' }
}

function aggText(i: Indicator, dk: string): string | null {
  const a = bizDimAgg(i.code, dk, 'actual')
  return a === null ? null : `${fmt(a, decOf(i))} ${i.unit}`
}

/* ---------------- 业财联动摘要 ---------------- */
const links = computed(() =>
  LINKAGE.slice().sort((a, b) => b.strength - a.strength).map((l) => {
    const it = find(l.biz)
    let now: string | null = '—'
    if (it) now = hasData(it) ? `${fmt(it.actual, decOf(it))} ${it.unit} / 目标 ${fmt(it.target, decOf(it))} ${it.unit}` : null
    return { l, now }
  }),
)
/** 强度条配色（原 barMini：≥0.7 红 / ≥0.5 橙 / 其余灰） */
const strengthCls = (v: number): string => (v >= 0.7 ? 'bar-bad' : v >= 0.5 ? 'bar-warn' : 'bar-muted')

/* ---------------- 编辑 ---------------- */
const inputOf = (e: Event): HTMLInputElement => e.target as HTMLInputElement

/** 维度单元格（原 change 事件 .dcell 分支） */
function onDimCell(e: Event, code: string, dk: string, mb: string, f: ValueField): void {
  const el = inputOf(e)
  const y = yearOf(find(code))
  const before = y ? [y.actual, y.target, y._dimAgg] : null
  try {
    editDimCell(code, dk, mb, f, el.value)
  } catch (err) {
    show(err instanceof Error ? err.message : String(err))
    el.value = cellVal(code, dk, mb, f)
    return
  }
  const yy = yearOf(find(code))
  const after = yy ? [yy.actual, yy.target, yy._dimAgg] : null
  const aggChanged = JSON.stringify(before) !== JSON.stringify(after)
  /* 维度值聚合回填为指标整体值时，指标部分一并保存 */
  commit(aggChanged ? ['biz_dim', 'indicators'] : 'biz_dim')
  const cleared = bizDimOf(code, dk, mb)[f] === null
  const label = BIZ_DIMS[dk] ? BIZ_DIMS[dk].label : '维度'
  show(`${code} 的${label}【${mb}】${f === 'target' ? '目标值' : '实际值'}` +
    (cleared ? '已清空（该指标整体值将与维度填报值重新聚合）' : '已更新，指标整体值与板块达成率已同步重算'))
}

/** 指标实际值（原 change 事件 .cell-input 分支） */
function onActual(e: Event, i: Indicator): void {
  const el = inputOf(e)
  const month = S.dim === 'month'
  try {
    editCell(i.code, 'actual', el.value)
  } catch (err) {
    show(err instanceof Error ? err.message : String(err))
    el.value = i.actual === null || i.actual === undefined ? '' : String(i.actual)
    return
  }
  commit('indicators')
  show(month
    ? `${i.code} 的 ${periodLabel()} 月度实际值已更新，年度累计值已同步反算，其余月份保持不变`
    : `${i.code} 实际值 已更新，相关指标与建议已重新计算`)
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-03" :sections="['indicators', 'biz_dim']" title="业务指标" desc="一级 / 二级业务指标体系 · 驱动因子与达成追踪">
    <div class="note card" data-testid="biz-note">
      <b>业务指标体系（4 板块）：</b>
      <code>S1</code> 营销板块（<b>分渠道</b>：Amazon / Wayfair / Home Depot / Lowe's / 独立站）｜
      <code>S2</code> 产品板块（<b>分品类</b>：框镜 / 灯镜 / 镜柜 / 其他）｜
      <code>S3</code> 供应链板块（采购周期<b>分品类</b>）｜
      <code>S4</code> 仓配履约板块（单位头程成本<b>分线路</b>：美东 / 美西 / 英国 / 欧洲；单位仓储费用、单位操作费用<b>分服务商</b>：A / B / C）。<br>
      <b>数据状态：</b>真实台账就绪前全部指标留空，页面显示「—」，避免以 0 拉低板块健康度。
      当前已填报 <b data-testid="filled-stat">{{ stat.filled }} / {{ stat.total }}</b> 项二级指标。<b data-testid="dim-stat">{{ stat.dimFilled }} / {{ stat.dimTotal }}</b> 个维度单元格已填报。
      可在下方矩阵中逐格填报，或在「<RouterLink :to="{ name: 'bizfin-data' }">数据管理</RouterLink>」中按「<code>编码, 维度, 实际值</code>」批量导入。
    </div>

    <template v-for="b in boards" :key="b.p.code">
      <section class="card section" :data-board="b.p.code">
        <div class="card-title">
          <span>{{ b.p.name }} <span class="code-tag">{{ b.p.code }}</span></span>
          <span class="badge" :class="fillBadge(b.fill).cls">{{ fillBadge(b.fill).text }}</span>
        </div>
        <p class="small muted desc">{{ b.p.note }}</p>
        <div class="table-wrap">
          <table class="table">
            <thead>
              <tr><th>编码</th><th>指标名称</th><th>单位</th><th class="num">实际值</th><th>责任部门</th></tr>
            </thead>
            <tbody>
              <tr v-for="i in b.kids" :key="i.code" :data-code="i.code">
                <td class="code-tag">{{ i.code }}</td>
                <td>
                  {{ i.name }}
                  <span v-if="i.dir === -1" class="badge" title="逆向指标：越低越好">逆向</span>
                  <span v-if="i._dimAgg" class="badge badge-info" title="整体值由分维度填报值聚合回填">维度派生</span>
                </td>
                <td class="small muted">{{ i.unit }}</td>
                <td class="num">
                  <input
                    v-if="store.canEdit && !i._dimAgg"
                    class="input cell" :value="i.actual ?? ''" placeholder="—"
                    :aria-label="`${i.code} ${i.name} 实际值`"
                    :title="`${i.code} 年度整体实际值`"
                    @change="onActual($event, i)"
                  >
                  <span v-else :title="i._dimAgg ? '由分维度填报值聚合回填；如需手工覆盖，请先清空维度矩阵中的填报值' : undefined" data-actual>
                    {{ i.actual === null || i.actual === undefined ? '—' : i.actual }}
                  </span>
                </td>
                <td class="small muted">{{ (i.depts || []).join(' / ') || '—' }}</td>
              </tr>
              <tr class="total">
                <td colspan="3">板块合计</td>
                <td class="small" data-testid="board-fill">{{ b.fill.filled }} / {{ b.fill.total }} 项二级已填报</td>
                <td>{{ b.p.depts.join(' / ') || '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section v-for="m in b.matrices" :key="b.p.code + m.dimKey" class="card section" :data-matrix="`${b.p.code}-${m.dimKey}`">
        <div class="card-title"><span>{{ b.p.name }} · 分{{ m.label }}矩阵</span></div>
        <p class="small muted desc">{{ matrixDesc(m) }}</p>
        <div class="table-wrap">
          <table class="table matrix">
            <thead>
              <tr>
                <th>{{ m.label }}</th>
                <th v-for="i in m.inds" :key="i.code" class="num">
                  {{ i.name }}<br><small class="muted">{{ i.code }} ｜ {{ i.unit }}{{ i.dir === -1 ? ' ｜ 逆向' : '' }}</small>
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="mb in m.members" :key="mb">
                <td class="dim">{{ mb }}</td>
                <td v-for="i in m.inds" :key="i.code" class="dcell-td">
                  <div class="dc-pair">
                    <template v-for="f in fieldsOf(m)" :key="f">
                      <input
                        v-if="store.canEdit"
                        class="input dcell" :value="cellVal(i.code, m.dimKey, mb, f)"
                        :placeholder="f === 'target' ? '目标' : '实际'"
                        :aria-label="`${mb} · ${i.name} ${f === 'target' ? '目标值' : '实际值'}`"
                        :title="`${mb} · ${i.name} ${f === 'target' ? '目标值' : '实际值'}`"
                        @change="onDimCell($event, i.code, m.dimKey, mb, f)"
                      >
                      <span v-else class="dcell-ro" :class="{ muted: cellVal(i.code, m.dimKey, mb, f) === '' }" :title="`${mb} · ${i.name} ${f === 'target' ? '目标值' : '实际值'}`">
                        {{ cellVal(i.code, m.dimKey, mb, f) || (f === 'target' ? '目标 —' : '—') }}
                      </span>
                    </template>
                  </div>
                  <div v-if="!m.actualOnly" class="dcr" :class="cellRate(i, m.dimKey, mb).cls" :title="cellRate(i, m.dimKey, mb).title">
                    {{ cellRate(i, m.dimKey, mb).text }}
                  </div>
                </td>
              </tr>
              <tr class="total">
                <td>合计 / 均值</td>
                <td v-for="i in m.inds" :key="i.code" :data-agg="i.code">
                  <span v-if="aggText(i, m.dimKey) === null" class="small muted">未填报 → 整体值待填报</span>
                  <span v-else class="small">整体值 <b>{{ aggText(i, m.dimKey) }}</b></span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p class="small muted chart-note">
          <b>聚合口径：</b>加总型指标（UV「万」、社媒产出「万元」、上架 SPU「款」）在维度成员间<b>求和</b>；
          比率型指标（%、元、天、倍）在维度成员间取<b>算术平均</b>。聚合值自动回填为该指标的年度整体值，
          形成「维度填报 → 指标整体 → 业财联动」的勾稽链路。在汇总格手工填报该指标整体值时，以手工值为准（优先级高于维度聚合）。
        </p>
      </section>
    </template>

    <section class="card section" data-testid="linkage-summary">
      <div class="card-title">
        <span>业务指标 → 财务指标 联动摘要</span>
        <span class="small muted">共 {{ LINKAGE.length }} 条，按关联强度排序</span>
      </div>
      <div class="table-wrap">
        <table class="table">
          <thead>
            <tr><th>业务指标</th><th>传导至财务指标</th><th>方向</th><th>强度</th><th>业务现状</th><th>责任部门</th></tr>
          </thead>
          <tbody>
            <tr v-for="{ l, now } in links" :key="l.biz + l.fin">
              <td><span class="code-tag">{{ l.biz }}</span> {{ l.bizName }}</td>
              <td><span class="code-tag">{{ l.fin }}</span> {{ l.finName }}</td>
              <td class="strong" :class="l.dir === '正向' ? 'up' : 'down'">{{ l.dir }}</td>
              <td>
                <span class="mini-prog"><span class="bar"><i :class="strengthCls(l.strength)" :style="{ width: Math.round(l.strength * 100) + '%' }" /></span>{{ (l.strength * 100).toFixed(0) }}%</span>
              </td>
              <td class="small"><span v-if="now === null" class="badge">待填报</span><template v-else>{{ now }}</template></td>
              <td class="small muted">{{ l.dept }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </BizfinPage>
</template>

<style scoped>
.note { margin-bottom: var(--space-4); font-size: var(--text-sm); line-height: 1.8; color: var(--fg-2); }
.note code { font-family: var(--font-mono); font-size: var(--text-xs); color: var(--accent); }
.desc { margin: calc(-1 * var(--space-2)) 0 var(--space-3); }
.strong { font-weight: 600; }
.badge { margin-left: var(--space-1); }
.input.cell { width: 110px; height: 28px; text-align: right; }
.matrix td { vertical-align: top; padding-top: 6px; padding-bottom: 6px; height: auto; }
/* 维度矩阵列头为右对齐（.num），单元格内输入框 / 只读值 / 达成率同样靠右，与列头对齐 */
.matrix td.dcell-td { text-align: right; }
.dc-pair { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; }
.input.dcell { width: 96px; height: 26px; text-align: right; font-size: var(--text-xs); }
.dcell-ro { display: inline-block; min-width: 96px; text-align: right; font-variant-numeric: tabular-nums; }
.dcr { margin-top: 2px; text-align: right; font-size: var(--text-xs); }
.chart-note { margin: var(--space-3) 0 0; line-height: 1.7; }
.mini-prog { display: inline-flex; align-items: center; gap: 6px; font-size: var(--text-xs); }
.mini-prog .bar { display: inline-block; width: 48px; height: 6px; border-radius: var(--radius-pill); background: var(--border-soft); overflow: hidden; }
.mini-prog i { display: block; height: 100%; }
.bar-bad { background: var(--danger); }
.bar-warn { background: var(--warn); }
.bar-muted { background: var(--muted); }
.t-good { color: var(--success); }
.t-info { color: var(--accent); }
.t-warn { color: var(--warn); }
.t-bad { color: var(--danger); }
</style>
