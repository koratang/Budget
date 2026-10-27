import { onBeforeUnmount, ref } from 'vue'

/** 轻提示：3 秒后消失（各页模板中用 <div v-if="toast" class="toast" role="status">） */
export function useToast() {
  const toast = ref('')
  let timer: ReturnType<typeof setTimeout> | null = null
  function show(message: string): void {
    toast.value = message
    if (timer) clearTimeout(timer)
    timer = setTimeout(() => (toast.value = ''), 3000)
  }
  onBeforeUnmount(() => {
    if (timer) clearTimeout(timer)
  })
  return { toast, show }
}

/** 取 ApiError 的字段级提示：details.field / details.fields */
export function fieldOf(details: Record<string, unknown>): string | null {
  if (typeof details.field === 'string') return details.field
  const fields = details.fields
  if (fields && typeof fields === 'object') return Object.keys(fields)[0] ?? null
  return null
}

/** 'YYYY-MM' 加 n 个月 */
export function addMonths(ym: string, n: number): string {
  const y = Number(ym.slice(0, 4))
  const m = Number(ym.slice(5, 7)) - 1 + n
  const yy = y + Math.floor(m / 12)
  const mm = (((m % 12) + 12) % 12) + 1
  return `${yy}-${String(mm).padStart(2, '0')}`
}

/** ISO 时间 → 'YYYY-MM-DD HH:mm'（本地显示） */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}
