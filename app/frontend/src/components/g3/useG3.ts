/** G3 页面小工具：轻提示（app.css .toast）与接口错误文案 */
import { ref } from 'vue'
import { ApiError, NETWORK_ERROR_MESSAGE } from '@/api/client'

export function useToast() {
  const toast = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  function show(message: string): void {
    toast.value = message
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => (toast.value = ''), 3000)
  }
  return { toast, show }
}

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : NETWORK_ERROR_MESSAGE
}

/** 后端字段错误 details.fields → { 字段: 提示 } */
export function fieldErrors(e: unknown): Record<string, string> {
  if (e instanceof ApiError && e.details && typeof e.details.fields === 'object' && e.details.fields) {
    return e.details.fields as Record<string, string>
  }
  return {}
}
