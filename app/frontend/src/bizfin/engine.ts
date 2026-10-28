/**
 * 业财一体化工作台 · 计算引擎（由单文件 HTML 工具 workbench.html 原样移植）
 *
 * 移植原则：
 * - 标识符名与参数签名与原代码保持一致，便于页面作者对照原 view* 函数逐行改写；
 * - 数值计算、舍入、容差、「未填报为 null 不当 0」等口径与原代码逐行一致，不做「改进」；
 * - 原全局可变状态（IND / CUR / BIZ_DIM / POLICY_EVENTS / ADVICE_EVENTS / KW_TASKS / TREND / dim / curM）
 *   集中在响应式对象 S 中，Vue 页面的 computed 读 S 即可随状态自动刷新；
 * - 不含登录 / 权限 / localStorage / toast / DOM 渲染逻辑；持久化由 seed / snapshot / hydrate 接口承担。
 */
import { reactive } from 'vue'

/* =========================================================================
   类型
   ========================================================================= */
export type Kind = 'fin' | 'biz'
export type DimMode = 'year' | 'month'
export type ValueField = 'target' | 'actual'

/** 指标（财务 F 前缀 / 业务 S 前缀）；以下划线开头的为运行期字段 */
export interface Indicator {
  code: string
  name: string
  level: number
  parent: string | null
  unit: string
  /** 1 = 越大越好；-1 = 越小越好 */
  dir: number
  target: number | null
  actual: number | null
  weight: number
  depts: string[]
  note: string
  /** 业务指标需分维度填报的维度键（channel / category / lane / provider） */
  dims?: string[]
  kind: Kind
  /** 月度实际序列（运行期，recompute 生成，不持久化） */
  _ma?: number[]
  /** 月度目标序列（运行期，recompute 生成，不持久化） */
  _mt?: number[]
  /** 月度维度视图副本指向的年度基准对象（运行期，不持久化） */
  _src?: Indicator
  /** 月度实际手工覆盖项：月份索引 → 值 */
  _ova?: Record<string, number>
  /** 月度目标手工覆盖项：月份索引 → 值 */
  _ovt?: Record<string, number>
  /** 首次设月度覆盖前的原始年度实际值（用于整体撤销） */
  _o0a?: number | null
  /** 首次设月度覆盖前的原始年度目标值（用于整体撤销） */
  _o0t?: number | null
  /** 整体值由维度填报值聚合派生 */
  _dimAgg?: boolean
  /** F2.x 分渠道 / 分市场毛利被手工编辑过，recompute 不再覆盖 */
  _chanEdited?: boolean
}
/** 示例数据中的指标（无 kind 与运行期字段） */
export type SeedIndicator = Omit<Indicator, 'kind' | '_ma' | '_mt' | '_src' | '_ova' | '_ovt' | '_o0a' | '_o0t' | '_dimAgg' | '_chanEdited'>

/** 业务指标维度单元格 */
export interface BizDimCell {
  target: number | null
  actual: number | null
}
/** 维度填报值：BIZ_DIM[编码（. 换成 _）][维度键][成员] = { target, actual } */
export type BizDimStore = Record<string, Record<string, Record<string, BizDimCell>>>
export interface BizDimDef {
  label: string
  members: string[]
}

export interface LinkageRule {
  biz: string
  bizName: string
  fin: string
  finName: string
  dir: '正向' | '负向'
  strength: number
  coef: string
  logic: string
  dept: string
  impact: string
}
export interface PolicyEvent {
  time: string
  seg: string
  desc: string
  impact: string
}
export interface AdviceEvent {
  time: string
  seg: string
  desc: string
  advice: string
  impact: string
}
export interface KwTask {
  time: string
  cat: string
  goal: string
  breakdown: string
  eta: string
  progress: number
  status: string
}
export interface TrendData {
  months: string[]
  revenue: number[]
  gross: number[]
  net: number[]
  acos: number[]
}
export interface ValidationItem {
  state: 'ok' | 'warn'
  title: string
  detail: string
}
export interface NavItem {
  id: string
  name: string
  icon: string
  desc?: string
  group?: string
  sub?: string
  children?: NavItem[]
}

/* =========================================================================
   JS 隐式转换辅助
   原代码中 null / undefined 会直接参与算术（null → 0、undefined → NaN）。
   这里只做类型断言，运行期值原样返回，保证与原代码结果逐位一致。
   ========================================================================= */
export function jsNum(v: number | null | undefined): number {
  return v as number
}

/* ------------------------- 基础常量 ------------------------- */
export const COMPANY = '示例公司'
export const DEPTS = ['产品作战部', '研发部', '运营部', '供应中心', '物流物控部', '视觉部', '市场部', '人力资源部', '财务部', '信息数字化部', '项目管理部', '总经办']
export const CHANNELS = ['Amazon', 'Wayfair', 'Home Depot', "Lowe's", '独立站']
export const CATEGORIES = ['框镜', '灯镜', '镜柜', '水龙头', '浴室柜', '淋浴门']
export const MARKETS: [string, number][] = [['美国', 5200], ['加拿大', 1440], ['英国', 1350], ['德国', 1150], ['法国', 700]]

/* ------------------------- 渠道 / 产品 效益分析数据 -------------------------
   9 项费用结构（万元）：收入、售后退款、产品成本、营销费用、渠道佣金、头程物流、尾程物流、其他费用、毛利额、毛利率
   渠道/产品的相对系数以经验占比为基础，再叠加确定性扰动（hashStr + jitOf）。 */
export const CHANNEL_BASE: Record<string, { share: number; comm: number; mkt: number; logiPre: number; logiPost: number; refundR: number; costR: number; otherR: number }> = {
  'Amazon': { share: 0.46, comm: 0.150, mkt: 0.075, logiPre: 0.045, logiPost: 0.075, refundR: 0.045, costR: 0.400, otherR: 0.012 },
  'Wayfair': { share: 0.18, comm: 0.220, mkt: 0.040, logiPre: 0.045, logiPost: 0.070, refundR: 0.044, costR: 0.430, otherR: 0.013 },
  'Home Depot': { share: 0.13, comm: 0.030, mkt: 0.025, logiPre: 0.045, logiPost: 0.075, refundR: 0.030, costR: 0.500, otherR: 0.012 },
  "Lowe's": { share: 0.09, comm: 0.030, mkt: 0.027, logiPre: 0.045, logiPost: 0.075, refundR: 0.034, costR: 0.480, otherR: 0.013 },
  '独立站': { share: 0.14, comm: 0.000, mkt: 0.110, logiPre: 0.045, logiPost: 0.070, refundR: 0.045, costR: 0.420, otherR: 0.022 },
}

export const PRODUCT_BASE: Record<string, { share: number; costR: number; mktR: number; logiPreR: number; logiPostR: number; refundR: number; commR: number; otherR: number }> = {
  '框镜': { share: 0.20, costR: 0.420, mktR: 0.040, logiPreR: 0.045, logiPostR: 0.075, refundR: 0.025, commR: 0.080, otherR: 0.012 },
  '灯镜': { share: 0.22, costR: 0.495, mktR: 0.065, logiPreR: 0.042, logiPostR: 0.072, refundR: 0.030, commR: 0.090, otherR: 0.013 },
  '镜柜': { share: 0.19, costR: 0.460, mktR: 0.058, logiPreR: 0.050, logiPostR: 0.085, refundR: 0.040, commR: 0.085, otherR: 0.014 },
  '水龙头': { share: 0.14, costR: 0.410, mktR: 0.050, logiPreR: 0.040, logiPostR: 0.065, refundR: 0.020, commR: 0.075, otherR: 0.011 },
  '浴室柜': { share: 0.15, costR: 0.510, mktR: 0.068, logiPreR: 0.055, logiPostR: 0.090, refundR: 0.042, commR: 0.090, otherR: 0.016 },
  '淋浴门': { share: 0.10, costR: 0.490, mktR: 0.058, logiPreR: 0.045, logiPostR: 0.080, refundR: 0.034, commR: 0.085, otherR: 0.014 },
}

/* ------------------------- 渠道 / 品类 结构权重 -------------------------
   【业财分摊引擎】财务指标 = 唯一真源；渠道 / 品类 / 物流结构只提供「分摊权重」。
     营业收入 F1；营业成本 = F1 − F2（拆为 售后退款 + 产品成本）
     营销费用池 = F1 × F4.1；渠道佣金池 = F1 × F4.2；头程 = F1 × F4.3；尾程 = F1 × F4.4；仓储 = F1 × F4.5
     其他费用池 = F1 × (F4.7 + F4.8)
   由「收入 − 营业成本 − 期间费用 = 净利润 F4」可得：贡献毛利额合计 ≡ F4，贡献毛利率合计 ≡ F5。
------------------------------------------------------------------------ */
export const REFUND_OF_COGS = 0.0586 /* 售后退款 / 营业成本（退货损失 + 报废折价） */
export const LOGI_DECOMP = { pre: 0.33547, delivery: 0.45359, warehouse: 0.21094 }
export const CHANNEL_IND: Record<string, string> = { 'Amazon': 'F1.1', 'Wayfair': 'F1.2', 'Home Depot': 'F1.3', "Lowe's": 'F1.4', '独立站': 'F1.5' }
export const CHANNEL_FALLBACK: Record<string, number> = { 'Amazon': 0.362, 'Wayfair': 0.201, 'Home Depot': 0.144, "Lowe's": 0.120, '独立站': 0.173 }
export const PRODUCT_SHARE: Record<string, number> = { '框镜': 0.20, '灯镜': 0.22, '镜柜': 0.19, '水龙头': 0.14, '浴室柜': 0.15, '淋浴门': 0.10 }

export type AllocWeights = Record<string, Record<string, number>>
export const CHANNEL_W: AllocWeights = {
  'Amazon': { cogs: 0.62, refund: 0.045, mkt: 0.075, comm: 0.150, pre: 0.0220, post: 0.0292, other: 0.012 },
  'Wayfair': { cogs: 0.68, refund: 0.044, mkt: 0.040, comm: 0.220, pre: 0.0215, post: 0.0282, other: 0.013 },
  'Home Depot': { cogs: 0.72, refund: 0.030, mkt: 0.025, comm: 0.030, pre: 0.0205, post: 0.0297, other: 0.012 },
  "Lowe's": { cogs: 0.71, refund: 0.034, mkt: 0.027, comm: 0.030, pre: 0.0205, post: 0.0297, other: 0.013 },
  '独立站': { cogs: 0.66, refund: 0.045, mkt: 0.110, comm: 0.000, pre: 0.0215, post: 0.0282, other: 0.022 },
}
export const PRODUCT_W: AllocWeights = {
  '框镜': { cogs: 0.420, refund: 0.025, mkt: 0.040, comm: 0.080, pre: 0.0205, post: 0.0285, other: 0.012 },
  '灯镜': { cogs: 0.495, refund: 0.030, mkt: 0.065, comm: 0.090, pre: 0.0215, post: 0.0290, other: 0.013 },
  '镜柜': { cogs: 0.460, refund: 0.040, mkt: 0.058, comm: 0.085, pre: 0.0230, post: 0.0305, other: 0.014 },
  '水龙头': { cogs: 0.410, refund: 0.020, mkt: 0.050, comm: 0.075, pre: 0.0195, post: 0.0270, other: 0.011 },
  '浴室柜': { cogs: 0.510, refund: 0.042, mkt: 0.068, comm: 0.090, pre: 0.0265, post: 0.0335, other: 0.016 },
  '淋浴门': { cogs: 0.490, refund: 0.034, mkt: 0.058, comm: 0.085, pre: 0.0245, post: 0.0315, other: 0.014 },
}

/* 成本结构行定义（顺序与表头一致） */
export const COST_LINES = [
  { key: 'revenue', name: '收入', type: 'income', fmt: 0 },
  { key: 'refund', name: '售后退款', type: 'cost', fmt: 0 },
  { key: 'productCost', name: '产品成本', type: 'cost', fmt: 0 },
  { key: 'market', name: '营销费用', type: 'cost', fmt: 0 },
  { key: 'comm', name: '渠道佣金', type: 'cost', fmt: 0 },
  { key: 'logiPre', name: '头程物流', type: 'cost', fmt: 0 },
  { key: 'logiPost', name: '尾程物流', type: 'cost', fmt: 0 },
  { key: 'other', name: '其他费用', type: 'cost', fmt: 0 },
  { key: 'gross', name: '毛利额', type: 'derived', fmt: 0 },
  { key: 'grossRate', name: '毛利率', type: 'rate', fmt: 1 },
]

/* ---------- 维度无关取数：m = null 取当前维度，m = 0~8 取指定月份 ---------- */
export function iv(code: string, m?: number | null): number | null {
  const i = find(code)
  if (!i) return 0
  if (m === null || m === undefined) return i.actual
  return mA(yearOf(i), m)
}
/* 业务指标取数：填报值优先，未填报时回落结构基准（保证下游分析模块不出现 NaN） */
export function ivOr(code: string, m: number | null | undefined, fb: number): number {
  const i = find(code)
  if (i && hasData(i)) {
    const v = iv(code, m)
    if (v !== null && v !== undefined && !isNaN(v) && isFinite(v)) return v
  }
  return fb
}
/* 业务指标维度单元格取值（分渠道 / 分品类 / 分线路 / 分服务商），未填报返回 null */
export function dnum(code: string, dimKey: string, member: string): number | null {
  const v = bizDimOf(code, dimKey, member).actual
  return (v === null || v === undefined || isNaN(v)) ? null : v
}
/* 加总型单位（可跨维度成员求和），其余按算术平均聚合 */
export const SUM_UNITS: Record<string, number> = { '万': 1, '万元': 1, '人民币': 1, '件': 1, '款': 1, '单': 1, '个': 1 }
export function isSumUnit(u: string | null | undefined): boolean {
  return u !== null && u !== undefined && !!SUM_UNITS[u]
}
/* 维度填报值 → 指标整体值：加总型求和、比率型算术平均；无任何填报返回 null */
export function bizDimAgg(code: string, dimKey: string, field: ValueField): number | null {
  const D = BIZ_DIMS[dimKey]
  if (!D) return null
  let sum = 0, n = 0
  D.members.forEach(function (mb) {
    const c = bizDimOf(code, dimKey, mb)
    const v = c[field]
    if (v === null || v === undefined || isNaN(v)) return
    sum += v; n++
  })
  if (!n) return null
  const i = find(code)
  return isSumUnit(i && i.unit) ? sum : sum / n
}

/* 月度指数：m = null 时按季节权重取年度平均 */
export function idxAt(arr: number[], m?: number | null): number {
  if (m === null || m === undefined) {
    let s = 0, w = 0
    for (let k = 0; k < 9; k++) { s += arr[k] * SEASON9[k]; w += SEASON9[k] }
    return w ? s / w : 1
  }
  return arr[m]
}
/* 确定性平滑月度波动（围绕 1） */
export function wave(seed: string, amp: number): (m?: number | null) => number {
  const ph = 0.7 + (hashStr(seed) % 1000) / 1000 * 5.0
  return function (m?: number | null) {
    if (m === null || m === undefined) return 1
    return 1 + amp * Math.sin(m * 0.85 + ph)
  }
}
/* 渠道收入占比：口径取自财务指标渠道二级 F1.1~F1.5，与订单分析的渠道集中度 CR1 同源 */
export function channelShare(c: string, m?: number | null): number {
  let tot = 0
  CHANNELS.forEach(function (x) { tot += jsNum(iv(CHANNEL_IND[x], m)) })
  if (tot > 0) return jsNum(iv(CHANNEL_IND[c], m)) / tot
  return CHANNEL_FALLBACK[c] || 0
}
/* 结构权重 → 费用池内分摊比例（同一池内合计 100%） */
export function wAlloc(W: AllocWeights, key: string, name: string, names: string[], shareOf: (n: string) => number): number {
  let tot = 0, self = 0
  names.forEach(function (n) {
    const v = shareOf(n) * ((W[n] && W[n][key]) || 0)
    tot += v
    if (n === name) self = v
  })
  return tot > 0 ? self / tot : 0
}

/* ---------- 费用池：金额完全由财务指标决定 ---------- */
export interface CostPools {
  rev: number; cogs: number; profit: number | null; netRate: number | null
  refund: number; productCost: number; sell: number; marketCost: number; commission: number
  logi: number; logiPre: number; logiPost: number; logiDelivery: number; warehouse: number
  other: number; otherByRate: number
}
export function costPools(m?: number | null): CostPools {
  const rev = jsNum(iv('F1', m)), gross = jsNum(iv('F2', m))
  const cogs = Math.max(0, rev - gross)
  /* 费用池全部由财务二级指标直接决定（v3 口径），不再使用拆分系数 */
  const mkt = rev * jsNum(iv('F4.1', m)) / 100 /* 营销费用率 */
  const comm = rev * jsNum(iv('F4.2', m)) / 100 /* 渠道佣金率 */
  const logiPre = rev * jsNum(iv('F4.3', m)) / 100 /* 头程成本占比 */
  const logiDelivery = rev * jsNum(iv('F4.4', m)) / 100 /* 尾程成本占比 */
  const warehouse = rev * jsNum(iv('F4.5', m)) / 100 /* 仓储成本占比 */
  const logi = logiPre + logiDelivery + warehouse
  /* 其他费用：由「毛利额 − 营销 − 佣金 − 物流 − 净利润」倒算的平衡项，
     年度口径与 F4.7 管理 + F4.8 研发完全一致（差异 < 0.1%），月度口径可保证与 F4 逐月勾稽 */
  const admin = rev - cogs - mkt - comm - logi - jsNum(iv('F4', m))
  const adminByRate = rev * (jsNum(iv('F4.7', m)) + jsNum(iv('F4.8', m))) / 100
  return {
    rev: rev, cogs: cogs, profit: iv('F4', m), netRate: iv('F5', m),
    refund: cogs * REFUND_OF_COGS,
    productCost: cogs * (1 - REFUND_OF_COGS),
    sell: mkt + comm,
    marketCost: mkt,
    commission: comm,
    logi: logi,
    logiPre: logiPre,
    logiPost: logiDelivery + warehouse,
    logiDelivery: logiDelivery,
    warehouse: warehouse,
    other: admin,
    otherByRate: adminByRate,
  }
}

