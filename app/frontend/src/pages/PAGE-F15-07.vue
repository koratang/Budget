<script setup lang="ts">
/**
 * 经营建议 PAGE-F15-07（原工具 viewAdvice + avAdd / avDel / avSet）
 * 管理建议台账：时间 · 业务板块 · 背景描述 · 管理建议 · 影响评估；可编辑者逐格修改、新增与删除（删除二次确认），修改即保存。
 */
import { ref } from 'vue'
import BizfinPage from '@/components/g5/BizfinPage.vue'
import { useToast } from '@/components/g1/useToast'
import { POLICY_SEGS, S, type AdviceEvent } from '@/bizfin/engine'
import { commit, store } from '@/bizfin/persist'

type Field = keyof AdviceEvent
const { toast, show } = useToast()
/** 等待二次确认删除的行 */
const pendingDel = ref<AdviceEvent | null>(null)

/** 业务板块下拉：当前值不在预设列表中时追加；未选时首项为空 */
function segList(cur: string): string[] {
  return cur && POLICY_SEGS.indexOf(cur) < 0 ? POLICY_SEGS.concat([cur]) : POLICY_SEGS
}

function avAdd(): void {
  S.ADVICE_EVENTS.push({ time: '', seg: '', desc: '', advice: '', impact: '' })
  commit('advice')
  show('已新增建议行，请填写时间 / 业务板块 / 背景描述 / 管理建议 / 影响评估')
}
function avDel(i: number): void {
  pendingDel.value = null
  if (!S.ADVICE_EVENTS[i]) return
  S.ADVICE_EVENTS.splice(i, 1)
  commit('advice')
  show(`已删除第 ${i + 1} 行管理建议`)
}
function avSet(i: number, f: Field, e: Event): void {
  const ev = S.ADVICE_EVENTS[i]
  if (!ev) return
  ev[f] = String((e.target as HTMLInputElement | HTMLSelectElement).value)
  commit('advice')
}
</script>

<template>
  <BizfinPage page-id="PAGE-F15-07" title="经营建议" desc="基于指标偏差自动生成的改善动作与财务影响测算" :dim="false">
    <section class="card">
      <div class="card-title">
        <span>管理建议台账 <span class="small muted desc">登记经营改善事项：时间 · 业务板块 · 背景描述 · 管理建议 · 影响评估</span></span>
        <span class="tools">
          <span class="badge" data-testid="count">{{ S.ADVICE_EVENTS.length }} 条</span>
          <button v-if="store.canEdit" type="button" class="btn btn-primary" @click="avAdd">＋ 新增建议</button>
        </span>
      </div>

      <div v-if="!S.ADVICE_EVENTS.length" class="empty muted">
        暂无管理建议记录{{ store.canEdit ? '，点击右上角「＋ 新增建议」开始登记' : '' }}
      </div>
      <div v-else class="table-wrap">
        <table class="table ledger">
          <thead>
            <tr><th class="w-time">时间</th><th class="w-seg">业务板块</th><th class="w-desc">背景描述</th><th class="w-adv">管理建议</th><th>影响评估</th><th v-if="store.canEdit" class="w-op" /></tr>
          </thead>
          <tbody>
            <tr v-for="(ev, i) in S.ADVICE_EVENTS" :key="i">
              <template v-if="store.canEdit">
                <td><input class="input" :value="ev.time" placeholder="如 2026-04" aria-label="时间" @change="avSet(i, 'time', $event)"></td>
                <td>
                  <select class="select" :value="ev.seg" aria-label="业务板块" @change="avSet(i, 'seg', $event)">
                    <option v-if="!ev.seg" value="" />
                    <option v-for="sg in segList(ev.seg)" :key="sg" :value="sg">{{ sg }}</option>
                  </select>
                </td>
                <td><input class="input" :value="ev.desc" placeholder="背景 / 问题现状" aria-label="背景描述" @change="avSet(i, 'desc', $event)"></td>
                <td><input class="input" :value="ev.advice" placeholder="管理建议 / 改善动作" aria-label="管理建议" @change="avSet(i, 'advice', $event)"></td>
                <td><input class="input" :value="ev.impact" placeholder="对业务 / 财务的影响评估" aria-label="影响评估" @change="avSet(i, 'impact', $event)"></td>
                <td class="num">
                  <div class="op">
                    <template v-if="pendingDel === ev">
                      <button type="button" class="btn btn-danger" @click="avDel(i)">确认删除</button>
                      <button type="button" class="btn" @click="pendingDel = null">取消</button>
                    </template>
                    <button v-else type="button" class="btn btn-danger" title="删除该行" @click="pendingDel = ev">删除</button>
                  </div>
                </td>
              </template>
              <template v-else>
                <td>{{ ev.time }}</td><td>{{ ev.seg }}</td><td class="wrap">{{ ev.desc }}</td><td class="wrap">{{ ev.advice }}</td><td class="wrap">{{ ev.impact }}</td>
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
.w-time { width: 112px; }
.w-seg { width: 128px; }
.w-desc { width: 27%; }
.w-adv { width: 32%; }
.w-op { width: 72px; }
.op { display: flex; gap: var(--space-1); justify-content: flex-end; align-items: center; }
.op .btn { height: 26px; padding: 0 var(--space-2); font-size: var(--text-xs); }
.note { margin: var(--space-3) 0 0; }
</style>
