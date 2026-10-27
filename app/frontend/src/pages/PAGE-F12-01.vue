<script setup lang="ts">
/**
 * PAGE-F12-01 规则库：类型标签、可信度与状态筛选、规则列表；财务BP / 财务负责人可新建（API-F12-01；AC-F12-01~03）。
 */
import { computed, onMounted, ref } from 'vue'
import { api, ApiError } from '@/api/client'
import PageState from '@/components/PageState.vue'
import '@/components/g3/g3.css'

interface RuleRow {
  id: number; name: string; type: string; type_label: string; is_preset: boolean; credibility: string | null
  credibility_label: string | null; effective_version_no: number | null; effective_at: string | null
  pending: { version_no: number; status_label: string; credibility_label: string; waiting_for: string } | null
  latest_submitter: string | null
}

const TYPES = [{ v: '', l: '全部' }, { v: 'driver_assumption', l: '驱动假设' }, { v: 'alert_rule', l: '预警规则' }, { v: 'quota_standard', l: '额度标准' }]
const type = ref('')
const cred = ref('')
const state = ref('')
const items = ref<RuleRow[]>([])
const canCreate = ref(false)
const loading = ref(true)
const error = ref<unknown>(null)

const rows = computed(() => items.value.filter((r) =>
  (!type.value || r.type === type.value) && (!cred.value || r.credibility === cred.value)
  && (!state.value || (state.value === 'effective' ? r.effective_version_no : r.pending))))
const forbiddenText = computed(() =>
  error.value instanceof ApiError && error.value.isForbidden ? '规则库仅对财务BP、财务负责人和 CEO 开放。' : undefined)

async function load(): Promise<void> {
  error.value = null
  try {
    const d = await api.get<{ items: RuleRow[]; can_create: boolean }>('/api/rules')
    items.value = d.items
    canCreate.value = d.can_create
  } catch (e) {
    error.value = e
  } finally {
    loading.value = false
  }
}
onMounted(load)

function credBadge(c: string | null): string {
  return c === 'unverified' ? 'badge-warn' : c === 'verified' ? 'badge-good' : ''
}
</script>

<template>
  <div data-page-id="PAGE-F12-01" class="g3">
    <div class="page-head"><h1 class="page-title">规则库</h1></div>
    <PageState v-if="loading" state="loading" />
    <PageState v-else-if="error" :error="error" :description="forbiddenText" @retry="load" />
    <div v-else-if="!items.length" class="card state">
      <div class="state-title">规则库还没有规则</div>
      <p>把驱动假设、预警规则和额度标准放进规则库，审批通过后生效并保留版本历史。</p>
      <RouterLink v-if="canCreate" class="btn" :to="{ name: 'rule-detail', params: { id: 'new' } }">新建规则</RouterLink>
    </div>
    <template v-else>
      <div class="row" style="margin-bottom: var(--space-3)">
        <div class="tabs" role="tablist" style="margin-bottom: 0">
          <a v-for="t in TYPES" :key="t.v" class="tab" href="#" role="tab" :aria-selected="type === t.v" @click.prevent="type = t.v">{{ t.l }}</a>
        </div>
        <span class="spacer"></span>
        <label class="small muted" for="f-cred">可信度</label>
        <select id="f-cred" v-model="cred" class="select"><option value="">全部</option><option value="unverified">未验证经验</option><option value="observed">历史观察</option><option value="verified">已验证</option></select>
        <label class="small muted" for="f-st">状态</label>
        <select id="f-st" v-model="state" class="select"><option value="">全部</option><option value="effective">有生效版本</option><option value="pending">有待审批版本</option></select>
        <RouterLink v-if="canCreate" class="btn btn-primary" :to="{ name: 'rule-detail', params: { id: 'new' } }">新建规则</RouterLink>
      </div>
      <p class="small muted" style="margin: 0 0 var(--space-3)">可信度：<span class="badge badge-warn">未验证经验</span> 凭经验提出、尚无数据支撑 · <span class="badge">历史观察</span> 有历史数据观察支撑 · <span class="badge badge-good">已验证</span> 经实际结果检验。驱动假设和预警规则由财务负责人审批；额度标准还需 CEO 审批。</p>
      <div class="table-wrap">
        <table class="table">
          <thead><tr><th>规则名称</th><th>类型</th><th>可信度</th><th>生效版本</th><th>待审批版本</th><th>生效时间</th><th>最近提交人</th><th>操作</th></tr></thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id">
              <td class="wrap"><RouterLink class="link" :to="{ name: 'rule-detail', params: { id: String(r.id) } }">{{ r.name }}</RouterLink>
                <span v-if="r.is_preset" class="small muted"> · 系统预置</span></td>
              <td>{{ r.type_label }}</td>
              <td><span v-if="r.credibility_label" class="badge" :class="credBadge(r.credibility)">{{ r.credibility_label }}</span><span v-else class="muted">—</span></td>
              <td>{{ r.effective_version_no ? `生效 v${r.effective_version_no}` : '无' }}</td>
              <td class="w-n">{{ r.pending ? `${r.pending.status_label} v${r.pending.version_no}（${r.pending.credibility_label}，待${r.pending.waiting_for}审批）` : '—' }}</td>
              <td class="num">{{ r.effective_at ?? '—' }}</td>
              <td>{{ r.latest_submitter ?? '—' }}</td>
              <td><RouterLink class="link" :to="{ name: 'rule-detail', params: { id: String(r.id) } }">查看</RouterLink></td>
            </tr>
          </tbody>
        </table>
        <div v-if="!rows.length" class="state"><div class="state-title">没有符合筛选条件的规则</div><p>换一个类型、可信度或状态。</p></div>
      </div>
      <div class="pager"><span>共 {{ rows.length }} 条</span></div>
    </template>
  </div>
</template>
