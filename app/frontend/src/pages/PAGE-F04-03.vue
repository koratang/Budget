<script setup lang="ts">
/** PAGE-F04-03 B端填报：月 × B 端客户 六个输入项（AC-F04-03），人民币收入与毛利（AC-F06-05） */
import { computed, ref } from 'vue'
import { useRoute } from 'vue-router'
import { rollingBase } from '@/components/g2/util'
import FillingWorkspace, { type GridResponse } from '@/components/g2/FillingWorkspace.vue'

interface B2bGrid extends GridResponse {
  department: string | null
  customers: { id: number; name: string; currency: string }[]
  fx: { currency: string; year: number; rate: string | null; missing: boolean }[]
  kpis: Record<string, string>
  refs: Record<string, string>[]
}

const route = useRoute()
const unitId = computed(() => Number(route.params.unitId))
const apiBase = computed(() => rollingBase(route.query))
const g = ref<B2bGrid | null>(null)
const REF_LABELS: [string, string][] = [
  ['purchase_cost_rate', '采购成本占比'],
  ['first_leg_rate', '头程费率'],
  ['last_mile_rate', '尾程费率'],
  ['storage_rate', '仓储费率'],
  ['tariff_rate', '关税率'],
]
</script>

<template>
  <div data-page-id="PAGE-F04-03">
    <FillingWorkspace
      :unit-id="unitId"
      :api-base="apiBase"
      title-prefix="B端填报"
      dims="维度：月 × B 端客户"
      loading-text="正在加载 B 端填报表格…"
      error-title="B 端填报表格加载失败"
      forbidden-text="该 B 端客户不在你的数据范围内。如需填报，请联系财务负责人分配。"
      @loaded="(x) => (g = x as B2bGrid)"
    >
      <template #info>
        <div v-if="g" class="meta-row">
          <span>负责客户 <b>{{ g.customers.map((c) => c.name).join('、') || '—' }}</b></span>
          <span v-for="f in g.fx" :key="f.currency">客户币种 <b>{{ f.currency }}</b> · {{ f.year }} 预算汇率 <b>{{ f.rate ?? '未录入' }}</b>（示例值，以财务BP录入为准）</span>
          <span>平台佣金率、库存索赔率默认 0.00%，有实际约定时再改</span>
        </div>
      </template>
      <template #kpis>
        <div v-if="g" class="kpis">
          <div class="card fade-in"><div class="kpi-label">全年销售额（本币）</div><div class="kpi-value sm tnum">{{ g.kpis.sales_local_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年收入（人民币）</div><div class="kpi-value sm tnum">{{ g.kpis.revenue_cny_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年毛利（人民币）</div><div class="kpi-value sm tnum">{{ g.kpis.gross_profit_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年毛利率</div><div class="kpi-value sm tnum">{{ g.kpis.gross_margin_display }}</div></div>
        </div>
      </template>
      <template #after>
        <details v-if="g" class="card" style="margin-top: var(--space-4)">
          <summary>毛利计算引用的比例（只读，由财务BP 与物流物控填报）</summary>
          <div class="table-wrap" style="margin-top: var(--space-3)">
            <table class="table">
              <thead><tr><th>B 端客户</th><th v-for="[k, l] in REF_LABELS" :key="k" class="num">{{ l }}</th></tr></thead>
              <tbody>
                <tr v-for="r in g.refs" :key="r.customer">
                  <td>{{ r.customer }}</td>
                  <td v-for="[k] in REF_LABELS" :key="k" class="num">{{ r[k] }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>
      </template>
    </FillingWorkspace>
  </div>
</template>
