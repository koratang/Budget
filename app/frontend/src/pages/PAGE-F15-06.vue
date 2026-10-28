<script setup lang="ts">
/**
 * 政策环境 PAGE-F15-06（原工具 viewPolicy + peAdd / peDel / peSet）
 * 政策环境事件台账：时间 · 业务板块 · 事件描述 · 事件影响；可编辑者逐格修改、新增与删除（删除二次确认），修改即保存。
 */
import { ref } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { useToast } from '@/components/g1/useToast'
import { POLICY_SEGS, S, type PolicyEvent } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

type Field = keyof PolicyEvent
const { toast, show } = useToast()
/** 等待二次确认删除的行 */
const pendingDel = ref<PolicyEvent | null>(null)

/** 业务板块下拉：当前值不在预设列表中时追加；未选时首项为空 */
function segList(cur: string): string[] {
  return cur && POLICY_SEGS.indexOf(cur) < 0 ? POLICY_SEGS.concat([cur]) : POLICY_SEGS
}

function peAdd(): void {
  S.POLICY_EVENTS.push({ time: '', seg: '', desc: '', impact: '' })
  commit('policy')
  show('已新增事件行，请填写时间 / 业务板块 / 事件描述 / 事件影响')
}
function peDel(i: number): void {
  pendingDel.value = null
  if (!S.POLICY_EVENTS[i]) return
  S.POLICY_EVENTS.splice(i, 1)
  commit('policy')
  show(`已删除第 ${i + 1} 行政策事件`)
}
function peSet(i: number, f: Field, e: Event): void {
  const ev = S.POLICY_EVENTS[i]
  if (!ev) return
  ev[f] = String((e.target as HTMLInputElement | HTMLSelectElement).value)
  commit('policy')
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-06" title="政策环境" desc="外部政策 → 业务指标 → 财务指标 的影响识别与影响量化" :dim="false">
    <section class="card">
      <div class="card-title">
        <span>政策环境事件台账 <span class="small muted desc">登记外部政策与事件：时间 · 业务板块 · 事件描述 · 事件影响</span></span>
        <span class="tools">
          <span class="badge" data-testid="count">{{ S.POLICY_EVENTS.length }} 条</span>
          <button v-if="store.canEdit" type="button" class="btn btn-primary" @click="peAdd">＋ 新增事件</button>
        </span>
      </div>

      <div v-if="!S.POLICY_EVENTS.length" class="empty muted">
        暂无政策事件记录{{ store.canEdit ? '，点击右上角「＋ 新增事件」开始登记' : '' }}
      </div>
      <div v-else class="table-wrap">
        <table class="table ledger">
          <thead>
            <tr><th class="w-time">时间</th><th class="w-seg">业务板块</th><th class="w-desc">事件描述</th><th>事件影响</th><th v-if="store.canEdit" class="w-op" /></tr>
          </thead>
          <tbody>
            <tr v-for="(ev, i) in S.POLICY_EVENTS" :key="i">
              <template v-if="store.canEdit">
                <td><input class="input" :value="ev.time" placeholder="如 2026-04-01" aria-label="时间" @change="peSet(i, 'time', $event)"></td>
                <td>
                  <select class="select" :value="ev.seg" aria-label="业务板块" @change="peSet(i, 'seg', $event)">
                    <option v-if="!ev.seg" value="" />
                    <option v-for="sg in segList(ev.seg)" :key="sg" :value="sg">{{ sg }}</option>
                  </select>
                </td>
                <td><input class="input" :value="ev.desc" placeholder="政策 / 事件描述" aria-label="事件描述" @change="peSet(i, 'desc', $event)"></td>
                <td><input class="input" :value="ev.impact" placeholder="对业务 / 财务的影响" aria-label="事件影响" @change="peSet(i, 'impact', $event)"></td>
                <td class="num">
                  <div class="op">
                    <template v-if="pendingDel === ev">
                      <button type="button" class="btn btn-danger" @click="peDel(i)">确认删除</button>
                      <button type="button" class="btn" @click="pendingDel = null">取消</button>
                    </template>
                    <button v-else type="button" class="btn btn-danger" title="删除该行" @click="pendingDel = ev">删除</button>
                  </div>
                </td>
              </template>
              <template v-else>
                <td>{{ ev.time }}</td><td>{{ ev.seg }}</td><td class="wrap">{{ ev.desc }}</td><td class="wrap">{{ ev.impact }}</td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="small muted note">
        台账按行登记，单元格可直接编辑，修改后自动保存；「业务板块」可选营销 / 产品 / 供应链 / 仓配履约 / 财务 / 综合。
      </p>
    </section>

    <div v-if="toast" class="toast" role="status">{{ toast }}</div>
  </BizfinPage>
</template>

<style scoped>
.desc { font-weight: 400; margin-left: var(--space-2); }
.tools { display: inline-flex; align-items: center; gap: var(--space-2); }
.empty { padding: var(--space-6) 0; text-align: center; font-size: var(--text-sm); }
.ledger .input, .ledger .select { width: 100%; height: 28px; }
.ledger td.wrap { white-space: normal; line-height: 1.6; padding-top: 6px; padding-bottom: 6px; }
.w-time { width: 128px; }
.w-seg { width: 140px; }
.w-desc { width: 36%; }
.w-op { width: 72px; }
.op { display: flex; gap: var(--space-1); justify-content: flex-end; align-items: center; }
.op .btn { height: 26px; padding: 0 var(--space-2); font-size: var(--text-xs); }
.note { margin: var(--space-3) 0 0; }
</style>
