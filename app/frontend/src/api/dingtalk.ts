/** 钉钉免登（dingtalk-jsapi 以 npm 包打包、仅在钉钉内按需加载，不从任何 CDN 加载） */

export function isInDingTalk(ua: string = navigator.userAgent): boolean {
  return /DingTalk/i.test(ua)
}

/** 在钉钉内置浏览器中取免登授权码（5 分钟有效、一次性） */
export async function requestDingTalkAuthCode(corpId: string): Promise<string> {
  const { default: dd } = await import('dingtalk-jsapi')
  const res = await dd.runtime.permission.requestAuthCode({ corpId })
  return res.code
}
