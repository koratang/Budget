<script setup lang="ts">
/**
 * 登录页 PAGE-F01-01（CMP-F01-01 LoginPanel）
 * - 普通浏览器：GET /api/auth/dingtalk/qr-url 取授权地址；按钉钉「扫码登录第三方网站」内嵌方式用 iframe 显示
 *   钉钉登录页二维码（不加载任何外部脚本）；钉钉页面以 postMessage 回传临时登录码后，带 loginTmpCode 打开授权地址，
 *   钉钉 302 到 /api/auth/dingtalk/callback；回调失败时后端重定向回
 *   /login?error=no_role|account_disabled|dingtalk_unavailable[&name=]；二维码加载失败显示「钉钉登录暂不可用」
 * - 钉钉内置浏览器：dingtalk-jsapi 取免登码 → POST /api/auth/dingtalk/h5，不显示二维码
 * - 开发身份切换：仅非 production 构建打包，且 /api/auth/dev-users 可用时渲染（DEC-002 / DEC-013）
 * - 登录后回到 redirect 原链接，否则工作台（DEC-F01-03）
 */
import { computed, defineAsyncComponent, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '@/api/client'
import { isInDingTalk, requestDingTalkAuthCode } from '@/api/dingtalk'
import { useUserStore } from '@/stores/user'

type View = 'normal' | 'loading' | 'norole' | 'disabled' | 'error'

// 生产构建时 __DEV_IDENTITY_SWITCH__ 为 false，动态 import 被整段剔除，产物不含开发身份切换组件与文案
const DevIdentitySwitch = __DEV_IDENTITY_SWITCH__
  ? defineAsyncComponent(() => import('@/components/DevIdentitySwitch.vue'))
  : null

const route = useRoute()
const router = useRouter()
const user = useUserStore()

const view = ref<View>('normal')
const expired = ref(route.query.expired === '1')
const deniedName = ref(typeof route.query.name === 'string' ? route.query.name : '')
const qrUrl = ref<string | null>(null)
const embedUrl = ref<string | null>(null)
const loginOrigin = ref('')
/** 每次重新加载换一个 key，强制重建 iframe */
const frameKey = ref(0)
const inDingTalk = isInDingTalk()
/** iframe 超过该时长仍未加载完成，视为二维码加载失败 */
const QR_LOAD_TIMEOUT = 15000
let loadTimer: ReturnType<typeof setTimeout> | null = null

/** 登录后去向：仅接受站内相对路径，防止开放重定向 */
const target = computed(() => {
  const r = route.query.redirect
  if (typeof r === 'string' && r.startsWith('/') && !r.startsWith('//') && !r.startsWith('/login')) return r
  return '/'
})

function applyDenied(code: string, name = ''): boolean {
  if (code === 'no_role') {
    view.value = 'norole'
    deniedName.value = name || deniedName.value
    return true
  }
  if (code === 'account_disabled') {
    view.value = 'disabled'
    return true
  }
  return false
}

function handleAuthError(e: unknown, name = ''): void {
  if (e instanceof ApiError) {
    const detailName = typeof e.details.name === 'string' ? e.details.name : name
    if (applyDenied(e.code, detailName)) return
  }
  view.value = 'error'
}

async function enterSystem(): Promise<void> {
  try {
    const me = await user.fetchMe(true)
    if (me) {
      await router.replace(target.value)
      return
    }
    view.value = 'error'
  } catch (e) {
    handleAuthError(e)
  }
}

/** 取扫码授权地址；keepView 为 true 时只在后台准备地址（拒绝提示保持显示） */
async function loadQrUrl(keepView = false): Promise<void> {
  try {
    const res = await api.get<{ url: string; embed_url: string; origin: string }>(
      '/api/auth/dingtalk/qr-url',
      { redirect: target.value },
      { redirectOn401: false },
    )
    qrUrl.value = res.url
    embedUrl.value = res.embed_url
    loginOrigin.value = res.origin
    if (!keepView) showQr()
  } catch {
    qrUrl.value = null
    embedUrl.value = null
    if (!keepView) view.value = 'error'
  }
}

function clearLoadTimer(): void {
  if (loadTimer) clearTimeout(loadTimer)
  loadTimer = null
}

/** 显示内嵌二维码：重建 iframe，并在超时未加载时转为「钉钉登录暂不可用」 */
function showQr(): void {
  view.value = 'normal'
  frameKey.value += 1
  clearLoadTimer()
  loadTimer = setTimeout(() => {
    if (view.value === 'normal') view.value = 'error'
  }, QR_LOAD_TIMEOUT)
}

/** 钉钉登录页回传临时登录码（只接受钉钉登录页的源）→ 带 loginTmpCode 打开授权地址完成授权 */
function onMessage(e: MessageEvent): void {
  if (!loginOrigin.value || e.origin !== loginOrigin.value || !qrUrl.value) return
  const tmpCode = e.data
  if (typeof tmpCode !== 'string' || !tmpCode) return
  const url = new URL(qrUrl.value)
  url.searchParams.set('loginTmpCode', tmpCode)
  view.value = 'loading'
  window.location.href = url.toString()
}

async function dingTalkLogin(): Promise<void> {
  view.value = 'loading'
  try {
    const config = await api.get<{ corp_id: string }>('/api/auth/config', undefined, { redirectOn401: false })
    const authCode = await requestDingTalkAuthCode(config.corp_id)
    await api.post('/api/auth/dingtalk/h5', { auth_code: authCode }, { redirectOn401: false })
    await enterSystem()
  } catch (e) {
    handleAuthError(e)
  }
}

async function init(): Promise<void> {
  const err = route.query.error
  if (typeof err === 'string') {
    if (!applyDenied(err)) view.value = 'error'
    if (!inDingTalk) void loadQrUrl(true)
    return
  }
  // 已有有效会话 → 直接进入
  try {
    const me = await user.fetchMe(true)
    if (me) {
      await router.replace(target.value)
      return
    }
  } catch (e) {
    if (e instanceof ApiError && applyDenied(e.code)) return
    // 后端不可用：继续走下面流程，二维码地址取不到时显示「钉钉登录暂不可用」
  }
  if (inDingTalk) await dingTalkLogin()
  else await loadQrUrl()
}

function backToScan(): void {
  expired.value = false
  if (inDingTalk) void dingTalkLogin()
  else if (embedUrl.value) showQr()
  else void loadQrUrl()
}

function reload(): void {
  expired.value = false
  void (inDingTalk ? dingTalkLogin() : loadQrUrl())
}

function onDevDenied(e: ApiError, name: string): void {
  handleAuthError(e, name)
}

onMounted(() => {
  window.addEventListener('message', onMessage)
  void init()
})
onBeforeUnmount(() => {
  window.removeEventListener('message', onMessage)
  clearLoadTimer()
})
</script>

<template>
  <main class="login" data-page-id="PAGE-F01-01">
    <div class="login-inner">
      <div class="brand">
        <h1>预算管理平台</h1>
        <p>年度全面预算 · 公司内部系统</p>
      </div>

      <div class="login-card">
        <section aria-labelledby="scan-title">
          <h2 id="scan-title" class="sec-title">{{ inDingTalk ? '钉钉免登' : '钉钉扫码登录' }}</h2>

          <div v-if="view === 'normal'" data-view="normal">
            <div v-if="expired" class="notice" role="status">登录已失效，请重新登录</div>
            <iframe
              v-if="embedUrl"
              :key="frameKey"
              class="qr-frame"
              :src="embedUrl"
              title="钉钉扫码登录二维码"
              @load="clearLoadTimer"
            ></iframe>
            <div v-else class="skeleton qr-frame" aria-hidden="true"></div>
            <p class="hint">请使用钉钉 App 扫码登录</p>
            <p class="sub">扫码后在手机上确认登录</p>
          </div>

          <div v-else-if="view === 'loading'" data-view="loading" aria-live="polite">
            <div class="skeleton" style="width: 150px; height: 150px; margin-bottom: var(--space-4)"></div>
            <p class="hint">正在验证钉钉身份…</p>
          </div>

          <div v-else-if="view === 'norole'" class="result" data-view="norole" role="alert">
            <p class="result-title bad">未开通预算权限，请联系财务负责人</p>
            <p v-if="deniedName">当前钉钉账号：{{ deniedName }}</p>
            <button type="button" class="btn" @click="backToScan">换个账号扫码</button>
          </div>

          <div v-else-if="view === 'disabled'" class="result" data-view="disabled" role="alert">
            <p class="result-title bad">无法登录：钉钉账号已停用或不在企业通讯录中</p>
            <p>如有疑问请联系人力资源部或信息数字化部。</p>
            <button type="button" class="btn" @click="backToScan">换个账号扫码</button>
          </div>

          <div v-else class="result" data-view="error" role="alert">
            <p class="result-title">钉钉登录暂不可用，请稍后重试</p>
            <p>{{ inDingTalk ? '钉钉身份验证未完成，系统没有其他登录方式。' : '二维码未能加载，系统没有其他登录方式。' }}</p>
            <button type="button" class="btn" @click="reload">
              <svg class="icon" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true">
                <path d="M13.5 8a5.5 5.5 0 1 1-1.6-3.9" />
                <path d="M13.5 2.5v3h-3" />
              </svg>
              重新加载
            </button>
          </div>
        </section>

        <section aria-labelledby="dt-title">
          <h2 id="dt-title" class="sec-title">在钉钉里使用</h2>
          <ol class="steps">
            <li>打开电脑版钉钉</li>
            <li>进入「工作台」，点击「预算管理平台」</li>
            <li>系统自动识别你的钉钉身份，无需扫码</li>
          </ol>
          <p class="sub" style="margin-top: var(--space-6)">钉钉工作通知里的系统链接，在钉钉内打开同样免登；登录后回到通知原链接。</p>
          <p class="sub" style="margin-top: var(--space-2)">登录 8 小时无操作将自动退出。</p>
        </section>
      </div>

      <component
        :is="DevIdentitySwitch"
        v-if="DevIdentitySwitch"
        @start="view = 'loading'"
        @success="enterSystem"
        @denied="onDevDenied"
      />

      <p class="foot">仅限公司内部使用</p>
    </div>
  </main>
</template>

<style scoped>
.login { min-height: 100vh; box-sizing: border-box; display: grid; place-items: center; padding: var(--space-8) var(--space-6); background: var(--bg); color: var(--fg); }
.login-inner { width: 760px; max-width: 100%; }
.brand { margin-bottom: var(--space-6); }
.brand h1 { font-family: var(--font-display); font-size: var(--text-3xl); letter-spacing: var(--tracking-display); line-height: var(--leading-tight); margin: 0 0 var(--space-1); }
.brand p { margin: 0; color: var(--muted); }
.login-card { display: grid; grid-template-columns: 1fr 1fr; background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); }
.login-card > section { padding: var(--space-8) var(--space-6); }
.login-card > section + section { border-left: 1px solid var(--border-soft); }
.sec-title { font-size: var(--text-lg); font-weight: 600; margin: 0 0 var(--space-4); }
.qr-frame { display: block; width: 280px; height: 320px; max-width: 100%; border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); margin-bottom: var(--space-4); }
.hint { color: var(--fg-2); margin: 0 0 var(--space-1); }
.sub { color: var(--muted); font-size: var(--text-sm); margin: 0; }
.steps { margin: 0; padding-left: 20px; color: var(--fg-2); }
.steps li + li { margin-top: var(--space-2); }
.notice { padding: var(--space-3) var(--space-4); border-radius: var(--radius-md); background: var(--surface-warm); border: 1px solid var(--border-soft); font-size: var(--text-sm); color: var(--fg-2); margin-bottom: var(--space-4); }
.result-title { font-size: var(--text-lg); font-weight: 600; margin: 0 0 var(--space-2); }
.result-title.bad { color: var(--danger); }
.result p { margin: 0 0 var(--space-4); color: var(--fg-2); }
.foot { text-align: center; color: var(--muted); font-size: var(--text-xs); margin-top: var(--space-6); }
.icon { width: 16px; height: 16px; flex: none; }
</style>
