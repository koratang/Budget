<script setup lang="ts">
/**
 * 开发模式身份切换（DEC-002 / DEC-013）
 * 仅开发构建打包（LoginPage 通过 __DEV_IDENTITY_SWITCH__ 常量引用，生产构建整段剔除），
 * 且仅当 GET /api/auth/dev-users 可用（后端开发配置注册）时渲染。
 */
import { onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import { roleName, type DevUser } from '@/api/types'

const emit = defineEmits<{ start: []; success: []; denied: [error: ApiError, name: string] }>()

const users = ref<DevUser[]>([])
const selected = ref<number | null>(null)
const busy = ref(false)

function labelOf(u: DevUser): string {
  if (u.label) return u.label
  const roles = (u.roles ?? []).map(roleName)
  return roles.length ? `${u.name} · ${roles.join('、')}` : `${u.name} · 未分配角色（测试拒绝）`
}

onMounted(async () => {
  try {
    const data = await api.get<DevUser[] | { users: DevUser[] }>('/api/auth/dev-users', undefined, { redirectOn401: false })
    users.value = Array.isArray(data) ? data : (data.users ?? [])
    selected.value = users.value[0]?.id ?? null
  } catch {
    users.value = [] // 未注册（生产配置 404）或后端不可用：不渲染
  }
})

async function enter(): Promise<void> {
  if (selected.value === null || busy.value) return
  const user = users.value.find((u) => u.id === selected.value)
  busy.value = true
  emit('start')
  try {
    await api.post('/api/auth/dev-login', { user_id: selected.value }, { redirectOn401: false })
    emit('success')
  } catch (e) {
    emit('denied', e instanceof ApiError ? e : new ApiError(0, 'network_error', String(e)), user?.name ?? '')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="users.length" class="dev" data-dev-switch>
    <span class="dev-tag">仅开发配置可见，生产强制关闭</span>
    <p class="hint" style="margin-bottom: var(--space-3)">
      <strong>开发模式身份切换</strong>　用样例员工身份进入，用于钉钉应用就绪前的本机验收
    </p>
    <div class="dev-row">
      <label for="dev-user" class="sub">身份</label>
      <select id="dev-user" v-model.number="selected" class="select">
        <option v-for="u in users" :key="u.id" :value="u.id">{{ labelOf(u) }}</option>
      </select>
      <button type="button" class="btn btn-primary" :disabled="busy" @click="enter">以此身份进入</button>
    </div>
  </div>
</template>

<style scoped>
.dev { margin-top: var(--space-6); border: 1px dashed var(--muted); border-radius: var(--radius-lg); padding: var(--space-4) var(--space-6); background: var(--surface-warm); position: relative; }
.dev-tag { position: absolute; top: -10px; left: var(--space-4); padding: 0 var(--space-2); background: var(--bg); font-size: var(--text-xs); color: var(--muted); }
.dev-row { display: flex; gap: var(--space-3); align-items: center; }
.dev-row .select { width: 340px; }
.hint { color: var(--fg-2); margin: 0 0 var(--space-1); }
.sub { color: var(--muted); font-size: var(--text-sm); margin: 0; }
</style>
