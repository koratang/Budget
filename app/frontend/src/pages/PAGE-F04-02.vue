<script setup lang="ts">
/** PAGE-F04-02 平台渠道填报：月 × 店铺 × 站点 × 品类 × 新品/老品 七个驱动（AC-F04-01/02）、新渠道超放量理由（AC-F13-02） */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '@/api/client'
import FillingWorkspace, { type GridResponse } from '@/components/g2/FillingWorkspace.vue'
import ExportButton from '@/components/ExportButton.vue'
import { errorText, rollingBase, toast, type UnitInfo } from '@/components/g2/util'

interface OverLimit {
  month: string
  k: number | null
  limit_display: string
  revenue_display: string
  reason: string | null
}
interface PlatformGrid extends GridResponse {
  over_limit: OverLimit[]
  store: { name: string; channel: string; site: string; currency: string; is_new_channel: boolean; new_channel_start: string | null }
  ramp_rule: { name: string; version_no: number } | null
  fx: { currency: string; year: number; rate: string | null; missing: boolean }
  kpis: Record<string, string>
  prior: PriorKpi | null
  refs: { categories: Record<string, string>[]; site: Record<string, string> }
}
interface PriorKpi { year: number; months: number; span: string; revenue_display: string; gross_profit_display: string; gross_margin_display: string }

const route = useRoute()
const router = useRouter()
const unitId = computed(() => Number(route.params.unitId))
const apiBase = computed(() => rollingBase(route.query))
const g = ref<PlatformGrid | null>(null)
const ws = ref<InstanceType<typeof FillingWorkspace> | null>(null)
const myStores = ref<UnitInfo[]>([])
const reasons = ref<Record<string, string>>({})

function onLoaded(grid: GridResponse): void {
  g.value = grid as PlatformGrid
  const next: Record<string, string> = {}
  for (const o of g.value.over_limit) next[o.month] = reasons.value[o.month] ?? o.reason ?? ''
  reasons.value = next
}

onMounted(async () => {
  try {
    const res = await api.get<{ items: UnitInfo[] }>('/api/filling-units', { mine: 1 })
    myStores.value = res.items.filter((u) => u.unit_type === 'platform' && !u.rolling)
  } catch {
    myStores.value = []
  }
})

function switchStore(ev: Event): void {
  const id = (ev.target as HTMLSelectElement).value
  void router.push({ name: 'fill-platform', params: { unitId: id } })
}

async function saveReasons(): Promise<void> {
  try {
    await api.put(`/api/filling-units/${unitId.value}/over-limit-reasons`, { reasons: reasons.value })
    toast('已保存超出理由')
    await ws.value?.reload()
  } catch (e) {
    toast(errorText(e))
  }
}

const REF_LABELS: [string, string][] = [
  ['purchase_cost_rate', '采购成本占比'],
  ['first_leg_rate', '头程费率'],
  ['last_mile_rate', '尾程费率'],
  ['storage_rate', '仓储费率'],
  ['tariff_rate', '关税率'],
]
</script>

