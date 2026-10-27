import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '@/api/client'

/**
 * 全局字典缓存（渠道、店铺、品类、部门等）。
 * 按 key 缓存一次请求结果；同一 key 并发请求共享同一个 Promise；失败不缓存。
 * 用法：const channels = await dict.load('channels', '/api/master/channels')
 */
export const useDictStore = defineStore('dict', () => {
  const items = ref<Record<string, unknown>>({})
  const inflight = new Map<string, Promise<unknown>>()

  async function load<T>(key: string, url: string, force = false): Promise<T> {
    if (!force && key in items.value) return items.value[key] as T
    const running = inflight.get(key)
    if (running && !force) return running as Promise<T>
    const p = api
      .get<T>(url)
      .then((data) => {
        items.value[key] = data
        return data
      })
      .finally(() => inflight.delete(key))
    inflight.set(key, p)
    return p
  }

  function peek<T>(key: string): T | undefined {
    return items.value[key] as T | undefined
  }

  /** 主数据被修改后让对应字典失效 */
  function invalidate(key?: string): void {
    if (key) delete items.value[key]
    else items.value = {}
  }

  return { items, load, peek, invalidate }
})
