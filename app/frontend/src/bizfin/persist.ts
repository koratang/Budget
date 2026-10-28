/**
 * 业财分析数据存取（CMP-F15-02）：首次进入从 /api/bizfin/sections 读取各部分，未保存过的部分用示例数据；
 * 页面改数后调 commit(部分) —— 500ms 内的连续修改合并为一次保存，基于 revision 乐观锁，冲突时提示刷新。
 */
import { reactive } from 'vue'
import { api, ApiError } from '@/api/client'
import { hydrate, snapshot, type SectionKey } from './engine'

export interface SectionMeta {
  revision: number | null
  is_demo: boolean
  updated_by: string | null
  updated_at: string | null
}
interface SectionDoc extends SectionMeta {
  data: unknown
}
interface SectionsResp {
  sections: Partial<Record<SectionKey, SectionDoc>>
  can_edit: boolean
  can_reset: boolean
}

export const SECTION_KEYS: SectionKey[] = ['indicators', 'biz_dim', 'policy', 'keywork']
export const SECTION_LABELS: Record<SectionKey, string> = {
  indicators: '财务与业务指标', biz_dim: '业务指标维度填报', policy: '政策环境事件', keywork: '重点工作',
}

const LEDGERS = new Set<SectionKey>(['policy', 'keywork'])

const blankMeta = (): SectionMeta => ({ revision: null, is_demo: true, updated_by: null, updated_at: null })

export const store = reactive({
  loaded: false,
  loading: false,
  error: null as unknown,
  canEdit: false,
  canReset: false,
  saving: 0,
  /** 最近一次保存失败的提示（冲突 / 网络），页面头部显示 */
  saveError: '',
  meta: Object.fromEntries(SECTION_KEYS.map((k) => [k, blankMeta()])) as Record<SectionKey, SectionMeta>,
})

let inflight: Promise<void> | null = null

/** 读取全部部分并装入引擎；force 为 true 时丢弃本地状态重新读取 */
export function load(force = false): Promise<void> {
  if (store.loaded && !force) return Promise.resolve()
  if (inflight) return inflight
  store.loading = true
  store.error = null
  inflight = api
    .get<SectionsResp>('/api/bizfin/sections')
    .then((r) => {
      const data: Partial<Record<SectionKey, unknown>> = {}
      for (const k of SECTION_KEYS) {
        const doc = r.sections[k]
        if (doc) data[k] = doc.data
        store.meta[k] = doc
          ? { revision: doc.revision, is_demo: doc.is_demo, updated_by: doc.updated_by, updated_at: doc.updated_at }
          : blankMeta()
      }
      hydrate(data)
      store.canEdit = r.can_edit
      store.canReset = r.can_reset
      store.saveError = ''
      store.loaded = true
    })
    .catch((e: unknown) => {
      store.error = e
    })
    .finally(() => {
      store.loading = false
      inflight = null
    })
  return inflight
}

const timers = new Map<SectionKey, ReturnType<typeof setTimeout>>()
const pendingOfficial = new Set<SectionKey>()

async function put(key: SectionKey): Promise<void> {
  const meta = store.meta[key]
  // 台账类（政策、重点工作）没有导入入口：用户保存过即视为正式台账
  const isDemo = pendingOfficial.has(key) || LEDGERS.has(key) ? false : meta.is_demo
  pendingOfficial.delete(key)
  store.saving++
  try {
    const r = await api.put<SectionDoc>(`/api/bizfin/sections/${key}`, {
      data: snapshot()[key], revision: meta.revision, is_demo: isDemo,
    })
    store.meta[key] = { revision: r.revision, is_demo: r.is_demo, updated_by: r.updated_by, updated_at: r.updated_at }
    store.saveError = ''
  } catch (e) {
    store.saveError = e instanceof ApiError && e.status === 409
      ? `${e.message}。刷新会丢弃你刚才未保存的修改。`
      : `「${SECTION_LABELS[key]}」保存失败：${e instanceof Error ? e.message : String(e)}`
  } finally {
    store.saving--
  }
}

/**
 * 引擎状态已修改，保存对应部分。markOfficial 为 true（数据管理导入正式数据）或台账类部分时去掉「示例数据」标记；
 * 指标与维度的普通编辑沿用原标记。
 */
export function commit(keys: SectionKey | SectionKey[], markOfficial = false): void {
  if (!store.canEdit) return
  for (const key of Array.isArray(keys) ? keys : [keys]) {
    if (markOfficial) pendingOfficial.add(key)
    const t = timers.get(key)
    if (t) clearTimeout(t)
    timers.set(key, setTimeout(() => {
      timers.delete(key)
      void put(key)
    }, 500))
  }
}

/** 恢复示例数据（财务负责人）：清空服务器上已保存的全部部分后重新读取 */
export async function resetDemo(): Promise<void> {
  await api.post('/api/bizfin/reset')
  await load(true)
}

export const anyDemo = (): boolean => SECTION_KEYS.some((k) => store.meta[k].is_demo)
