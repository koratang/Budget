<script setup lang="ts">
/**
 * 导出按钮 ExportButton（CMP-F14-01）：以当前页面的视图与筛选条件调用 GET /api/export?view=&filters=，
 * 下载服务端生成的 .xlsx（范围过滤在服务端，AC-F14-01）。
 */
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { ApiError, download, NETWORK_ERROR_MESSAGE } from '@/api/client'

const props = withDefaults(
  defineProps<{
    /** 页面视图标识，如 report-channel */
    view: string
    /** 当前筛选条件，序列化为 JSON 放在 filters 参数 */
    filters?: Record<string, unknown>
    label?: string
    disabled?: boolean
    /** 服务端未给文件名时的兜底文件名 */
    filename?: string
  }>(),
  { filters: () => ({}), label: '导出 Excel', disabled: false, filename: '' },
)

const emit = defineEmits<{ exported: [filename: string]; failed: [error: unknown] }>()
const busy = ref(false)

async function run(): Promise<void> {
  if (busy.value || props.disabled) return
  busy.value = true
  try {
    const name = await download(
      '/api/export',
      { view: props.view, filters: JSON.stringify(props.filters) },
      props.filename || `${props.view}.xlsx`,
    )
    ElMessage({ message: `已导出 ${name}`, duration: 3000 })
    emit('exported', name)
  } catch (e) {
    ElMessage({ type: 'error', message: e instanceof ApiError ? e.message : NETWORK_ERROR_MESSAGE, duration: 3000 })
    emit('failed', e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <button type="button" class="btn" :disabled="disabled || busy" :aria-busy="busy" data-cmp="CMP-F14-01" @click="run">
    {{ busy ? '正在导出…' : label }}
  </button>
</template>
