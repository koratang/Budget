<script setup lang="ts">
/**
 * 重点工作进度 PAGE-F15-08（原工具 viewKeywork + renderKwTable + kwAdd / kwDel / kwSet）
 * KPI 概览 + 重点工作台账（年度重点工作 / 需要关注工作两分区共用一份台账）；可编辑者逐格修改、新增与删除（删除二次确认）。
 */
import { computed, ref, type Directive } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { useToast } from '@/components/g1/useToast'
import { KW_CATEGORIES, KW_STATUS, S, fmt, kwStat, type KwTask } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

type Field = keyof KwTask
const { toast, show } = useToast()
const pendingDel = ref<KwTask | null>(null)

/* 多行文本框按内容行数自动增高：支持 field-sizing 的浏览器交给 CSS（随列宽变化实时重排）；
   其余浏览器在挂载 / 更新 / 输入时按 scrollHeight 设高度。仍以 @change 保存，语义不变 */
function fit(el: HTMLTextAreaElement): void {
  if (typeof CSS !== 'undefined' && typeof CSS.supports === 'function' && CSS.supports('field-sizing', 'content')) return
  el.style.height = ''
  if (el.scrollHeight > 0) el.style.height = el.scrollHeight + 2 + 'px'
}
const vAutogrow: Directive<HTMLTextAreaElement> = {
  mounted(el) { fit(el); el.addEventListener('input', () => fit(el)) },
  updated: fit,
}

const st = computed(() => kwStat())
const usedCats = computed(() => Object.keys(st.value.byCat).filter((k) => st.value.byCat[k] > 0).length)
/** 年度重点工作：按状态排序（进行中 → 已完成 → 延误 → 阻滞，其余置后） */
const annual = computed(() => {
  const order: Record<string, number> = { '进行中': 0, '已完成': 1, '延误': 2, '阻滞': 3 }
  return S.KW_TASKS.slice().sort((a, b) => (order[a.status] ?? 9) - (order[b.status] ?? 9))
})
/** 需要关注工作：由台账按状态自动派生 */
const watch = computed(() => annual.value.filter((p) => p.status === '延误' || p.status === '阻滞'))
const sections = computed(() => [
  { key: 'annual', title: '年度重点工作', note: '含「进行中」「已完成」与「未达延误阈值」的常规工作；按状态排序。', rows: annual.value, empty: '该分区暂无工作记录' },
  { key: 'watch', title: '需要关注工作', note: `由台账按工作状态自动派生：「延误」「阻滞」合计 ${st.value.hot} 项。`, rows: watch.value, empty: '暂无延误 / 阻滞工作' },
])

/** 下拉选项：当前值不在预设列表中时追加 */
const optsOf = (list: string[], cur: string): string[] => (cur && list.indexOf(cur) < 0 ? list.concat([cur]) : list)
/** 状态色（原 KW_STATUS_COLOR 语义）→ 平台令牌 */
const STATUS_TONE: Record<string, string> = { '进行中': 'var(--accent)', '已完成': 'var(--success)', '延误': 'var(--warn)', '阻滞': 'var(--danger)' }
const progressOf = (p: KwTask): number => Math.max(0, Math.min(100, Number(p.progress || 0)))

