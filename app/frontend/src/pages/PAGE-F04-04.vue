<script setup lang="ts">
/** PAGE-F04-04 成本比例填报（财务BP）：采购成本占比 · 平台 / B端客户、库存索赔率与其他运营费用率、公司层其他损益 */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { rollingBase } from '@/components/g2/util'
import FillingWorkspace from '@/components/g2/FillingWorkspace.vue'

const route = useRoute()
const unitId = computed(() => Number(route.params.unitId))
const apiBase = computed(() => rollingBase(route.query))
const TABS = [
  { key: 'platform', label: '采购成本占比 · 平台', desc: '维度：月 × 渠道 × 站点 × 品类。同一渠道站点品类下的新品、老品共用该比例。' },
  { key: 'b2b', label: '采购成本占比 · B端客户', desc: '维度：月 × B 端客户。' },
  { key: 'site', label: '库存索赔率与其他运营费用率', desc: '维度：月 × 渠道 × 站点。该比例适用于该渠道站点下全部品类和新老品单元。' },
  {
    key: 'other',
    label: '公司层其他损益',
    desc: '计入公司净利润，不分摊到任何渠道、品类或部门。收益填正数，损失或支出填负数（如财务费用 −85,000.00）。',
  },
]
</script>

<template>
  <div data-page-id="PAGE-F04-04">
    <FillingWorkspace
      :unit-id="unitId"
      :api-base="apiBase"
      title-prefix="成本比例填报"
      dims="财务BP 填报采购成本占比、库存索赔率、其他运营费用率与公司层其他损益"
      loading-text="正在加载成本比例…"
      error-title="成本比例加载失败"
      forbidden-text="成本比例只由财务BP 填报。如需开通，请联系财务负责人。"
      :tabs="TABS"
      channel-filter
    />
  </div>
</template>
