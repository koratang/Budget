/** 与后端约定的共用类型（开发约定「接口约定」） */

export type RoleCode =
  | 'ceo'
  | 'finance_head'
  | 'finance_bp'
  | 'operations'
  | 'b2b'
  | 'logistics'
  | 'dept_head'
  | 'dept_budget'

export const ROLE_NAMES: Record<RoleCode, string> = {
  ceo: 'CEO',
  finance_head: '财务负责人',
  finance_bp: '财务BP',
  operations: '运营',
  b2b: 'B端业务',
  logistics: '物流物控',
  dept_head: '部门负责人',
  dept_budget: '部门预算专员',
}

export function roleName(code: string): string {
  return (ROLE_NAMES as Record<string, string>)[code] ?? code
}

export interface MeUser {
  id: number
  name: string
  dingtalk_userid?: string
}

export interface MeScopes {
  departments: unknown[]
  channels: unknown[]
  stores: unknown[]
  customers: unknown[]
}

/** GET /api/me */
export interface Me {
  user: MeUser
  roles: RoleCode[]
  scopes: MeScopes
  all_company: boolean
  /** 可见菜单 key（= 路由 name） */
  menus: string[]
  dev_switch: boolean
}

/** GET /api/auth/dev-users 的一项（仅开发配置注册） */
export interface DevUser {
  id: number
  name: string
  roles?: string[]
  /** 可选：后端给出的完整显示名，如「王浩 · 运营（Amazon）」 */
  label?: string
}