function kwAdd(): void {
  S.KW_TASKS.push({ time: '', cat: '', goal: '', breakdown: '', eta: '', progress: 0, status: '进行中' })
  commit('keywork')
  show('已新增工作行，请填写时间 / 工作分类 / 工作目标 / 工作分解 / 预计完成时间 / 目前进度 / 工作状态')
}
function kwDel(p: KwTask): void {
  pendingDel.value = null
  const i = S.KW_TASKS.indexOf(p)
  if (i < 0) return
  S.KW_TASKS.splice(i, 1)
  commit('keywork')
  show(`已删除第 ${i + 1} 行工作台账`)
}
function kwSet(p: KwTask, f: Field, e: Event): void {
  const el = e.target as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement
  if (f === 'progress') {
    const v = parseFloat(el.value)
    p.progress = isNaN(v) ? 0 : Math.max(0, Math.min(100, v))
    el.value = String(p.progress)
  } else {
    p[f] = String(el.value)
  }
  commit('keywork')
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-08" :sections="['keywork']" title="重点工作进度" desc="年度重点项目立项 / 进度 / 责任部门 / 财务影响归因">
    <div class="card note">
      <b>重点工作进度口径：</b>聚焦年度重点工作与需要关注工作，按工作分类核算 / 资金 / 合规 / 降本增收 / 财务BP / 信息化 共六档登记；
      每行可直接编辑，年度视图展示全部进行中与已完成工作，关注视图自动派生延误与阻滞项。
    </div>

    <section class="kpi-row section" aria-label="KPI 概览">
      <div class="card" data-kpi="total">
        <div class="kpi-label">年度重点工作</div>
        <div class="kpi-value">{{ st.total }}<span class="u">项</span></div>
        <div class="small muted">已完成 <b>{{ st.byStatus['已完成'] || 0 }}</b> · 平均进度 <b>{{ fmt(st.progressAvg, 0) }}%</b></div>
      </div>
      <div class="card" data-kpi="hot">
        <div class="kpi-label">需要关注工作</div>
        <div class="kpi-value" :class="st.hot ? 'warn' : 'good'">{{ st.hot }}<span class="u">项</span></div>
        <div class="small muted">延误 <b>{{ st.delayed }}</b> · 阻滞 <b>{{ st.blocked }}</b></div>
      </div>
      <div class="card" data-kpi="doing">
        <div class="kpi-label">进行中工作</div>
        <div class="kpi-value">{{ st.byStatus['进行中'] || 0 }}<span class="u">项</span></div>
        <div class="small muted">分类覆盖 <b>{{ usedCats }} / 6</b></div>
      </div>
      <div class="card" data-kpi="cats">
        <div class="kpi-label">分类覆盖</div>
        <div class="cats">
          <!-- 分类标签统一用中性色，不用原工具的红 / 绿分类色，避免与涨红跌绿语义冲突 -->
          <span v-for="c in KW_CATEGORIES" :key="c" class="kw-cat">{{ c }} <b>{{ st.byCat[c] || 0 }}</b></span>
        </div>
        <div class="small muted">已使用分类 <b>{{ usedCats }} / 6</b> 项</div>
      </div>
    </section>

    <section class="card">
      <div class="card-title">
        <span>重点工作台账 <span class="small muted desc">行字段：时间 · 工作分类 · 工作目标 · 工作分解 · 预计完成时间 · 目前进度 · 工作状态</span></span>
        <span class="tools">
          <span class="badge" data-testid="count">{{ S.KW_TASKS.length }} 项</span>
          <button v-if="store.canEdit" type="button" class="btn btn-primary" @click="kwAdd">＋ 新增工作</button>
        </span>
      </div>

      <div v-for="sec in sections" :key="sec.key" class="part" :data-part="sec.key">
        <div class="part-title" :class="{ warn: sec.key === 'watch' }">{{ sec.title }}</div>
        <p class="small muted part-note">{{ sec.note }}</p>
        <div v-if="!sec.rows.length" class="empty muted">{{ sec.empty }}</div>
        <div v-else class="table-wrap">
          <table class="table ledger">
            <!-- 固定布局：工作分解为唯一弹性主列（同原工具），工作目标定宽 180px；分类 / 状态列按下拉完整文字定宽，进度列收紧 -->
            <colgroup>
              <col class="w-time"><col class="w-cat"><col class="w-goal"><col><col class="w-eta"><col class="w-prog"><col class="w-st"><col v-if="store.canEdit" class="w-op">
            </colgroup>
            <thead>
              <tr>
                <th>时间</th><th>工作分类</th><th>工作目标</th><th>工作分解</th>
                <th>预计完成时间</th><th>目前进度</th><th>工作状态</th><th v-if="store.canEdit" />
              </tr>
            </thead>
            <tbody>
              <tr v-for="(p, idx) in sec.rows" :key="idx">
                <template v-if="store.canEdit">
                  <td><input class="input" :value="p.time" placeholder="如 2026-04" aria-label="时间" @change="kwSet(p, 'time', $event)"></td>
                  <td>
                    <select class="select" :value="p.cat" aria-label="工作分类" @change="kwSet(p, 'cat', $event)">
                      <option v-if="!p.cat" value="" />
                      <option v-for="c in optsOf(KW_CATEGORIES, p.cat)" :key="c" :value="c">{{ c }}</option>
                    </select>
                  </td>
                  <td><textarea v-autogrow class="area" rows="1" :value="p.goal" placeholder="工作目标" aria-label="工作目标" @change="kwSet(p, 'goal', $event)" /></td>
                  <td><textarea v-autogrow class="area" rows="1" :value="p.breakdown" placeholder="工作分解 / 关键路径" aria-label="工作分解" @change="kwSet(p, 'breakdown', $event)" /></td>
                  <td><input class="input" :value="p.eta" placeholder="如 2026-11" aria-label="预计完成时间" @change="kwSet(p, 'eta', $event)"></td>
                  <td>
                    <span class="prog-edit">
                      <input class="input num" type="number" min="0" max="100" step="1" :value="Number(p.progress || 0)" aria-label="目前进度" @change="kwSet(p, 'progress', $event)">
                      <span class="muted">%</span>
                    </span>
                  </td>
                  <td>
                    <select class="select" :value="p.status" aria-label="工作状态" @change="kwSet(p, 'status', $event)">
                      <option v-if="!p.status" value="" />
                      <option v-for="s in optsOf(KW_STATUS, p.status)" :key="s" :value="s">{{ s }}</option>
                    </select>
                  </td>
                  <td class="op-td">
                    <div class="op">
                      <template v-if="pendingDel === p">
                        <button type="button" class="btn btn-danger" title="确认删除该行" aria-label="确认删除该行" @click="kwDel(p)">确认</button>
                        <button type="button" class="btn" @click="pendingDel = null">取消</button>
                      </template>
                      <button v-else type="button" class="btn btn-danger" title="删除该行" @click="pendingDel = p">删除</button>
                    </div>
                  </td>
                </template>
                <template v-else>
                  <td>{{ p.time }}</td>
                  <td>{{ p.cat }}</td>
                  <td class="wrap">{{ p.goal }}</td>
                  <td class="wrap">{{ p.breakdown }}</td>
                  <td>{{ p.eta }}</td>
                  <td>
                    <span class="kw-bar" data-progress>
                      <i :style="{ width: progressOf(p) + '%', background: STATUS_TONE[p.status] || 'var(--muted)' }" />
                      <span>{{ progressOf(p) }}%</span>
                    </span>
                  </td>
                  <td>{{ p.status }}</td>
                </template>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <p class="small muted foot">
        台账按行登记，单元格可直接编辑，修改后自动保存；「工作分类」下拉可选核算 / 资金 / 合规 / 降本增收 / 财务BP / 信息化；
        「工作状态」下拉可选进行中 / 已完成 / 延误 / 阻滞。修改任一行后，上方 KPI 与分区自动联动。
      </p>
    </section>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </BizfinPage>
</template>

<style scoped>
.note { margin-bottom: var(--space-4); font-size: var(--text-sm); line-height: 1.8; color: var(--fg-2); }
.kpi-value .u { font-size: var(--text-sm); font-weight: 400; margin-left: 2px; color: var(--muted); }
.kpi-value.warn { color: var(--warn); }
.kpi-value.good { color: var(--success); }
/* 分类覆盖卡加宽（1.6 份），6 个分类标签排两行即可，四张 KPI 卡高度接近，前三张卡底部不再空出一截 */
.kpi-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)) minmax(0, 1.6fr); gap: var(--space-4); }
@media (max-width: 1200px) { .kpi-row { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 760px) { .kpi-row { grid-template-columns: minmax(0, 1fr); } }
.cats { display: flex; flex-wrap: wrap; gap: 4px; margin: var(--space-1) 0; }
.kw-cat { display: inline-block; padding: 1px 6px; border-radius: var(--radius-sm); background: var(--surface-warm); border: 1px solid var(--border-soft); color: var(--fg-2); font-size: var(--text-xs); }
.kw-cat b { color: var(--fg); }
.desc { font-weight: 400; margin-left: var(--space-2); }
.tools { display: inline-flex; align-items: center; gap: var(--space-2); }
.part + .part { margin-top: var(--space-5); }
.part-title { font-size: var(--text-sm); font-weight: 700; margin: var(--space-2) 0 var(--space-1); }
.part-title.warn { color: var(--warn); }
.part-note { margin: 0 0 var(--space-2); }
.empty { padding: var(--space-4) 0; text-align: center; font-size: var(--text-sm); }
/* 盒模型按 border-box 计，输入框 / 下拉 / 多行框不再溢出到相邻列 */
.ledger { table-layout: fixed; min-width: 960px; }
.ledger td { vertical-align: top; padding-top: 4px; padding-bottom: 4px; height: auto; }
.ledger .input, .ledger .select, .ledger .area { width: 100%; box-sizing: border-box; }
.ledger .input, .ledger .select { height: 30px; }
.ledger .select { padding-right: var(--space-1); }
.area { display: block; min-height: 30px; padding: 5px var(--space-2); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--fg); font: inherit; font-size: var(--text-sm); line-height: 1.55; resize: vertical; overflow: hidden; field-sizing: content; transition: border-color var(--motion-fast) var(--ease-standard); }
.area:hover { border-color: var(--muted); }
.area:focus-visible { outline: none; border-color: var(--accent); box-shadow: var(--focus-ring); }
.ledger td.wrap { white-space: normal; line-height: 1.6; padding-top: 6px; padding-bottom: 6px; word-break: break-word; }
.prog-edit { display: flex; align-items: center; gap: 4px; }
.ledger .prog-edit .input { width: 64px; text-align: right; padding: 0 var(--space-1); }
.kw-bar { position: relative; display: inline-block; width: 100%; max-width: 120px; height: 16px; border-radius: var(--radius-sm); background: var(--border-soft); overflow: hidden; vertical-align: middle; }
.kw-bar i { position: absolute; inset: 0 auto 0 0; }
.kw-bar span { position: relative; display: block; text-align: center; font-size: var(--text-xs); line-height: 16px; color: var(--fg); }
.w-time { width: 96px; }
.w-cat { width: 116px; }
.w-goal { width: 180px; }
.w-eta { width: 96px; }
.w-prog { width: 92px; }
.w-st { width: 100px; }
.w-op { width: 60px; }
/* 操作列宽贴合「删除」按钮；二次确认时「确认 / 取消」上下竖排，不撑宽列 */
.ledger td.op-td { padding-left: var(--space-1); padding-right: var(--space-1); }
.op { display: flex; flex-direction: column; gap: var(--space-1); align-items: stretch; }
.op .btn { height: 26px; padding: 0 var(--space-2); font-size: var(--text-xs); justify-content: center; }
.foot { margin: var(--space-3) 0 0; line-height: 1.7; }
</style>