/* ---------- 渠道 / 品类 九项费用结构（分摊结果） ---------- */
export interface EffRow {
  key: string; share: number; revenue: number
  refund: number; productCost: number; market: number; comm: number; logiPre: number; logiPost: number; other: number
  cost: number; gross: number; grossRate: number
}
export function effRows(kind: string, m?: number | null): EffRow[] {
  const p = costPools(m)
  const isCh = (kind === 'channel')
  const names = isCh ? CHANNELS : CATEGORIES
  const W = isCh ? CHANNEL_W : PRODUCT_W
  const shareOf = function (n: string): number { return isCh ? channelShare(n, m) : (PRODUCT_SHARE[n] || 0) }
  return names.map(function (n) {
    const sh = shareOf(n)
    const refund = p.refund * wAlloc(W, 'refund', n, names, shareOf)
    const productCost = p.productCost * wAlloc(W, 'cogs', n, names, shareOf)
    const market = p.marketCost * wAlloc(W, 'mkt', n, names, shareOf)
    const comm = p.commission * wAlloc(W, 'comm', n, names, shareOf)
    const logiPre = p.logiPre * wAlloc(W, 'pre', n, names, shareOf)
    const logiPost = p.logiPost * wAlloc(W, 'post', n, names, shareOf)
    const other = p.other * wAlloc(W, 'other', n, names, shareOf)
    const revenue = p.rev * sh
    const cost = refund + productCost + market + comm + logiPre + logiPost + other
    const gross = revenue - cost
    return {
      key: n, share: sh, revenue: revenue,
      refund: refund, productCost: productCost, market: market, comm: comm, logiPre: logiPre, logiPost: logiPost, other: other,
      cost: cost, gross: gross, grossRate: revenue > 0 ? gross / revenue : 0,
    }
  })
}
export function channelEffectAll(): EffRow[] { return effRows('channel', null) }
export function productEffectAll(): EffRow[] { return effRows('product', null) }
/* ---------- SPU 粒度数据生成（品类分析 TOP/BOTTOM 用） ---------- */
export const SPU_GROSS_BASE: Record<string, number> = { '框镜': 0.33, '灯镜': 0.24, '镜柜': 0.35, '水龙头': 0.40, '浴室柜': 0.19, '淋浴门': 0.13 }
export interface SpuRow { code: string; cat: string; grossRate: number; revenue: number; gross: number }
export function buildSpuTable(): SpuRow[] {
  const rows = productEffectAll()
  const revBy: Record<string, number> = {}
  rows.forEach(function (r) { revBy[r.key] = r.revenue })
  const spuRows: SpuRow[] = []
  CATEGORIES.forEach(function (cat) {
    const n = (CAT_SPU[cat] || 0)
    const baseRev = revBy[cat] || 0
    const baseRate = SPU_GROSS_BASE[cat] || 0.25
    for (let k = 1; k <= n; k++) {
      const seed = 'spu:' + cat + ':' + k
      const jit = jitOf(seed)
      const rate = Math.max(0.02, Math.min(0.55, baseRate + jit * 0.10))
      const w = Math.max(0.05, 1 + jitOf(seed + ':w') * 0.6)
      const rev = (baseRev / n) * w
      spuRows.push({
        code: 'SPU-' + cat.substring(0, 1) + '-' + String(k).padStart(3, '0'),
        cat: cat,
        grossRate: rate,
        revenue: rev,
        gross: rev * rate,
      })
    }
  })
  spuRows.sort(function (a, b) { return b.grossRate - a.grossRate })
  return spuRows
}
export function channelRowsAt(m?: number | null): EffRow[] { return effRows('channel', m) }
export function productRowsAt(m?: number | null): EffRow[] { return effRows('product', m) }

/* ---------- 订单模型：订单量 = 渠道收入 × 10000 ÷ 渠道客单价
   客单价优先取营销板块 S1.3「客单价」分渠道填报值，未填报回落渠道结构基准；
   因此「各渠道订单量合计 = 总订单量」「收入 ÷ 订单量 = 客单价」两条恒等式始终成立 ---------- */
export const CH_AOV: Record<string, number> = { 'Amazon': 1065, 'Wayfair': 2010, 'Home Depot': 2470, "Lowe's": 2330, '独立站': 1340 }
export interface OrderModel {
  total: number; revenue: number
  revenueByChannel: Record<string, number>; orders: Record<string, number>; aov: Record<string, number>
  blendedAov: number; indOrders: null; indAov: null
}
export function orderModel(m?: number | null): OrderModel {
  const revTot = jsNum(iv('F1', m))
  const rev: Record<string, number> = {}, orders: Record<string, number> = {}, aov: Record<string, number> = {}
  let revSum = 0, ordSum = 0
  CHANNELS.forEach(function (c) {
    rev[c] = revTot * channelShare(c, m)
    const d = dnum('S1.3', 'channel', c)
    aov[c] = (d !== null && d > 0) ? d : CH_AOV[c]
    orders[c] = aov[c] > 0 ? rev[c] * 10000 / aov[c] : 0
    revSum += rev[c]
    ordSum += orders[c]
  })
  return {
    total: ordSum, revenue: revSum, revenueByChannel: rev, orders: orders, aov: aov,
    blendedAov: ordSum > 0 ? revSum * 10000 / ordSum : 0,
    indOrders: null, indAov: null,
  }
}

/* ---------- 流量 / 用户 结构基准 ---------- */
export const CH_CVR: Record<string, number> = { 'Amazon': 0.0415, 'Wayfair': 0.0235, 'Home Depot': 0.0305, "Lowe's": 0.0292, '独立站': 0.0308 }
export const CH_ORGANIC: Record<string, number> = { 'Amazon': 0.58, 'Wayfair': 0.52, 'Home Depot': 0.74, "Lowe's": 0.72, '独立站': 0.26 }
export const CH_NEW: Record<string, number> = { 'Amazon': 0.62, 'Wayfair': 0.55, 'Home Depot': 0.40, "Lowe's": 0.38, '独立站': 0.68 }
export const ORG_IDX = [0.98, 0.99, 1.00, 1.00, 1.01, 1.01, 1.00, 0.99, 1.02]
export const NEW_IDX = [0.95, 0.97, 0.99, 1.00, 1.02, 1.03, 1.04, 1.05, 1.05]

export interface ChannelModelRow {
  channel: string; revenue: number; orders: number; aov: number
  uv: number; cvr: number; organic: number; paidUv: number; cpc: number
  mkt: number; mktRate: number; newShare: number; oldShare: number
  newOrders: number; oldOrders: number; newRevenue: number; oldRevenue: number
  aovNew: number; aovOld: number
}
export interface ChannelModel {
  rows: ChannelModelRow[]; pools: CostPools; om: OrderModel
  uv: number; paidUv: number; orders: number; mkt: number; revenue: number; newRevenue: number
  cvr: number; cpc: number; organic: number; newShare: number
}
/* 渠道经营模型：流量（UV / CVR / 非付费占比 / CPC）+ 用户（新客 / 老客） */
export function channelModel(m?: number | null): ChannelModel {
  const om = orderModel(m)
  const p = costPools(m)
  const orgIdx = idxAt(ORG_IDX, m), newIdx = idxAt(NEW_IDX, m)
  const cvrPools: Record<string, number> = {}, rows: ChannelModelRow[] = []
  let rawSum = 0
  CHANNELS.forEach(function (c) {
    /* 分渠道转化率优先取营销板块 S1.2 填报值，未填报回落渠道结构基准 */
    const dcvr = dnum('S1.2', 'channel', c)
    const base = CH_CVR[c] > 0 ? om.orders[c] / CH_CVR[c] : 0
    cvrPools[c] = (dcvr !== null && dcvr > 0) ? om.orders[c] / (dcvr / 100) : base
    rawSum += cvrPools[c]
  })
  /* 综合转化率 = 订单量 ÷ UV */
  const cvrBase = rawSum > 0 ? om.total / rawSum * 100 : 3.1
  const cvr = ivOr('S1.2', m, cvrBase)
  const uvTotal = cvr > 0 ? om.total / (cvr / 100) : 0
  const scale = rawSum > 0 ? uvTotal / rawSum : 0
  let tUv = 0, tPaid = 0, tOrders = 0, tNew = 0, tMkt = 0, tRev = 0, tNewRev = 0
  CHANNELS.forEach(function (c) {
    const shareOf = function (n: string): number { return channelShare(n, m) }
    const v = cvrPools[c] * scale
    /* 非付费流量占比优先取 S1.8 分渠道填报值 */
    const dorg = dnum('S1.8', 'channel', c)
    const organic = (dorg !== null) ? Math.min(0.99, Math.max(0, dorg / 100)) : Math.min(0.92, CH_ORGANIC[c] * orgIdx)
    const paid = v * (1 - organic)
    const mkt = p.marketCost * wAlloc(CHANNEL_W, 'mkt', c, CHANNELS, shareOf)
    /* 新客占比：复购率 S1.7 分渠道填报值优先（新客占比 ≈ 1 − 复购率） */
    const drep = dnum('S1.7', 'channel', c)
    const newSh = (drep !== null) ? Math.max(0.05, Math.min(0.90, 1 - drep / 100)) : Math.min(0.85, CH_NEW[c] * newIdx)
    const orders = om.orders[c], rev = om.revenueByChannel[c]
    const nOrd = orders * newSh, oOrd = orders - nOrd
    const aovNew = (nOrd + oOrd * 1.12) > 0 ? rev * 10000 / (nOrd + oOrd * 1.12) : 0
    tUv += v; tPaid += paid; tOrders += orders; tNew += nOrd; tMkt += mkt; tRev += rev; tNewRev += rev * newSh
    rows.push({
      channel: c, revenue: rev, orders: orders, aov: om.aov[c],
      uv: v, cvr: v > 0 ? orders / v * 100 : 0,
      organic: organic * 100, paidUv: paid,
      cpc: paid > 0 ? mkt * 10000 / paid : 0,
      mkt: mkt, mktRate: rev > 0 ? mkt / rev * 100 : 0,
      newShare: newSh * 100, oldShare: (1 - newSh) * 100,
      newOrders: nOrd, oldOrders: oOrd,
      newRevenue: rev * newSh, oldRevenue: rev * (1 - newSh),
      aovNew: aovNew, aovOld: aovNew * 1.12,
    })
  })
  return {
    rows: rows, pools: p, om: om,
    uv: tUv, paidUv: tPaid, orders: tOrders, mkt: tMkt, revenue: tRev, newRevenue: tNewRev,
    cvr: tUv > 0 ? tOrders / tUv * 100 : 0,
    cpc: tPaid > 0 ? tMkt * 10000 / tPaid : 0,
    organic: tUv > 0 ? (tUv - tPaid) / tUv * 100 : 0,
    newShare: tOrders > 0 ? tNew / tOrders * 100 : 0,
  }
}

/* ---------- 头程 / 仓储 结构基准 ---------- */
export interface Provider { name: string; cost: number; share: number }
export const FREIGHT_IDX = [0.96, 0.94, 0.97, 0.99, 1.02, 1.03, 1.05, 1.08, 1.10] /* 头程运价指数 */
export const WARE_IDX = [0.99, 0.99, 0.99, 1.00, 1.00, 1.00, 1.01, 1.01, 1.02] /* 仓储单价指数 */
export const LOGI_PROVIDERS: Provider[] = [
  { name: '美森快船（海运快线）', cost: 31.5, share: 0.34 },
  { name: '中远海运（普船）', cost: 17.8, share: 0.27 },
  { name: '燕文物流', cost: 22.4, share: 0.13 },
  { name: '递四方', cost: 24.6, share: 0.15 },
  { name: '万邑通（头程集运）', cost: 26.8, share: 0.11 },
]
export const WH_PROVIDERS: Provider[] = [
  { name: '万邑通（美西仓）', cost: 0.92, share: 0.34 },
  { name: '递四方（美东仓）', cost: 1.05, share: 0.24 },
  { name: '谷仓（美中仓）', cost: 0.83, share: 0.19 },
  { name: '大健云仓（欧洲仓）', cost: 1.18, share: 0.13 },
  { name: '自有仓（广州）', cost: 0.38, share: 0.10 },
]
export const WH_CH_SHARE: Record<string, number> = { 'Amazon': 0.34, 'Wayfair': 0.20, 'Home Depot': 0.16, "Lowe's": 0.13, '独立站': 0.17 }

/* 服务商单位成本（元 / kg 或 元 / 件） */
export function providerCost(base: number, idx: number[], seed: string, m?: number | null): number {
  const w = wave(seed, 0.05)
  return base * idxAt(idx, m) * w(m)
}
/* 服务商份额（确定性月度波动后归一化） */
export function provShares(list: Provider[], m?: number | null): number[] {
  const js = list.map(function (p) { return p.share * wave('ps-' + p.name, 0.08)(m) })
  const tot = js.reduce(function (a, b) { return a + b }, 0) || 1
  return list.map(function (_p, i) { return js[i] / tot })
}
/* 渠道仓储占比（确定性月度波动后归一化） */
export function whChShares(m?: number | null): Record<string, number> {
  const w: Record<string, number> = {}
  let tot = 0
  CHANNELS.forEach(function (c) {
    w[c] = WH_CH_SHARE[c] * wave('whc-' + c, 0.10)(m)
    tot += w[c]
  })
  CHANNELS.forEach(function (c) { w[c] = w[c] / (tot || 1) })
  return w
}

/* ---------- 品类：SPU / 件均价 / 上市年份结构 ---------- */
/* 品类相对件价：已校准使 Σ(收入份额 ÷ 相对价) = 1 ⇒ 销量合计 ≡ 订单量（件单比 1.00），且加权件均价 ≡ 客单价 */
export const CAT_PRICE_REL: Record<string, number> = { '框镜': 0.6837, '灯镜': 0.8161, '镜柜': 1.6331, '水龙头': 0.6646, '浴室柜': 2.4678, '淋浴门': 1.9944 }
export const CAT_SPU: Record<string, number> = { '框镜': 168, '灯镜': 142, '镜柜': 96, '水龙头': 74, '浴室柜': 58, '淋浴门': 42 }
export const CAT_NEW_SPU: Record<string, number> = { '框镜': 14, '灯镜': 12, '镜柜': 8, '水龙头': 6, '浴室柜': 5, '淋浴门': 4 }
export const PRICE_IDX = [1.00, 0.99, 1.00, 0.98, 0.99, 1.00, 0.97, 0.98, 0.96]
export const NEW_YEARS = ['2023 年及以前', '2024 年上新', '2025 年上新', '2026 年上新']
export const CAT_YEAR_MIX: Record<string, number[]> = {
  '框镜': [0.50, 0.24, 0.18, 0.08],
  '灯镜': [0.38, 0.22, 0.27, 0.13],
  '镜柜': [0.45, 0.26, 0.19, 0.10],
  '水龙头': [0.60, 0.20, 0.14, 0.06],
  '浴室柜': [0.43, 0.28, 0.20, 0.09],
  '淋浴门': [0.58, 0.22, 0.14, 0.06],
}

/* 件均价（元/件）= 客单价 × 品类相对价；月份指数体现大促降价 */
export function catPrice(cat: string, m?: number | null): number {
  const om = orderModel(m)
  return om.blendedAov * (CAT_PRICE_REL[cat] || 1) * idxAt(PRICE_IDX, m)
}
/* 在售 SPU：m = null 取期末值，m = 0~8 取指定月份 */
export function catSpu(cat: string, m?: number | null): number {
  const base = CAT_SPU[cat] || 0, add = CAT_NEW_SPU[cat] || 0
  if (m === null || m === undefined) return base + add - Math.round(base * 0.02)
  const grow = Math.round(add * (m + 1) / 9)
  const cut = Math.round(base * 0.02 * (m + 1) / 9)
  return base + grow - cut
}
export interface CatModelRow { cat: string; revenue: number; share: number; gross: number; grossRate: number; spu: number; price: number; qty: number; perSpu: number }
export function catModel(m?: number | null): CatModelRow[] {
  return productRowsAt(m).map(function (r) {
    const price = catPrice(r.key, m)
    const qty = price > 0 ? r.revenue * 10000 / price : 0
    const spu = catSpu(r.key, m)
    return {
      cat: r.key, revenue: r.revenue, share: r.share * 100, gross: r.gross, grossRate: r.grossRate * 100,
      spu: spu, price: price, qty: qty, perSpu: spu > 0 ? r.revenue / spu : 0,
    }
  })
}
/* 按月上市年份结构的销售占比 */
export function yearMixRows(m?: number | null): { label: string; money: number; share: number }[] {
  const rows = productRowsAt(m)
  const tot = rows.reduce(function (a, r) { return a + r.revenue }, 0) || 1
  return NEW_YEARS.map(function (y, i) {
    const money = rows.reduce(function (a, r) {
      const mix = CAT_YEAR_MIX[r.key]
      return a + r.revenue * (mix ? mix[i] : 0)
    }, 0)
    return { label: y, money: money, share: money / tot * 100 }
  })
}

export const YEAR_LABEL = '2026年度累计（1-9月）'

/* 月度 / 年度维度基础参数
   月份集合：2026 年 1-9 月（有实际数据的月份）
   季节权重：用于发生额型指标的月度拆分，同时作为比率型指标的加权平均权重；全年 12 个月权重合计为 1.000 */
export const MONTHS9 = ['01月', '02月', '03月', '04月', '05月', '06月', '07月', '08月', '09月']
export const SEASON12 = [0.072, 0.066, 0.076, 0.082, 0.090, 0.092, 0.088, 0.092, 0.084, 0.086, 0.090, 0.082]
export const SEASON9 = SEASON12.slice(0, 9)
export const SEASON9_SUM = 0.742

/* 图表配色 */
export const PAL = ['#2563eb', '#0d9488', '#7c3aed', '#e08600', '#0ea5e9', '#d9251d', '#65a30d', '#db2777', '#0891b2', '#9333ea']
export const C = {
  biz: '#2563eb', bizSoft: '#eaf1fe',
  fin: '#0d9488', finSoft: '#e3f5f2',
  up: '#d9251d', down: '#0f9d58', warn: '#e08600',
  line: '#e3e8f0', text: '#16203a', text2: '#5b6780', text3: '#8c97ad', grid: '#eef1f7',
}

export const TREND_OFFSET = 3 /* TREND 取月度序列的第 4~9 个月（索引 3~8） */

