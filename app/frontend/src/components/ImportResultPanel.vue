<script setup lang="ts">
/**
 * 导入与错误清单 ImportResultPanel（CMP-F09-02）
 * 上传（进度）→ 轮询校验状态 → 未通过：问题清单（行号 / 问题类型 / 编码或名称 / 处理方式）
 * → 通过：摘要插槽 + 覆盖提示 → 确认导入（需覆盖时二次确认弹窗）。
 * 复用于 SKU 对照表、填报模板、金蝶、BI 导入；接口地址由使用方传入。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { ElDialog, ElProgress } from 'element-plus'
import { api, ApiError, NETWORK_ERROR_MESSAGE, upload } from '@/api/client'
import type { ImportBatch } from './importTypes'

const props = withDefaults(
  defineProps<{
    /** 上传地址，如 /api/imports */
    uploadUrl: string
    /** 批次状态地址，默认 /api/imports/{id} */
    statusUrl?: (id: ImportBatch['id']) => string
    /** 确认入库地址，默认 /api/imports/{id}/confirm；为 null 表示校验通过即入库（无确认步骤） */
    confirmUrl?: ((id: ImportBatch['id']) => string) | null
    /** 随文件一起提交的表单字段，如 { source: 'kingdee' } */
    fields?: Record<string, string>
    accept?: string
    buttonText?: string
    pollInterval?: number
    disabled?: boolean
  }>(),
  {
    statusUrl: (id: ImportBatch['id']) => `/api/imports/${id}`,
    confirmUrl: (id: ImportBatch['id']) => `/api/imports/${id}/confirm`,
    fields: () => ({}),
    accept: '.xlsx,.xls',
    buttonText: '上传文件',
    pollInterval: 1500,
    disabled: false,
  },
)

const emit = defineEmits<{
  imported: [batch: ImportBatch]
  failed: [batch: ImportBatch]
  passed: [batch: ImportBatch]
  cancelled: []
}>()

type Phase = 'idle' | 'uploading' | 'validating' | 'failed' | 'passed' | 'confirming' | 'imported' | 'error'

const phase = ref<Phase>('idle')
const progress = ref(0)
const fileName = ref('')
const batch = ref<ImportBatch | null>(null)
const errorMessage = ref('')
const confirmOpen = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let timer: ReturnType<typeof setTimeout> | null = null
let disposed = false

const issues = computed(() => batch.value?.issues ?? [])
const busy = computed(() => ['uploading', 'validating', 'confirming'].includes(phase.value))
const overwriteText = computed(() => {
  const o = batch.value?.overwrite
  if (!o) return ''
  return `${o.periods.join('、')} 已有导入数据：${o.file_name}（${o.imported_by}，${o.imported_at}）`
})

function stopPolling(): void {
  if (timer) clearTimeout(timer)
  timer = null
}

function fail(e: unknown): void {
  stopPolling()
  phase.value = 'error'
  errorMessage.value = e instanceof ApiError ? e.message : NETWORK_ERROR_MESSAGE
}

function apply(b: ImportBatch): void {
  batch.value = b
  if (b.status === 'validating') {
    phase.value = 'validating'
    timer = setTimeout(poll, props.pollInterval)
  } else if (b.status === 'failed') {
    phase.value = 'failed'
    emit('failed', b)
  } else if (b.status === 'passed') {
    phase.value = 'passed'
    emit('passed', b)
  } else if (b.status === 'imported') {
    phase.value = 'imported'
    emit('imported', b)
  }
}

async function poll(): Promise<void> {
  if (disposed || !batch.value) return
  try {
    apply(await api.get<ImportBatch>(props.statusUrl(batch.value.id)))
  } catch (e) {
    fail(e)
  }
}

async function onFile(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  stopPolling()
  batch.value = null
  fileName.value = file.name
  progress.value = 0
  phase.value = 'uploading'
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(props.fields)) form.append(k, v)
  try {
    const created = await upload<ImportBatch>(props.uploadUrl, form, (p) => (progress.value = p))
    apply({ ...created, status: created.status ?? 'validating' })
  } catch (e) {
    fail(e)
  }
}

function pick(): void {
  fileInput.value?.click()
}

async function confirm(overwrite: boolean): Promise<void> {
  if (!batch.value || !props.confirmUrl) return
  confirmOpen.value = false
  phase.value = 'confirming'
  try {
    apply(await api.post<ImportBatch>(props.confirmUrl(batch.value.id), { overwrite }))
  } catch (e) {
    fail(e)
  }
}

function onConfirmClick(): void {
  if (batch.value?.needs_overwrite) confirmOpen.value = true
  else void confirm(false)
}

function reset(): void {
  stopPolling()
  phase.value = 'idle'
  batch.value = null
  fileName.value = ''
  emit('cancelled')
}

onBeforeUnmount(() => {
  disposed = true
  stopPolling()
})

