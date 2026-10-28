<script setup lang="ts">
/**
 * 业财联动关系 PAGE-F15-04：由原工作台 viewLinkage + barMini + linkTable 原样移植。
 * 联动图谱改为 Vue 模板绘制的 SVG（节点名称来自可导入的指标数据，不经 v-html），悬停节点高亮其关联路径。
 */
import { computed, ref } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import {
  C, LINKAGE, NAV, bizHealth, buildReverse, children, fmt, hasData, healthColor, isBlankBiz, l1, rate,
} from '@/bizfin/engine'

const desc = NAV.find((n) => n.id === 'linkage')?.sub

/** 达成率分档（同原 healthColor 四档），颜色走平台令牌 */
function tier(r: number): string {
  const c = healthColor(r)
  return c === C.down ? 't-good' : c === C.warn ? 't-warn' : c === C.up ? 't-bad' : 't-info'
}

/* 业务 4 板块 → 财务一级指标的传导关系（线宽 ∝ 关联强度，- 表示反向传导） */
const EDGES: { b: string; f: string; s: number; d: '+' | '-' }[] = [
  { b: 'S1', f: 'F1', s: 0.80, d: '+' }, { b: 'S1', f: 'F4', s: 0.55, d: '-' }, { b: 'S1', f: 'F3', s: 0.45, d: '+' },
  { b: 'S2', f: 'F1', s: 0.55, d: '+' }, { b: 'S2', f: 'F2', s: 0.50, d: '+' }, { b: 'S2', f: 'F7', s: 0.40, d: '+' },
  { b: 'S3', f: 'F2', s: 0.75, d: '+' }, { b: 'S3', f: 'F7', s: 0.45, d: '+' }, { b: 'S3', f: 'F7', s: 0.40, d: '+' },
  { b: 'S4', f: 'F4', s: 0.62, d: '-' }, { b: 'S4', f: 'F7', s: 0.65, d: '+' }, { b: 'S4', f: 'F1', s: 0.50, d: '+' },
]
const SAME = '#2563eb', REVERSE = '#e08600'
/* 节点宽 260：副标题（编码 · 二级数 · 部门）单独占第二行，达成率与名称同处第一行右侧，两者不再重叠；
   两列首个节点从 y=46 起，给列标题（y=30）留出完整一行 */
const W = 1040, lx = 18, lw = 260, rx = W - 18 - lw
const lTop = 46, lGap = 96, rTop = 46, rGap = 74

const graph = computed(() => {
  const bizL1 = l1('biz'), finL1 = l1('fin')
  const ly: Record<string, number> = {}, ry: Record<string, number> = {}
  bizL1.forEach((n, i) => { ly[n.code] = lTop + i * lGap })
  finL1.forEach((n, i) => { ry[n.code] = rTop + i * rGap })
  const H = Math.max(lTop + (bizL1.length - 1) * lGap + 52, rTop + (finL1.length - 1) * rGap + 52) + 16
  const edges = EDGES.filter((e) => ly[e.b] !== undefined && ry[e.f] !== undefined).map((e, idx) => {
    const y1 = ly[e.b] + 21, y2 = ry[e.f] + 20
    const x1 = lx + lw, x2 = rx
    const c1 = x1 + (x2 - x1) * 0.42, c2 = x1 + (x2 - x1) * 0.58
    return {
      key: idx, b: e.b, f: e.f, x2, y2,
      d: 'M' + x1 + ',' + y1 + ' C' + c1 + ',' + y1 + ' ' + c2 + ',' + y2 + ' ' + x2 + ',' + y2,
      color: e.d === '+' ? SAME : REVERSE,
      sw: (0.9 + e.s * 3.2).toFixed(2),
    }
  })
  const left = bizL1.map((n) => {
    const blank = isBlankBiz(n)
    return {
      code: n.code, name: n.name, y: ly[n.code],
      sub: n.code + ' · ' + children(n.code).length + ' 项二级 · ' + n.depts.slice(0, 2).join('/'),
      rate: blank ? '待填报' : fmt(rate(n), 0) + '%',
      cls: blank ? 't-blank' : tier(rate(n)),
    }
  })
  /* 未填报 / 无目标的财务指标（如 F6 净资产收益率）达成率无意义，节点显示「—」，与财务指标页同口径，不再显示「0%」；
     百分比指标实际值保留 1 位（31.4 而非 31.40），与 KPI 卡一致 */
  const right = finL1.map((n) => {
    const blank = !hasData(n) || !n.target
    return {
      code: n.code, name: n.name, y: ry[n.code],
      sub: n.code + ' · ' + n.unit + ' · 实际 ' + (hasData(n) ? fmt(n.actual, n.unit === '%' ? 1 : undefined) : '—'),
      rate: blank ? '—' : fmt(rate(n), 0) + '%',
      cls: blank ? 't-blank' : tier(rate(n)),
    }
  })
  const bh = bizHealth()
  return {
    H, edges, left, right,
    nBiz: bizL1.length, nFin: finL1.length,
    health: bh === null ? '业务指标待填报' : '业务健康度 ' + fmt(bh, 1) + '%',
    healthBlank: bh === null,
  }
})

