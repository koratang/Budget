import type { Component } from 'vue'
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ApiError } from '@/api/client'
import { useUserStore } from '@/stores/user'
import AppShell from '@/components/AppShell.vue'
import { LOGIN_ROUTE, PAGE_ROUTES } from './routes'

declare module 'vue-router' {
  interface RouteMeta {
    pageId?: string
    title?: string
    group?: string
    parent?: string
    public?: boolean
  }
}

// 每个页面一个文件 src/pages/PAGE-Fxx-xx.vue，按需加载
const pageModules = import.meta.glob<{ default: Component }>('../pages/PAGE-*.vue')

function pageComponent(pageId: string) {
  const loader = pageModules[`../pages/${pageId}.vue`]
  if (!loader) throw new Error(`缺少页面文件 src/pages/${pageId}.vue`)
  return loader
}

const shellChildren: RouteRecordRaw[] = PAGE_ROUTES.map((r) => ({
  path: r.path,
  ...(r.alias ? { alias: r.alias } : {}),
  name: r.name,
  component: pageComponent(r.pageId),
  meta: { pageId: r.pageId, title: r.title, group: r.group, parent: r.parent },
}))

export const routes: RouteRecordRaw[] = [
  {
    path: LOGIN_ROUTE.path,
    name: LOGIN_ROUTE.name,
    component: pageComponent(LOGIN_ROUTE.pageId),
    meta: { pageId: LOGIN_ROUTE.pageId, title: LOGIN_ROUTE.title, public: true },
  },
  { path: '/', component: AppShell, children: shellChildren },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

export const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

/** 登录被拒原因：后端以这些 code 表示（无角色 / 账号停用） */
export const LOGIN_DENY_CODES = ['no_role', 'account_disabled'] as const

// 守卫：未登录跳 /login?redirect=原链接。后端不可用时放行，由 AppShell 显示错误态。
router.beforeEach(async (to) => {
  if (to.meta.public) return true
  const user = useUserStore()
  try {
    const me = await user.fetchMe()
    if (!me) return { name: 'login', query: { redirect: to.fullPath } }
    return true
  } catch (e) {
    if (e instanceof ApiError && (LOGIN_DENY_CODES as readonly string[]).includes(e.code)) {
      return { name: 'login', query: { error: e.code } }
    }
    return true
  }
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} · 预算管理平台` : '预算管理平台'
})