defineExpose({ reset, pick })
</script>

<template>
  <div class="import-panel" data-cmp="CMP-F09-02" :data-phase="phase">
    <div class="import-actions">
      <button type="button" class="btn btn-primary" :disabled="disabled || busy" @click="pick">{{ buttonText }}</button>
      <input ref="fileInput" type="file" :accept="accept" hidden @change="onFile" />
      <span v-if="fileName" class="meta">{{ fileName }}</span>
    </div>

    <div v-if="phase === 'uploading'" class="import-body" aria-live="polite">
      <el-progress :percentage="progress" :stroke-width="6" />
      <p class="meta">正在上传 {{ fileName }}…</p>
    </div>

    <div v-else-if="phase === 'validating' || phase === 'confirming'" class="import-body" aria-live="polite" aria-busy="true">
      <div class="skeleton" style="width: 40%"></div>
      <div class="skeleton" style="margin-top: var(--space-3)"></div>
      <p class="meta">
        {{ phase === 'confirming' ? '正在写入…' : `正在校验 ${fileName}${batch?.row_count ? `（${batch.row_count} 行）` : ''}…` }}
      </p>
    </div>

    <div v-else-if="phase === 'error'" class="notice notice-bad import-body" role="alert">
      <span class="t">{{ errorMessage }}</span>
      <button type="button" class="btn" style="margin-left: var(--space-3)" @click="reset">重新选择文件</button>
    </div>

    <div v-else-if="phase === 'failed'" class="import-body">
      <div class="notice notice-bad" role="alert">
        <span class="t">校验未通过，本文件没有写入任何数据。</span>共 {{ issues.length }} 个问题行
      </div>
      <slot name="issues-summary" :batch="batch" />
      <div class="table-wrap issues">
        <table class="table">
          <thead>
            <tr>
              <th class="num">行号</th>
              <th>问题类型</th>
              <th>涉及编码或名称</th>
              <th>处理方式</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(it, i) in issues" :key="i">
              <td class="num">{{ typeof it.row === 'number' ? `第 ${it.row.toLocaleString('en-US')} 行` : it.row }}</td>
              <td>{{ it.type }}</td>
              <td class="code">{{ it.name ?? '—' }}</td>
              <td>
                <RouterLink v-if="it.link" :to="it.link" class="link">{{ it.action ?? '去处理' }}</RouterLink>
                <span v-else>{{ it.action ?? '—' }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-else-if="phase === 'passed'" class="import-body">
      <div class="notice notice-good" role="status"><span class="t">校验通过</span></div>
      <slot name="summary" :batch="batch" />
      <div v-if="batch?.needs_overwrite" class="notice notice-warn" role="status">{{ overwriteText }}</div>
      <div v-if="confirmUrl" class="import-actions">
        <button type="button" class="btn" @click="reset">放弃</button>
        <button type="button" class="btn btn-primary" @click="onConfirmClick">
          {{ batch?.needs_overwrite ? '确认覆盖导入' : '确认导入' }}
        </button>
      </div>
    </div>

    <div v-else-if="phase === 'imported'" class="import-body">
      <div class="notice notice-good" role="status"><span class="t">已导入</span> {{ fileName }}</div>
      <slot name="imported" :batch="batch" />
    </div>

    <el-dialog v-model="confirmOpen" title="确认覆盖导入" width="480px" append-to-body>
      <p>{{ overwriteText }}</p>
      <p>确认后用新文件替换这些期间的全部数据，旧导入记录保留并标记「已被替换」。</p>
      <template #footer>
        <button type="button" class="btn" @click="confirmOpen = false">取消</button>
        <button type="button" class="btn btn-danger" style="margin-left: var(--space-2)" @click="confirm(true)">确认覆盖</button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.import-panel { display: flex; flex-direction: column; gap: var(--space-3); }
.import-actions { display: flex; align-items: center; gap: var(--space-2); }
.import-body { display: flex; flex-direction: column; gap: var(--space-3); }
.notice { padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); border: 1px solid var(--border); background: var(--surface); font-size: var(--text-sm); }
.notice .t { font-weight: 600; color: var(--fg); }
.notice-bad { border-color: color-mix(in oklab, var(--danger), white 60%); background: color-mix(in oklab, var(--danger), white 95%); }
.notice-bad .t { color: var(--danger); }
.notice-warn { border-color: color-mix(in oklab, var(--warn), white 60%); background: color-mix(in oklab, var(--warn), white 94%); }
.notice-good { border-color: color-mix(in oklab, var(--success), white 60%); background: color-mix(in oklab, var(--success), white 94%); }
.notice-good .t { color: var(--success); }
.issues { max-height: 360px; }
.code { font-family: var(--font-mono); font-size: var(--text-xs); }
.link { color: var(--fg-2); text-decoration: underline; }
</style>
