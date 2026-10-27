/** G2 页面共用：轻提示、时间显示、状态徽章、单位类型对应的填报页 */
import { ApiError, NETWORK_ERROR_MESSAGE } from '@/api/client'

/** 轻提示（app.css .toast，3 秒后消失；原型同款） */
export function toast(message: string): void {
  const t = document.createElement('div')
  t.className = 'toast'
  t.setAttribute('role', 'status')
  t.textContent = message
  document.body.appendChild(t)
  window.setTimeout(() => t.remove(), 3000)
}

/** ISO 时间 → 'YYYY-MM-DD HH:mm'（按浏览器本地时区；服务端已带时区） */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

export function nowClock(): string {
  const d = new Date()
  return [d.getHours(), d.getMinutes(), d.getSeconds()].map((x) => String(x).padStart(2, '0')).join(':')
}

export const UNIT_STATUS_BADGE: Record<string, string> = {
  not_started: 'badge',
  filling: 'badge',
  adjusting: 'badge',
  submitted: 'badge badge-info',
  dept_approved: 'badge badge-info',
  returned: 'badge badge-bad',
  approved: 'badge badge-good',
}

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : NETWORK_ERROR_MESSAGE
}

export interface TaskInfo {
  id: number
  name: string
  year: number
  deadline: string
  status: string
  status_label: string
}

export interface UnitInfo {
  id: number
  name: string
  unit_type: 'platform' | 'b2b' | 'cost_ratio' | 'logistics_ratio' | 'dept_expense'
  type_label: string
  scope_object_id: number | null
  status: string
  status_label: string
  filler: { id: number; name: string } | null
  reviewer: { id: number; name: string } | null
  return_reason: string | null
  returned_by: string | null
  returned_at: string | null
  submitted_at: string | null
  updated_at: string | null
  editable: boolean
  locked: boolean
  overdue: boolean
  version_id: number
  task: TaskInfo | null
  adjustment: { id: number; year: number; quarter: number; status: string; name: string } | null
  adjust_reason: string | null
  path?: string
}

export function fillRoute(u: Pick<UnitInfo, 'id' | 'unit_type'>): { name: string; params?: Record<string, string>; query?: Record<string, string> } {
  const id = String(u.id)
  switch (u.unit_type) {
    case 'platform':
      return { name: 'fill-platform', params: { unitId: id } }
    case 'b2b':
      return { name: 'fill-b2b', params: { unitId: id } }
    case 'cost_ratio':
      return { name: 'fill-cost', params: { unitId: id } }
    case 'logistics_ratio':
      return { name: 'fill-logistics', params: { unitId: id } }
    default:
      return { name: 'dept-expense', query: { unitId: id } }
  }
}

export function isForbidden(e: unknown): boolean {
  return e instanceof ApiError && e.isForbidden
}
