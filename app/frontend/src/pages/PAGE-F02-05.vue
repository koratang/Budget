<script setup lang="ts">
/**
 * PAGE-F02-05 汇率（年度预算汇率 | 月度实际汇率）。财务BP 维护；CEO、财务负责人只读（DEC-F02-01）。
 * 年初原始目标锁定后已有币种预算汇率不可修改，尚无汇率的币种仍可新增（AC-F02-11、DEC-020）。
 * 接口：GET/PUT /api/master/fx/budget、/api/master/fx/actual（API-F02-05）。
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import G1Modal from '@/components/g1/G1Modal.vue'
import { fmtTime, useToast } from '@/components/g1/useToast'
import '@/components/g1/g1.css'

interface BudgetItem { currency: string; name: string; rate: string | null; stores: number; customers: number; editable: boolean; updated_at: string | null; updated_by: string | null }
interface BudgetPage { year: number; years: number[]; locked: boolean; locked_on: string | null; items: BudgetItem[]; missing: string[]; used_count: number; can_edit: boolean }
interface ActualRow { month: string; bi_imported: boolean; rates: Record<string, string | null> }
interface ActualPage { year: number; currencies: string[]; rows: ActualRow[]; missing: string[]; can_edit: boolean }

const FORMAT = '请输入大于 0 的数字，最多 4 位小数'
const tab = ref<'b' | 'a'>('b')
const year = ref<number | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const budget = ref<BudgetPage | null>(null)
const actual = ref<ActualPage | null>(null)
const showEmptyTable = ref(false)
const invalid = ref<Record<string, boolean>>({})
const { toast, show } = useToast()

async function load(): Promise<void> {
  error.value = null
  try {
    const [b, a] = await Promise.all([
      api.get<BudgetPage>('/api/master/fx/budget', { year: year.value ?? undefined }),
      api.get<ActualPage>('/api/master/fx/actual', { year: year.value ?? undefined }),
    ])
    budget.value = b
    actual.value = a
    year.value = b.year
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

function changeYear(ev: Event): void {
  year.value = Number((ev.target as HTMLSelectElement).value)
  showEmptyTable.value = false
  void load()
}

const canEdit = computed(() => budget.value?.can_edit === true)
const isEmptyYear = computed(() => !!budget.value && budget.value.items.every((i) => i.rate === null) && !showEmptyTable.value)
const valid = (v: string) => /^\d+(\.\d{1,4})?$/.test(v) && Number(v) > 0
const fmt4 = (v: string) => Number(v).toFixed(4)
function usage(i: BudgetItem): string {
  const parts = []
  if (i.stores) parts.push(`${i.stores} 个店铺`)
  if (i.customers) parts.push(`${i.customers} 个 B端客户`)
  return parts.join('、') || '—'
}

// ---- 预算汇率单元格 ----
const pending = ref<{ item: BudgetItem; value: string; td: HTMLElement } | null>(null)
let oldText = ''
function onFocus(ev: FocusEvent, key: string): void {
  oldText = (ev.target as HTMLElement).textContent?.trim() ?? ''
  invalid.value[key] = false
}

async function saveBudget(item: BudgetItem, value: string, changed: boolean): Promise<void> {
  try {
    await api.put('/api/master/fx/budget', { year: budget.value?.year, currency: item.currency, rate: value })
    show(changed ? `已保存 ${item.currency} 预算汇率 ${value}，预算金额已重新折算` : `已保存 ${item.currency} 预算汇率 ${value}`)
    await load()
  } catch (e) {
    invalid.value[`b-${item.currency}`] = true
    show(e instanceof ApiError ? `${item.currency}：${e.message}` : '保存失败，请重试')
  }
}

function onBudgetBlur(ev: FocusEvent, item: BudgetItem): void {
  const td = ev.target as HTMLElement
  const v = td.textContent?.trim() ?? ''
  if (v === oldText) return
  if (!valid(v)) {
    invalid.value[`b-${item.currency}`] = true
    show(`${item.currency}：${FORMAT}`)
    return
  }
  const value = fmt4(v)
  if (item.rate) {
    pending.value = { item, value, td }
    return
  }
  void saveBudget(item, value, false)
}

function cancelPending(): void {
  if (pending.value) pending.value.td.textContent = pending.value.item.rate ?? ''
  pending.value = null
}
function confirmPending(): void {
  const p = pending.value
  pending.value = null
  if (p) void saveBudget(p.item, p.value, true)
}

// ---- 当月平均汇率单元格 ----
async function onActualBlur(ev: FocusEvent, row: ActualRow, cur: string): Promise<void> {
  const td = ev.target as HTMLElement
  const v = td.textContent?.trim() ?? ''
  const key = `a-${row.month}-${cur}`
  if (v === oldText) return
  if (!v) { td.textContent = oldText; return }
  if (!valid(v)) {
    invalid.value[key] = true
    show(`${row.month} ${cur}：${FORMAT}`)
    return
  }
  try {
    await api.put('/api/master/fx/actual', { month: row.month, currency: cur, rate: fmt4(v) })
    show(`已保存 ${row.month} ${cur} 当月平均汇率 ${fmt4(v)}`)
    await load()
  } catch (e) {
    invalid.value[key] = true
    show(e instanceof ApiError ? e.message : '保存失败，请重试')
  }
}

function blurOnEnter(ev: KeyboardEvent): void {
  ev.preventDefault();
  (ev.target as HTMLElement).blur()
}
</script>

<template>
  <div class="g1" data-page-id="PAGE-F02-05">
    <div class="page-head"><h1 class="page-title">汇率</h1></div>

    <div class="tabs" role="tablist">
      <a class="tab" href="#" role="tab" :aria-selected="tab === 'b' ? 'true' : 'false'" @click.prevent="tab = 'b'">年度预算汇率</a>
      <a class="tab" href="#" role="tab" :aria-selected="tab === 'a' ? 'true' : 'false'" @click.prevent="tab = 'a'">月度实际汇率</a>
    </div>

    <PageState v-if="loading" state="loading" :rows="4" />
    <PageState v-else-if="error && error instanceof ApiError && error.isForbidden" state="forbidden" description="汇率由财务BP 维护。" />
    <PageState v-else-if="error" state="error" title="汇率加载失败" description="网络异常或服务暂时不可用，请重试。" @retry="load" />

    <template v-else-if="budget && actual">
      <section v-if="tab === 'b'" role="tabpanel">
        <div class="bar">
          <label for="year" class="meta">预算年度</label>
          <select id="year" class="select" :value="budget.year" @change="changeYear">
            <option v-for="y in budget.years" :key="y" :value="y">{{ y }}</option>
          </select>
          <span class="meta">口径：2026-09-30 中国银行人民币外币汇率中间价 · 1 单位外币折合人民币 · <span class="example">示例值，以财务BP录入为准</span></span>
        </div>

        <PageState v-if="isEmptyYear" :title="`${budget.year} 年度还没有预算汇率`"
                   description="为该年度涉及的每个币种录入预算汇率后，填报才能提交；缺少汇率的币种会阻止提交。">
          <template #action><button v-if="canEdit" type="button" class="btn" @click="showEmptyTable = true">录入预算汇率</button><span v-else /></template>
        </PageState>

        <template v-else>
          <div v-if="budget.locked" class="notice" role="status">已随年初原始目标锁定：{{ budget.year }} 年度年初原始目标已于 {{ budget.locked_on }} 经 CEO 审批锁定，该年度各币种预算汇率不可修改。</div>
          <div class="notice" :class="{ warn: budget.missing.length }">
            <template v-if="budget.missing.length">缺少预算汇率：{{ budget.missing.join('、') }}。涉及这些币种的填报将无法提交，提交时会提示缺少汇率的币种代码。</template>
            <template v-else>{{ budget.year }} 年度店铺与 B端客户使用的 {{ budget.used_count }} 个币种均已录入预算汇率。</template>
          </div>
          <div class="table-wrap">
            <table class="table" aria-label="年度预算汇率">
              <thead><tr><th>币种</th><th>名称</th><th class="num">预算汇率（CNY）</th><th>使用该币种的店铺 / 客户</th><th>状态</th><th>最近修改</th></tr></thead>
              <tbody>
                <tr v-for="i in budget.items" :key="i.currency">
                  <td class="cur">{{ i.currency }}</td>
                  <td>{{ i.name }}</td>
                  <td v-if="canEdit && i.editable" class="num rate cell-edit" contenteditable="true" role="textbox"
                      :aria-label="`${i.currency} 预算汇率`" :aria-invalid="invalid[`b-${i.currency}`] || undefined"
                      :title="invalid[`b-${i.currency}`] ? FORMAT : undefined"
                      @focus="onFocus($event, `b-${i.currency}`)" @blur="onBudgetBlur($event, i)" @keydown.enter="blurOnEnter">{{ i.rate ?? '' }}</td>
                  <td v-else class="num rate" :class="{ 'cell-locked': budget.locked && i.rate }" :aria-label="`${i.currency} 预算汇率（不可修改）`">
                    <template v-if="i.rate">{{ i.rate }}</template><span v-else class="meta">未录入</span>
                  </td>
                  <td>{{ usage(i) }}</td>
                  <td>
                    <span v-if="i.rate" class="badge badge-good">已录入</span><span v-else class="badge badge-bad">缺少汇率</span>
                    <span v-if="budget.locked && i.rate" class="badge"> 已随年初原始目标锁定</span>
                  </td>
                  <td class="meta">{{ i.updated_at ? `${fmtTime(i.updated_at).slice(0, 10)} ${i.updated_by ?? ''}` : '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="canEdit && !budget.locked" class="meta">点击汇率单元格直接修改，离开单元格即保存。保存后该年度所有该币种的预算金额按新汇率重新折算。</p>
          <p v-else-if="canEdit" class="meta">已锁定年度只能为尚无预算汇率的币种新增预算汇率。</p>
        </template>
      </section>

      <section v-else role="tabpanel">
        <div class="bar">
          <span class="meta">{{ actual.year }} 年 · 当月平均汇率 · 1 单位外币折合人民币 · 用于把该月 BI 本币实际收入折算为人民币、计算汇率差，以及 BI 与金蝶核对</span>
        </div>
        <div v-if="actual.missing.length" class="notice warn">已导入 BI 数据但缺少当月平均汇率：{{ actual.missing.join('、') }}。补录前该月 BI 本币收入无法折算为人民币，偏差报告该月汇率差显示「缺少 {{ actual.missing[0].slice(0, 7) }} 汇率」。</div>
        <div class="table-wrap">
          <table class="table" aria-label="月度实际汇率">
            <thead><tr><th>月份</th><th v-for="c in actual.currencies" :key="c" class="num">{{ c }} 当月平均汇率</th><th>BI 数据</th></tr></thead>
            <tbody>
              <tr v-for="r in actual.rows" :key="r.month">
                <td class="dim">{{ r.month }}</td>
                <template v-for="c in actual.currencies" :key="c">
                  <td v-if="canEdit" class="num rate cell-edit" contenteditable="true" role="textbox"
                      :aria-label="`${r.month} ${c} 当月平均汇率`" :aria-invalid="invalid[`a-${r.month}-${c}`] || undefined"
                      @focus="onFocus($event, `a-${r.month}-${c}`)" @blur="onActualBlur($event, r, c)" @keydown.enter="blurOnEnter">{{ r.rates[c] ?? '' }}</td>
                  <td v-else class="num rate"><template v-if="r.rates[c]">{{ r.rates[c] }}</template><span v-else class="meta">—</span></td>
                </template>
                <td><span v-if="r.bi_imported" class="badge">已导入</span><span v-else class="meta">—</span></td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="canEdit" class="meta">点击单元格录入，离开单元格即保存；保留 4 位小数。</p>
      </section>
    </template>

    <G1Modal v-if="pending" alert title="修改预算汇率？" @close="cancelPending">
      <p>{{ pending.item.currency }} 预算汇率由 {{ pending.item.rate }} 改为 {{ pending.value }}。确认后，{{ budget?.year }} 年度所有 {{ pending.item.currency }} 预算金额将按新汇率重新折算为人民币。</p>
      <template #actions>
        <button type="button" class="btn" @click="cancelPending">取消</button>
        <button type="button" class="btn btn-primary" @click="confirmPending">确认修改</button>
      </template>
    </G1Modal>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </div>
</template>

<style scoped>
.rate { font-family: var(--font-mono); width: 160px; }
.example { font-size: var(--text-xs); color: var(--muted); }
</style>
