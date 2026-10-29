/**
 * 路由注册表（开发约定「前端路由」：33 个页面，菜单 key = 路由 name）
 * group / parent 用于顶栏面包屑：分组 / [上级页链接] / 本页标题
 */
export interface PageRouteDef {
  pageId: string
  path: string
  name: string
  title: string
  group?: string
  /** 上级页路由 name，面包屑中显示为链接 */
  parent?: string
  /** 设计稿 / 通知链接使用的等价路径（保持原链接不跳转） */
  alias?: string
}

export const PAGE_ROUTES: PageRouteDef[] = [
  { pageId: 'PAGE-F00-01', path: '/', name: 'workbench', title: '工作台' },
  { pageId: 'PAGE-F01-02', path: '/settings/roles', name: 'roles', title: '角色与权限', group: '系统设置' },
  { pageId: 'PAGE-F02-01', path: '/master/stores', name: 'stores', title: '渠道与店铺', group: '基础数据' },
  { pageId: 'PAGE-F02-02', path: '/master/sku', name: 'sku', title: 'SKU 对照表', group: '基础数据' },
  { pageId: 'PAGE-F02-03', path: '/master/customers', name: 'customers', title: 'B端客户与部门', group: '基础数据' },
  { pageId: 'PAGE-F02-04', path: '/master/accounts', name: 'accounts', title: '科目映射', group: '基础数据' },
  { pageId: 'PAGE-F02-05', path: '/master/fx', name: 'fx', title: '汇率', group: '基础数据' },
  { pageId: 'PAGE-F03-01', path: '/tasks', name: 'tasks', title: '编制任务', group: '预算编制' },
  { pageId: 'PAGE-F03-02', path: '/tasks/:id', name: 'task-detail', title: '编制任务详情', group: '预算编制', parent: 'tasks' },
  { pageId: 'PAGE-F04-01', path: '/filling', name: 'my-filling', title: '我的填报', group: '预算编制' },
  { pageId: 'PAGE-F04-02', path: '/filling/platform/:unitId', name: 'fill-platform', title: '平台渠道填报', group: '预算编制', parent: 'my-filling' },
  { pageId: 'PAGE-F04-03', path: '/filling/b2b/:unitId', name: 'fill-b2b', title: 'B端填报', group: '预算编制', parent: 'my-filling' },
  { pageId: 'PAGE-F04-04', path: '/filling/cost/:unitId', name: 'fill-cost', title: '成本比例填报', group: '预算编制', parent: 'my-filling' },
  { pageId: 'PAGE-F04-05', path: '/filling/logistics/:unitId', name: 'fill-logistics', title: '物流比例填报', group: '预算编制', parent: 'my-filling' },
  { pageId: 'PAGE-F05-01', path: '/dept-expense', name: 'dept-expense', title: '部门费用', group: '预算编制' },
  { pageId: 'PAGE-F05-02', path: '/dept-expense/reserves', name: 'reserves', title: '专项预留额度', group: '预算编制', parent: 'dept-expense' },
  { pageId: 'PAGE-F07-01', path: '/approvals', name: 'approvals', title: '待我审批', group: '预算编制' },
  { pageId: 'PAGE-F07-02', path: '/approvals/:type/:id', name: 'approval-detail', title: '审批详情', group: '预算编制', parent: 'approvals' },
  { pageId: 'PAGE-F08-01', path: '/versions', name: 'versions', title: '预算版本', group: '预算编制' },
  { pageId: 'PAGE-F08-02', path: '/versions/compare', name: 'version-compare', title: '版本对比', group: '预算编制', parent: 'versions' },
  { pageId: 'PAGE-F09-01', path: '/actuals/import', name: 'import', title: '实际数导入', group: '实际数' },
  { pageId: 'PAGE-F09-02', path: '/actuals/reconcile', name: 'reconcile', title: 'BI 与金蝶核对', group: '实际数' },
  { pageId: 'PAGE-F10-01', path: '/reports/company', name: 'report-company', title: '公司汇总', group: '预算执行' },
  { pageId: 'PAGE-F10-02', path: '/reports/channel', alias: '/reports/channel-site', name: 'report-channel', title: '渠道×站点偏差', group: '预算执行' },
  { pageId: 'PAGE-F10-03', path: '/reports/category', name: 'report-category', title: '品类×新老品偏差', group: '预算执行' },
  { pageId: 'PAGE-F15-02', path: '/bizfin/finance', name: 'bizfin-finance', title: '财务指标', group: '业财分析' },
  { pageId: 'PAGE-F15-03', path: '/bizfin/business', name: 'bizfin-business', title: '业务指标', group: '业财分析' },
  { pageId: 'PAGE-F15-05', path: '/bizfin/analysis/:sub?', name: 'bizfin-analysis', title: '数据分析', group: '业财分析' },
  { pageId: 'PAGE-F15-06', path: '/bizfin/policy', name: 'bizfin-policy', title: '政策环境', group: '业财分析' },
  { pageId: 'PAGE-F11-01', path: '/alerts', name: 'alerts', title: '预算预警', group: '预算执行' },
  { pageId: 'PAGE-F12-01', path: '/rules', name: 'rules', title: '规则库', group: '预算执行', parent: 'alerts' },
  { pageId: 'PAGE-F12-02', path: '/rules/:id', name: 'rule-detail', title: '规则详情', group: '预算执行', parent: 'rules' },
]