/* ------------------------- 财务指标体系 -------------------------
   dir: 1 = 越大越好（正向）; -1 = 越小越好（逆向）
   level: 1 一级指标 / 2 二级指标 ; parent: 所属一级指标编码
------------------------------------------------------------------ */
export const SEED_FIN: SeedIndicator[] = [
  /* ===== 一级 1：净销售额 ===== */
  { code: 'F1', name: '净销售额', level: 1, parent: null, unit: '人民币', dir: 1, target: 12000, actual: 9840, weight: 20, depts: ['财务部', '运营部'], note: '全渠道主营业务收入（净额法）' },
  { code: 'F1.1', name: 'Amazon', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 4200, actual: 3560, weight: 5, depts: ['运营部', '财务部'], note: '渠道口径 · 北美站为主' },
  { code: 'F1.2', name: 'Wayfair', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 2400, actual: 1980, weight: 4, depts: ['运营部'], note: '渠道口径 · 家居垂直平台' },
  { code: 'F1.3', name: 'HomeDepot', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 1800, actual: 1420, weight: 3, depts: ['运营部'], note: '渠道口径 · 商超线上化' },
  { code: 'F1.4', name: "Lowe's", level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 1500, actual: 1180, weight: 3, depts: ['运营部'], note: '渠道口径 · 商超线上化' },
  { code: 'F1.5', name: '独立站', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 2100, actual: 1700, weight: 5, depts: ['市场部', '运营部'], note: '渠道口径 · DTC，毛利率最高' },
  { code: 'F1.6', name: '北美市场', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 9200, actual: 7660, weight: 6, depts: ['市场部'], note: '市场口径 · 美国 + 加拿大' },
  { code: 'F1.7', name: '欧洲市场', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 1000, actual: 800, weight: 4, depts: ['市场部'], note: '市场口径 · 德国 + 法国（不含英国）' },
  { code: 'F1.8', name: '英国市场', level: 2, parent: 'F1', unit: '人民币', dir: 1, target: 1800, actual: 1380, weight: 4, depts: ['市场部'], note: '市场口径 · 英国站群' },
  /* ===== 一级 2：毛利额 ===== */
  { code: 'F2', name: '毛利额', level: 1, parent: null, unit: '人民币', dir: 1, target: 4200, actual: 3092.6, weight: 15, depts: ['财务部', '供应中心'], note: '净销售额 − 营业成本' },
  { code: 'F2.1', name: 'Amazon', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 1323, actual: 1039.5, weight: 3, depts: ['运营部', '财务部'], note: '派生 · Amazon F1.1 × 毛利率 F3.1' },
  { code: 'F2.2', name: 'Wayfair', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 756, actual: 578.2, weight: 3, depts: ['运营部'], note: '派生 · Wayfair F1.2 × 毛利率 F3.2' },
  { code: 'F2.3', name: 'HomeDepot', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 567, actual: 414.6, weight: 3, depts: ['运营部'], note: '派生 · HomeDepot F1.3 × 毛利率 F3.3' },
  { code: 'F2.4', name: "Lowe's", level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 472.5, actual: 344.6, weight: 3, depts: ['运营部'], note: "派生 · Lowe's F1.4 × 毛利率 F3.4" },
  { code: 'F2.5', name: '独立站', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 924, actual: 715.7, weight: 3, depts: ['市场部', '运营部'], note: '派生 · 独立站 F1.5 × 毛利率 F3.5' },
  { code: 'F2.6', name: '北美市场', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 2944, actual: 2320.9, weight: 4, depts: ['市场部', '财务部'], note: '派生 · 北美市场 F1.6 × 毛利率 F3.6' },
  { code: 'F2.7', name: '欧洲市场', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 450, actual: 336.8, weight: 3, depts: ['市场部', '财务部'], note: '派生 · 欧洲市场 F1.7 × 毛利率 F3.7' },
  { code: 'F2.8', name: '英国市场', level: 2, parent: 'F2', unit: '人民币', dir: 1, target: 594, actual: 433.3, weight: 3, depts: ['市场部', '财务部'], note: '派生 · 英国市场 F1.8 × 毛利率 F3.8' },
  /* ===== 一级 3：毛利率 ===== */
  { code: 'F3', name: '毛利率', level: 1, parent: null, unit: '%', dir: 1, target: 35.0, actual: 31.4, weight: 10, depts: ['财务部', '供应中心'], note: '毛利额 / 净销售额' },
  { code: 'F3.1', name: 'Amazon', level: 2, parent: 'F3', unit: '%', dir: 1, target: 31.5, actual: 29.2, weight: 2, depts: ['运营部'], note: '已扣除平台佣金' },
  { code: 'F3.2', name: 'Wayfair', level: 2, parent: 'F3', unit: '%', dir: 1, target: 31.5, actual: 29.2, weight: 2, depts: ['运营部'], note: '已扣除平台佣金' },
  { code: 'F3.3', name: 'HomeDepot', level: 2, parent: 'F3', unit: '%', dir: 1, target: 31.5, actual: 29.2, weight: 2, depts: ['运营部'], note: '已扣除平台佣金' },
  { code: 'F3.4', name: "Lowe's", level: 2, parent: 'F3', unit: '%', dir: 1, target: 31.5, actual: 29.2, weight: 2, depts: ['运营部'], note: '已扣除平台佣金' },
  { code: 'F3.5', name: '独立站', level: 2, parent: 'F3', unit: '%', dir: 1, target: 44.0, actual: 42.1, weight: 2, depts: ['市场部'], note: 'DTC 无平台佣金' },
  { code: 'F3.6', name: '北美市场', level: 2, parent: 'F3', unit: '%', dir: 1, target: 32.0, actual: 30.3, weight: 2, depts: ['市场部'], note: '北美渠道加权' },
  { code: 'F3.7', name: '欧洲市场', level: 2, parent: 'F3', unit: '%', dir: 1, target: 45.0, actual: 42.1, weight: 2, depts: ['市场部'], note: '欧洲（不含英）以独立站为主' },
  { code: 'F3.8', name: '英国市场', level: 2, parent: 'F3', unit: '%', dir: 1, target: 33.0, actual: 31.4, weight: 2, depts: ['市场部'], note: '英国站群加权' },
  /* ===== 一级 4：净利润（7 项费用占比为驱动因子） ===== */
  { code: 'F4', name: '净利润', level: 1, parent: null, unit: '人民币', dir: 1, target: 1320, actual: 553.9, weight: 20, depts: ['财务部'], note: '毛利额 − 收入 × 期间费用率合计（税后净利）' },
  { code: 'F4.1', name: '营销费用率', level: 2, parent: 'F4', unit: '%', dir: -1, target: 5.10, actual: 5.69, weight: 4, depts: ['运营部', '市场部'], note: '广告投放 / 收入（由旧销售费用池按 36.45% 营销拆分衔接）' },
  { code: 'F4.2', name: '渠道佣金率', level: 2, parent: 'F4', unit: '%', dir: -1, target: 8.90, actual: 9.91, weight: 4, depts: ['运营部', '财务部'], note: '平台佣金与支付手续费 / 收入（衔接拆分系数 63.55%）' },
  { code: 'F4.3', name: '头程成本占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: 2.01, actual: 2.15, weight: 3, depts: ['物流物控部'], note: '头程物流成本 / 收入' },
  { code: 'F4.4', name: '尾程成本占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: 2.72, actual: 2.90, weight: 3, depts: ['物流物控部'], note: '尾程配送成本 / 收入' },
  { code: 'F4.5', name: '仓储成本占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: 1.27, actual: 1.35, weight: 3, depts: ['物流物控部'], note: '仓储成本 / 收入' },
  { code: 'F4.6', name: '人力成本占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: null, actual: null, weight: 3, depts: ['人力资源部'], note: '跨费用科目监测口径，不进入期间费用合计与净利润勾稽，待填报' },
  { code: 'F4.7', name: '管理费用占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: 2.6, actual: 2.5, weight: 3, depts: ['人力资源部', '财务部'], note: '管理费用 / 收入' },
  { code: 'F4.8', name: '研发费用占比', level: 2, parent: 'F4', unit: '%', dir: -1, target: 1.4, actual: 1.3, weight: 2, depts: ['研发部'], note: '补充项 · 结构性投入，需理性看待' },
  { code: 'F4.9', name: '期间费用率（合计）', level: 2, parent: 'F4', unit: '%', dir: -1, target: 24.0, actual: 25.8, weight: 2, depts: ['财务部'], note: '派生 = F4.1+F4.2+F4.3+F4.4+F4.5+F4.7+F4.8（不含 F4.6）' },

  /* ===== 一级 5：净利润率 ===== */
  { code: 'F5', name: '净利润率', level: 1, parent: null, unit: '%', dir: 1, target: 11.0, actual: 5.63, weight: 10, depts: ['财务部'], note: '净利润 / 收入' },

  /* ===== 一级 6：净资产收益率 ===== */
  { code: 'F6', name: '净资产收益率', level: 1, parent: null, unit: '%', dir: 1, target: null, actual: null, weight: 5, depts: ['财务部'], note: '净利润 / 平均净资产（杜邦分解锚点），待填报' },
  { code: 'F6.1', name: '资产负债率', level: 2, parent: 'F6', unit: '%', dir: -1, target: null, actual: null, weight: 2, depts: ['财务部'], note: '总负债 / 总资产，决定权益乘数，待填报' },

  /* ===== 一级 7：经营净现金流（营运资金 6 项为驱动因子） ===== */
  { code: 'F7', name: '经营净现金流', level: 1, parent: null, unit: '人民币', dir: 1, target: 1500, actual: 820, weight: 20, depts: ['财务部'], note: '经营活动现金流入 - 流出' },
  { code: 'F7.3', name: '应收账款', level: 2, parent: 'F7', unit: '人民币', dir: -1, target: 986.3, actual: 1024.4, weight: 3, depts: ['财务部'], note: '派生 = 收入 ÷ 365 × 应收账款周转天数（期末余额口径）' },
  { code: 'F7.4', name: '应收账款周转天数', level: 2, parent: 'F7', unit: '天', dir: -1, target: 30, actual: 38, weight: 4, depts: ['财务部'], note: '平台账期 + 分销账期' },
  { code: 'F7.5', name: '存货', level: 2, parent: 'F7', unit: '人民币', dir: -1, target: 1282.2, actual: 1408.9, weight: 3, depts: ['物流物控部', '供应中心'], note: '派生 = 营业成本 ÷ 365 × 存货周转天数（期末余额口径）' },
  { code: 'F7.6', name: '存货周转天数', level: 2, parent: 'F7', unit: '天', dir: -1, target: 60, actual: 78, weight: 4, depts: ['物流物控部', '供应中心'], note: '平均存货 / 日均营业成本' },
  { code: 'F7.7', name: '应付账款', level: 2, parent: 'F7', unit: '人民币', dir: 1, target: null, actual: null, weight: 3, depts: ['财务部', '供应中心'], note: '派生 = 营业成本 ÷ 365 × 应付账款周转天数，待填报' },
  { code: 'F7.8', name: '应付账款周转天数', level: 2, parent: 'F7', unit: '天', dir: 1, target: null, actual: null, weight: 3, depts: ['财务部', '供应中心'], note: '采购付款周期，待填报' },
]

/* ------------------------- 业务指标体系（4 板块） -------------------------
   结构：营销板块 S1 / 产品板块 S2 / 供应链板块 S3 / 仓配履约板块 S4
   维度（dims 字段声明该指标需要分维度填报的维度键）：
     channel 渠道 / category 品类 / lane 线路区域 / provider 服务商
   【数据状态】全部指标的目标值与实际值默认为空（null），页面显示「—」。
   CSV 批量导入格式：编码,维度,目标值,实际值（维度列填写维度成员名）
------------------------------------------------------------------------ */
export const BIZ_DIMS: Record<string, BizDimDef> = {
  channel: { label: '渠道', members: ['Amazon', 'Wayfair', 'Home Depot', "Lowe's", '独立站'] },
  category: { label: '品类', members: ['框镜', '灯镜', '镜柜', '其他'] },
  lane: { label: '线路区域', members: ['美东', '美西', '英国', '欧洲'] },
  provider: { label: '服务商', members: ['服务商A', '服务商B', '服务商C'] },
}
export const BIZ_DIM_ORDER = ['channel', 'category', 'lane', 'provider']
export function bizDimKey(code: string): string {
  return code.replace(/\./g, '_')
}
export function bizDimOf(code: string, dimKey: string, member: string): BizDimCell {
  const a = S.BIZ_DIM[bizDimKey(code)]
  const b = a && a[dimKey]
  const c = b && b[member]
  return c || { target: null, actual: null }
}
export function setBizDimOf(code: string, dimKey: string, member: string, field: ValueField, v: number | null): void {
  const k = bizDimKey(code)
  const a = S.BIZ_DIM[k] || (S.BIZ_DIM[k] = {})
  const b = a[dimKey] || (a[dimKey] = {})
  const c = b[member] || (b[member] = { target: null, actual: null })
  c[field] = v
}
/* 已填报的维度单元格数（用于进度展示） */
export function bizDimFilled(code: string): number {
  const a = S.BIZ_DIM[bizDimKey(code)]
  if (!a) return 0
  let n = 0
  for (const dk in a) {
    for (const mb in a[dk]) {
      const c = a[dk][mb]
      if (c && c.actual !== null && c.actual !== undefined) n++
    }
  }
  return n
}
/* 指标与维度成员：把某个指标的所有维度值展开成 [{dimKey, member, val}] */
export function bizDimCells(code: string, fields?: string[] | null): { dimKey: string; member: string; val: BizDimCell }[] {
  const out: { dimKey: string; member: string; val: BizDimCell }[] = []
  ;(fields || []).forEach(function (dk) {
    const D = BIZ_DIMS[dk]
    if (!D) return
    D.members.forEach(function (mb) {
      out.push({ dimKey: dk, member: mb, val: bizDimOf(code, dk, mb) })
    })
  })
  return out
}

export const SEED_BIZ: SeedIndicator[] = [
  /* ===== 营销板块 ===== */
  { code: 'S1', name: '营销板块', level: 1, parent: null, unit: '%', dir: 1, target: null, actual: null, weight: 30, depts: ['运营部', '市场部'], note: '由二级指标自动汇总（数据待填报）' },
  { code: 'S1.1', name: 'UV', level: 2, parent: 'S1', unit: '万', dir: 1, target: null, actual: null, weight: 4, depts: ['运营部', '市场部'], dims: ['channel'], note: '分渠道独立访客数，含付费与自然流量' },
  { code: 'S1.2', name: '转化率', level: 2, parent: 'S1', unit: '%', dir: 1, target: null, actual: null, weight: 4, depts: ['运营部', '视觉部'], dims: ['channel'], note: '订单量 / UV' },
  { code: 'S1.3', name: '客单价', level: 2, parent: 'S1', unit: '元', dir: 1, target: null, actual: null, weight: 4, depts: ['运营部', '产品作战部'], dims: ['channel'], note: '渠道收入 / 渠道订单量' },
  { code: 'S1.4', name: '折扣率', level: 2, parent: 'S1', unit: '%', dir: -1, target: null, actual: null, weight: 3, depts: ['运营部', '市场部'], dims: ['channel'], note: '实际成交价相对标价的折扣幅度，越低越好' },
  { code: 'S1.5', name: '品效', level: 2, parent: 'S1', unit: '倍', dir: 1, target: null, actual: null, weight: 3, depts: ['市场部', '运营部'], dims: ['channel'], note: '渠道销售额 / 该渠道投放费用' },
  { code: 'S1.6', name: '连带率', level: 2, parent: 'S1', unit: '件/单', dir: 1, target: null, actual: null, weight: 3, depts: ['运营部', '产品作战部'], dims: ['channel'], note: '销售件数 / 订单数' },
  { code: 'S1.7', name: '复购率', level: 2, parent: 'S1', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['市场部', '运营部'], dims: ['channel'], note: '周期内重复购买客户占比' },
  { code: 'S1.8', name: '非付费流量占比', level: 2, parent: 'S1', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['市场部', '运营部'], dims: ['channel'], note: '自然流量 UV / 总 UV' },
  { code: 'S1.9', name: '非付费订单占比', level: 2, parent: 'S1', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['运营部'], dims: ['channel'], note: '自然流量带来的订单 / 总订单' },
  { code: 'S1.10', name: '单位广告成本', level: 2, parent: 'S1', unit: '元', dir: -1, target: null, actual: null, weight: 4, depts: ['运营部', '市场部'], dims: ['channel'], note: '广告费用 / 广告带来的订单或点击，越低越好' },
  { code: 'S1.11', name: '社媒产出', level: 2, parent: 'S1', unit: '人民币', dir: 1, target: null, actual: null, weight: 3, depts: ['市场部'], note: '社媒渠道可归因产出金额（不分渠道）' },
  { code: 'S1.12', name: '客服人效', level: 2, parent: 'S1', unit: '单/人', dir: 1, target: null, actual: null, weight: 3, depts: ['运营部'], note: '客服承接订单量 / 客服人数（不分渠道）' },
  { code: 'S1.13', name: '视觉人效', level: 2, parent: 'S1', unit: '款/人', dir: 1, target: null, actual: null, weight: 3, depts: ['视觉部'], note: '视觉产出款数 / 视觉人数（不分渠道）' },

  /* ===== 产品板块 ===== */
  { code: 'S2', name: '产品板块', level: 1, parent: null, unit: '%', dir: 1, target: null, actual: null, weight: 20, depts: ['产品作战部', '研发部'], note: '由二级指标自动汇总（数据待填报）' },
  { code: 'S2.1', name: '新品开发周期', level: 2, parent: 'S2', unit: '天', dir: -1, target: null, actual: null, weight: 4, depts: ['研发部', '项目管理部'], dims: ['category'], note: '立项到上架全周期，分品类' },
  { code: 'S2.2', name: '上架SPU数量（老品迭代）', level: 2, parent: 'S2', unit: '款', dir: 1, target: null, actual: null, weight: 3, depts: ['产品作战部'], dims: ['category'], note: '老品迭代上架 SPU 数，分品类' },
  { code: 'S2.3', name: '上架SPU数量（新品）', level: 2, parent: 'S2', unit: '款', dir: 1, target: null, actual: null, weight: 3, depts: ['研发部', '产品作战部'], dims: ['category'], note: '全新品上架 SPU 数，分品类' },

  /* ===== 供应链板块 ===== */
  { code: 'S3', name: '供应链板块', level: 1, parent: null, unit: '%', dir: 1, target: null, actual: null, weight: 22, depts: ['供应中心', '物流物控部'], note: '由二级指标自动汇总（数据待填报）' },
  { code: 'S3.1', name: '交货准时率（新品）', level: 2, parent: 'S3', unit: '%', dir: 1, target: null, actual: null, weight: 4, depts: ['供应中心', '项目管理部'], note: '新品订单按期交付占比' },
  { code: 'S3.2', name: '交货准时率（老品）', level: 2, parent: 'S3', unit: '%', dir: 1, target: null, actual: null, weight: 4, depts: ['供应中心'], note: '老品订单按期交付占比' },
  { code: 'S3.3', name: '降本率', level: 2, parent: 'S3', unit: '%', dir: 1, target: null, actual: null, weight: 4, depts: ['供应中心'], note: '同规格物料同比采购成本降幅' },
  { code: 'S3.4', name: '质检合格率（新品）', level: 2, parent: 'S3', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['供应中心', '研发部'], note: '新品到货检验合格批次占比' },
  { code: 'S3.5', name: '质检合格率（老品）', level: 2, parent: 'S3', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['供应中心'], note: '老品到货检验合格批次占比' },
  { code: 'S3.6', name: '采购周期', level: 2, parent: 'S3', unit: '天', dir: -1, target: null, actual: null, weight: 3, depts: ['供应中心'], dims: ['category'], note: '下单到入库天数，分品类' },

  /* ===== 仓配履约板块 ===== */
  { code: 'S4', name: '仓配履约板块', level: 1, parent: null, unit: '%', dir: 1, target: null, actual: null, weight: 28, depts: ['物流物控部', '供应中心'], note: '由二级指标自动汇总（数据待填报）' },
  { code: 'S4.1', name: '整柜装载率', level: 2, parent: 'S4', unit: 'm³', dir: 1, target: null, actual: null, weight: 3, depts: ['物流物控部'], note: '实际装载体积' },
  { code: 'S4.2', name: '单位头程成本', level: 2, parent: 'S4', unit: '元/kg', dir: -1, target: null, actual: null, weight: 4, depts: ['物流物控部'], dims: ['lane'], note: '分线路区域：美东 / 美西 / 英国 / 欧洲' },
  { code: 'S4.3', name: '单位尾程成本', level: 2, parent: 'S4', unit: '元/单', dir: -1, target: null, actual: null, weight: 4, depts: ['物流物控部'], note: '尾程配送费用 / 配送订单量' },
  { code: 'S4.4', name: '单位仓储费用', level: 2, parent: 'S4', unit: '元/件', dir: -1, target: null, actual: null, weight: 3, depts: ['物流物控部'], dims: ['provider'], note: '分服务商：服务商A / 服务商B / 服务商C' },
  { code: 'S4.5', name: '单位操作费用', level: 2, parent: 'S4', unit: '元/件', dir: -1, target: null, actual: null, weight: 3, depts: ['物流物控部'], dims: ['provider'], note: '出入库操作费 / 操作件数，分服务商' },
  { code: 'S4.6', name: '存销比', level: 2, parent: 'S4', unit: '倍', dir: -1, target: null, actual: null, weight: 3, depts: ['物流物控部', '供应中心'], note: '库存量 / 销量的倍数关系，越低越健康' },
  { code: 'S4.7', name: '有货率（增量）', level: 2, parent: 'S4', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['物流物控部'], note: '增量 SKU / 新品的在架有货比例' },
  { code: 'S4.8', name: '有货率（存量）', level: 2, parent: 'S4', unit: '%', dir: 1, target: null, actual: null, weight: 3, depts: ['物流物控部'], note: '存量 SKU 的在架有货比例' },
  { code: 'S4.9', name: '呆滞库存占比', level: 2, parent: 'S4', unit: '%', dir: -1, target: null, actual: null, weight: 3, depts: ['物流物控部', '供应中心'], note: '长库龄呆滞库存金额 / 库存总额' },
]

/* ------------------------- 业财关联关系 -------------------------
   biz 字段对应业务指标（4 板块）编码；fin 字段为其传导到的财务指标。 */
export const LINKAGE: LinkageRule[] = [
  /* --- 营销板块 → 收入 / 费用 / 毛利 --- */
  { biz: 'S1.1', bizName: 'UV', fin: 'F1', finName: '营业收入', dir: '正向', strength: 0.80, coef: '强',
    logic: '流量规模是收入的第一驱动因子，同等转化与客单价下 UV 直接放大成交规模', dept: '运营部 / 市场部', impact: 'UV 每 +10% → 收入约 +8%（受转化率与客单价共同约束）' },
  { biz: 'S1.2', bizName: '转化率', fin: 'F1', finName: '营业收入', dir: '正向', strength: 0.75, coef: '强',
    logic: '同等流量下转化率提升直接放大成交量，且不额外增加流量成本', dept: '运营部 / 视觉部', impact: '转化率 +0.3pt → 收入约 +9%' },
  { biz: 'S1.3', bizName: '客单价', fin: 'F1 / F3', finName: '营业收入 / 毛利率', dir: '正向', strength: 0.60, coef: '中',
    logic: '产品结构与连带销售推高客单价，带动收入与毛利结构同步优化', dept: '运营部 / 产品作战部', impact: '客单价 +5% → 收入约 +2.8%，毛利率 +0.4pt' },
  { biz: 'S1.4', bizName: '折扣率', fin: 'F3', finName: '毛利率', dir: '负向', strength: 0.70, coef: '强',
    logic: '折扣直接让利，折扣率每上升 1pt 近似等额侵蚀毛利率', dept: '运营部 / 市场部', impact: '折扣率 −1pt → 毛利率约 +1pt' },
  { biz: 'S1.5', bizName: '品效', fin: 'F4.1', finName: '营销费用率', dir: '正向', strength: 0.68, coef: '强',
    logic: '品效（销售额 / 投放费用）提升等价于单位投放产出提高，直接摊薄销售费用率', dept: '市场部 / 运营部', impact: '品效 +0.5 倍 → 销售费用率约 −0.9pt' },
  { biz: 'S1.6', bizName: '连带率', fin: 'F1 / F3', finName: '营业收入 / 毛利率', dir: '正向', strength: 0.45, coef: '中',
    logic: '连带率提升摊薄单次获客与履约成本，提升每单收入贡献', dept: '运营部 / 产品作战部', impact: '连带率 +0.2 件/单 → 客单价约 +6%' },
  { biz: 'S1.7', bizName: '复购率', fin: 'F1 / F4.1', finName: '营业收入 / 营销费用率', dir: '正向', strength: 0.52, coef: '中',
    logic: '复购客户获客成本极低，同时提升收入稳定性与 LTV', dept: '市场部 / 运营部', impact: '复购率 +4pt → 销售费用率约 −0.4pt' },
  { biz: 'S1.8', bizName: '非付费流量占比', fin: 'F4.1', finName: '营销费用率', dir: '正向', strength: 0.62, coef: '强',
    logic: '自然流量占比越高，同等成交规模下的广告投入越少', dept: '市场部 / 运营部', impact: '非付费流量占比 +5pt → 销售费用率约 −0.5pt' },
  { biz: 'S1.9', bizName: '非付费订单占比', fin: 'F4.1 → F4', finName: '营销费用率 → 净利润', dir: '正向', strength: 0.60, coef: '强',
    logic: '非付费订单占比提升直接减少广告归因订单，压降单位获客成本', dept: '运营部', impact: '非付费订单占比 +5pt → 释放利润约 140 万元' },
  { biz: 'S1.10', bizName: '单位广告成本', fin: 'F4.1 → F4', finName: '营销费用率 → 净利润', dir: '负向', strength: 0.70, coef: '强',
    logic: '单位广告成本上升直接推高销售费用率，按比例侵蚀净利润', dept: '运营部 / 市场部', impact: '单位广告成本 −15% → 释放利润约 280 万元' },
  { biz: 'S1.11', bizName: '社媒产出', fin: 'F1 / F4.1', finName: '营业收入 / 营销费用率', dir: '正向', strength: 0.40, coef: '中',
    logic: '社媒内容带来低成本的品牌与长尾流量，摊薄整体获客成本', dept: '市场部', impact: '社媒产出每 +50 万元 → 销售费用率约 −0.2pt' },
  { biz: 'S1.12', bizName: '客服人效', fin: 'F4.7', finName: '管理费用率', dir: '正向', strength: 0.35, coef: '弱',
    logic: '客服人效提升摊薄固定人力与办公成本，间接改善管理费用率', dept: '运营部', impact: '客服人效 +10% → 管理费用率约 −0.05pt' },
  { biz: 'S1.13', bizName: '视觉人效', fin: 'F4.3 / F2', finName: '管理费用占比 / 毛利额', dir: '正向', strength: 0.38, coef: '弱',
    logic: '视觉产出效率提升降低内容成本，同时提升详情页转化与毛利结构', dept: '视觉部', impact: '视觉人效 +10% → 管理费用率约 −0.05pt' },

  /* --- 产品板块 → 毛利 / 现金流 --- */
  { biz: 'S2.1', bizName: '新品开发周期', fin: 'F7 / F2', finName: '经营净现金流 / 毛利额', dir: '负向', strength: 0.45, coef: '中',
    logic: '周期拉长占用研发投入与备货资金，拖累现金流周转并延后新品毛利贡献', dept: '研发部 / 项目管理部', impact: '周期每缩短 10 天 → 释放资金约 45 万元' },
  { biz: 'S2.2', bizName: '上架SPU数量（老品迭代）', fin: 'F2 / F3', finName: '毛利额 / 毛利率', dir: '正向', strength: 0.50, coef: '中',
    logic: '老品迭代通过结构优化与成本改善提升单品毛利贡献', dept: '产品作战部', impact: '迭代上架 +10 款 → 毛利率约 +0.3pt' },
  { biz: 'S2.3', bizName: '上架SPU数量（新品）', fin: 'F1 / F2', finName: '营业收入 / 毛利额', dir: '正向', strength: 0.55, coef: '中',
    logic: '新品上架数量决定增量收入来源与货架竞争位，是规模增长的结构性抓手', dept: '研发部 / 产品作战部', impact: '新品上架 +10 款 → 收入约 +260 万元' },

  /* --- 供应链板块 → 成本 / 毛利 --- */
  { biz: 'S3.1', bizName: '交货准时率（新品）', fin: 'F1 / F4', finName: '营业收入 / 净利润', dir: '正向', strength: 0.55, coef: '中',
    logic: '新品准时交付决定上市节奏与首发销量，延迟直接损失窗口期收入', dept: '供应中心 / 项目管理部', impact: '准时率 +5pt → 收入约 +120 万元' },
  { biz: 'S3.2', bizName: '交货准时率（老品）', fin: 'F1 / F4.3+F4.4+F4.5', finName: '营业收入 / 头程+尾程+仓储费用合计', dir: '正向', strength: 0.58, coef: '中',
    logic: '老品准时交付保障持续供货，避免断货损失并减少紧急空运等溢价运费', dept: '供应中心', impact: '准时率 +5pt → 履约费用率约 −0.2pt' },
  { biz: 'S3.3', bizName: '降本率', fin: 'F2 / F3', finName: '毛利额 / 毛利率', dir: '正向', strength: 0.80, coef: '强',
    logic: '采购降本直接减少营业成本，几乎 1:1 转化为毛利额增长', dept: '供应中心', impact: '降本率 +1pt → 毛利约 +99 万元' },
  { biz: 'S3.4', bizName: '质检合格率（新品）', fin: 'F2 / F5', finName: '毛利额 / 净利润', dir: '正向', strength: 0.50, coef: '中',
    logic: '新品合格率不足带来返工、返修与退货损失，直接侵蚀毛利', dept: '供应中心 / 研发部', impact: '合格率 +2pt → 减少返工与退货损失约 60 万元' },
  { biz: 'S3.5', bizName: '质检合格率（老品）', fin: 'F2 / F4.2', finName: '毛利额 / 物流履约费用率', dir: '正向', strength: 0.45, coef: '中',
    logic: '批量质量问题触发退换货与逆向物流，同时推高履约成本', dept: '供应中心', impact: '合格率 +2pt → 减少损失约 45 万元' },
  { biz: 'S3.6', bizName: '采购周期', fin: 'F7.6 / F7', finName: '存货周转天数 / 经营净现金流', dir: '负向', strength: 0.60, coef: '中',
    logic: '采购周期越长，为保供货所需的安全库存越高，资金占用越重', dept: '供应中心', impact: '采购周期 −5 天 → 释放占用资金约 110 万元' },

  /* --- 仓配履约板块 → 履约费用 / 周转 --- */
  { biz: 'S4.1', bizName: '整柜装载率', fin: 'F4.3+F4.4+F4.5', finName: '头程+尾程+仓储费用合计', dir: '正向', strength: 0.62, coef: '强',
    logic: '装载率提升直接摊薄单位头程成本，是头程降本的最大杠杆', dept: '物流物控部', impact: '装载率 +5pt → 头程成本约 −6%，履约费用率 −0.13pt' },
  { biz: 'S4.2', bizName: '单位头程成本', fin: 'F4.3+F4.4+F4.5', finName: '头程+尾程+仓储费用合计', dir: '负向', strength: 0.72, coef: '强',
    logic: '头程单位成本上升按货量直接计入履约费用，侵蚀净利', dept: '物流物控部', impact: '单位头程成本 −5% → 履约费用率约 −0.11pt' },
  { biz: 'S4.3', bizName: '单位尾程成本', fin: 'F4.3+F4.4+F4.5 → F4', finName: '头程+尾程+仓储费用合计 → 净利润', dir: '负向', strength: 0.70, coef: '强',
    logic: '尾程为履约费用最大构成，单位成本下降近似等额转化为净利', dept: '物流物控部', impact: '单位尾程成本 −5% → 净利约 +72 万元' },
  { biz: 'S4.4', bizName: '单位仓储费用', fin: 'F4.3+F4.4+F4.5', finName: '头程+尾程+仓储费用合计', dir: '负向', strength: 0.60, coef: '强',
    logic: '仓储单价与前置库存量共同决定仓储费用，单价优化直接降低履约成本', dept: '物流物控部', impact: '单位仓储费用 −5% → 履约费用率约 −0.07pt' },
  { biz: 'S4.5', bizName: '单位操作费用', fin: 'F4.3+F4.4+F4.5', finName: '头程+尾程+仓储费用合计', dir: '负向', strength: 0.55, coef: '中',
    logic: '出入库操作费按件计费，操作效率与自动化水平决定该项成本', dept: '物流物控部', impact: '单位操作费用 −8% → 履约费用率约 −0.04pt' },
  { biz: 'S4.6', bizName: '存销比', fin: 'F7.6 / F7', finName: '存货周转天数 / 经营净现金流', dir: '负向', strength: 0.70, coef: '强',
    logic: '存销比偏高意味着库存相对销量冗余，直接拉长周转、占用现金', dept: '物流物控部 / 供应中心', impact: '存销比 −0.2 倍 → 周转约 −8 天，释放现金约 145 万元' },
  { biz: 'S4.7', bizName: '有货率（增量）', fin: 'F1', finName: '营业收入', dir: '正向', strength: 0.62, coef: '强',
    logic: '增量 SKU 的有货率决定新品能否承接流量与广告投放，直接影响增量收入', dept: '物流物控部', impact: '有货率 +5pt → 收入约 +130 万元' },
  { biz: 'S4.8', bizName: '有货率（存量）', fin: 'F1 / F7.6', finName: '营业收入 / 存货周转天数', dir: '正向', strength: 0.58, coef: '强',
    logic: '存量有货率不足直接丢失货架销售，同时拉低 Listing 自然排名权重', dept: '物流物控部', impact: '有货率 +5pt → 收入约 +180 万元' },
  { biz: 'S4.9', bizName: '呆滞库存占比', fin: 'F7.6 / F7', finName: '存货周转天数 / 经营净现金流', dir: '负向', strength: 0.65, coef: '强',
    logic: '呆滞库存占用仓储与资金，并可能形成跌价损失', dept: '物流物控部 / 供应中心', impact: '呆滞占比 −2pt → 释放资金约 90 万元' },
]

/* =========================================================================
   政策环境：事件台账（时间 / 业务板块 / 事件描述 / 事件影响）；POLICY_SEED 为示例数据
   ========================================================================= */
export const POLICY_SEGS = ['营销板块', '产品板块', '供应链板块', '仓配履约板块', '财务板块', '综合']
export const POLICY_SEED: PolicyEvent[] = [
  { time: '2026-01-02', seg: '供应链板块', desc: '美国 301 关税对卫浴镜类、浴室柜、淋浴门等品类继续加征关税，并收紧原产地认定', impact: '到岸成本上升：毛利额 -80 万元、净利润 -98 万元，需推进二供转移与提价对冲' },
  { time: '2026-03-01', seg: '供应链板块', desc: '加州 65 号提案与 CARB / TSCA Title VI 甲醛限量收紧，板材须切换 E0 / NAF 基材', impact: '板材升级年增成本约 96 万元、净利润 -82 万元，过渡库存占用现金流 88 万元' },
  { time: '2026-04-01', seg: '产品板块', desc: '美国 STURDY 法案（16 CFR 1261）稳定性强制标准，镜柜 / 浴室柜须通过测试并随附防倾倒件', impact: '两款新品延期上市：收入 -95 万元、净利润 -73 万元，一次性改模测试投入 24 万元' },
  { time: '2024-12-13', seg: '营销板块', desc: '欧盟 GPSR 通用产品安全法规进入强执法，须设立 EC REP 并建立可追溯技术文件', impact: '欧洲 SKU 面临下架风险：收入敞口 -320 万元、净利润 -124 万元' },
]

/* =========================================================================
   重点工作进度：工作台账行字段 = 时间 / 工作分类 / 工作目标 / 工作分解 / 预计完成时间 / 目前进度 / 工作状态。
   工作分类六档，工作状态四档；「需要关注工作」按状态自动从台账派生（延误 + 阻滞）。
   ========================================================================= */
export const KW_CATEGORIES = ['核算', '资金', '合规', '降本增收', '财务BP', '信息化']
export const KW_CATEGORY_COLOR: Record<string, string> = { '核算': '#2563eb', '资金': '#0ea5b7', '合规': '#d9251d', '降本增收': '#0f9d58', '财务BP': '#7c3aed', '信息化': '#475569' }
export const KW_STATUS = ['进行中', '已完成', '延误', '阻滞']
export const KW_STATUS_COLOR: Record<string, string> = { '进行中': '#2563eb', '已完成': '#0f9d58', '延误': '#e08600', '阻滞': '#d9251d' }

export const KW_SEED: KwTask[] = [
  { time: '2026-04', cat: '合规', goal: '美国 STURDY 防倾倒标准合规改模', breakdown: '框镜主结构重新开模 · 二轮试产 09/20 · 一次性模具分摊到 Q3-Q4 量产批次', eta: '2026-11', progress: 62, status: '进行中' },
  { time: '2026-03', cat: '合规', goal: 'EUDR 木材合规溯源体系', breakdown: 'FCA 入库 100% 标注 → QR 链路 09/30 上线 · 小型供应商 FAVOR ID 组合方式缓出', eta: '2026-12', progress: 48, status: '进行中' },
  { time: '2026-05', cat: '合规', goal: '欧盟 GPSR 产品安全合规建设', breakdown: '全 SKU 合规标签上线 · EC REP 已签约 · 9 月底完成 80%', eta: '2026-11', progress: 55, status: '进行中' },
  { time: '2026-02', cat: '合规', goal: '德国 VerpackG / EPR 包装许可', breakdown: 'LUCID 注册 + 包装回收合同签约 → 后续年费 18 万/年', eta: '2026-08', progress: 100, status: '已完成' },
  { time: '2026-01', cat: '降本增收', goal: '头程物流拼柜 + FBA 多仓调拨优化', breakdown: 'FBA 多仓分拨覆盖 5 个仓号 → 9 月单柜成本下降 14% · 目标物流成本占收入比 -1.5pt', eta: '2026-12', progress: 71, status: '进行中' },
  { time: '2026-02', cat: '降本增收', goal: '关键 SKU 集中采购 + 战略供应商返利', breakdown: 'Top 20 SKU 已 70% 集中下单 · 季度返利机制谈判中 · 目标采购成本占收入比 -1.2pt', eta: '2026-12', progress: 65, status: '进行中' },
  { time: '2026-03', cat: '降本增收', goal: '模具共享 + 通用化平台', breakdown: '通用底座方案已定稿 · 客户定制化响应时间缩短 30% · 3 个新品 BOM 重叠度低于预期', eta: '2026-11', progress: 32, status: '延误' },
  { time: '2026-04', cat: '降本增收', goal: '视觉素材 AI 化生产', breakdown: '新品视觉成本较去年下降 28% · 单图时效由 6h 缩至 1.5h', eta: '2026-10', progress: 78, status: '进行中' },
  { time: '2026-05', cat: '降本增收', goal: 'Home Depot 招商上架 20 款', breakdown: '首批 12 SKU 通过招商审核 · 9/25 上架 8 SKU · 预计 Q4 单月贡献 80 万', eta: '2026-12', progress: 45, status: '进行中' },
  { time: '2026-06', cat: '降本增收', goal: "Lowe's 招商上架 15 款", breakdown: "招商资料提交 8/15 → 进入合规审核阶段 · Lowe's 要求额外 EHS 检测报告，预计延后 8 周", eta: '2026-12', progress: 18, status: '阻滞' },
  { time: '2026-04', cat: '核算', goal: '独立站 DTC 升级 + CRM 体系', breakdown: '新站 9/20 上线 · 复购率由 18% 升至 24% · 目标毛利率提升 0.4pt', eta: '2026-12', progress: 52, status: '进行中' },
  { time: '2026-03', cat: '降本增收', goal: '智能灯镜二代上市', breakdown: '小批量 9/15 试产 · 计划 10/8 全面上市 · 目标新品成功率 70%', eta: '2026-10', progress: 58, status: '进行中' },
  { time: '2026-02', cat: '核算', goal: '镜柜 SKU 全面升级', breakdown: '镜柜系列全面切换 → 月度件数较去年 +15.3% · 项目已闭环', eta: '2026-08', progress: 100, status: '已完成' },
  { time: '2026-06', cat: '信息化', goal: '业财一体化工作台上线', breakdown: 'V1.0 已上线 · 月度填报闭环 9 月底前完成 · 年化节省财务+运营人力约 30 万', eta: '2026-10', progress: 82, status: '进行中' },
  { time: '2026-05', cat: '信息化', goal: '仓储 WMS 二期 + 多仓可视化', breakdown: '主仓功能上线 → 海外仓对接延期至 11 月 · 海外仓 API 对接比预期复杂', eta: '2026-12', progress: 38, status: '延误' },
]

/* ------------------------- 经营建议：管理建议台账 -------------------------
   行字段：时间 / 业务板块 / 背景描述 / 管理建议 / 影响评估；业务板块下拉复用 POLICY_SEGS */
export const ADVICE_SEED: AdviceEvent[] = [
  { time: '2026-01', seg: '营销板块', desc: '渠道品效（销售额 ÷ 投放费用）低于目标，营销费用率超标，投放费用为期间费用首要增量来源',
    advice: '① 按 ASIN 分级管理，单位广告成本高于渠道均值 1.5 倍的广告组限期降预算或淘汰；② 高转化词迁移至精确匹配，收缩无效流量；③ 强化 Listing 自然排名，提升非付费流量占比；④ 建立周度品效预警看板，分渠道设定阈值',
    impact: '品效提升至目标水平，可释放投放费用并压降营销费用率，直接增厚净利润' },
  { time: '2026-02', seg: '供应链板块', desc: '采购降本率低于目标，营业成本约占收入 67%，采购端每 1pt 降幅即为可观的毛利增量',
    advice: '① 对框镜、灯镜、镜柜 Top20 物料做成本拆解，锁定可议价空间；② 合并分散订单，提升单批次采购量换取阶梯价；③ 引入 2~3 家备用供应商形成常态比价机制；④ 与研发协同推进结构优化 / 材料替代降本',
    impact: '采购成本率补足缺口，直接转化为毛利额与净利润增量' },
  { time: '2026-03', seg: '仓配履约板块', desc: '存货周转天数超标，海外仓备货周期偏长，占用资金与仓租成本上升',
    advice: '① 建立 ABC 分级补货模型，A 类保安全库存、C 类按需补货；② 清理 180 天以上长库龄 SKU，通过站内促销 / 清仓渠道变现；③ 优化头程节奏，压缩海外仓备货周期；④ 打通 ERP 与平台销量数据，实现周度补货决策',
    impact: '周转天数降至目标，可释放占用现金并改善经营性现金流' },
  { time: '2026-04', seg: '产品板块', desc: '上架 SPU 数量（老品迭代与新品）低于目标，货架覆盖不足限制增量收入',
    advice: '① 按「销量 × 毛利率」四象限盘点全量 SKU，淘汰双低 SKU 释放开发与视觉资源；② 资源集中到高毛利品类（灯镜、镜柜）的迭代与新品排期；③ 新品立项增加市场验证环节；④ 建立 90 天上市复盘机制，未达标即决策加投或退出',
    impact: '补足上架款数缺口，按单款年贡献毛利估算可增厚毛利额' },
]

/* =========================================================================
   全局状态（原代码中的 let/var 全局变量），集中为响应式对象
   - IND：年度基准数据（唯一真源，actual/target 均为年度累计口径）
   - CUR：当前维度视图数组：年度维度下与 IND 同引用；月度维度下为换算后的副本
   - dim：全局维度 year 年度 / month 月度；curM：月度维度选中的月份，取值 1~9
   - TREND：趋势序列（近 6 个月），由 refreshTrend 从指标月度序列派生
   ========================================================================= */
export const S = reactive({
  IND: [] as Indicator[],
  CUR: [] as Indicator[],
  BIZ_DIM: {} as BizDimStore,
  POLICY_EVENTS: POLICY_SEED.map(function (o) { return Object.assign({}, o) }) as PolicyEvent[],
  ADVICE_EVENTS: ADVICE_SEED.map(function (o) { return Object.assign({}, o) }) as AdviceEvent[],
  KW_TASKS: KW_SEED.map(function (o) { return Object.assign({}, o) }) as KwTask[],
  TREND: {
    months: ['04月', '05月', '06月', '07月', '08月', '09月'],
    revenue: [0, 0, 0, 0, 0, 0],
    gross: [0, 0, 0, 0, 0, 0],
    net: [0, 0, 0, 0, 0, 0],
    acos: [0, 0, 0, 0, 0, 0],
  } as TrendData,
  dim: 'year' as DimMode,
  curM: 9,
})

/* 「今天」：集中为可注入函数，便于测试固定时间 */
export let today: () => Date = () => new Date()
export function setToday(fn: () => Date): void {
  today = fn
}

/* 台账统计：分类 / 状态 计数 + 平均进度 + 需关注数 */
export interface KwStat {
  total: number; byStatus: Record<string, number>; byCat: Record<string, number>; progSum: number
  delayed: number; blocked: number; hot: number; progressAvg: number; watch: number
}
export function kwStat(): KwStat {
  const s: KwStat = {
    total: S.KW_TASKS.length, byStatus: {}, byCat: {}, progSum: 0,
    delayed: 0, blocked: 0, hot: 0, progressAvg: 0, watch: 0,
  }
  KW_STATUS.forEach(function (x) { s.byStatus[x] = 0 })
  KW_CATEGORIES.forEach(function (x) { s.byCat[x] = 0 })
  S.KW_TASKS.forEach(function (p) {
    s.byStatus[p.status] = (s.byStatus[p.status] || 0) + 1
    s.byCat[p.cat] = (s.byCat[p.cat] || 0) + 1
    s.progSum += Number(p.progress || 0)
  })
  s.delayed = s.byStatus['延误'] || 0
  s.blocked = s.byStatus['阻滞'] || 0
  s.hot = s.delayed + s.blocked
  s.watch = s.hot
  s.progressAvg = S.KW_TASKS.length ? s.progSum / S.KW_TASKS.length : 0
  return s
}

/* ------------------------- 数据分析二级导航 -------------------------
   数据分析模块下的 9 个子模块；左导航「数据分析」展开的二级菜单与页内二级导航栏共用此定义 */
export const ANA_NAV: NavItem[] = [
  { id: 'anaChannel', name: '渠道效益分析', icon: 'linkage', desc: '按渠道拆解九项损益结构，贡献毛利合计 = 净利润' },
  { id: 'anaTraffic', name: '流量分析', icon: 'analysis', desc: '渠道 UV / 转化率 / 非付费流量占比 / 单位广告成本 CPC' },
  { id: 'anaUser', name: '用户分析', icon: 'keywork', desc: '渠道新客与老客结构、客单价差异与留存贡献' },
  { id: 'anaOrder', name: '订单分析', icon: 'finance', desc: '渠道订单量、客单价与订单结构' },
  { id: 'anaCategory', name: '品类分析', icon: 'data', desc: '品类在售 SPU / 销量 / 品效，及新品销售占比' },
  { id: 'anaLogiPre', name: '头程物流分析', icon: 'policy', desc: '服务商单位成本趋势与渠道头程占比趋势' },
  { id: 'anaLogiPost', name: '尾程物流分析', icon: 'policy', desc: '渠道尾程配送成本占比月度趋势' },
  { id: 'anaWarehouse', name: '仓储分析', icon: 'policy', desc: '服务商单位仓储成本趋势与渠道仓储占比趋势' },
  { id: 'anaAdmin', name: '管理费用分析', icon: 'finance', desc: '各部门月度费用发生额与费用类型结构' },
]
export const ANA_IDS = ANA_NAV.map(function (a) { return a.id })
export function anaSubName(id: string): string {
  const it = ANA_NAV.filter(function (a) { return a.id === id })[0]
  return it ? it.name : '渠道效益分析'
}

/* 一级导航（icon 对应 charts.ts 中的 ICONS 键） */
export const NAV: NavItem[] = [
  { id: 'dashboard', name: '经营总览驾驶舱', group: '经营视图', icon: 'dashboard',
    sub: '财务与业务指标全景视图 · 业财联动穿透' },
  { id: 'finance', name: '财务指标', group: '指标体系', icon: 'finance',
    sub: '一级 / 二级财务指标体系 · 目标达成与责任部门' },
  { id: 'business', name: '业务指标', group: '指标体系', icon: 'business',
    sub: '一级 / 二级业务指标体系 · 驱动因子与达成追踪' },
  { id: 'linkage', name: '业财联动关系', group: '指标体系', icon: 'linkage',
    sub: '业务指标 → 财务指标 传导路径与量化影响' },
  { id: 'policy', name: '政策环境', group: '外部环境', icon: 'policy',
    sub: '外部政策 → 业务指标 → 财务指标 的影响识别与影响量化' },
  { id: 'analysis', name: '数据分析', group: '决策支持', icon: 'analysis',
    sub: '渠道效益 / 产品效益 / 流量 / 用户 / 订单 / 品类 / 物流 / 仓储 / 管理费用 多维度分析',
    children: ANA_NAV },
  { id: 'advice', name: '经营建议', group: '决策支持', icon: 'advice',
    sub: '基于指标偏差自动生成的改善动作与财务影响测算' },
  { id: 'keywork', name: '重点工作进度', group: '决策支持', icon: 'keywork',
    sub: '年度重点项目立项 / 进度 / 责任部门 / 财务影响归因' },
  { id: 'data', name: '数据管理', group: '系统', icon: 'data',
    sub: '表格导入 / 手动填写 / 导出 / 指标字典' },
]

/* ------------------------- 持久化接口（替代原 save / load / seed） ------------------------- */
export type SectionKey = 'indicators' | 'biz_dim' | 'policy' | 'advice' | 'keywork'
/** 每个持久化部分对应的状态字段 */
export const SECTION_OF = {
  indicators: 'IND',
  biz_dim: 'BIZ_DIM',
  policy: 'POLICY_EVENTS',
  advice: 'ADVICE_EVENTS',
  keywork: 'KW_TASKS',
} as const satisfies Record<SectionKey, keyof typeof S>

function seedIND(): Indicator[] {
  return SEED_FIN.map(function (o): Indicator { return Object.assign({}, o, { kind: 'fin' as const }) })
    .concat(SEED_BIZ.map(function (o): Indicator { return Object.assign({}, o, { kind: 'biz' as const }) }))
}

/** 等价原 seed()：装入全部示例数据并 recompute */
export function seed(): void {
  S.IND = seedIND()
  S.BIZ_DIM = {}
  S.POLICY_EVENTS = POLICY_SEED.map(function (o) { return Object.assign({}, o) })
  S.ADVICE_EVENTS = ADVICE_SEED.map(function (o) { return Object.assign({}, o) })
  S.KW_TASKS = KW_SEED.map(function (o) { return Object.assign({}, o) })
  recompute()
}

/** 序列化各部分（JSON 深拷贝；indicators 去掉 _ma/_mt/_src 运行期字段，同原 save 的 clean 逻辑） */
export function snapshot(): Record<SectionKey, unknown> {
  const clean = S.IND.map(function (i) {
    const o: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(i)) {
      if (k !== '_ma' && k !== '_mt' && k !== '_src') o[k] = v
    }
    return o
  })
  const json = function (v: unknown): unknown { return JSON.parse(JSON.stringify(v)) }
  return {
    indicators: json(clean),
    biz_dim: json(S.BIZ_DIM),
    policy: json(S.POLICY_EVENTS),
    advice: json(S.ADVICE_EVENTS),
    keywork: json(S.KW_TASKS),
  }
}

function isRecord(x: unknown): x is Record<string, unknown> {
  return typeof x === 'object' && x !== null && !Array.isArray(x)
}
function isIndicator(x: unknown): x is Indicator {
  return isRecord(x) && typeof x.code === 'string' && (x.kind === 'fin' || x.kind === 'biz')
}
function isPolicyEvent(x: unknown): x is PolicyEvent {
  return isRecord(x) && ['time', 'seg', 'desc', 'impact'].every(function (k) { return typeof x[k] === 'string' })
}
function isAdviceEvent(x: unknown): x is AdviceEvent {
  return isRecord(x) && ['time', 'seg', 'desc', 'advice', 'impact'].every(function (k) { return typeof x[k] === 'string' })
}
function isKwTask(x: unknown): x is KwTask {
  return isRecord(x) && ['time', 'cat', 'goal', 'breakdown', 'eta', 'status'].every(function (k) { return typeof x[k] === 'string' }) &&
    typeof x.progress === 'number'
}
function cellNum(v: unknown): number | null {
  return typeof v === 'number' ? v : null
}
/* 维度填报存储：逐层读取，单元格只保留数值型 target / actual */
function toBizDimStore(x: unknown): BizDimStore {
  const out: BizDimStore = {}
  if (!isRecord(x)) return out
  for (const code in x) {
    const a = x[code]
    if (!isRecord(a)) continue
    out[code] = {}
    for (const dk in a) {
      const b = a[dk]
      if (!isRecord(b)) continue
      out[code][dk] = {}
      for (const mb in b) {
        const c = b[mb]
        if (!isRecord(c)) continue
        out[code][dk][mb] = { target: cellNum(c.target), actual: cellNum(c.actual) }
      }
    }
  }
  return out
}

/** 有的部分覆盖、缺的部分用示例数据，然后 recompute。curM / dim 为界面选择，不受影响。 */
export function hydrate(input: Partial<Record<SectionKey, unknown>>): void {
  /* 先做 JSON 深拷贝：引擎会在指标对象上写运行期字段，不能改动调用方传入的数据 */
  const sec: Partial<Record<SectionKey, unknown>> = {}
  for (const k of Object.keys(SECTION_OF) as SectionKey[]) {
    if (input[k] !== undefined) sec[k] = JSON.parse(JSON.stringify(input[k]))
  }
  const ind = Array.isArray(sec.indicators) ? sec.indicators.filter(isIndicator) : []
  S.IND = ind.length ? ind : seedIND()
  S.BIZ_DIM = sec.biz_dim !== undefined ? toBizDimStore(sec.biz_dim) : {}
  S.POLICY_EVENTS = Array.isArray(sec.policy) ? sec.policy.filter(isPolicyEvent) : POLICY_SEED.map(function (o) { return Object.assign({}, o) })
  S.ADVICE_EVENTS = Array.isArray(sec.advice) ? sec.advice.filter(isAdviceEvent) : ADVICE_SEED.map(function (o) { return Object.assign({}, o) })
  S.KW_TASKS = Array.isArray(sec.keywork) ? sec.keywork.filter(isKwTask) : KW_SEED.map(function (o) { return Object.assign({}, o) })
  recompute()
}

/* 当前维度标签 */
export function periodLabel(): string {
  return S.dim === 'year' ? YEAR_LABEL : ('2026年 ' + MONTHS9[S.curM - 1])
}
export function dimLabel(): string { return S.dim === 'year' ? '年度累计达成' : '当月达成' }

/* =========================================================================
   计算引擎（所有取数均基于当前维度视图 CUR）
   ========================================================================= */
export function find(code: string | null | undefined): Indicator | undefined { return S.CUR.find(i => i.code === code) }
export function children(code: string): Indicator[] { return S.CUR.filter(i => i.parent === code) }
export function byKind(k: Kind): Indicator[] { return S.CUR.filter(i => i.kind === k) }
export function l1(k: Kind): Indicator[] { return S.CUR.filter(i => i.kind === k && i.level === 1) }
export function l2(k: Kind): Indicator[] { return S.CUR.filter(i => i.kind === k && i.level === 2) }

/* ---------------------- 月度 / 年度维度模型 ----------------------
   · 发生额型指标（万元 / 单 / 万次）：按月汇总 = 年度累计
   · 比率均值型指标（% / 天 / 元 / 倍 / 分）：按收入权重加权平均 = 年度累计
   月度值由年度累计值确定性地派生，并支持在月度维度下直接编辑：编辑值作为覆盖项写入 _ova / _ovt。
------------------------------------------------------------------- */
export function rnd(v: number, d: number): number { const p = Math.pow(10, d); return Math.round(v * p) / p }
export function hashStr(s: unknown): number {
  let h = 2166136261 >>> 0
  const str = String(s)
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0 }
  return h
}
/* 确定性扰动，取值 -1 ~ 1，用于让月度数据呈现自然波动 */
export function jitOf(seed: string): number { return (hashStr(seed) % 2001) / 1000 - 1 }
/* 指标展示精度 */
export function decOf(i: Indicator | null | undefined): number {
  const u = i && i.unit
  const a = (i && i.actual !== null && i.actual !== undefined && !isNaN(i.actual)) ? Math.abs(i.actual) : 0
  if (u === '万元' || u === '万' || u === '人民币') return 1
  if (u === '%') return a < 10 ? 2 : 1
  if (u === '分' || u === '倍' || u === '万元/人' || u === '次/年' || u === '次') return 1
  /* 单位成本 / 效率类：保留 2 位小数，避免 0.88 被四舍五入为 1 */
  if (u === '元/kg' || u === '元/件' || u === '元/单') return 2
  if (u === '件/单' || u === '款/人' || u === '单/人') return 2
  return 0
}
/* 是否为发生额型（月度可加总） */
export function isFlow(i: Indicator | null | undefined): boolean { const u = i && i.unit; return u === '万元' || u === '人民币' || u === '单' || u === '万次' }

/* 基础月度序列：type 为 "a"（实际）或 "t"（目标） */
export function buildBase(i: Indicator, type: 'a' | 't'): number[] {
  const total = jsNum((type === 'a') ? i.actual : i.target)
  const d = decOf(i)
  if (isFlow(i)) {
    /* 目标：统一按季节权重拆分，不加扰动，保证一级与二级明细月度目标完全勾稽 */
    const amp = (type === 't') ? 0 : 0.14
    const raw = SEASON9.map(function (w, m) {
      return (w / SEASON9_SUM) * total * (1 + amp * jitOf(i.code + '#' + type + '#' + m))
    })
    let s = 0; raw.forEach(function (v) { s += v })
    if (!s) return SEASON9.map(function () { return 0 })
    return raw.map(function (v) { return rnd(v * total / s, d) })
  }
  /* 比率型目标取水平线；比率型实际带轻微改善趋势 + 波动 */
  if (type === 't') return SEASON9.map(function () { return rnd(total, d) })
  const n = SEASON9.length
  const raw = SEASON9.map(function (_w, m) {
    const trend = (i.dir === 1 ? 1 : -1) * ((m / (n - 1)) - 0.5) * 0.09
    return total * (1 + trend + 0.05 * jitOf(i.code + '#' + type + '#' + m))
  })
  let sw = 0, ss = 0
  SEASON9.forEach(function (w, m) { sw += w; ss += raw[m] * w })
  const mean = sw ? ss / sw : 0
  const k = mean ? total / mean : 1
  return raw.map(function (v) { return rnd(v * k, d) })
}

/* 应用手工覆盖后的月度序列 */
export function effectiveMonthly(i: Indicator, type: 'a' | 't'): number[] {
  const base = buildBase(i, type)
  const ov = (type === 'a') ? i._ova : i._ovt
  if (!ov) return base
  const keys = Object.keys(ov).filter(function (k) { return ov[k] !== undefined && ov[k] !== null })
  if (!keys.length) return base
  const d = decOf(i)
  const has = function (m: number): boolean { return ov[m] !== undefined && ov[m] !== null }
  const out = base.slice()
  const total = jsNum((type === 'a') ? i.actual : i.target)
  if (isFlow(i)) {
    let sumOv = 0
    keys.forEach(function (k) { sumOv += ov[k] })
    const remain = total - sumOv
    let wSum = 0
    for (let m = 0; m < 9; m++) { if (!has(m)) wSum += base[m] }
    for (let m = 0; m < 9; m++) { out[m] = has(m) ? ov[m] : (wSum ? rnd(remain * base[m] / wSum, d) : 0) }
  } else {
    let ovS = 0, sw = 0, s = 0
    for (let m = 0; m < 9; m++) {
      const w = SEASON9[m]
      if (has(m)) { ovS += w * ov[m] } else { sw += w; s += w * base[m] }
    }
    const k = (sw && s) ? ((total * SEASON9_SUM) - ovS) / s : 0
    for (let m = 0; m < 9; m++) { out[m] = has(m) ? ov[m] : rnd(base[m] * k, d) }
  }
  /* 发生额型：修正尾差，确保月度合计严格等于年度累计 */
  if (isFlow(i)) {
    let sum = 0; out.forEach(function (v) { sum += v })
    const diff = rnd(total - sum, d)
    if (diff) {
      for (let m = 8; m >= 0; m--) { if (!has(m)) { out[m] = rnd(out[m] + diff, d); break } }
    }
  }
  return out
}

/* 指定月份的达成率（用于业务一级指标的月度汇总） */
export function rateAt(i: Indicator, m: number): number {
  const t = i._mt ? i._mt[m] : i.target
  const a = jsNum(i._ma ? i._ma[m] : i.actual)
  if (!t) return 0
  let r = i.dir === 1 ? (a / t * 100) : (a > 0 ? (t / a * 100) : 0)
  if (!isFinite(r) || r < 0) r = 0
  return Math.min(130, Math.max(0, r))
}

/* 财务二级明细分组：与数据校验中的勾稽分组保持一致 */
export const FIN_GROUPS: { p: string; kids: string[] }[] = [
  { p: 'F1', kids: ['F1.1', 'F1.2', 'F1.3', 'F1.4', 'F1.5'] },
  { p: 'F1', kids: ['F1.6', 'F1.7', 'F1.8'] },
  { p: 'F2', kids: ['F2.1', 'F2.2', 'F2.3', 'F2.4', 'F2.5'] },
  { p: 'F2', kids: ['F2.6', 'F2.7', 'F2.8'] },
  { p: 'F3', kids: ['F3.1', 'F3.2', 'F3.3', 'F3.4', 'F3.5'] },
  { p: 'F3', kids: ['F3.6', 'F3.7', 'F3.8'] },
  { p: 'F4', kids: ['F4.1', 'F4.2', 'F4.3', 'F4.4', 'F4.5', 'F4.7', 'F4.8'] },
  { p: 'F6', kids: ['F6.1'] },
  { p: 'F7', kids: ['F7.4', 'F7.6'] },
]

/* 以一级指标月度形态为基准，按比例分摊到二级明细
   · 可加总分组（明细合计 = 一级）：叠加轻微扰动后由 rakeGroup 双约束校准
   · 不可加总分组：完全跟随一级形态，保持线性关系不失真
   调用方保证 p._ma 已生成 */
export function deriveFromParent(kid: Indicator, p: Indicator, amp: number): number[] {
  const pma = p._ma!
  let colSum = 0
  pma.forEach(function (v) { colSum += v })
  const pMean = colSum / SEASON9.length
  const ref = isFlow(kid) ? (colSum || 1) : (pMean || 1)
  const out: number[] = []
  for (let m = 0; m < 9; m++) {
    const j = amp ? (1 + amp * jitOf(kid.code + '#pf#' + m)) : 1
    out.push(jsNum(kid.actual) * (pma[m] / ref) * j)
  }
  return out
}
/* 双约束迭代校准（Raking）：同时满足
   ① 每月「二级明细合计 = 一级指标当月值」 ② 每个二级指标「月度合计 / 加权平均 = 其累计值」
   调用方保证 kids 的 _ma 已生成 */
export function rakeGroup(kids: Indicator[], parentMonths: number[], additive: boolean): void {
  for (let it = 0; it < 80; it++) {
    if (additive) {
      for (let m = 0; m < 9; m++) {
        let s = 0
        kids.forEach(function (k) { s += k._ma![m] })
        if (s > 0) {
          const f = parentMonths[m] / s
          kids.forEach(function (k) { k._ma![m] = k._ma![m] * f })
        }
      }
    }
    kids.forEach(function (k) {
      if (isFlow(k)) {
        let s = 0; k._ma!.forEach(function (v) { s += v })
        if (s > 0) { const f = jsNum(k.actual) / s; k._ma = k._ma!.map(function (v) { return v * f }) }
      } else {
        let sw = 0, s = 0
        k._ma!.forEach(function (v, m) { sw += SEASON9[m]; s += v * SEASON9[m] })
        const mean = sw ? s / sw : 0
        if (mean > 0) { const f = jsNum(k.actual) / mean; k._ma = k._ma!.map(function (v) { return v * f }) }
      }
    })
  }
  kids.forEach(function (k) { k._ma = k._ma!.map(function (v) { return rnd(v, decOf(k)) }) })
}

/* 构建全部指标的月度实际 / 月度目标序列 */
export function buildMonthlyAll(): void {
  const IND = S.IND
  const byCode: Record<string, Indicator> = {}
  IND.forEach(function (i) { byCode[i.code] = i })

  /* 1) 月度目标序列（发生额型按季节拆分，比率型取水平线） */
  IND.forEach(function (i) { i._mt = effectiveMonthly(i, 't') })

  /* 2) 先算所有一级指标的月度实际序列（业务一级稍后由二级汇总） */
  const autoBizL1 = IND.filter(function (i) { return i.kind === 'biz' && i.level === 1 })
  IND.forEach(function (i) {
    if (i.level === 1 && i.kind === 'biz') return
    i._ma = effectiveMonthly(i, 'a')
  })

  /* 3) 财务二级：按一级月度形态分摊，再做双约束校准 */
  const grouped: Record<string, boolean> = {}
  FIN_GROUPS.forEach(function (g) {
    const p = byCode[g.p]
    if (!p || !p._ma) return
    const kids = g.kids.map(function (c) { return byCode[c] }).filter(function (k) { return !!k })
    if (!kids.length) return
    kids.forEach(function (k) { grouped[k.code] = true })
    let sumA = 0
    kids.forEach(function (k) { sumA += jsNum(k.actual) })
    const additive = Math.abs(sumA - jsNum(p.actual)) / (Math.abs(jsNum(p.actual)) || 1) < 0.15
    kids.forEach(function (k) { k._ma = deriveFromParent(k, p, additive ? 0.10 : 0) })
    rakeGroup(kids, p._ma, additive)
  })
  /* 未纳入分组的财务二级（新增指标）按自身季节形态独立分解 */
  IND.forEach(function (i) {
    if (i.kind !== 'fin' || i.level !== 2 || grouped[i.code]) return
    i._ma = effectiveMonthly(i, 'a')
  })

  /* 4) 手工覆盖项优先（覆盖后仍严格满足该指标自身的累计口径） */
  IND.forEach(function (i) {
    if (i._ova && Object.keys(i._ova).length) i._ma = effectiveMonthly(i, 'a')
  })

  /* 4.5) 口径对齐：存在恒等关系的指标，其月度序列跟随主指标 */
  alignMonthly()

  /* 5) 业务一级指标 = 二级指标月度加权达成率 */
  autoBizL1.forEach(function (i) {
    const kids = IND.filter(function (k) { return k.parent === i.code })
    if (!kids.length) { i._ma = effectiveMonthly(i, 'a'); return }
    const out: number[] = []
    for (let m = 0; m < 9; m++) {
      let sw = 0, s = 0
      kids.forEach(function (k) { const w = k.weight || 1; sw += w; s += rateAt(k, m) * w })
      out.push(sw ? rnd(s / sw, 1) : 0)
    }
    i._ma = out
  })
}

/* 口径对齐（v4）：F3 = F2/F1、F4 = F2 − F1×期间费用合计、F5 = F4/F1、
   F4.9 = Σ费用率、应收/存货/应付余额 = 月收入或月成本 ÷ 30 × 周转天数 */
export function alignMonthly(): void {
  const by: Record<string, Indicator> = {}
  S.IND.forEach(function (i) { by[i.code] = i })
  const ok = function (c: string): boolean {
    const i = by[c]
    return !!(i && i._ma && !(i._ova && Object.keys(i._ova).length))
  }
  const put = function (c: string, fn: (m: number) => number): void {
    if (!ok(c)) return
    const i = by[c]
    i._ma = i._ma!.map(function (_, m) { return rnd(fn(m), decOf(i)) })
  }
  const num = function (v: number | null | undefined): number { return (v === null || v === undefined || isNaN(v)) ? 0 : v }
  const f1 = by.F1, f2 = by.F2, f4 = by.F4
  if (!f1 || !f1._ma) return
  const f1ma = f1._ma
  if (f2 && f2._ma) put('F3', function (m) { return f1ma[m] > 0 ? f2._ma![m] / f1ma[m] * 100 : 0 })
  /* 期间费用合计（不含人力跨科目监测项），任一项未填报按 0 处理 */
  const EX = ['F4.1', 'F4.2', 'F4.3', 'F4.4', 'F4.5', 'F4.7', 'F4.8']
  const exSum = function (m: number): number {
    let s = 0
    EX.forEach(function (c) { const x = by[c]; if (x && x._ma) s += num(x._ma[m]) })
    return s
  }
  /* 净利润月度 = 毛利额 − 期间费用 */
  if (f2 && f2._ma) put('F4', function (m) { return f2._ma![m] - f1ma[m] * exSum(m) / 100 })
  if (f4 && f4._ma) put('F5', function (m) { return f1ma[m] > 0 ? f4._ma![m] / f1ma[m] * 100 : 0 })
  put('F4.9', function (m) { return exSum(m) })
  /* 营运资金余额（期末口径）：月余额 = 当月收入或成本 ÷ 30 × 周转天数 */
  const dso = by['F7.4']
  if (dso && dso._ma && hasData(dso)) put('F7.3', function (m) { return f1ma[m] / 30 * num(dso._ma![m]) })
  const invd = by['F7.6']
  if (invd && invd._ma && hasData(invd) && f2 && f2._ma) put('F7.5', function (m) { return (f1ma[m] - f2._ma![m]) / 30 * num(invd._ma![m]) })
  const dpo = by['F7.8']
  if (dpo && dpo._ma && hasData(dpo) && f2 && f2._ma) put('F7.7', function (m) { return (f1ma[m] - f2._ma![m]) / 30 * num(dpo._ma![m]) })
  /* 分渠道 / 分市场毛利月度派生：F2.x 月度 = F1.x 月度 × F3.x 月度 / 100 */
  const CHAN = [['F2.1', 'F1.1', 'F3.1'], ['F2.2', 'F1.2', 'F3.2'], ['F2.3', 'F1.3', 'F3.3'], ['F2.4', 'F1.4', 'F3.4'], ['F2.5', 'F1.5', 'F3.5'], ['F2.6', 'F1.6', 'F3.6'], ['F2.7', 'F1.7', 'F3.7'], ['F2.8', 'F1.8', 'F3.8']]
  CHAN.forEach(function (p) {
    const fc = by[p[0]], rc = by[p[1]], mr = by[p[2]]
    if (!fc) return
    if (rc && rc._ma && mr && mr._ma) {
      put(p[0], function (m) { return rc._ma![m] * num(mr._ma![m]) / 100 })
    }
    if (rc && rc._mt && mr && mr._mt && fc._mt) {
      fc._mt = fc._mt.map(function (_, m) { return rc._mt![m] * num(mr._mt![m]) / 100 })
    }
  })
}

/* 取指标的年度基准对象（编辑与导入始终写入年度数据） */
export function yearOf<T extends Indicator | null | undefined>(i: T): T | Indicator {
  return (i && i._src) ? i._src : i
}
export function mA(i: Indicator | null | undefined, m: number): number | null { return (i && i._ma) ? i._ma[m] : (i ? i.actual : 0) }
export function mT(i: Indicator | null | undefined, m: number): number | null { return (i && i._mt) ? i._mt[m] : (i ? i.target : 0) }

/* 按当前维度重建视图数组 */
export function syncDim(): void {
  if (S.dim === 'year') { S.CUR = S.IND; return }
  S.CUR = S.IND.map(function (i) {
    const o: Indicator = { ...i }
    o.actual = mA(i, S.curM - 1)
    o.target = mT(i, S.curM - 1)
    o._src = i
    return o
  })
}

/* 月度维度下编辑单元格：写入覆盖项并反算年度累计值 */
export function setMonthOverride(i: Indicator, f: ValueField, m: number, v: number): void {
  const type = (f === 'actual') ? 'a' : 't'
  let ov = (f === 'actual') ? i._ova : i._ovt
  if (!ov) {
    ov = {}
    if (f === 'actual') i._ova = ov; else i._ovt = ov
  }
  /* 首次对该字段设覆盖时，记录原始年度值，便于整体撤销 */
  if (!Object.keys(ov).length) {
    if (f === 'actual' && i._o0a === undefined) i._o0a = i.actual
    if (f === 'target' && i._o0t === undefined) i._o0t = i.target
  }
  const before = effectiveMonthly(i, type)
  const old = before[m]
  if (isFlow(i)) {
    i[f] = rnd(jsNum(i[f]) - old + v, decOf(i))
  } else {
    /* 比率型：年度值为月度加权平均，按当月权重折算变动 */
    i[f] = rnd(jsNum(i[f]) + (v - old) * (SEASON9[m] / SEASON9_SUM), 2)
  }
  /* 通过 i 上的字段再取一次，保证写入的是响应式对象中的覆盖表 */
  const target = (f === 'actual') ? i._ova : i._ovt
  if (target) target[m] = v
}
/* 撤销月度覆盖：某字段的全部覆盖清空后，年度累计值回到原始值 */
export function clearMonthOverride(i: Indicator, m: number): void {
  if (i._ova && i._ova[m] !== undefined) {
    delete i._ova[m]
    if (!Object.keys(i._ova).length) {
      delete i._ova
      if (i._o0a !== undefined) { i.actual = i._o0a; delete i._o0a }
    }
  }
  if (i._ovt && i._ovt[m] !== undefined) {
    delete i._ovt[m]
    if (!Object.keys(i._ovt).length) {
      delete i._ovt
      if (i._o0t !== undefined) { i.target = i._o0t; delete i._o0t }
    }
  }
}
/* 清空全部分子项覆盖（供数据管理页使用） */
export function clearAllMonthlyOverrides(m: number): void {
  S.IND.forEach(function (i) { clearMonthOverride(i, m) })
}

/* 趋势序列（近 6 个月，供驾驶舱与数据分析使用） */
export function refreshTrend(): void {
  const g = function (c: string): Indicator | undefined { return S.IND.filter(function (i) { return i.code === c })[0] }
  const pick = function (c: string): number[] {
    const i = g(c)
    if (!i || !i._ma) return [0, 0, 0, 0, 0, 0]
    return i._ma.slice(TREND_OFFSET, TREND_OFFSET + 6)
  }
  S.TREND.months = MONTHS9.slice(TREND_OFFSET, TREND_OFFSET + 6)
  S.TREND.revenue = pick('F1')
  S.TREND.gross = pick('F3')
  S.TREND.net = pick('F5')
  /* 营销费用率（ACOS 近似口径）= 财务指标 F4.1 营销费用率，直接取月度序列 */
  S.TREND.acos = pick('F4.1')
}

/* 达成率（封顶 130%，逆向指标取 目标/实际）；actual/target 已随维度切换 */
export function rate(i: Indicator | null | undefined): number {
  if (!i || !i.target) return 0
  const a = jsNum(i.actual)
  let r: number
  if (i.dir === 1) { r = a / i.target * 100 } else { r = a > 0 ? (i.target / a * 100) : 0 }
  if (!isFinite(r) || r < 0) r = 0
  return Math.min(130, Math.max(0, r))
}
/* 未封顶达成率，用于偏差展示 */
export function rawRate(i: Indicator | null | undefined): number {
  if (!i || !i.target) return 0
  const a = jsNum(i.actual)
  return i.dir === 1 ? (a / i.target * 100) : (a > 0 ? (i.target / a * 100) : 0)
}
export function devPct(i: Indicator | null | undefined): number {
  if (!i || !i.target) return 0
  return (jsNum(i.actual) - i.target) / i.target * 100
}
/* ------------------------- 业务指标空值口径 -------------------------
   hasData(i) 该指标是否已填报（年度基准口径，与当前维度无关）
   isBlankBiz(i) 业务指标是否仍为空（一级板块看其子项是否全部为空）
   rateText(i) / rateColor(i) 达成率文本与配色（空值显示「—」） */
export function hasData(i: Indicator | null | undefined): boolean {
  if (!i) return false
  const y = yearOf(i)
  return (y.actual !== null && y.actual !== undefined && !isNaN(y.actual))
}
export function isBlankBiz(i: Indicator | null | undefined): boolean {
  if (!i || i.kind !== 'biz') return false
  if (i.level === 1) {
    const kids = children(i.code)
    if (!kids.length) return !hasData(i)
    return kids.every(function (k) { return !hasData(k) })
  }
  return !hasData(i)
}
export function rateText(i: Indicator | null | undefined): string {
  if (!hasData(i) || isBlankBiz(i) || !i || !i.target) return '—'
  return fmt(rate(i), 0) + '%'
}
export function rateColor(i: Indicator | null | undefined): string {
  if (!hasData(i) || isBlankBiz(i) || !i || !i.target) return 'var(--text-3)'
  return healthColor(rate(i))
}
/* 已填报的二级指标数 / 总数（用于板块进度展示） */
export function bizFilledStat(boardCode: string): { filled: number; total: number } {
  const kids = children(boardCode)
  let n = 0
  kids.forEach(function (k) { if (hasData(k)) n++ })
  return { filled: n, total: kids.length }
}
/* 维度标签：标注该指标需按渠道 / 品类 / 线路 / 服务商分列，并显示维度单元格填报进度
   （原样返回 HTML 片段，内容全部来自常量与计数，无用户输入） */
export function dimTag(i: Indicator): string {
  const dks = i.dims || []
  if (!dks.length || i.kind !== 'biz') return ''
  const parts: string[] = []
  let t = 0
  dks.forEach(function (dk) {
    const D = BIZ_DIMS[dk]
    if (!D) return
    parts.push(D.label)
    t += D.members.length
  })
  if (!parts.length) return ''
  const n = bizDimFilled(i.code)
  const done = (t > 0 && n >= t)
  return ' <span class="tag" style="background:' + (done ? '#e8f5ee' : '#fff5e6') + ';color:' + (done ? '#0f9d58' : '#b26a00') +
    ';border-color:transparent" title="需分' + parts.join(' / ') + '列示，已填报 ' + n + ' / ' + t +
    ' 个维度单元格（可在本页矩阵或「数据管理」导入）">分' + parts.join('/') + ' ' + n + '/' + t + '</span>'
}

/* 业务一级 = 二级加权达成率自动汇总（按年度口径重算）；财务一级保留手工录入 */
export function recompute(): void {
  S.CUR = S.IND /* 汇总必须在年度口径下进行 */
  const IND = S.IND

  /* -1) 财务派生指标同步【勾稽闭环】（年度基准口径，改一处全站重算）
     F4.9 期间费用合计 = 七项费用率之和（不含 F4.6 人力跨科目监测）；
     F7.3 应收账款 = 收入 ÷ 365 × 应收周转天数；F7.5 存货 / F7.7 应付同理；
     任一驱动量未填报时派生值置空（显示「—」），不参与达成率与汇总。 */
  ;(function () {
    const Y = function (c: string): Indicator | null { const i = IND.filter(function (x) { return x.code === c })[0]; return i ? yearOf(i) : null }
    const num = function (v: number | null | undefined): number | null { return (v === null || v === undefined || isNaN(v)) ? null : v }
    const f1 = Y('F1'), f2 = Y('F2')
    const EX = ['F4.1', 'F4.2', 'F4.3', 'F4.4', 'F4.5', 'F4.7', 'F4.8']
    const f49 = Y('F4.9')
    if (f49) {
      let sa = 0, st = 0, okA = true, okT = true
      EX.forEach(function (c) {
        const x = Y(c); if (!x) return
        if (num(x.actual) === null) okA = false; else sa += jsNum(x.actual)
        if (num(x.target) === null) okT = false; else st += jsNum(x.target)
      })
      f49.actual = okA ? rnd(sa, 2) : null
      f49.target = okT ? rnd(st, 2) : null
    }
    const dso = Y('F7.4'), ar = Y('F7.3')
    if (ar) {
      ar.actual = (f1 && dso && num(f1.actual) !== null && num(dso.actual) !== null) ? rnd(jsNum(f1.actual) * jsNum(dso.actual) / 365, 1) : null
      ar.target = (f1 && dso && num(f1.target) !== null && num(dso.target) !== null) ? rnd(jsNum(f1.target) * jsNum(dso.target) / 365, 1) : null
    }
    const costA = (f1 && f2 && num(f1.actual) !== null && num(f2.actual) !== null) ? (jsNum(f1.actual) - jsNum(f2.actual)) : null
    const costT = (f1 && f2 && num(f1.target) !== null && num(f2.target) !== null) ? (jsNum(f1.target) - jsNum(f2.target)) : null
    const invd = Y('F7.6'), inv = Y('F7.5')
    if (inv) {
      inv.actual = (costA !== null && invd && num(invd.actual) !== null) ? rnd(costA * jsNum(invd.actual) / 365, 1) : null
      inv.target = (costT !== null && invd && num(invd.target) !== null) ? rnd(costT * jsNum(invd.target) / 365, 1) : null
    }
    const dpo = Y('F7.8'), ap = Y('F7.7')
    if (ap) {
      ap.actual = (costA !== null && dpo && num(dpo.actual) !== null) ? rnd(costA * jsNum(dpo.actual) / 365, 1) : null
      ap.target = (costT !== null && dpo && num(dpo.target) !== null) ? rnd(costT * jsNum(dpo.target) / 365, 1) : null
    }
  })()

  /* -0.5) 分渠道 / 分市场毛利派生（与净销售额 F1 二级分类一一对应）
     F2.x = F1.x × F3.x / 100；任一驱动量未填报 → 派生置空；手工编辑过的（_chanEdited）保留用户值。 */
  ;(function () {
    const Y2 = function (c: string): Indicator | null { const i = IND.filter(function (x) { return x.code === c })[0]; return i ? yearOf(i) : null }
    const num2 = function (v: number | null | undefined): number | null { return (v === null || v === undefined || isNaN(v)) ? null : v }
    const CHAN = [['F2.1', 'F1.1', 'F3.1'], ['F2.2', 'F1.2', 'F3.2'], ['F2.3', 'F1.3', 'F3.3'], ['F2.4', 'F1.4', 'F3.4'], ['F2.5', 'F1.5', 'F3.5'], ['F2.6', 'F1.6', 'F3.6'], ['F2.7', 'F1.7', 'F3.7'], ['F2.8', 'F1.8', 'F3.8']]
    CHAN.forEach(function (p) {
      const fc = Y2(p[0]), rc = Y2(p[1]), mr = Y2(p[2])
      if (!fc) return
      if (fc._chanEdited) return
      fc.actual = (rc && mr && num2(rc.actual) !== null && num2(mr.actual) !== null) ? rnd(jsNum(rc.actual) * jsNum(mr.actual) / 100, 1) : null
      fc.target = (rc && mr && num2(rc.target) !== null && num2(mr.target) !== null) ? rnd(jsNum(rc.target) * jsNum(mr.target) / 100, 1) : null
    })
  })()

  /* 0) 维度填报值 → 指标整体值【勾稽闭环】
     按「加总型单位求和、比率型单位算术平均」聚合为指标整体值，自动回填到年度值；
     手工直接填报的指标值优先级更高（_dimAgg 标记区分）。 */
  IND.forEach(function (i) {
    if (i.kind !== 'biz' || i.level !== 2) return
    const dks = i.dims || []
    if (!dks.length) return
    let aggA: number | null = null, aggT: number | null = null
    dks.forEach(function (dk) {
      const a = bizDimAgg(i.code, dk, 'actual')
      const t = bizDimAgg(i.code, dk, 'target')
      if (a !== null) aggA = (aggA === null) ? a : aggA + a
      if (t !== null) aggT = (aggT === null) ? t : aggT + t
    })
    if (aggA === null && aggT === null) {
      /* 维度单元格全部清空 → 撤销此前的维度派生值，回到待填报状态 */
      if (i._dimAgg) { delete i._dimAgg; i.actual = null; i.target = null }
      return
    }
    if (i._dimAgg || i.actual === null || i.actual === undefined) {
      i._dimAgg = true
      i.actual = (aggA === null) ? null : rnd(aggA, decOf(i))
      i.target = (aggT === null) ? null : rnd(aggT, decOf(i))
    }
  })

  l1('biz').forEach(p => {
    const kids = children(p.code)
    if (!kids.length) return
    let sw = 0, s = 0, n = 0
    kids.forEach(function (k) {
      if (!hasData(k) || !k.target) return
      const w = k.weight || 1; sw += w; s += rate(k) * w; n++
    })
    if (n && sw) {
      p.actual = Number((s / sw).toFixed(1))
      p.target = 100
    } else {
      p.actual = null /* 无任何子项数据 → 板块不参与汇总，显示「—」 */
      p.target = null
    }
  })
  buildMonthlyAll()
  refreshTrend()
  syncDim() /* 回到当前维度视图 */
}
export function weightedRate(list: Indicator[]): number | null {
  let sw = 0, s = 0
  list.forEach(function (i) {
    if (!hasData(i) || !i.target) return /* 未填报指标不参与加权，避免被当作 0 拉低 */
    const w = i.weight || 1; sw += w; s += rate(i) * w
  })
  return sw ? s / sw : null
}
export function finHealth(): number | null { return weightedRate(l1('fin')) }
export function bizHealth(): number | null { return weightedRate(l1('biz')) }
/* 综合健康度：业务指标未填报时，仅按财务指标计算，不因缺数被拉低 */
export function overallHealth(): number | null {
  const f = finHealth(), b = bizHealth()
  if (f === null && b === null) return null
  if (f === null) return b
  if (b === null) return f
  return (f + b) / 2
}

export function healthColor(v: number): string {
  if (v >= 100) return C.down
  if (v >= 90) return '#3b82f6'
  if (v >= 80) return C.warn
  return C.up
}
export function grade(v: number): { g: string; c: string } {
  if (v >= 110) return { g: 'S', c: '#0d9488' }
  if (v >= 100) return { g: 'A', c: '#0f9d58' }
  if (v >= 90) return { g: 'B', c: '#2563eb' }
  if (v >= 80) return { g: 'C', c: '#e08600' }
  return { g: 'D', c: '#d9251d' }
}
export function fmt(n: number | null | undefined, d?: number): string {
  if (n === null || n === undefined || isNaN(n)) return '-'
  let dd = d
  if (dd === undefined) {
    const a = Math.abs(n)
    dd = a >= 1000 ? 0 : (a >= 100 ? 1 : 2)
  }
  return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: dd, maximumFractionDigits: dd })
}
export function pct(n: number | null | undefined, d?: number): string { return (n === null || n === undefined || isNaN(n)) ? '-' : fmt(n, d === undefined ? 1 : d) + '%' }
export function deptOf(i: Indicator): string { return (i.depts && i.depts.length) ? i.depts.join(' / ') : '-' }
const ESC_MAP: Record<string, string> = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }
export function esc(s: unknown): string {
  return String(s == null ? '' : s).replace(/[&<>"']/g, m => ESC_MAP[m])
}

/* 数据一致性校验（随维度切换：年度口径阈值严格，月度口径考虑各科目季节性分布差异） */
export function validations(): ValidationItem[] {
  const out: ValidationItem[] = []
  const push = (state: 'ok' | 'warn', title: string, detail: string) => out.push({ state: state, title: title, detail: detail })
  const scope = S.dim === 'month' ? '〔' + periodLabel() + '〕' : '〔年度累计〕'
  const K = S.dim === 'month' ? 8 : 1
  const checks: { p: string; kids: string[]; label: string; tolerance?: number; base?: string }[] = [
    { p: 'F1', kids: ['F1.1', 'F1.2', 'F1.3', 'F1.4', 'F1.5'], label: '净销售额 一级 vs 渠道二级合计' },
    { p: 'F1', kids: ['F1.6', 'F1.7', 'F1.8'], label: '净销售额 一级 vs 市场二级合计' },
    { p: 'F2', kids: ['F2.1', 'F2.2', 'F2.3', 'F2.4', 'F2.5'], label: '毛利额 一级 vs 渠道二级合计（派生对照）', tolerance: 3 },
    { p: 'F2', kids: ['F2.6', 'F2.7', 'F2.8'], label: '毛利额 渠道合计 vs 市场合计（交叉勾稽）', tolerance: 3, base: 'F2G' },
    { p: 'F4.9', kids: ['F4.1', 'F4.2', 'F4.3', 'F4.4', 'F4.5', 'F4.7', 'F4.8'], label: '期间费用合计 vs 七项费用率加总（不含人力监测项）' },
  ]
  checks.forEach(ck => {
    const P = find(ck.p); if (!P) return
    let s = 0, miss = false
    ck.kids.forEach(k => { const c = find(k); if (c) s += jsNum(c.actual); else miss = true })
    if (miss) return
    /* base 支持：交叉勾稽时基准 = 另一维度组合的合计（如毛利额渠道合计 vs 市场合计） */
    let baseV = jsNum(P.actual), baseLbl = '一级 ' + fmt(P.actual)
    if (ck.base === 'F2G') {
      let g = 0, gm = false
      ;['F2.1', 'F2.2', 'F2.3', 'F2.4', 'F2.5'].forEach(k => { const c = find(k); if (c) g += jsNum(c.actual); else gm = true })
      if (gm) return
      baseV = g; baseLbl = '渠道合计 ' + fmt(g)
    }
    const diff = baseV - s
    const base = Math.abs(jsNum(P.actual)) || 1
    const d = Math.abs(diff) / base * 100
    const tol = (ck.tolerance !== undefined) ? ck.tolerance : 1.5
    push(d < tol * K ? 'ok' : 'warn', scope + ck.label,
      baseLbl + ' ｜ 明细合计 ' + fmt(s) + ' ｜ 偏差 ' + (diff >= 0 ? '+' : '') + fmt(diff) + '（' + d.toFixed(1) + '%）')
  })
  const F1 = find('F1'), F2 = find('F2'), F3 = find('F3'), F4 = find('F4'), F5 = find('F5')
  const F49 = find('F4.9'), F73 = find('F7.3'), F74 = find('F7.4'), F75 = find('F7.5'), F76 = find('F7.6')
  if (F1 && F2 && F3) {
    const calc = jsNum(F1.actual) * jsNum(F3.actual) / 100
    const d = Math.abs(jsNum(F2.actual) - calc) / (Math.abs(jsNum(F2.actual)) || 1) * 100
    push(d < 3 * K ? 'ok' : 'warn', scope + '毛利额 与「收入 × 毛利率」交叉验证',
      '毛利额 ' + fmt(F2.actual) + ' ｜ 推算 ' + fmt(calc) + ' ｜ 偏差 ' + d.toFixed(1) + '%')
  }
  if (F1 && F3 && F4 && F5 && F49) {
    const calc = jsNum(F1.actual) * (jsNum(F3.actual) - jsNum(F49.actual)) / 100
    const d = Math.abs(jsNum(F4.actual) - calc) / (Math.abs(jsNum(F4.actual)) || 1) * 100
    push(d < 8 * K ? 'ok' : 'warn', scope + '净利润 与「收入 ×（毛利率 − 期间费用合计）」交叉验证',
      '净利润 ' + fmt(F4.actual) + ' ｜ 推算 ' + fmt(calc) + ' ｜ 偏差 ' + d.toFixed(1) + '%')
  }
  if (F1 && F4 && F5 && F5.target) {
    const calc = jsNum(F1.actual) > 0 ? jsNum(F4.actual) / jsNum(F1.actual) * 100 : 0
    const d = Math.abs(jsNum(F5.actual) - calc) / (Math.abs(jsNum(F5.actual)) || 1) * 100
    push(d < 3 * K ? 'ok' : 'warn', scope + '净利润率 与「净利润 ÷ 收入」交叉验证',
      '净利润率 ' + pct(F5.actual) + ' ｜ 推算 ' + pct(calc) + ' ｜ 偏差 ' + d.toFixed(1) + '%')
  }
  if (F1 && F73 && F74) {
    const calc = jsNum(F1.actual) * jsNum(F74.actual) / 365
    const d = Math.abs(jsNum(F73.actual) - calc) / (Math.abs(calc) || 1) * 100
    push(d < 3 * K ? 'ok' : 'warn', scope + '应收账款 与「收入 ÷ 365 × 周转天数」交叉验证',
      '应收账款 ' + fmt(F73.actual) + ' ｜ 推算 ' + fmt(calc) + ' ｜ 偏差 ' + d.toFixed(1) + '%')
  }
  if (F1 && F2 && F75 && F76) {
    const calc = (jsNum(F1.actual) - jsNum(F2.actual)) * jsNum(F76.actual) / 365
    const d = Math.abs(jsNum(F75.actual) - calc) / (Math.abs(calc) || 1) * 100
    push(d < 3 * K ? 'ok' : 'warn', scope + '存货 与「营业成本 ÷ 365 × 周转天数」交叉验证',
      '存货 ' + fmt(F75.actual) + ' ｜ 推算 ' + fmt(calc) + ' ｜ 偏差 ' + d.toFixed(1) + '%')
  }
  if (S.dim === 'month') {
    push('ok', scope + '月度 — 年度口径勾稽',
      '本页所有数值为 ' + periodLabel() + ' 的月度口径；发生额型指标「月度合计 = 年度累计」，比率型指标「按月加权平均 = 年度累计」，可在数据管理页导出月度明细核对。')
  }
  return out
}

/* ------------------------- 部门绩效 ------------------------- */
export interface DeptScore { dept: string; score: number | null; items: Indicator[]; finItems: Indicator[]; bizItems: Indicator[] }
export function deptScores(): DeptScore[] {
  return DEPTS.map(function (d) {
    const items = S.IND.filter(i => i.level === 2 && i.depts && i.depts.indexOf(d) >= 0)
    const score = items.length ? weightedRate(items) : null
    return {
      dept: d, score: score, items: items,
      finItems: items.filter(i => i.kind === 'fin'),
      bizItems: items.filter(i => i.kind === 'biz'),
    }
  })
}

/* =========================================================================
   以下为原视图区中的纯计算辅助
   ========================================================================= */

/* ---------- 环比 / 同比（财务明细专用） ----------
   去年基准：加总型按增速回推（Σ二级 = 一级，自动勾稽），比率型按 pt 变化回推、天数型按改善天数回推；
   仅用于展示，不写回指标数据。 */
export function prevYearOf(i: Indicator): number | null {
  const a = (i.actual === null || i.actual === undefined) ? null : i.actual
  if (a === null) return null
  let base = i
  if (i.level === 2) { const p = find(i.parent); if (p) base = p }
  if (i.unit === '%') {
    const PT: Record<string, number> = { F3: -1.2, F4: 0.6, F5: -1.4, F6: -2.0 }
    const pt = (PT[base.code] !== undefined) ? PT[base.code] : -1.0
    return rnd(a + pt, 2)
  }
  if (i.unit === '天') {
    return rnd(a + 1.5, 1) /* 去年周转天数多 1.5 天（今年改善） */
  }
  const GROW: Record<string, number> = { F1: 0.15, F2: 0.18, F4: 0.25, F7: 0.12 }
  const g = (GROW[base.code] !== undefined) ? GROW[base.code] : 0.10
  return rnd(a / (1 + g), 2)
}
export function momYoyOf(i: Indicator): { mom: number | null; yoy: number | null } {
  const src = yearOf(i)
  const py = prevYearOf(src)
  let yoy: number | null = null, mom: number | null = null
  if (S.dim === 'month' && src._ma) {
    const m = S.curM - 1
    const cur = src._ma[m]
    if (m > 0) {
      const pv = src._ma[m - 1]
      if (cur !== null && pv) mom = (cur - pv) / Math.abs(pv) * 100
    }
    if (cur !== null && py) {
      /* 去年同月：加总型按季节权重分摊；比率 / 天数型取去年年度值 */
      const pmo = (i.unit === '%' || i.unit === '天') ? py : py * SEASON9[m] / SEASON9_SUM
      if (pmo) yoy = (cur - pmo) / Math.abs(pmo) * 100
    }
  } else {
    const cur = src.actual
    if (cur !== null && cur !== undefined && py) {
      yoy = (cur - py) / Math.abs(py) * 100
    }
  }
  return { mom: (mom === null || isNaN(mom)) ? null : mom, yoy: (yoy === null || isNaN(yoy)) ? null : yoy }
}

/* 某个维度成员在若干指标上的加权达成率（行视角） */
export function memberRate(codes: string[], dimKey: string, member: string): number | null {
  let sw = 0, sum = 0
  codes.forEach(function (code) {
    const it = find(code)
    if (!it || !it.weight) return
    const c = bizDimOf(code, dimKey, member)
    if (c.actual === null || c.actual === undefined || !c.target) return
    let r = it.dir === -1 ? (c.actual > 0 ? c.target / c.actual * 100 : 0) : c.actual / c.target * 100
    r = Math.min(130, Math.max(0, r))
    sw += it.weight; sum += r * it.weight
  })
  return sw ? sum / sw : null
}

/* 反向归因：从财务缺口出发定位业务动因。
   bizState(code) 输出「指标名（实际 / 目标）」或「指标名（待填报）」 */
export function bizState(code: string): string {
  const i = find(code)
  if (!i) return '—'
  const sep = /[%）]$/.test(i.name) ? ' ' : ''
  if (!hasData(i)) return i.name + '（待填报）'
  return i.name + '（' + fmt(i.actual) + i.unit + sep + ' / 目标 ' + fmt(i.target) + i.unit + '）'
}
export interface ReverseItem { fin: string; biz: string; dept: string; gap: string }
export function buildReverse(): ReverseItem[] {
  const rev = jsNum((find('F1') || { actual: 0 }).actual) || 0
  const g = function (c: string): { actual: number | null; target: number | null; name: string; unit: string } { return find(c) || { actual: 0, target: 0, name: c, unit: '' } }
  const A = function (c: string): number { return jsNum(g(c).actual) }
  const T = function (c: string): number { return jsNum(g(c).target) }
  const gapOf = function (c: string): number { return Math.max(0, T(c) - A(c)) }
  const items: ReverseItem[] = [
    { fin: '毛利率缺口 ' + fmt(gapOf('F3'), 1) + 'pt（损失约 ' + fmt(rev * gapOf('F3') / 100, 0) + ' 万元）',
      biz: bizState('S3.3') + ' ＋ ' + bizState('S1.4') + ' ＋ 平台渠道毛利率偏低（' + pct((A('F3.1') + A('F3.2') + A('F3.3') + A('F3.4')) / 4) + '）',
      dept: '供应中心 / 运营部 / 产品作战部',
      gap: '采购端每补足 1pt 降本率 ≈ 毛利 +' + fmt(rev * 0.67 / 100, 0) + ' 万元；营业成本占收入 ' + fmt(100 - A('F3'), 1) + '%' },
    { fin: '期间费用率超标 ' + fmt(gapOf('F4'), 1) + 'pt（多支出约 ' + fmt(rev * gapOf('F4') / 100, 0) + ' 万元）',
      biz: bizState('S1.5') + ' ＋ ' + bizState('S1.10') + ' ＋ ' + bizState('S4.3') + ' ＋ ' + bizState('S4.4'),
      dept: '运营部 / 市场部 / 物流物控部',
      gap: '营销费用率超标 ' + fmt(A('F4.1') - T('F4.1'), 1) + 'pt、物流费用合计超标 ' + fmt((A('F4.3') - T('F4.3')) + (A('F4.4') - T('F4.4')) + (A('F4.5') - T('F4.5')), 1) + 'pt 为主因' },
    { fin: '经营净现金流缺口 ' + fmt(gapOf('F7'), 0) + ' 万元',
      biz: '存货周转天数超目标 ' + fmt(Math.max(0, A('F7.6') - T('F7.6')), 0) + ' 天 ＋ ' + bizState('S4.6') + ' ＋ ' + bizState('S4.9'),
      dept: '物流物控部 / 供应中心 / 产品作战部',
      gap: '周转天数降至目标可释放现金约 ' + fmt(Math.max(0, A('F7.6') - T('F7.6')) * rev * 0.67 / 365, 0) + ' 万元' },
    { fin: '净利润达成率仅 ' + fmt(rate(find('F4')), 0) + '%（缺口 ' + fmt(gapOf('F4'), 0) + ' 万元）',
      biz: bizState('S4.8') + ' ＋ ' + bizState('S3.5') + ' ＋ ' + bizState('S1.7'),
      dept: '产品作战部 / 物流物控部 / 市场部',
      gap: '有货率每 +1pt ≈ 收入 ' + fmt(rev / 100 * 0.5, 0) + ' 万元；质检合格率每 +1pt ≈ 减少返工与退货损失 30 万元' },
    { fin: '应收账款周转天数超目标 ' + fmt(A('F7.4') - T('F7.4'), 0) + ' 天',
      biz: '应收账期偏长（' + fmt(A('F7.4'), 0) + ' 天）＋ ' + bizState('S4.6'),
      dept: '财务部 / 运营部',
      gap: '账期降至目标可释放资金约 ' + fmt(Math.max(0, A('F7.4') - T('F7.4')) * rev / 365, 0) + ' 万元' },
  ]
  return items
}

/* ---------- 数据分析小工具 ---------- */
/* fn(m) 在 m = 0..8 上的取值序列 */
export function mSeries<T>(fn: (m: number) => T): T[] { const o: T[] = []; for (let m = 0; m < 9; m++) o.push(fn(m)); return o }
/* 渠道 / 品类统一配色 */
export const CH_COLOR: Record<string, string> = {}; CHANNELS.forEach(function (c, i) { CH_COLOR[c] = PAL[i % PAL.length] })
export const CAT_COLOR: Record<string, string> = {}; CATEGORIES.forEach(function (c, i) { CAT_COLOR[c] = PAL[i % PAL.length] })
export const PROV_COLOR = ['#2563eb', '#0d9488', '#7c3aed', '#e08600', '#0ea5e9', '#d9251d']
export function provColor(i: number): string { return PROV_COLOR[i % PROV_COLOR.length] }
export const G = '#0f9d58', R = '#d9251d', Y = '#e08600' /* 绿 = 优 / 红 = 劣 */

/* =========================================================================
   管理费用分析：各部门月度费用发生额 × 费用类型
     管理费用池 = 营业收入 F1 × F4.7 管理费用率；部门 / 费用类型仅提供分摊权重：Σ部门 ≡ Σ类型 ≡ 管理费用池
     月度拆分：当月池 = 当月收入 × 当月费率，再整体归一校准，使 1-9 月合计精确等于年度池
   ========================================================================= */
/* 费用类型（顺序即表头顺序；mix 数组与之逐位对应） */
export const ADMIN_TYPES = [
  { name: '职工薪酬及社保', w: 0.52 },
  { name: '办公及场地费', w: 0.14 },
  { name: '折旧与摊销', w: 0.08 },
  { name: '差旅费', w: 0.07 },
  { name: '中介服务费', w: 0.06 },
  { name: '测试与合规费', w: 0.09 },
  { name: '其他管理费用', w: 0.04 },
]
/* 部门权重（合计 = 1）+ 各部门费用类型结构 mix（每位合计 = 1） */
export const ADMIN_DEPTS = [
  { name: '总经办', w: 0.14, mix: [0.55, 0.12, 0.10, 0.10, 0.05, 0.03, 0.05] },
  { name: '人力资源部', w: 0.20, mix: [0.72, 0.10, 0.04, 0.04, 0.03, 0.02, 0.05] },
  { name: '财务部', w: 0.17, mix: [0.58, 0.08, 0.05, 0.05, 0.16, 0.02, 0.06] },
  { name: '信息数字化部', w: 0.12, mix: [0.60, 0.06, 0.16, 0.02, 0.04, 0.02, 0.10] },
  { name: '项目管理部', w: 0.09, mix: [0.62, 0.10, 0.04, 0.12, 0.04, 0.03, 0.05] },
  { name: '运营部', w: 0.10, mix: [0.55, 0.14, 0.06, 0.09, 0.03, 0.08, 0.05] },
  { name: '供应中心', w: 0.07, mix: [0.52, 0.12, 0.05, 0.13, 0.03, 0.10, 0.05] },
  { name: '产品作战部', w: 0.06, mix: [0.54, 0.12, 0.05, 0.10, 0.03, 0.11, 0.05] },
  { name: '物流物控部', w: 0.05, mix: [0.56, 0.12, 0.06, 0.10, 0.03, 0.07, 0.06] },
]
export const ADMIN_D_COLOR: Record<string, string> = {}; ADMIN_DEPTS.forEach(function (d, i) { ADMIN_D_COLOR[d.name] = PAL[i % PAL.length] })
export const ADMIN_T_COLOR: Record<string, string> = {}; ADMIN_TYPES.forEach(function (t, i) { ADMIN_T_COLOR[t.name] = PAL[i % PAL.length] })

/* 年度管理费用池（始终取年度基准，与维度切换无关） */
export function adminAnnualPool(): number {
  const f1 = find('F1'), f43 = find('F4.7')
  const a1 = f1 ? yearOf(f1).actual : 0, a3 = f43 ? yearOf(f43).actual : 0
  return jsNum(a1) * jsNum(a3) / 100
}
/* 月度管理费用池（归一校准：9 个月合计 ≡ 年度池） */
export function adminPoolByM(): number[] {
  const annual = adminAnnualPool()
  const raw: number[] = [], pool: number[] = []
  let s = 0
  for (let m = 0; m < 9; m++) {
    const v = jsNum(iv('F1', m)) * jsNum(iv('F4.7', m)) / 100
    raw.push(v); s += v
  }
  const f = s > 0 ? annual / s : 1
  for (let m = 0; m < 9; m++) pool.push(raw[m] * f)
  return pool
}
/* 部门份额（确定性月度波动后归一化，每月合计 = 100%） */
export function adminDeptShares(m?: number | null): number[] {
  const js = ADMIN_DEPTS.map(function (d) { return d.w * wave('adm-' + d.name, 0.10)(m) })
  const tot = js.reduce(function (a, b) { return a + b }, 0) || 1
  return js.map(function (v) { return v / tot })
}
/* 部门 × 费用类型 发生额矩阵：m = 0~8 取当月；m = null 取年度累计；全部行 × 列总计 = 当期管理费用池 */
export interface AdminRow { dept: string; types: number[]; total: number }
export function adminMatrix(m?: number | null): AdminRow[] {
  const pool = (m === null || m === undefined) ? adminAnnualPool() : adminPoolByM()[m]
  const ds = adminDeptShares(m)
  return ADMIN_DEPTS.map(function (d, i) {
    const tw = d.mix.map(function (w, t) { return w * wave('admx-' + ADMIN_TYPES[t].name, 0.07)(m) })
    const tt = tw.reduce(function (a, b) { return a + b }, 0) || 1
    const types = tw.map(function (v) { return pool * ds[i] * v / tt })
    return { dept: d.name, types: types, total: types.reduce(function (a, b) { return a + b }, 0) }
  })
}
/* 当前维度下的快照矩阵：年度 = 年度累计；月度 = 选中月份 */
export function adminMatrixNow(): AdminRow[] {
  return (S.dim === 'month') ? adminMatrix(S.curM - 1) : adminMatrix(null)
}

/* 目标市场拆解：按当前维度的营业收入等比例缩放，保证与 F1 勾稽一致 */
export function marketsNow(): { label: string; value: number; color: string }[] {
  const base = MARKETS.reduce(function (a, m) { return a + m[1] }, 0) || 1
  const f1 = find('F1')
  const k = (f1 && base) ? (jsNum(f1.actual) / base) : 1
  return MARKETS.map(function (m, idx) { return { label: m[0], value: rnd(m[1] * k, 1), color: PAL[idx] } })
}

/* =========================================================================
   数据管理：导入 / 导出（纯函数部分）
   ========================================================================= */
export function parseTable(text: string): string[][] {
  text = String(text).replace(/^﻿/, '').replace(/\r\n?/g, '\n')
  const lines = text.split('\n').filter(function (l) { return l.trim().length })
  if (!lines.length) return []
  const dTab = (lines[0].match(/\t/g) || []).length
  const dCom = (lines[0].match(/,/g) || []).length
  const delim = dTab >= dCom ? '\t' : ','
  return lines.map(function (l) {
    return l.split(delim).map(function (s) { return s.trim().replace(/^"(.*)"$/, '$1') })
  })
}

export type HeaderKey = 'code' | 'name' | 'target' | 'actual' | 'weight' | 'dept' | 'unit' | 'dir' | 'dim' | 'month'
export type HeaderIndex = Partial<Record<HeaderKey, number>>
export function mapHeader(h: string[]): HeaderIndex {
  const idx: HeaderIndex = {}
  h.forEach(function (c, i) {
    const k = String(c).toLowerCase().replace(/\s/g, '')
    if (idx.code === undefined && /^(编码|code|指标编码|编号)$/.test(k)) idx.code = i
    else if (idx.name === undefined && /(指标名称|名称|name)/.test(k)) idx.name = i
    else if (idx.target === undefined && /(目标值|目标|target)/.test(k)) idx.target = i
    else if (idx.actual === undefined && /(实际值|实际|actual|完成值|本期值)/.test(k)) idx.actual = i
    else if (idx.weight === undefined && /(权重|weight)/.test(k)) idx.weight = i
    else if (idx.dept === undefined && /(责任部门|部门|dept|department)/.test(k)) idx.dept = i
    else if (idx.unit === undefined && /(单位|unit)/.test(k)) idx.unit = i
    else if (idx.dir === undefined && /(方向|dir|正逆)/.test(k)) idx.dir = i
    else if (idx.dim === undefined && /^(维度|维度成员|维度值|维度名称|成员|member|dim)$/.test(k)) idx.dim = i
    else if (idx.month === undefined && /^(月份|月度|month|数据月份|期间月份)$/.test(k)) idx.month = i
  })
  return idx
}

/* 解析月份文本：支持 “9”、“09月”、“2026年9月”、“2026-09” */
export function monthIndex(s: unknown): number {
  const str = String(s == null ? '' : s).trim()
  if (!str) return -1
  if (/^(年度|全年|年度累计|累计|年)$/.test(str)) return -1
  const m = str.match(/(\d{1,2})\s*月?\s*$/)
  if (!m) return -1
  const n = parseInt(m[1], 10)
  return (n >= 1 && n <= 9) ? (n - 1) : -1
}

export function looksLikeHeader(row: string[]): boolean {
  const s = row.join('').toLowerCase()
  return /编码|指标|名称|code|name|目标|实际|target|actual/.test(s)
}

/* 维度成员 → 维度键：仅当该指标声明了对应维度、且成员名在维度成员清单内时命中 */
export function pickDimKey(it: Indicator | null | undefined, member: string): string | null {
  const dks = (it && it.dims) || []
  for (let i = 0; i < dks.length; i++) {
    const D = BIZ_DIMS[dks[i]]
    if (D && D.members.indexOf(member) >= 0) return dks[i]
  }
  return null
}

export interface ImportResult { updated: number; notfound: number; total: number; monthly: number; dim: number; dimbad: number }
export function applyRows(rows: string[][]): ImportResult {
  if (!rows.length) return { updated: 0, notfound: 0, total: 0, monthly: 0, dim: 0, dimbad: 0 }
  const hasHeader = looksLikeHeader(rows[0])
  const idx: HeaderIndex = hasHeader ? mapHeader(rows[0]) : { code: 0, target: 1, actual: 2 }
  const data = hasHeader ? rows.slice(1) : rows
  let updated = 0, notfound = 0, monthly = 0, dimrows = 0, dimbad = 0
  data.forEach(function (r) {
    const code = idx.code !== undefined ? String(r[idx.code] || '').trim() : ''
    const name = idx.name !== undefined ? String(r[idx.name] || '').trim() : ''
    let it: Indicator | undefined
    if (code) {
      it = S.IND.filter(function (x) { return x.code.toLowerCase() === code.toLowerCase() })[0]
    }
    if (!it && name) it = S.IND.filter(function (x) { return x.name === name })[0]
    if (!it) { notfound++; return }
    const num = function (v: unknown): number | null { const n = parseFloat(String(v).replace(/[,%¥\s]/g, '')); return isNaN(n) ? null : n }
    const mt = idx.target !== undefined ? num(r[idx.target]) : null
    const ma = idx.actual !== undefined ? num(r[idx.actual]) : null

    /* A) 含「维度」列且填了维度成员 → 写入业务指标的分维度矩阵（BIZ_DIM）。
          指标整体值不在此处直接改写，由 recompute() 按维度填报值聚合回填。 */
    if (idx.dim !== undefined && String(r[idx.dim] || '').trim()) {
      const mbName = String(r[idx.dim]).trim()
      const dk = pickDimKey(it, mbName)
      if (dk === null) { dimbad++ } else {
        if (mt !== null) setBizDimOf(it.code, dk, mbName, 'target', mt)
        if (ma !== null) setBizDimOf(it.code, dk, mbName, 'actual', ma)
        dimrows++
      }
      updated++
      return
    }

    /* B) 含「月份」列 → 该行视为月度数据，写入对应月份的覆盖项并反算年度累计 */
    const mi = idx.month !== undefined ? monthIndex(r[idx.month]) : -1
    if (mi >= 0) {
      if (mt !== null) setMonthOverride(it, 'target', mi, mt)
      if (ma !== null) setMonthOverride(it, 'actual', mi, ma)
      monthly++
    } else {
      if (mt !== null) it.target = mt
      if (ma !== null) it.actual = ma
      /* 手工直接填报 → 取消维度派生标记，以手工值为准 */
      if (mt !== null || ma !== null) { if (it._dimAgg) delete it._dimAgg }
    }
    if (idx.weight !== undefined) { const w = num(r[idx.weight]); if (w !== null) it.weight = w }
    if (idx.unit !== undefined && r[idx.unit]) it.unit = String(r[idx.unit]).trim()
    if (idx.name !== undefined && name) it.name = name
    if (idx.dir !== undefined && r[idx.dir]) it.dir = /逆向|反向|-1|越小|越低/.test(String(r[idx.dir])) ? -1 : 1
    if (idx.dept !== undefined && r[idx.dept]) {
      it.depts = String(r[idx.dept]).split(/[/、,，|]/).map(function (s) { return s.trim() }).filter(Boolean)
    }
    updated++
  })
  return { updated: updated, notfound: notfound, total: data.length, monthly: monthly, dim: dimrows, dimbad: dimbad }
}

/* 导入一段 CSV / TSV 文本（替代原 readFile + afterImport 中的非 DOM 部分）：
   解析 → 写入 → recompute；无有效行或全部未匹配时抛 Error（文案同原 toast） */
export function importTable(text: string): ImportResult {
  const res = applyRows(parseTable(text))
  recompute()
  if (!res.total) throw new Error('未解析到有效数据行，请检查文件格式')
  if (!res.updated) throw new Error('导入失败：共 ' + res.total + ' 行，均未匹配到已有指标编码，请检查「编码」列是否填写正确')
  return res
}
/* 导入成功提示文案（同原 afterImport 的成功 toast） */
export function importMessage(res: ImportResult): string {
  const extra: string[] = []
  if (res.monthly) extra.push(res.monthly + ' 行为月度数据，已反算年度累计')
  if (res.dim) extra.push(res.dim + ' 行为分维度填报，已写入维度矩阵')
  if (res.dimbad) extra.push(res.dimbad + ' 行的维度成员不在该指标声明的维度内，已跳过')
  return '导入完成：成功更新 ' + res.updated + ' 条指标' +
    (extra.length ? '（其中 ' + extra.join('；') + '）' : '') +
    (res.notfound ? '，' + res.notfound + ' 条未匹配到编码被跳过' : '')
}

export type CsvCell = string | number | null | undefined
export function toCSV(header: string[], rows: CsvCell[][]): string {
  const out = [header.join(',')]
  rows.forEach(function (r) {
    out.push(r.map(function (c) {
      const s = (c === null || c === undefined) ? '' : String(c)
      return /[",\n]/.test(s) ? '"' + s.replace(/"/g, '""') + '"' : s
    }).join(','))
  })
  return '﻿' + out.join('\r\n')
}
/* 导出文件名时间戳（原 stamp，今天取自可注入的 today()） */
export function stamp(): string {
  const d = today(), p = function (n: number): string { return (n < 10 ? '0' : '') + n }
  return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + '_' + p(d.getHours()) + p(d.getMinutes())
}
/* 指标声明的维度标签（分渠道 / 分品类 / 分线路 / 分服务商） */
export function dimLabels(i: Indicator | null | undefined): string {
  const dks = (i && i.dims) || []
  return dks.map(function (dk) { return BIZ_DIMS[dk] ? BIZ_DIMS[dk].label : dk }).join('/')
}
export function rowsOf(list: Indicator[]): CsvCell[][] {
  return list.map(function (i) {
    return [i.code, i.name, (i.kind === 'fin' ? '财务' : '业务'), (i.level === 1 ? '一级' : '二级'),
      i.unit, (i.dir === 1 ? '正向' : '逆向'), dimLabels(i), i.target, i.actual, i.weight, i.depts.join('/'), i.note || '']
  })
}
export const IND_HEADER = ['编码', '指标名称', '类型', '层级', '单位', '方向', '维度声明', '目标值', '实际值', '权重', '责任部门', '说明/计算口径']

/* 维度填报明细 / 导入模板：每行一个「指标 × 维度成员」单元 */
export const DIM_SKIP_MAP: Record<string, Set<string>> = { S3: new Set(['category']), S4: new Set(['provider']) }
export function dimRowsOf(list: Indicator[]): CsvCell[][] {
  const rows: CsvCell[][] = []
  list.forEach(function (i) {
    const dks = (i && i.dims) || []
    dks.forEach(function (dk) {
      const skip = i.parent !== null ? DIM_SKIP_MAP[i.parent] : undefined
      if (skip && skip.has(dk)) return
      const D = BIZ_DIMS[dk]
      if (!D) return
      D.members.forEach(function (mb) {
        const c = bizDimOf(i.code, dk, mb)
        rows.push([i.code, i.name, D.label, mb,
          (c.target === null || c.target === undefined ? '' : c.target),
          (c.actual === null || c.actual === undefined ? '' : c.actual),
          i.unit])
      })
    })
  })
  return rows
}
export const DIM_HEADER = ['编码', '指标名称', '维度', '维度成员', '目标值', '实际值', '单位']

/* 月度明细导出：每个指标展开为 9 行（2026 年 1-9 月） */
export function monthlyRowsOf(list: Indicator[]): CsvCell[][] {
  const rows: CsvCell[][] = []
  list.forEach(function (i) {
    for (let m = 0; m < 9; m++) {
      rows.push([i.code, i.name, (i.kind === 'fin' ? '财务' : '业务'), (i.level === 1 ? '一级' : '二级'),
        i.unit, (i.dir === 1 ? '正向' : '逆向'), '2026年' + MONTHS9[m], mT(i, m), mA(i, m),
        i.weight, i.depts.join('/'), i.note || ''])
    }
  })
  return rows
}
export const MONTH_HEADER = ['编码', '指标名称', '类型', '层级', '单位', '方向', '月份', '月目标值', '月实际值', '权重', '责任部门', '说明/计算口径']

/* =========================================================================
   单元格编辑（原 document change 事件委托中的非 DOM 部分；权限校验 / toast / save / render 由页面负责）
   数字无效时抛 Error（文案同原 toast）
   ========================================================================= */
/* 维度单元格（分渠道 / 分品类 / 分线路 / 分服务商）：空串表示清空 */
export function editDimCell(code: string, dimKey: string, member: string, field: ValueField, raw: string | number | null): void {
  if (!find(code)) throw new Error('未找到指标 ' + code)
  const dRaw = String(raw == null ? '' : raw).trim()
  const dV = (dRaw === '') ? null : parseFloat(dRaw.replace(/[,%¥\s]/g, ''))
  if (dV !== null && isNaN(dV)) throw new Error('请输入有效数字，已恢复原值')
  setBizDimOf(code, dimKey, member, field, dV)
  recompute()
}
/* 指标单元格：月度维度下写月度覆盖并反算年度；年度维度下直接写年度值 */
export function editCell(code: string, f: ValueField | 'weight', raw: string | number): void {
  const it = find(code)
  if (!it) throw new Error('未找到指标 ' + code)
  const v = parseFloat(String(raw).replace(/[,%¥\s]/g, ''))
  if (isNaN(v)) throw new Error('请输入有效数字，已恢复原值')
  const y = yearOf(it) /* 始终写入年度基准对象 */
  if (S.dim === 'month' && (f === 'target' || f === 'actual')) {
    setMonthOverride(y, f, S.curM - 1, v)
    recompute()
    return
  }
  y[f] = v
  /* 手工直接填报后，该指标不再由分维度填报值聚合派生 */
  if (f === 'target' || f === 'actual') { if (y._dimAgg) delete y._dimAgg }
  /* 分渠道毛利（F2.1-F2.8）由 F1.x × F3.x 派生；手工编辑后打 _chanEdited 标记，recompute 不再覆盖 */
  if ((f === 'target' || f === 'actual') && /^F2\.[1-8]$/.test(code)) { y._chanEdited = true }
  recompute()
}
