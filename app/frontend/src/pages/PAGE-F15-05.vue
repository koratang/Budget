<script setup lang="ts">
/**
 * 数据分析 PAGE-F15-05（REQ-F15-03）：九个子模块页内切换，子模块 id 放在路径 /bizfin/analysis/:sub。
 * 子模块顺序与名称取引擎 ANA_NAV（同原工作台）；缺数据源的子模块标「示例数据」。
 */
import { computed, type Component } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import AnaAdmin from '@/components/g5/analysis/AnaAdmin.vue'
import AnaCategory from '@/components/g5/analysis/AnaCategory.vue'
import AnaChannel from '@/components/g5/analysis/AnaChannel.vue'
import AnaLogiPost from '@/components/g5/analysis/AnaLogiPost.vue'
import AnaLogiPre from '@/components/g5/analysis/AnaLogiPre.vue'
import AnaOrder from '@/components/g5/analysis/AnaOrder.vue'
import AnaTraffic from '@/components/g5/analysis/AnaTraffic.vue'
import AnaUser from '@/components/g5/analysis/AnaUser.vue'
import AnaWarehouse from '@/components/g5/analysis/AnaWarehouse.vue'
import { ANA_NAV } from '@/bizfin/engine'

const VIEWS: Record<string, Component> = {
  anaChannel: AnaChannel, anaTraffic: AnaTraffic, anaUser: AnaUser, anaOrder: AnaOrder, anaCategory: AnaCategory,
  anaLogiPre: AnaLogiPre, anaLogiPost: AnaLogiPost, anaWarehouse: AnaWarehouse, anaAdmin: AnaAdmin,
}
/** 依赖平台暂无数据源的推算模型（流量、新老客、订单、SPU、服务商单价、库存、部门费用结构）的子模块 */
const SYNTHETIC = new Set(['anaTraffic', 'anaUser', 'anaOrder', 'anaCategory', 'anaLogiPre', 'anaLogiPost',
  'anaWarehouse', 'anaAdmin'])

const route = useRoute()
const router = useRouter()
const sub = computed(() => {
  const s = String(route.params.sub ?? '')
  return s in VIEWS ? s : 'anaChannel'
})
const current = computed(() => ANA_NAV.find((a) => a.id === sub.value) ?? ANA_NAV[0])

function go(id: string): void {
  void router.replace({ name: 'bizfin-analysis', params: { sub: id } })
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-05" :title="`数据分析 · ${current.name}`" :desc="current.desc" :synthetic="SYNTHETIC.has(sub)">
    <div class="tabs" role="tablist" aria-label="分析子模块">
      <button
        v-for="a in ANA_NAV"
        :key="a.id"
        type="button"
        role="tab"
        class="tab tab-btn"
        :aria-selected="a.id === sub"
        :data-ana="a.id"
        @click="go(a.id)"
      >{{ a.name }}</button>
    </div>
    <component :is="VIEWS[sub]" :key="sub" />
  </BizfinPage>
</template>

<style scoped>
.tab-btn { background: none; border-top: 0; border-left: 0; border-right: 0; font: inherit; cursor: pointer; }
.tabs { flex-wrap: wrap; }
</style>