export const LOGIN_ROUTE = { pageId: 'PAGE-F01-01', path: '/login', name: 'login', title: '登录' } as const

/** 侧栏：分组与顺序照 PAGE-F00-01 原型；条目 key = 路由 name = /api/me 的 menus */
export interface NavGroup {
  label: string | null
  items: { name: string; label: string }[]
}

export const NAV_GROUPS: NavGroup[] = [
  { label: null, items: [{ name: 'workbench', label: '工作台' }] },
  {
    label: '预算编制',
    items: [
      { name: 'tasks', label: '编制任务' },
      { name: 'my-filling', label: '我的填报' },
      { name: 'dept-expense', label: '部门费用' },
      { name: 'approvals', label: '待我审批' },
      { name: 'versions', label: '预算版本' },
    ],
  },
  {
    label: '实际数',
    items: [
      { name: 'import', label: '实际数导入' },
      { name: 'reconcile', label: 'BI 与金蝶核对' },
    ],
  },
  {
    label: '预算执行',
    items: [
      { name: 'report-company', label: '公司汇总' },
      { name: 'report-channel', label: '渠道×站点偏差' },
      { name: 'report-category', label: '品类×新老品偏差' },
      { name: 'alerts', label: '预算预警' },
    ],
  },
  {
    label: '业财分析',
    items: [
      { name: 'bizfin-finance', label: '财务指标' },
      { name: 'bizfin-business', label: '业务指标' },
      { name: 'bizfin-analysis', label: '数据分析' },
      { name: 'bizfin-policy', label: '政策环境' },
    ],
  },
  {
    label: '基础数据',
    items: [
      { name: 'stores', label: '渠道与店铺' },
      { name: 'sku', label: 'SKU 对照表' },
      { name: 'customers', label: 'B端客户与部门' },
      { name: 'accounts', label: '科目映射' },
      { name: 'fx', label: '汇率' },
    ],
  },
  { label: '系统设置', items: [{ name: 'roles', label: '角色与权限' }] },
]

/** 子页面高亮其最上级菜单（如 /tasks/12 高亮「编制任务」，/rules/3 → 规则库 → 高亮「预算预警」） */
export function navKeyFor(routeName: string): string {
  let def = PAGE_ROUTES.find((r) => r.name === routeName)
  while (def?.parent) {
    const up = PAGE_ROUTES.find((r) => r.name === def?.parent)
    if (!up) break
    def = up
  }
  return def?.name ?? routeName
}
