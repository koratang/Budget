<script setup lang="ts">
/** PAGE-F04-05 物流比例填报（物流物控）：只有头程、尾程、仓储、关税四项比例（AC-F04-05、AC-F01-09） */
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { rollingBase } from '@/components/g2/util'
import FillingWorkspace from '@/components/g2/FillingWorkspace.vue'

const route = useRoute()
const unitId = computed(() => Number(route.params.unitId))
const apiBase = computed(() => rollingBase(route.query))
const TABS = [
  { key: 'platform', label: '平台渠道', desc: '只填写头程费率、尾程费率、仓储费率、关税率四项；各项按人民币收入的百分比计算。' },
  { key: 'b2b', label: 'B 端客户', desc: '每个 B 端客户四项比例，维度：月 × B 端客户。' },
]
</script>

<template>
  <div data-page-id="PAGE-F04-05">
    <FillingWorkspace
      :unit-id="unitId"
      :api-base="apiBase"
      title-prefix="物流比例填报"
      dims="维度：月 × 渠道 × 站点 × 品类、月 × B 端客户"
      loading-text="正在加载物流比例…"
      error-title="物流比例加载失败"
      forbidden-text="物流比例只由物流物控填报。如需开通，请联系财务负责人。"
      :tabs="TABS"
      channel-filter
      foot-right="本页不显示收入、销量与利润"
    />
  </div>
</template>
