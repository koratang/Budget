import { createApp } from 'vue'
import { createPinia } from 'pinia'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './styles/app.css'
import './styles/element-theme.css'
import './styles/base.css'
import App from './App.vue'
import { router } from './router'
import { setUnauthorizedHandler } from './api/client'
import { useUserStore } from './stores/user'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 任一接口 401：清空当前用户，跳登录页并带 redirect 回原链接
setUnauthorizedHandler((error) => {
  const user = useUserStore()
  const wasLoggedIn = user.loggedIn
  user.clear()
  const current = router.currentRoute.value
  if (current.name === 'login') return
  const query: Record<string, string> = { redirect: current.fullPath }
  if (error.code === 'account_disabled' || error.code === 'no_role') query.error = error.code
  else if (wasLoggedIn) query.expired = '1'
  void router.replace({ name: 'login', query })
})

app.mount('#app')
