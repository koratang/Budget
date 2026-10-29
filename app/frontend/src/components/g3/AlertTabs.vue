<script setup lang="ts">
/**
 * 预算预警页签（预警中心与规则库合并为一个模块「预算预警」）：预警记录 | 规则库。
 * 规则库页签按原菜单权限显示（/api/me menus 含 rules：CEO、财务负责人、财务BP）。
 */
import { useUserStore } from '@/stores/user'

defineProps<{ current: 'alerts' | 'rules' }>()
const user = useUserStore()
</script>

<template>
  <div class="tabs" role="tablist" aria-label="预算预警">
    <RouterLink class="tab" role="tab" :to="{ name: 'alerts' }" :aria-selected="current === 'alerts'" data-tab="alerts">预警记录</RouterLink>
    <RouterLink v-if="user.canSee('rules')" class="tab" role="tab" :to="{ name: 'rules' }" :aria-selected="current === 'rules'" data-tab="rules">规则库</RouterLink>
  </div>
</template>
