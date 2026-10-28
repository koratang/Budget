<script setup lang="ts">
/**
 * 应用外壳 AppShell（CMP-F00-01）：左侧分组侧栏 + 顶栏面包屑与当前用户。
 * 菜单按 /api/me 的 menus 显示，无权限项与空分组隐藏（路由守卫只是体验层，拦截在服务端）。
 */
import { computed, watch, type Component } from 'vue'
import {
  Bell, Box, Calendar, Coin, Collection, Connection, DataAnalysis, DataBoard, DataLine, Document, DocumentChecked, EditPen,
  Files, Flag, Goods, Guide, HomeFilled, Histogram, Link, List, Lock, Money, Notebook, OfficeBuilding, Odometer, PieChart,
  Promotion, Setting, ShoppingBag, TrendCharts, Upload, Wallet, Warning,
} from '@element-plus/icons-vue'
import { useRoute, useRouter } from 'vue-router'
import { useUserStore } from '@/stores/user'
import { useUiStore } from '@/stores/ui'
import { NAV_GROUPS, PAGE_ROUTES, navKeyFor } from '@/router/routes'
import PageState from './PageState.vue'

const route = useRoute()
const router = useRouter()
const user = useUserStore()
const ui = useUiStore()

/** 一级标题（分组）与二级菜单图标；按分组名 / 路由名取，未列出的不显示图标 */
const GROUP_ICONS: Record<string, Component> = {
  预算编制: Notebook, 预算版本: Files, 实际数: Coin, 报表: DataAnalysis, 业财分析: TrendCharts, 预警与规则: Bell, 基础数据: Box, 系统设置: Setting,
}
const ITEM_ICONS: Record<string, Component> = {
  workbench: HomeFilled, tasks: Calendar, 'my-filling': EditPen, 'dept-expense': Wallet, approvals: DocumentChecked,
  versions: Collection, import: Upload, reconcile: Connection, 'report-company': Odometer, 'report-channel': DataBoard,
  'report-category': PieChart, 'report-dept': DataLine, alerts: Warning, rules: Document, stores: ShoppingBag, sku: Goods,
  customers: OfficeBuilding, accounts: Link, fx: Money, roles: Lock,
  'bizfin-finance': Histogram, 'bizfin-business': Promotion, 'bizfin-analysis': DataAnalysis, 'bizfin-policy': Guide,
  'bizfin-keywork': Flag,
  'bizfin-data': List,
}

const groups = computed(() =>
  NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((it) => user.canSee(it.name)) })).filter((g) => g.items.length > 0),
)

const activeNav = computed(() => navKeyFor(String(route.name ?? '')))

const crumbs = computed(() => {
  const list: { label: string; to?: { name: string } }[] = []
  if (route.meta.group) list.push({ label: route.meta.group })
  if (route.meta.parent) {
    const parent = PAGE_ROUTES.find((r) => r.name === route.meta.parent)
    if (parent) list.push({ label: parent.title, to: { name: parent.name } })
  }
  list.push({ label: ui.crumbTitle ?? route.meta.title ?? '' })
  return list
})

watch(
  () => route.fullPath,
  () => ui.setCrumbTitle(null),
)

async function logout(): Promise<void> {
  try {
    await user.logout()
  } finally {
    await router.replace({ name: 'login' })
  }
}

async function retry(): Promise<void> {
  try {
    const me = await user.fetchMe(true)
    if (!me) await router.replace({ name: 'login', query: { redirect: route.fullPath } })
  } catch {
    // loadError 已记录，继续显示错误态
  }
}
</script>

<template>
  <div class="app" data-cmp="CMP-F00-01">
    <aside class="sidebar" aria-label="主导航">
      <div class="brand">预算管理平台</div>
      <template v-for="g in groups" :key="g.label ?? '_'">
        <div v-if="g.label" class="nav-group">
          <component :is="GROUP_ICONS[g.label]" v-if="GROUP_ICONS[g.label]" class="nav-icon" aria-hidden="true" />{{ g.label }}
        </div>
        <RouterLink v-for="it in g.items" :key="it.name" :to="{ name: it.name }" custom v-slot="{ href, navigate }">
          <a
            class="nav-item"
            :class="{ 'nav-top': !g.label }"
            :href="href"
            :aria-current="activeNav === it.name ? 'page' : undefined"
            :data-menu="it.name"
            @click="navigate"
            ><component :is="ITEM_ICONS[it.name]" v-if="ITEM_ICONS[it.name]" class="nav-icon" aria-hidden="true" />{{ it.label }}</a
          >
        </RouterLink>
      </template>
    </aside>
    <div class="shell-body">
      <header class="topbar">
        <nav aria-label="面包屑" class="crumbs">
          <template v-for="(c, i) in crumbs" :key="i">
            <span v-if="i > 0" class="sep"> / </span>
            <RouterLink v-if="c.to" :to="c.to">{{ c.label }}</RouterLink>
            <span v-else :aria-current="i === crumbs.length - 1 ? 'page' : undefined">{{ c.label }}</span>
          </template>
        </nav>
        <div v-if="user.me" class="who">
          当前用户：<span data-current-user>{{ user.displayName }}</span> ·
          <a href="/login" @click.prevent="logout">退出</a>
        </div>
      </header>
      <main class="main">
        <PageState
          v-if="!user.me && user.loadError"
          :error="user.loadError"
          title="无法连接服务"
          @retry="retry"
        />
        <RouterView v-else />
      </main>
    </div>
  </div>
</template>

<style scoped>
.brand { font-weight: 600; padding: 8px 12px 12px; }
.shell-body { min-width: 0; }
.crumbs { color: var(--muted); font-size: var(--text-sm); }
.crumbs a, .who a { color: var(--fg-2); }
.crumbs a:focus-visible, .who a:focus-visible { outline: none; box-shadow: var(--focus-ring); border-radius: var(--radius-sm); }
.who { font-size: var(--text-sm); color: var(--fg-2); }
</style>
