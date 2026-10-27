// E4 浏览器验收共用：后端 8014（tests.acceptance.e4_server，库 budget_acc4，托管 E4_STATIC_DIR 下的 build:dev 产物）、
// 钉钉替身 8024。服务由执行者事先启动；本文件只提供登录与断言工具。
import { createRequire } from 'node:module'

// playwright 为本机全局安装（NODE_PATH），ESM import 不读 NODE_PATH，用 require 解析
export const { chromium } = createRequire(import.meta.url)('/opt/node-tools/node_modules/playwright')
export const BASE = process.env.E4_BASE || 'http://127.0.0.1:8014'

export async function devUsers(request) {
  const r = await request.get(`${BASE}/api/auth/dev-users`)
  return r.json()
}

export async function loginAs(page, userid) {
  const users = await devUsers(page.request)
  const u = users.find((x) => x.dingtalk_userid === userid || x.label?.includes(userid) || x.name === userid)
  if (!u) throw new Error(`找不到开发身份 ${userid}`)
  const r = await page.request.post(`${BASE}/api/dev/login-as`, { data: { user_id: u.id } })
  if (r.status() !== 200) throw new Error(`登录失败 ${userid}: ${r.status()}`)
  return u
}

export function check(results, label, ok, detail = '') {
  results.push({ label, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${label}${detail ? ' — ' + detail : ''}`)
}

export function finish(results) {
  const failed = results.filter((r) => !r.ok).length
  console.log(`passed=${results.length - failed}; failed=${failed}`)
  process.exit(failed ? 1 : 0)
}
