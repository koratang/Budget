/// <reference types="vite/client" />

/** 构建期常量：非 production 模式为 true；生产构建为 false，开发身份切换代码被整段剔除（DEC-013） */
declare const __DEV_IDENTITY_SWITCH__: boolean

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
