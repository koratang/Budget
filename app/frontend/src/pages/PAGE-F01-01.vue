<script setup lang="ts">
/**
 * 登录页 PAGE-F01-01（CMP-F01-01 LoginPanel）
 * - 普通浏览器：GET /api/auth/dingtalk/qr-url 取钉钉扫码授权地址并跳转；回调失败时后端重定向回
 *   /login?error=no_role|account_disabled|dingtalk_unavailable[&name=]
 * - 钉钉内置浏览器：dingtalk-jsapi 取免登码 → POST /api/auth/dingtalk/h5，不显示二维码
 * - 开发身份切换：仅非 production 构建打包，且 /api/auth/dev-users 可用时渲染（DEC-002 / DEC-013）
 * - 登录后回到 redirect 原链接，否则工作台（DEC-F01-03）
 */
import { computed, defineAsyncComponent, onMounted, ref } from 'vue'
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
const inDingTalk = isInDingTalk()

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
    const res = await api.get<{ url: string }>('/api/auth/dingtalk/qr-url', { redirect: target.value }, { redirectOn401: false })
    qrUrl.value = res.url
    if (!keepView) view.value = 'normal'
  } catch {
    qrUrl.value = null
    if (!keepView) view.value = 'error'
  }
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

function openQr(): void {
  if (qrUrl.value) window.location.href = qrUrl.value
}

function backToScan(): void {
  expired.value = false
  if (inDingTalk) void dingTalkLogin()
  else if (qrUrl.value) view.value = 'normal'
  else void loadQrUrl()
}

function reload(): void {
  expired.value = false
  void (inDingTalk ? dingTalkLogin() : loadQrUrl())
}

function onDevDenied(e: ApiError, name: string): void {
  handleAuthError(e, name)
}

onMounted(init)
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
            <button
              type="button"
              class="qr"
              :disabled="!qrUrl"
              aria-label="打开钉钉扫码登录页"
              title="打开钉钉扫码登录页"
              @click="openQr"
            >
              <svg viewBox="0 0 48 48" width="72" height="72" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2.5">
                <rect x="5" y="5" width="14" height="14" rx="1" />
                <rect x="29" y="5" width="14" height="14" rx="1" />
                <rect x="5" y="29" width="14" height="14" rx="1" />
                <rect x="10" y="10" width="4" height="4" fill="currentColor" stroke="none" />
                <rect x="34" y="10" width="4" height="4" fill="currentColor" stroke="none" />
                <rect x="10" y="34" width="4" height="4" fill="currentColor" stroke="none" />
                <path d="M29 29h5v5h-5zM38 29h5M29 38h5M38 38h5v5h-5z" />
              </svg>
              <span class="qr-cta">点击打开钉钉扫码</span>
            </button>
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
.qr { width: 176px; height: 176px; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: var(--space-2); padding: var(--space-3); border: 1px solid var(--border); border-radius: var(--radius-md); background: var(--surface); color: var(--fg); margin-bottom: var(--space-4); cursor: pointer; font: inherit; transition: background var(--motion-fast) var(--ease-standard), border-color var(--motion-fast) var(--ease-standard); }
.qr:hover { background: var(--surface-raised); border-color: var(--muted); }
.qr:active { background: var(--border-soft); }
.qr:focus-visible { outline: none; box-shadow: var(--focus-ring); }
.qr[disabled] { cursor: progress; color: var(--muted); }
.qr-cta { font-size: var(--text-sm); color: var(--fg-2); letter-spacing: 0.02em; }
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
