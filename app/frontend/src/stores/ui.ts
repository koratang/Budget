import { defineStore } from 'pinia'
import { ref } from 'vue'

/** 页面可覆盖面包屑末级文字（如「平台渠道填报」→「Amazon-US-01」） */
export const useUiStore = defineStore('ui', () => {
  const crumbTitle = ref<string | null>(null)
  function setCrumbTitle(title: string | null): void {
    crumbTitle.value = title
  }
  return { crumbTitle, setCrumbTitle }
})
