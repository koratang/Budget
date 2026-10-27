/**
 * 接口客户端（fetch 封装）
 * - 同源携带 Cookie（budget_session）
 * - 错误统一为 ApiError：{ status, code, message, details }（开发约定「接口约定 · 错误」）
 * - 401：交给 setUnauthorizedHandler 注册的处理器跳 /login?redirect=原链接
 * - 403：抛出 code=forbidden、message「无权限」的 ApiError，由页面用 PageState 显示无权限态
 */

export interface ApiErrorBody {
  code?: string
  message?: string
  details?: Record<string, unknown>
}

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details: Record<string, unknown>

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }

  get isUnauthenticated(): boolean {
    return this.status === 401
  }

  get isForbidden(): boolean {
    return this.status === 403
  }
}

export const NETWORK_ERROR_MESSAGE = '网络异常或服务暂时不可用，请重试。'
export const FORBIDDEN_MESSAGE = '无权限'

type UnauthorizedHandler = (error: ApiError) => void
let unauthorizedHandler: UnauthorizedHandler | null = null

/** main.ts 注册：401 时跳转登录页并带上 redirect */
export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler
}

export type Query = Record<string, string | number | boolean | null | undefined>

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  query?: Query
  /** JSON 请求体；FormData 原样发送（上传） */
  body?: unknown
  /** 为 false 时 401 不触发全局跳转（登录页、路由守卫自行处理） */
  redirectOn401?: boolean
  signal?: AbortSignal
}

export function buildUrl(path: string, query?: Query): string {
  if (!query) return path
  const params = new URLSearchParams()
  for (const [k, v] of Object.entries(query)) {
    if (v === undefined || v === null || v === '') continue
    params.append(k, String(v))
  }
  const qs = params.toString()
  if (!qs) return path
  return path + (path.includes('?') ? '&' : '?') + qs
}

async function toApiError(res: Response): Promise<ApiError> {
  let body: ApiErrorBody = {}
  const type = res.headers.get('content-type') ?? ''
  if (type.includes('application/json')) {
    try {
      body = (await res.json()) as ApiErrorBody
    } catch {
      body = {}
    }
  }
  if (res.status === 403) {
    return new ApiError(403, body.code ?? 'forbidden', body.message ?? FORBIDDEN_MESSAGE, body.details ?? {})
  }
  if (res.status === 401) {
    return new ApiError(401, body.code ?? 'unauthenticated', body.message ?? '登录已失效，请重新登录', body.details ?? {})
  }
  if (res.status >= 500 || !body.message) {
    return new ApiError(res.status, body.code ?? 'server_error', body.message ?? NETWORK_ERROR_MESSAGE, body.details ?? {})
  }
  return new ApiError(res.status, body.code ?? 'error', body.message, body.details ?? {})
}

async function send(path: string, options: RequestOptions, accept: string): Promise<Response> {
  const { method = 'GET', query, body, signal } = options
  const headers: Record<string, string> = { Accept: accept }
  let payload: BodyInit | undefined
  if (body instanceof FormData) {
    payload = body
  } else if (body !== undefined) {
    headers['Content-Type'] = 'application/json'
    payload = JSON.stringify(body)
  }
  let res: Response
  try {
    res = await fetch(buildUrl(path, query), { method, headers, body: payload, credentials: 'same-origin', signal })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    throw new ApiError(0, 'network_error', NETWORK_ERROR_MESSAGE)
  }
  if (!res.ok) {
    const error = await toApiError(res)
    if (error.isUnauthenticated && options.redirectOn401 !== false && unauthorizedHandler) {
      unauthorizedHandler(error)
    }
    throw error
  }
  return res
}

/** JSON 请求；204 返回 undefined */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const res = await send(path, options, 'application/json')
  if (res.status === 204) return undefined as T
  const type = res.headers.get('content-type') ?? ''
  if (!type.includes('application/json')) {
    // 后端未就绪时开发服务器可能回落到 index.html，按服务不可用处理
    throw new ApiError(res.status, 'invalid_response', NETWORK_ERROR_MESSAGE)
  }
  return (await res.json()) as T
}

export const api = {
  get: <T>(path: string, query?: Query, options: Omit<RequestOptions, 'method' | 'query'> = {}) =>
    request<T>(path, { ...options, method: 'GET', query }),
  post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'PUT', body }),
  patch: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'method' | 'body'> = {}) =>
    request<T>(path, { ...options, method: 'PATCH', body }),
  delete: <T>(path: string, options: Omit<RequestOptions, 'method'> = {}) =>
    request<T>(path, { ...options, method: 'DELETE' }),
}

/** 从 Content-Disposition 取文件名（支持 RFC 5987 filename*=UTF-8''） */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header)
  if (star) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))
    } catch {
      return fallback
    }
  }
  const plain = /filename\s*=\s*"?([^";]+)"?/.exec(header)
  return plain ? plain[1].trim() : fallback
}

/** 下载服务端生成的文件（导出 .xlsx、模板） */
export async function download(path: string, query: Query | undefined, fallbackName: string): Promise<string> {
  const res = await send(buildUrl(path, query), {}, '*/*')
  const blob = await res.blob()
  const name = filenameFromDisposition(res.headers.get('content-disposition'), fallbackName)
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  // 立即 revoke 会让部分浏览器丢失 download 文件名（落成 "download"），延后释放
  setTimeout(() => {
    a.remove()
    URL.revokeObjectURL(url)
  }, 1000)
  return name
}

/** 带上传进度的 multipart 上传（fetch 无上传进度，改用 XHR）；错误语义与 request 一致 */
export function upload<T>(path: string, form: FormData, onProgress?: (percent: number) => void): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', path)
    xhr.withCredentials = true
    xhr.setRequestHeader('Accept', 'application/json')
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onerror = () => reject(new ApiError(0, 'network_error', NETWORK_ERROR_MESSAGE))
    xhr.onload = () => {
      const headers = new Headers()
      const type = xhr.getResponseHeader('content-type')
      if (type) headers.set('content-type', type)
      const res = new Response(xhr.status === 204 ? null : xhr.responseText, { status: xhr.status, headers })
      if (xhr.status >= 200 && xhr.status < 300) {
        if (!type?.includes('application/json')) {
          reject(new ApiError(xhr.status, 'invalid_response', NETWORK_ERROR_MESSAGE))
          return
        }
        res.json().then((data) => resolve(data as T), () => reject(new ApiError(xhr.status, 'invalid_response', NETWORK_ERROR_MESSAGE)))
        return
      }
      void toApiError(res).then((error) => {
        if (error.isUnauthenticated && unauthorizedHandler) unauthorizedHandler(error)
        reject(error)
      })
    }
    xhr.send(form)
  })
}