/* 悬停高亮：悬停节点、与之相连的边和对侧节点保持高亮，其余淡出 */
const hover = ref<{ code: string; side: 'biz' | 'fin' } | null>(null)
const related = computed(() => {
  const h = hover.value
  if (!h) return null
  const edges = new Set<number>(), nodes = new Set<string>([h.side + ':' + h.code])
  graph.value.edges.forEach((e) => {
    if (h.side === 'biz' ? e.b === h.code : e.f === h.code) {
      edges.add(e.key)
      nodes.add(h.side === 'biz' ? 'fin:' + e.f : 'biz:' + e.b)
    }
  })
  return { edges, nodes }
})
const edgeCls = (key: number): string => !related.value ? '' : related.value.edges.has(key) ? 'hl' : 'dim'
const nodeCls = (side: string, code: string): string => !related.value ? '' : related.value.nodes.has(side + ':' + code) ? 'hl' : 'dim'


/** 财务偏差反向归因（期间费用率条已在引擎按 F4.9 修正） */
const reverse = computed(() => buildReverse())

/* ---------- 关联关系明细表（原 linkTable / barMini） ---------- */
const q = ref('')
const links = computed(() => {
  const s = q.value.trim().toLowerCase()
  return LINKAGE.filter((l) => !s || (l.bizName + l.finName + l.dept + l.biz + l.fin + l.logic).toLowerCase().includes(s))
})
/* 关联强度条：≥70% 强（红）、≥50% 中（橙）、其余弱（灰） */
const barCls = (v: number): string => v >= 0.7 ? 'b-strong' : v >= 0.5 ? 'b-mid' : 'b-weak'
</script>

<template>
  <BizfinPage page-id="PAGE-F15-04" :sections="['indicators', 'biz_dim']" title="业财联动关系" :desc="desc">
    <section class="card section">
      <div class="card-title head-wrap">
        <span>业财联动关系图谱 <span class="small muted sub">一级指标层面传导关系 ｜ 鼠标悬停节点可高亮其关联路径</span></span>
        <span class="pills">
          <span class="badge">{{ graph.nBiz }} 业务一级 → {{ graph.nFin }} 财务一级</span>
          <span class="badge">{{ EDGES.length }} 条主传导路径</span>
          <span class="badge" :class="{ 'badge-warn': graph.healthBlank }" data-health>{{ graph.health }}</span>
        </span>
      </div>
      <div class="graph-wrap">
        <svg :viewBox="`0 0 ${W} ${graph.H}`" preserveAspectRatio="xMidYMid meet" role="img" aria-label="业财联动关系图谱" @mouseleave="hover = null">
          <rect :x="lx - 8" y="10" :width="lw + 16" :height="graph.H - 20" rx="10" class="zone-biz" />
          <rect :x="rx - 8" y="10" :width="lw + 16" :height="graph.H - 20" rx="10" class="zone-fin" />
          <text :x="lx + lw / 2" y="30" text-anchor="middle" font-size="11.5" font-weight="700" :fill="C.biz">业务指标（驱动因子）</text>
          <text :x="rx + lw / 2" y="30" text-anchor="middle" font-size="11.5" font-weight="700" :fill="C.fin">财务指标（经营结果）</text>

          <g v-for="e in graph.edges" :key="e.key" class="gedge" :class="edgeCls(e.key)">
            <path :d="e.d" fill="none" :stroke="e.color" :stroke-width="e.sw" opacity=".32" stroke-linecap="round" />
            <circle :cx="e.x2" :cy="e.y2" r="3.2" :fill="e.color" opacity=".6" />
          </g>

          <g v-for="n in graph.left" :key="n.code" class="gnode" :class="nodeCls('biz', n.code)" :data-code="n.code" data-side="biz" @mouseenter="hover = { code: n.code, side: 'biz' }">
            <rect :x="lx" :y="n.y" :width="lw" height="42" rx="8" class="node-box node-biz" />
            <rect :x="lx" :y="n.y" width="4" height="42" rx="2" :fill="C.biz" />
            <text :x="lx + 14" :y="n.y + 18" font-size="12" font-weight="700" class="t-name">{{ n.name }}</text>
            <text :x="lx + 14" :y="n.y + 33" font-size="10" class="t-sub">{{ n.sub }}</text>
            <text :x="lx + lw - 12" :y="n.y + 18" font-size="12.5" font-weight="800" text-anchor="end" :class="n.cls">{{ n.rate }}</text>
          </g>

          <g v-for="n in graph.right" :key="n.code" class="gnode" :class="nodeCls('fin', n.code)" :data-code="n.code" data-side="fin" @mouseenter="hover = { code: n.code, side: 'fin' }">
            <rect :x="rx" :y="n.y" :width="lw" height="40" rx="8" class="node-box node-fin" />
            <rect :x="rx" :y="n.y" width="4" height="40" rx="2" :fill="C.fin" />
            <text :x="rx + 14" :y="n.y + 17" font-size="12" font-weight="700" class="t-name">{{ n.name }}</text>
            <text :x="rx + 14" :y="n.y + 31" font-size="10" class="t-sub">{{ n.sub }}</text>
            <text :x="rx + lw - 12" :y="n.y + 17" font-size="12.5" font-weight="800" text-anchor="end" :class="n.cls">{{ n.rate }}</text>
          </g>

          <text :x="W / 2" :y="graph.H - 6" text-anchor="middle" font-size="10.5" class="t-sub">线宽表示关联强度，蓝色为同向传导，橙色为反向传导（业务指标提升 → 财务指标下降）</text>
        </svg>
      </div>
      <div class="legend">
        <span><i :style="{ background: SAME }"></i>同向传导（业务↑ → 财务↑）</span>
        <span><i :style="{ background: REVERSE }"></i>反向传导（业务↑ → 财务↓）</span>
        <span>线宽 ∝ 关联强度</span>
        <span>节点右侧数字为当前达成率</span>
      </div>
    </section>

    <div class="grid-1-2 section">
      <section class="card">
        <div class="card-title">联动层级结构</div>
        <pre class="struct">业务二级指标（可操作项）
    ↓ 加权汇总