<template>
  <div data-page-id="PAGE-F04-02">
    <FillingWorkspace
      ref="ws"
      :unit-id="unitId"
      :api-base="apiBase"
      title-prefix="平台渠道填报"
      dims="维度：月 × 店铺 × 站点 × 品类 × 新品/老品"
      loading-text="正在加载填报表格…"
      error-title="填报表格加载失败"
      forbidden-text="该店铺不在你的数据范围内。如需填报，请联系财务负责人分配。"
      foot="白底单元格可编辑：失焦即保存并刷新合计；可从 Excel 复制整块粘贴（按输入行顺序填入，跳过计算行）。比率按百分数录入，输入 15 即 15%。"
      @loaded="onLoaded"
    >
      <template #toolbar>
        <ExportButton v-if="g && !apiBase" view="budget-platform" :filters="{ unit_id: unitId }" />
      </template>
      <template #info>
        <div v-if="g" class="meta-row">
          <label v-if="myStores.length > 1 && !apiBase">
            填报单位
            <select class="select" :value="String(unitId)" aria-label="切换填报单位（仅显示你负责的店铺）" @change="switchStore">
              <option v-for="s in myStores" :key="s.id" :value="String(s.id)">{{ s.name }}</option>
            </select>
          </label>
          <span>渠道 <b>{{ g.store.channel }}</b></span>
          <span>站点 <b>{{ g.store.site }}</b></span>
          <span>结算币种 <b>{{ g.store.currency }}</b></span>
          <span>
            {{ g.fx.year }} 预算汇率 <b>{{ g.fx.rate ?? '未录入' }}</b>（示例值，以财务BP录入为准）
          </span>
          <span v-if="g.store.is_new_channel" data-new-channel>
            新渠道 · 起始月 <b>{{ g.store.new_channel_start }}</b> · 放量上限按起始后第 1–12 个月逐月设定（人民币/店铺/月，
            <RouterLink class="link" :to="{ name: 'rules' }">规则库「{{ g.ramp_rule?.name ?? '新渠道月收入放量上限' }}」<template v-if="g.ramp_rule">v{{ g.ramp_rule.version_no }}</template></RouterLink>
            · 额度标准）
          </span>
        </div>
        <div v-if="g && g.fx.missing" class="notice notice-warn" role="status">
          {{ g.fx.year }} 年度缺少 {{ g.fx.currency }} 的预算汇率，人民币收入暂无法计算。请联系财务BP 在「汇率」中录入后再提交。
        </div>
      </template>
      <template #kpis>
        <div v-if="g" class="kpis">
          <div class="card fade-in"><div class="kpi-label">全年收入（本币）</div><div class="kpi-value sm tnum">{{ g.kpis.revenue_local_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年收入（人民币）</div><div class="kpi-value sm tnum">{{ g.kpis.revenue_cny_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年毛利（人民币）</div><div class="kpi-value sm tnum">{{ g.kpis.gross_profit_display }}</div></div>
          <div class="card fade-in"><div class="kpi-label">全年毛利率</div><div class="kpi-value sm tnum">{{ g.kpis.gross_margin_display }}</div></div>
        </div>
        <p v-if="g" class="sub prior-line" data-prior>
          <template v-if="g.prior">上年参考：{{ g.prior.year }} 年 {{ g.prior.span }} 实际收入 <b class="tnum">{{ g.prior.revenue_display }}</b>、毛利 <b class="tnum">{{ g.prior.gross_profit_display }}</b>、毛利率 <b class="tnum">{{ g.prior.gross_margin_display }}</b>。表格最上方灰底行是 {{ g.prior.year }} 年同月实际，可对照填写。</template>
          <template v-else>该店铺还没有上年实际，财务BP 在「实际数导入 → 经营历史表」导入后，这里会显示上年同月实际作参考。</template>
        </p>
      </template>
      <template #after>
        <div v-if="g && g.over_limit.length" class="card over-limit-form" data-over-limit>
          <div class="notice notice-warn" style="margin-bottom: var(--space-3)">
            <span class="t">{{ g.over_limit.length }} 个月份超出新渠道放量规则</span>：
            {{ g.over_limit.map((o) => `${o.month}（第 ${o.k} 个月，上限 ${o.limit_display}）`).join('、') }}
            人民币收入超过当月上限。请逐月填写超出理由，未填写前不能提交。
          </div>
          <div v-for="o in g.over_limit" :key="o.month" class="ol-row">
            <span>{{ o.month }} · 店铺收入 {{ o.revenue_display }}</span>
            <input v-model="reasons[o.month]" class="input" :disabled="!g.unit.editable || !!apiBase" :placeholder="'必填：超出理由'" :aria-label="`${o.month} 超出理由`" />
            <span></span>
          </div>
          <button v-if="g.unit.editable && !apiBase" class="btn" type="button" data-save-reasons @click="saveReasons">保存超出理由</button>
        </div>
        <details v-if="g" class="card" style="margin-top: var(--space-4)">
          <summary>毛利计算引用的比例（只读，由财务BP 与物流物控填报）</summary>
          <div class="table-wrap" style="margin-top: var(--space-3)">
            <table class="table">
              <thead>
                <tr><th>品类</th><th v-for="[k, l] in REF_LABELS" :key="k" class="num">{{ l }}</th></tr>
              </thead>
              <tbody>
                <tr v-for="c in g.refs.categories" :key="c.category">
                  <td>{{ c.category }}</td>
                  <td v-for="[k] in REF_LABELS" :key="k" class="num">{{ c[k] }}</td>
                </tr>
                <tr>
                  <td>{{ g.store.channel }} · {{ g.store.site }}</td>
                  <td colspan="5">库存索赔率 {{ g.refs.site.inventory_claim_rate }} · 其他运营费用率 {{ g.refs.site.other_opex_rate }}（适用该渠道站点全部品类与新老品）</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="sub">毛利 = 人民币收入 − 退款 − 采购成本 − 佣金 − 推广费用（广告费）− 头程 − 尾程 − 关税 − 仓储 + 库存索赔 − 其他运营费用；各项金额 = 人民币收入 × 对应比率。比例未填时按 0% 计算并在此处标「未填」。</p>
        </details>
      </template>
    </FillingWorkspace>
  </div>
</template>
