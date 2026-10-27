<script setup lang="ts">
/**
 * 部门费用报告 PAGE-F10-04（API-F10-04 GET /api/reports/dept-expense、API-F10-05、API-F14-01）
 * 「部门 × 预算科目」全年预算、截至最近导入月累计实际、额度使用率与时间进度（AC-F10-07）。
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import AchievementBar from '@/components/AchievementBar.vue'
import ExportButton from '@/components/ExportButton.vue'
import PageState from '@/components/PageState.vue'
import { achievementLevel } from '@/components/achievement'
import NoteCell from '@/components/g4/NoteCell.vue'
import NoteDialog from '@/components/g4/NoteDialog.vue'
import { money, pct } from '@/components/g4/format'
import type { NoteKey, NoteTarget, VarianceNote } from '@/components/g4/types'
import { useUserStore } from '@/stores/user'
import '@/components/g4/report.css'

interface Line {
  department: string
  account: string
  budget: string | null
  actual: string | null
  usage: string | null
  note_key?: NoteKey
  note?: VarianceNote | null
}
interface Report {
  year: number
  empty: boolean
  message?: string
  departments: { id: number; name: string }[]
  department_id: number | null
  can_edit_note: boolean
  through?: string
  imported_months?: number
  time_progress?: string
  baseline_label?: string
  groups?: { department_id: number; department: string; rows: Line[]; subtotal: Line }[]
  total?: Line
}

const user = useUserStore()
const data = ref<Report | null>(null)
const loading = ref(true)
const error = ref<unknown>(null)
const dept = ref<string>('')
const collapsed = ref<Record<number, boolean>>({})
const noteTarget = ref<NoteTarget | null>(null)
const isBP = computed(() => user.me?.roles.includes('finance_bp') ?? false)
const isForbidden = computed(() => error.value instanceof ApiError && error.value.isForbidden)
const ready = computed(() => !loading.value && !error.value && !!data.value && !data.value.empty)

async function load(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    data.value = await api.get<Report>('/api/reports/dept-expense', { department_id: dept.value || undefined })
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

function level(usage: string | null): string {
  const l = achievementLevel('expense', usage, data.value?.time_progress)
  return l === 'bad' ? 'bad' : l === 'warn' ? 'warn' : ''
}
function openNote(r: Line): void {
  if (!data.value?.through || !r.note_key) return
  noteTarget.value = { report_type: 'dept-expense', month: data.value.through, ...r.note_key, label: `${r.department} · ${r.account}`, note: r.note }
}
function onSaved(note: VarianceNote): void {
  const t = noteTarget.value
  for (const g of data.value?.groups ?? []) for (const r of g.rows) if (t && r.note_key?.object_key === t.object_key) r.note = note
  noteTarget.value = null
}
</script>

<template>
  <div data-page-id="PAGE-F10-04" class="g4-report">
    <div class="page-head">
      <div>
        <h1 class="page-title">部门费用报告</h1>
        <div class="meta">
          <template v-if="data?.through">截至 {{ data.through }}（最近金蝶导入期间）· </template>预算年度 {{ data?.year ?? '' }} · 全年预算固定取最新调整后目标（无调整时为年初原始目标）· 金额单位：人民币元
        </div>
      </div>
      <ExportButton class="btn-primary" view="report-dept" :filters="{ year: data?.year, department_id: dept || undefined }" :disabled="!ready" />
    </div>

    <PageState v-if="loading && !data" state="loading" :rows="8" />
    <PageState v-else-if="isForbidden" state="forbidden" description="你没有被分配任何部门，无法查看部门费用报告。如需查看请联系财务负责人分配数据范围。" />
    <PageState v-else-if="error" :error="error" title="部门费用报告加载失败" description="服务器未返回数据，可能是网络中断。请重试。" @retry="load" />
    <PageState v-else-if="data?.empty" :title="data.message" description="导入金蝶实际后，这里按部门和预算科目显示额度使用率与时间进度。">
      <template #action>
        <RouterLink v-if="isBP" class="btn btn-primary" :to="{ name: 'import' }">去导入实际数</RouterLink>
      </template>
    </PageState>

    <template v-else-if="data && data.total && data.groups">
      <section class="grid-kpi" aria-label="合计">
        <div class="card fade-in"><div class="kpi-label">全年预算</div><div class="kpi-value">{{ money(data.total.budget) }}</div></div>
        <div class="card fade-in"><div class="kpi-label">累计实际（{{ data.year }}-01 至 {{ data.through }}）</div><div class="kpi-value">{{ money(data.total.actual) }}</div></div>
        <div class="card fade-in"><div class="kpi-label">额度使用率</div><div class="kpi-value" :class="level(data.total.usage)">{{ pct(data.total.usage) }}</div></div>
        <div class="card fade-in"><div class="kpi-label">时间进度（{{ data.imported_months }} ÷ 12）</div><div class="kpi-value">{{ pct(data.time_progress) }}</div></div>
      </section>

      <div class="filters">
        <label>部门
          <select v-model="dept" class="select" :disabled="loading" @change="load">
            <option v-if="data.departments.length > 1" value="">全部</option>
            <option v-for="d in data.departments" :key="d.id" :value="String(d.id)">{{ d.name }}</option>
          </select>
        </label>
        <div class="legend">
          <span><AchievementBar rate="34" :progress="data.time_progress" level="neutral" />在时间进度 10 个百分点以内</span>
          <span><AchievementBar rate="53" :progress="data.time_progress" level="warn" />超出时间进度 10 个百分点以上</span>
          <span><AchievementBar rate="103" :progress="data.time_progress" level="bad" />超出全年预算</span>
          <span>竖刻度线 = 时间进度</span>
        </div>
      </div>

      <div class="table-wrap">
        <table class="table" data-testid="dept-table">
          <thead>
            <tr>
              <th class="dim-h">部门</th><th>预算科目</th><th class="num sep">全年预算</th><th class="num">累计实际</th>
              <th class="num">额度使用率</th><th class="num">时间进度</th><th>达成条</th><th class="sep">偏差说明</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="g in data.groups" :key="g.department_id">
              <tr class="dept-row">
                <td class="dim">
                  <button type="button" class="xbtn" :aria-expanded="!collapsed[g.department_id]" :aria-label="`展开或收起 ${g.department}`" @click="collapsed = { ...collapsed, [g.department_id]: !collapsed[g.department_id] }">
                    <svg width="12" height="12" viewBox="0 0 256 256" fill="currentColor" aria-hidden="true"><path d="M181.66,133.66l-80,80a8,8,0,0,1-11.32-11.32L164.69,128,90.34,53.66a8,8,0,0,1,11.32-11.32l80,80A8,8,0,0,1,181.66,133.66Z" /></svg>
                  </button>{{ g.department }}
                </td>
                <td>部门合计</td>
                <td class="num sep">{{ money(g.subtotal.budget) }}</td>
                <td class="num">{{ money(g.subtotal.actual) }}</td>
                <td class="num" :class="level(g.subtotal.usage)">{{ pct(g.subtotal.usage) }}</td>
                <td class="num">{{ pct(data.time_progress) }}</td>
                <td><AchievementBar :rate="g.subtotal.usage" :progress="data.time_progress" kind="expense" /></td>
                <td class="sep"></td>
              </tr>
              <template v-if="!collapsed[g.department_id]">
                <tr v-for="r in g.rows" :key="r.account">
                  <td class="dim"></td>
                  <td>{{ r.account }}</td>
                  <td class="num sep">{{ money(r.budget) }}</td>
                  <td class="num">{{ money(r.actual) }}</td>
                  <td class="num" :class="level(r.usage)">{{ pct(r.usage) }}</td>
                  <td class="num">{{ pct(data.time_progress) }}</td>
                  <td><AchievementBar :rate="r.usage" :progress="data.time_progress" kind="expense" /></td>
                  <td class="sep"><NoteCell :note="r.note" :can-edit="data.can_edit_note" @open="openNote(r)" /></td>
                </tr>
              </template>
            </template>
            <tr class="total">
              <td class="dim">{{ data.total.department }}</td><td></td>
              <td class="num sep">{{ money(data.total.budget) }}</td>
              <td class="num">{{ money(data.total.actual) }}</td>
              <td class="num" :class="level(data.total.usage)">{{ pct(data.total.usage) }}</td>
              <td class="num">{{ pct(data.time_progress) }}</td>
              <td><AchievementBar :rate="data.total.usage" :progress="data.time_progress" kind="expense" /></td>
              <td class="sep"></td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="foot">额度使用率 = 累计实际 ÷ 全年预算；时间进度 = 最近导入月份数 ÷ 12。累计实际来自金蝶，按科目映射归集到预算科目。专项预留额度已计入所属科目的全年预算，不另列行。偏差说明按「部门 × 预算科目」填写。</p>
    </template>

    <NoteDialog :target="noteTarget" :can-edit="data?.can_edit_note ?? false" @close="noteTarget = null" @saved="onSaved" />
  </div>
</template>

<style scoped>
.grid-kpi { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: var(--space-4); margin-bottom: var(--space-4); }
.kpi-value.warn { color: var(--warn); }
.legend { display: flex; flex-wrap: wrap; gap: var(--space-4); align-items: center; font-size: var(--text-xs); color: var(--muted); padding-bottom: 8px; }
.legend > span { display: inline-flex; align-items: center; gap: var(--space-2); }
tr.dept-row td { font-weight: 600; background: var(--surface-warm); }
td.warn { color: var(--warn); }
.xbtn { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-right: var(--space-1); border: 1px solid transparent; border-radius: var(--radius-sm); background: transparent; color: var(--fg-2); cursor: pointer; vertical-align: middle; }
.xbtn:hover { background: var(--surface-raised); border-color: var(--border); }
.xbtn:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.xbtn svg { transition: transform var(--motion-fast) var(--ease-standard); }
.xbtn[aria-expanded='true'] svg { transform: rotate(90deg); }
</style>