<b>业务一级指标（驱动因子）</b>
    ↓ 传导系数 / 影响路径
<b>财务一级指标（经营结果）</b>
    ↓ 拆分归因
财务二级指标（可考核项）

反查路径：
财务偏差 → 定位二级财务指标
        → 回溯关联业务一级
        → 落到业务二级与责任部门</pre>
        <p class="note">一级指标回答"结果好不好"，二级指标回答"问题在哪里、谁来负责"。本工作台支持从任一财务偏差出发，沿关联关系反向定位到业务动因与责任部门。</p>
      </section>

      <section class="card">
        <div class="card-title"><span>财务偏差反向归因 <span class="small muted sub">从财务缺口出发，定位业务动因</span></span></div>
        <ol class="stack-list" data-reverse>
          <li v-for="(s, i) in reverse" :key="i" class="stack-item">
            <span class="n">{{ i + 1 }}</span>
            <div class="c">
              <b>{{ s.fin }}</b> <span class="muted">←</span> {{ s.biz }}
              <div class="small muted">责任部门：{{ s.dept }}｜缺口量化：{{ s.gap }}</div>
            </div>
          </li>
        </ol>
      </section>
    </div>

    <section class="card section">
      <div class="card-title head-wrap">
        <span>业财关联关系明细表 <span class="small muted sub">共 {{ LINKAGE.length }} 条｜包含传导逻辑与量化影响测算</span></span>
        <input v-model="q" class="input" placeholder="搜索指标 / 部门" aria-label="搜索指标 / 部门">
      </div>
      <div v-if="links.length" class="table-wrap">
        <table class="table link-table" data-testid="link-table">
          <!-- 固定布局：传导逻辑为自适应主列，量化影响固定 200px 换行显示，其余列收紧，1280 宽下整表放得下不出现裁切 -->
          <colgroup>
            <col style="width: 124px"><col style="width: 150px"><col style="width: 72px"><col style="width: 108px">
            <col><col style="width: 104px"><col style="width: 200px">
          </colgroup>
          <thead>
            <tr>
              <th>业务指标</th><th>财务指标</th><th>方向</th><th>关联强度</th>
              <th>传导逻辑</th><th>责任部门</th><th>量化影响</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(l, i) in links" :key="i">
              <td class="wrap"><span class="badge badge-info">{{ l.biz }}</span> {{ l.bizName }}</td>
              <td class="wrap"><span class="badge">{{ l.fin }}</span> {{ l.finName }}</td>
              <td><span class="badge dir" :class="l.dir === '正向' ? 'badge-bad' : 'badge-good'">{{ l.dir }}</span></td>
              <td>
                <div class="mini-prog">
                  <div class="bar"><i :class="barCls(l.strength)" :style="{ width: Math.round(l.strength * 100) + '%' }"></i></div>
                  <span>{{ (l.strength * 100).toFixed(0) }}%</span>
                </div>
                <div class="tiny muted">{{ l.coef }}</div>
              </td>
              <td class="wrap small">{{ l.logic }}</td>
              <td class="wrap small muted">{{ l.dept }}</td>
              <td class="wrap small impact">{{ l.impact }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="empty">没有匹配的关联关系。</div>
    </section>
  </BizfinPage>
</template>

<style scoped>
.sub { font-weight: 400; margin-left: var(--space-2); }
.head-wrap { flex-wrap: wrap; }
.pills { display: flex; gap: var(--space-2); flex-wrap: wrap; }
.graph-wrap { overflow-x: auto; padding: var(--space-1); }
.graph-wrap svg { width: 100%; height: auto; display: block; min-width: 820px; }
.zone-biz { fill: color-mix(in oklab, var(--accent), white 95%); }
.zone-fin { fill: color-mix(in oklab, var(--success), white 95%); }
.node-box { fill: var(--surface); stroke-width: 1.2; }
.node-biz { stroke: color-mix(in oklab, var(--accent), white 75%); }
.node-fin { stroke: color-mix(in oklab, var(--success), white 75%); }
.t-name { fill: var(--fg); }
.t-sub { fill: var(--muted); }
.gnode { cursor: pointer; transition: opacity var(--motion-fast) var(--ease-standard); }
.gedge { transition: opacity var(--motion-fast) var(--ease-standard); }
.dim { opacity: 0.1; }
.gedge.hl path, .gedge.hl circle { opacity: 1; }
text.t-good { fill: var(--success); }
text.t-info { fill: var(--accent); }
text.t-warn { fill: var(--warn); }
text.t-bad { fill: var(--danger); }
text.t-blank { fill: var(--muted); }
.legend { margin-top: var(--space-2); }
/* 左侧层级结构内容短：列宽 1 : 2 让右侧归因列表少换行、整体变矮；两卡顶对齐，左卡不再被拉高留出大片空白 */
.grid-1-2 { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: var(--space-4); align-items: start; }
@media (max-width: 1240px) { .grid-1-2 { grid-template-columns: minmax(0, 1fr); } }
.struct { font-size: var(--text-xs); font-family: var(--font-mono); background: var(--surface-warm); border: 1px solid var(--border-soft); border-radius: var(--radius-md); padding: var(--space-3); line-height: 1.85; color: var(--fg-2); overflow-x: auto; margin: 0; }
.struct b { color: var(--accent); font-weight: 600; }
.note { font-size: var(--text-xs); color: var(--muted); line-height: 1.75; margin: var(--space-3) 0 0; }
.stack-list { list-style: none; margin: 0; padding: 0; display: grid; gap: var(--space-2); }
.stack-item { display: flex; gap: var(--space-3); align-items: flex-start; padding: var(--space-2) var(--space-3); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); }
.stack-item .n { width: 20px; height: 20px; border-radius: var(--radius-md); background: color-mix(in oklab, var(--accent), white 88%); color: var(--accent); font-size: var(--text-xs); font-weight: 700; display: flex; align-items: center; justify-content: center; flex: 0 0 20px; }
.stack-item .c { font-size: var(--text-sm); color: var(--fg-2); line-height: 1.75; }
.stack-item .c b { color: var(--fg); }
.link-table { table-layout: fixed; min-width: 900px; }
.link-table td { white-space: normal; overflow-wrap: anywhere; }
/* 编码徽标可能较长（如 F4.3+F4.4+F4.5 → F4）：允许换行且底色随内容撑开；方向徽标单行 */
.link-table .badge { height: auto; min-height: 22px; line-height: 1.4; padding: 2px 6px; white-space: normal; }
.link-table .badge.dir { white-space: nowrap; }
.link-table .mini-prog { padding-right: var(--space-2); }
.link-table td.wrap { white-space: normal; line-height: 1.65; padding-top: var(--space-1); padding-bottom: var(--space-1); }
/* 量化影响同一格里正负并存，无法整体按涨红跌绿着色，统一用正文色加粗（原工具为财务主题绿，会与「跌绿」冲突） */
.impact { color: var(--fg); font-weight: 600; }
.tiny { font-size: 10px; }
.mini-prog { display: flex; align-items: center; gap: 6px; min-width: 96px; }
.mini-prog .bar { flex: 1; height: 6px; border-radius: var(--radius-pill); background: var(--border-soft); overflow: hidden; min-width: 40px; }
.mini-prog .bar i { display: block; height: 100%; border-radius: var(--radius-pill); }
.mini-prog span { font-size: var(--text-xs); font-variant-numeric: tabular-nums; color: var(--fg-2); width: 38px; text-align: right; }
.b-strong { background: var(--danger); }
.b-mid { background: var(--warn); }
.b-weak { background: var(--muted); }
.empty { text-align: center; color: var(--muted); padding: var(--space-6) var(--space-4); }
</style>
