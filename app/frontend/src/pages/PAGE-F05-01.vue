<script setup lang="ts">
/** PAGE-F05-01 部门费用填报：预算科目 × 月人民币金额（AC-F05-01）+ 上年同月实际 / 近 12 月实际合计（AC-F05-02） */
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import { rollingBase } from '@/components/g2/util'
import FillingWorkspace, { type GridResponse } from '@/components/g2/FillingWorkspace.vue'
import type { GridRow } from '@/components/budgetGrid'

interface DeptGrid extends GridResponse {
  department: { id: number; name: string }
  kpis: { year_total_display: string; reserve_total_display: string; reserve_count: number; recent12_display: string }
}

const route = useRoute()
const router = useRouter()
const unitId = computed(() => Number(route.query.unitId ?? 0))
const apiBase = computed(() => rollingBase(route.query))
const g = ref<DeptGrid | null>(null)
const resolving = ref(false)
const resolveError = ref<unknown>(null)

async function resolve(): Promise<void> {
  if (unitId.value || apiBase.value) return
  resolving.value = true
  resolveError.value = null
  try {
    const res = await api.get<{ unit_id: number }>('/api/dept-expense/my-unit')
    await router.replace({ name: 'dept-expense', query: { unitId: String(res.unit_id) } })
  } catch (e) {
    resolveError.value = e
  } finally {
    resolving.value = false
  }
}
onMounted(resolve)
watch(unitId, resolve)

const MONTH = /^\d{4}-\d{2}$/
const NO_HISTORY = '无历史数据'
/**
 * 历史参考并入单元格（AC-F05-02）：服务端「…|prior」行不单独成行，
 * 改为对应科目预算行（合计行）每个月格下方的灰字「上年 x」；无历史时在科目名下方显示「无历史数据」。
 */
function mergeHistory(rows: GridRow[]): GridRow[] {
  const out: GridRow[] = []
  for (const r of rows) {
    const [prefix, item] = r.key.split('|')
    if (item !== 'prior') {
      out.push({ ...r })
      continue
    }
    const target = out.find((x) => x.key === (prefix === 'total' ? 'total|budget' : `${prefix}|amount`))
    if (!target) continue
    const sub: Record<string, string> = {}
    if (r.values.item === NO_HISTORY) sub.account = NO_HISTORY
    else for (const [k, v] of Object.entries(r.values)) if (MONTH.test(k) && v) sub[k] = `上年 ${v}`
    target.sub = sub
    target.sub_key = r.key
  }
  return out
}
</script>

<template>
  <div data-page-id="PAGE-F05-01">
    <PageState v-if="resolving" state="loading" />
    <PageState
      v-else-if="resolveError"
      :error="resolveError instanceof ApiError && resolveError.status === 404 ? undefined : resolveError"
      :state="resolveError instanceof ApiError && resolveError.status === 404 ? 'empty' : undefined"
      :title="resolveError instanceof ApiError && resolveError.status === 404 ? '你目前没有需要填报的部门费用' : '部门费用加载失败'"
      description="财务负责人发布编制任务后，你负责的部门费用单位会出现在这里。"
      @retry="resolve"
    />
    <FillingWorkspace
      v-else-if="unitId || apiBase"
      :unit-id="unitId"
      :api-base="apiBase"
      title-prefix="部门费用填报"
      dims="维度：预算科目 × 月（人民币）"
      loading-text="正在加载部门费用…"
      error-title="部门费用加载失败"
      forbidden-text="你只能查看和填写被分配部门的费用预算。如需开通，请联系财务负责人。"
      :grid-url="(id) => `/api/dept-expense/${id}/grid`"
      :fill-year="false"
      :templates="false"
      :rows-view="mergeHistory"
      toolbar-note="每个单元格下方灰字为该科目上一年同月实际；「近 12 月实际合计」列为最近 12 个已导入月份之和。"
      foot="白底单元格可编辑：失焦即保存并刷新合计；可从 Excel 复制整块粘贴。专项预留在「专项预留额度」中维护，自动计入对应科目和月份。"
      @loaded="(x) => (g = x as DeptGrid)"
    >
      <template #kpis>
        <div v-if="g" class="kpis k3">
          <div class="card fade-in">
            <div class="kpi-label">{{ g.unit.task?.year ?? '' }} 全年预算合计（含专项）</div>
            <div class="kpi-value sm tnum" data-kpi-total>{{ g.kpis.year_total_display }}</div>
            <div class="kpi-foot">其中专项预留 {{ g.kpis.reserve_total_display }}，共 {{ g.kpis.reserve_count }} 项</div>
          </div>
          <div class="card fade-in">
            <div class="kpi-label">近 12 月实际合计</div>
            <div class="kpi-value sm tnum">{{ g.kpis.recent12_display }}</div>
            <div class="kpi-foot">无历史数据的科目不计入</div>
          </div>
          <div class="card fade-in">
            <div class="kpi-label">专项预留额度</div>
            <div class="kpi-value sm tnum">{{ g.kpis.reserve_total_display }}</div>
            <div class="kpi-foot">
              <RouterLink class="link" :to="{ name: 'reserves', query: { departmentId: String(g.department.id) } }">管理专项预留额度</RouterLink>
            </div>
          </div>
        </div>
      </template>
    </FillingWorkspace>
  </div>
</template>
