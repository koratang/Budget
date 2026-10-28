<script setup lang="ts">
/**
 * 业财分析页面外壳（CMP-F15-03）：页头（标题、示例数据标记、年度 / 月度维度切换、保存状态）+ 加载 / 无权限 / 错误态。
 * 数据由 persist.load() 一次读入引擎，同一会话内各页共享；默认插槽在数据就绪后渲染。
 */
import { computed, onMounted } from 'vue'
import PageState from '@/components/PageState.vue'
import { MONTHS9, S, periodLabel, recompute } from '@/bizfin/engine'
import { anyDemo, load, store } from '@/bizfin/persist'
import './g5.css'

const props = withDefaults(
  defineProps<{
    pageId: string
    title: string
    desc?: string
    /** 显示年度 / 月度维度切换（原工具全局维度） */
    dim?: boolean
    /** 本页含按结构基准推算的模拟数据（流量、新老客、订单、服务商单价、库存等），始终标「示例数据」 */
    synthetic?: boolean
  }>(),
  { desc: undefined, dim: true, synthetic: false },
)

const demo = computed(() => props.synthetic || anyDemo())
const demoTip = computed(() =>
  props.synthetic
    ? '本页部分数据为按结构基准推算的示例数据（平台暂无流量、新老客、订单、服务商单价、库存等数据源），仅供演示口径与分析方法。'
    : '尚有部分内容为原工具自带的示例数据；在「数据管理」导入正式数据后，此标记消失。',
)

function setDim(d: 'year' | 'month'): void {
  if (S.dim === d) return
  S.dim = d
  recompute()
}
function setMonth(e: Event): void {
  S.curM = Math.min(9, Math.max(1, Number((e.target as HTMLSelectElement).value) || 9))
  recompute()
}

onMounted(() => void load())
</script>

<template>
  <div :data-page-id="pageId" class="g5">
    <div class="page-head">
      <div>
        <h1 class="page-title">
          {{ title }}
          <span v-if="store.loaded && demo" class="badge badge-warn demo-badge" :title="demoTip" data-demo-badge>示例数据</span>
        </h1>
        <div v-if="desc" class="meta">{{ desc }}</div>
      </div>
      <div v-if="store.loaded" class="head-tools">
        <span v-if="store.saving" class="small muted" role="status">保存中…</span>
        <template v-if="dim">
          <div class="seg" role="group" aria-label="维度">
            <button type="button" :aria-pressed="S.dim === 'year'" @click="setDim('year')">年度</button>
            <button type="button" :aria-pressed="S.dim === 'month'" @click="setDim('month')">月度</button>
          </div>
          <select v-if="S.dim === 'month'" class="select" aria-label="月份" :value="S.curM" @change="setMonth">
            <option v-for="(m, i) in MONTHS9" :key="m" :value="i + 1">{{ m }}</option>
          </select>
          <span class="small muted">{{ periodLabel() }}</span>
        </template>
        <slot name="tools" />
      </div>
    </div>

    <div v-if="store.saveError" class="save-error" role="alert">
      {{ store.saveError }}
      <button type="button" class="btn" @click="load(true)">刷新数据</button>
    </div>

    <PageState v-if="!store.loaded && store.error" :error="store.error" title="业财分析数据加载失败" @retry="load(true)" />
    <PageState v-else-if="!store.loaded" state="loading" :rows="8" />
    <template v-else>
      <p v-if="demo" class="demo-note">{{ demoTip }}</p>
      <slot />
    </template>
  </div>
</template>
