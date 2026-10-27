import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { roleName, type Me } from '@/api/types'

/** 当前用户（GET /api/me） */
export const useUserStore = defineStore('user', () => {
  const me = ref<Me | null>(null)
  /** 最近一次加载 /api/me 的非 401 错误（后端不可用等），AppShell 据此显示错误态 */
  const loadError = ref<ApiError | null>(null)
  let pending: Promise<Me | null> | null = null

  const loggedIn = computed(() => me.value !== null)
  const menus = computed(() => new Set(me.value?.menus ?? []))
  const roleNames = computed(() => (me.value?.roles ?? []).map(roleName))
  /** 顶栏显示：林晓（财务负责人） */
  const displayName = computed(() => {
    if (!me.value) return ''
    const roles = roleNames.value.join('、')
    return roles ? `${me.value.user.name}（${roles}）` : me.value.user.name
  })

  /** 加载当前用户；未登录返回 null，其他错误抛出 */
  async function fetchMe(force = false): Promise<Me | null> {
    if (me.value && !force) return me.value
    if (pending) return pending
    pending = (async () => {
      try {
        me.value = await api.get<Me>('/api/me', undefined, { redirectOn401: false })
        loadError.value = null
        return me.value
      } catch (e) {
        if (e instanceof ApiError && e.isUnauthenticated) {
          me.value = null
          loadError.value = null
          return null
        }
        loadError.value = e instanceof ApiError ? e : new ApiError(0, 'network_error', String(e))
        throw e
      } finally {
        pending = null
      }
    })()
    return pending
  }

  function canSee(menuKey: string): boolean {
    return menus.value.has(menuKey)
  }

  async function logout(): Promise<void> {
    try {
      await api.post('/api/auth/logout', undefined, { redirectOn401: false })
    } finally {
      clear()
    }
  }

  function clear(): void {
    me.value = null
    loadError.value = null
  }

  return { me, loadError, loggedIn, menus, roleNames, displayName, fetchMe, canSee, logout, clear }
})
