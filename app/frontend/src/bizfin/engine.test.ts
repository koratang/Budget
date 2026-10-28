import { beforeEach, describe, expect, it } from 'vitest'
import {
  ADMIN_TYPES, BIZ_DIM_ORDER, BIZ_DIMS, DIM_HEADER, IND_HEADER, KW_CATEGORIES, KW_STATUS, LINKAGE, POLICY_SEGS,
  S, SEED_BIZ, SEED_FIN,
  adminAnnualPool, adminMatrix, adminPoolByM, applyRows, bizDimFilled, bizHealth, byKind, channelModel,
  children, dimRowsOf, dimTag, editCell, editDimCell, find, finHealth, hasData, hydrate, importMessage, importTable,
  isBlankBiz, isSumUnit, kwStat, l1, l2, mapHeader, momYoyOf, monthIndex, monthlyRowsOf, orderModel, overallHealth, parseTable,
  rate, rateText, recompute, rowsOf, seed, setBizDimOf, setToday, snapshot, stamp, toCSV, validations,
  type Indicator,
} from './engine'
import { barChart, donutChart, gauge, hBarChart, lineChart, stack100, txt } from './charts'

const close = (a: number | null | undefined, b: number, tol = 1e-9): boolean =>
  typeof a === 'number' && Math.abs(a - b) <= Math.max(1e-9, Math.abs(b) * tol)
const act = (code: string): number => {
  const i = find(code)
  if (!i || i.actual === null) throw new Error(code + ' 无实际值')
  return i.actual
}
const sum = (codes: string[]): number => codes.reduce((s, c) => s + act(c), 0)
const CH = ['F1.1', 'F1.2', 'F1.3', 'F1.4', 'F1.5']
const MK = ['F1.6', 'F1.7', 'F1.8']

/* verify2 的维度单元格期望数：S3 不展开品类、S4 不展开服务商 */
const cellExpect = (): number => {
  const skip: Record<string, Set<string>> = { S3: new Set(['category']), S4: new Set(['provider']) }
  let n = 0
  l2('biz').forEach((i) => (i.dims || []).forEach((dk) => {
    if (BIZ_DIMS[dk] && !(i.parent && skip[i.parent] && skip[i.parent].has(dk))) n += BIZ_DIMS[dk].members.length
  }))
  return n
}

beforeEach(() => {
  S.dim = 'year'
  S.curM = 9
  seed()
})

describe('示例数据装入后的勾稽基准', () => {
  it('validations() 全部通过', () => {
    const vs = validations()
    expect(vs.length).toBe(10)
    expect(vs.filter((v) => v.state !== 'ok').map((v) => v.title + ' ' + v.detail)).toEqual([])
  })

  it('F1=9840、渠道Σ=市场Σ=F1，F2/F3/F4/F5 与 F4.9 派生一致', () => {
    expect(act('F1')).toBe(9840)
    expect(sum(CH)).toBe(9840)
    expect(sum(MK)).toBe(9840)
    expect(act('F2')).toBe(3092.6)
    expect(act('F3')).toBe(31.4)
    expect(act('F4')).toBe(553.9)
    expect(act('F5')).toBe(5.63)
    // F4.9 = 七项费用率之和（不含 F4.6）
    expect(act('F4.9')).toBe(25.8)
    // L3 F4 = F2 − F1 × F4.9 / 100（容差 0.5）
    expect(close(act('F4'), act('F2') - act('F1') * act('F4.9') / 100, 0.5)).toBe(true)
    expect(close(act('F5'), act('F4') / act('F1') * 100, 0.05)).toBe(true)
    // F7.3 = F1 / 365 × F7.4；F7.5 = (F1 − F2) / 365 × F7.6
    // 注：示例数据中 F7.5 写的是 1408.9，recompute 按公式重算为 6747.4 × 78 / 365 = 1441.9（以代码为准）
    expect(act('F7.3')).toBe(1024.4)
    expect(act('F7.5')).toBe(1441.9)
    // 未填报的应付天数 → 应付账款派生置空，不当 0
    expect(find('F7.7')?.actual).toBeNull()
  })

  it('F2.x = F1.x × F3.x / 100（8 项）；F2 渠道合计 ≈ 市场合计', () => {
    for (let k = 1; k <= 8; k++) {
      expect(close(act('F2.' + k), act('F1.' + k) * act('F3.' + k) / 100, 0.15)).toBe(true)
    }
    const f2ch = sum(['F2.1', 'F2.2', 'F2.3', 'F2.4', 'F2.5'])
    const f2mk = sum(['F2.6', 'F2.7', 'F2.8'])
    expect(close(act('F2'), f2ch, 0.5)).toBe(true)
    expect(close(f2ch, f2mk, f2ch * 0.03)).toBe(true)
  })

  it('月度序列：发生额型逐月合计 = 年度累计，比率型季节加权平均 = 年度累计', () => {
    const f1 = find('F1') as Indicator
    expect(f1._ma).toHaveLength(9)
    expect(close(f1._ma!.reduce((a, b) => a + b, 0), 9840, 1e-6)).toBe(true)
    const kids = CH.map((c) => find(c)!._ma!)
    for (let m = 0; m < 9; m++) {
      expect(Math.abs(kids.reduce((s, k) => s + k[m], 0) - f1._ma![m])).toBeLessThan(0.6)
    }
    expect(S.TREND.acos).toHaveLength(6)
    expect(S.TREND.acos.every((v) => Number.isFinite(v))).toBe(true)
  })

  it('月度维度：CUR 换成当月口径副本；除余额两项外校验全部通过', () => {
    S.dim = 'month'
    S.curM = 5
    recompute()
    const f1 = find('F1') as Indicator
    expect(f1._src).toBeDefined()
    expect(f1.actual).toBe(f1._src!._ma![4])
    const vs = validations()
    // 原代码行为：月度余额按「月收入 ÷ 30 × 天数」派生，而校验按「÷ 365」推算，月度口径下这两项恒为 warn（verify2 只要求无 err）
    expect(vs.filter((v) => v.state !== 'ok').map((v) => v.title)).toEqual([
      '〔2026年 05月〕应收账款 与「收入 ÷ 365 × 周转天数」交叉验证',
      '〔2026年 05月〕存货 与「营业成本 ÷ 365 × 周转天数」交叉验证',
    ])
    expect(vs[vs.length - 1].title).toContain('2026年 05月')
    const r = momYoyOf(f1)
    expect(r.mom).not.toBeNull()
    expect(r.yoy).not.toBeNull()
  })
})

describe('持久化：snapshot / hydrate 往返', () => {
  it('修改后 snapshot → 重置 → hydrate 得到一致状态', () => {
    editCell('F1.1', 'actual', '3,600') // 年度编辑
    editCell('F2.3', 'actual', 420) // 手工毛利，打 _chanEdited
    editDimCell('S1.1', 'channel', 'Amazon', 'actual', '138')
    editDimCell('S1.1', 'channel', 'Amazon', 'target', '150')
    S.dim = 'month'
    S.curM = 4
    recompute()
    editCell('F4.1', 'actual', 6.1) // 月度覆盖，反算年度
    S.dim = 'year'
    recompute()
    S.POLICY_EVENTS.push({ time: '2026-09-30', seg: '财务板块', desc: '美元兑人民币中间价走弱，海外回款结汇收益收窄', impact: '财务费用 -12 万元' })
    S.KW_TASKS[0].progress = 70

    const snap = snapshot()
    const f73 = act('F7.3'), f41 = act('F4.1'), s11 = act('S1.1')
    // 运行期字段不进快照
    const ind = snap.indicators as Record<string, unknown>[]
    expect(ind.some((i) => '_ma' in i || '_mt' in i || '_src' in i)).toBe(false)
    expect(ind.find((i) => i.code === 'F2.3')?._chanEdited).toBe(true)
    expect(ind.find((i) => i.code === 'F4.1')?._ova).toEqual({ 3: 6.1 })

    seed()
    expect(act('F1.1')).toBe(3560)
    hydrate(snap)
    expect(snapshot()).toEqual(snap)
    expect(act('F1.1')).toBe(3600)
    expect(act('F2.3')).toBe(420)
    expect(act('F4.1')).toBe(f41)
    expect(act('F7.3')).toBe(f73)
    expect(act('S1.1')).toBe(s11)
    expect(S.POLICY_EVENTS).toHaveLength(5)
    expect(S.KW_TASKS[0].progress).toBe(70)
  })

  it('缺的部分用示例数据，非法行被过滤', () => {
    hydrate({ policy: [{ time: '2026-05-01', seg: '营销板块', desc: '亚马逊调整家居类目佣金', impact: '佣金率 +0.5pt' }, null, { time: 1 }] })
    expect(S.POLICY_EVENTS).toHaveLength(1)
    expect(S.KW_TASKS).toHaveLength(15)
    expect(act('F1')).toBe(9840)
    expect(validations().every((v) => v.state === 'ok')).toBe(true)
  })
})

describe('verify2 · D 空值口径默认态', () => {
  it('业务指标默认待填报，不参与健康度', () => {
    l1('biz').forEach((p) => expect(isBlankBiz(p)).toBe(true))
    expect(l2('biz').every((i) => !hasData(i))).toBe(true)
    expect(bizHealth()).toBeNull()
    expect(close(overallHealth(), finHealth()!)).toBe(true)
    expect(rateText(find('S1'))).toBe('—')
    expect(dimTag(find('S1.1')!)).toContain('0/5')
    expect(isSumUnit(find('S1.1')!.unit)).toBe(true)
    expect(isSumUnit(find('S1.2')!.unit)).toBe(false)
  })
})

describe('verify2 · E/F/G 维度填报 → 聚合勾稽 / 导出 / 清零回滚', () => {
  const csv = [
    '编码,维度,目标值,实际值',
    'S1.1,Amazon,150,138',
    'S1.1,Wayfair,90,96',
    'S1.1,Home Depot,60,55',
    "S1.1,Lowe's,40,42",
    'S1.1,独立站,120,130',
    'S1.2,Amazon,4.0,4.2',
    'S1.2,Wayfair,2.4,2.2',
    'S1.3,Amazon,1065,1100',
    'S2.2,镜柜,30,32',
    'S4.2,美东,12.5,12.0',
    'S4.4,服务商A,0.92,0.88',
    'S1.1,不存在的渠道,10,10',
  ].join('\n')

  it('导入维度行并聚合', () => {
    expect(mapHeader(['编码', '维度', '目标值', '实际值']).dim).toBe(1)
    const res = applyRows(parseTable(csv))
    expect(res.dim).toBe(11)
    expect(res.dimbad).toBe(1)
    recompute()
    const d11 = find('S1.1')!
    expect(close(d11.actual, 461)).toBe(true)
    expect(close(d11.target, 460)).toBe(true)
    expect(d11._dimAgg).toBe(true)
    expect(close(find('S1.2')!.actual, 3.2)).toBe(true)
    expect(close(find('S1.2')!.target, 3.2)).toBe(true)
    expect(act('S1.3')).toBe(1100)
    expect(act('S2.2')).toBe(32)
    expect(act('S4.2')).toBe(12)
    expect(act('S4.4')).toBe(0.88)
    expect(bizDimFilled('S1.1')).toBe(5)

    // E14 板块达成率 = 已填报二级加权
    const kids = children('S1').filter((k) => hasData(k) && k.target)
    let sw = 0, ss = 0
    kids.forEach((k) => { sw += k.weight; ss += rate(k) * k.weight })
    expect(close(find('S1')!.actual, Number((ss / sw).toFixed(1)), 0.06)).toBe(true)
    expect(find('S1')!.target).toBe(100)
    expect(isBlankBiz(find('S3'))).toBe(true)
    expect(dimTag(find('S1.1')!)).toContain('5/5')

    // F 维度导出
    const dimRows = dimRowsOf(byKind('biz'))
    expect(dimRows.length).toBe(cellExpect())
    expect(dimRows.some((r) => r[0] === 'S1.1' && r[3] === 'Amazon' && r[5] === 138)).toBe(true)
    expect(IND_HEADER).toContain('维度声明')
    expect(rowsOf([find('S1.1')!])[0][6]).toBe('渠道')
    expect(DIM_HEADER).toContain('维度成员')

    // G 清零回滚
    for (const mb of BIZ_DIMS.channel.members) {
      setBizDimOf('S1.1', 'channel', mb, 'target', null)
      setBizDimOf('S1.1', 'channel', mb, 'actual', null)
    }
    recompute()
    expect(find('S1.1')!.actual).toBeNull()
    expect(find('S1.1')!._dimAgg).not.toBe(true)
    expect(close(find('S1.2')!.actual, 3.2)).toBe(true)
    setBizDimOf('S1.2', 'channel', 'Amazon', 'actual', 9.9)
    recompute()
    expect(close(find('S1.2')!.actual, (9.9 + 2.2) / 2)).toBe(true)
  })

  it('importTable：成功返回结果与提示文案，无有效行抛错', () => {
    const res = importTable(csv)
    expect(res.updated).toBe(12)
    expect(importMessage(res)).toContain('11 行为分维度填报')
    expect(() => importTable('')).toThrow('未解析到有效数据行')
    expect(() => importTable('编码,实际值\nX9.9,1')).toThrow('均未匹配到已有指标编码')
  })

  it('月份列导入写月度覆盖并反算年度', () => {
    expect(monthIndex('2026年9月')).toBe(8)
    expect(monthIndex('09月')).toBe(8)
    expect(monthIndex('年度累计')).toBe(-1)
    const before = act('F1')
    const res = applyRows(parseTable('编码,月份,实际值\nF1,2026-03,800'))
    expect(res.monthly).toBe(1)
    recompute()
    const f1 = find('F1')!
    expect(f1._ma![2]).toBe(800)
    expect(close(f1._ma!.reduce((a, b) => a + b, 0), act('F1'), 1e-9)).toBe(true)
    expect(act('F1')).not.toBe(before)
  })
})

describe('verify2 · H 编码完整性 / 台账', () => {
  it('业务指标与业财关联', () => {
    expect(SEED_BIZ.filter((i) => i.level === 2)).toHaveLength(31)
    expect(SEED_BIZ.every((i) => !/^B\d/.test(i.code))).toBe(true)
    expect(LINKAGE).toHaveLength(31)
    expect(LINKAGE.filter((l) => !find(l.biz))).toEqual([])
    const badFin = LINKAGE.filter((l) => l.fin.split(/[/→+]/).map((x) => x.trim()).filter(Boolean).some((c) => !find(c)))
    expect(badFin).toEqual([])
    expect(BIZ_DIM_ORDER).toEqual(['channel', 'category', 'lane', 'provider'])
  })

  it('政策 / 重点工作台账', () => {
    expect(S.POLICY_EVENTS).toHaveLength(4)
    expect(S.POLICY_EVENTS.every((e) => POLICY_SEGS.includes(e.seg))).toBe(true)
    expect(S.KW_TASKS).toHaveLength(15)
    expect(KW_CATEGORIES).toEqual(['核算', '资金', '合规', '降本增收', '财务BP', '信息化'])
    expect(KW_STATUS).toEqual(['进行中', '已完成', '延误', '阻滞'])
    const st = kwStat()
    expect(st.hot).toBe(3) // 延误 2 + 阻滞 1
    expect(st.progressAvg).toBeGreaterThanOrEqual(0)
    expect(st.progressAvg).toBeLessThanOrEqual(100)
  })
})

describe('verify2 · I 分析模块派生量有限性', () => {
  it('订单 / 渠道模型恒等式', () => {
    const fin = (v: number): boolean => Number.isFinite(v)
    const om = orderModel(null)
    expect(Object.values(om.orders).every(fin) && fin(om.total)).toBe(true)
    expect(om.aov['Amazon']).toBe(1065)
    expect(close(om.revenue * 10000 / om.total, om.blendedAov, 1e-6)).toBe(true)
    const cm = channelModel(null)
    expect(cm.rows.every((r) => fin(r.uv) && fin(r.cvr) && fin(r.cpc) && fin(r.organic))).toBe(true)
    expect(Math.abs(cm.uv * cm.cvr / 100 - cm.orders)).toBeLessThanOrEqual(1e-6 * cm.orders + 1)
  })
})

describe('verify2 · J 管理费用分析', () => {
  it('年度池 = F1 × F4.7，月度池合计 = 年度池，逐月 Σ部门 = Σ类型 = 月度池', () => {
    const pool = adminAnnualPool()
    expect(close(pool, 9840 * 2.5 / 100)).toBe(true)
    const pm = adminPoolByM()
    expect(close(pm.reduce((a, b) => a + b, 0), pool)).toBe(true)
    for (let m = 0; m < 9; m++) {
      const mx = adminMatrix(m)
      const deptSum = mx.reduce((a, r) => a + r.total, 0)
      const typeSum = ADMIN_TYPES.reduce((a, _t, ti) => a + mx.reduce((x, r) => x + r.types[ti], 0), 0)
      expect(close(deptSum, pm[m])).toBe(true)
      expect(close(typeSum, pm[m])).toBe(true)
    }
  })
})

describe('verify2 · L 财务指标 v3 结构 / N 月度导出', () => {
  it('7 个一级 + 核心二级齐全', () => {
    expect(l1('fin').map((x) => x.code)).toEqual(['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7'])
    expect(l2('fin').length).toBeGreaterThanOrEqual(16)
    const codes = new Set(SEED_FIN.map((i) => i.code))
    ;['F1.1', 'F1.2', 'F4.1', 'F4.2', 'F4.3', 'F4.4', 'F4.5', 'F4.7', 'F4.8', 'F4.9', 'F5', 'F7.3', 'F7.4', 'F7.5', 'F7.6']
      .forEach((c) => expect(codes.has(c)).toBe(true))
    expect(find('F4')!.name).toBe('净利润')
    expect(find('F5')!.name).toBe('净利润率')
    expect(find('F6')!.name).toBe('净资产收益率')
    expect(find('F7')!.name).toBe('经营净现金流')
  })

  it('月度导出每个指标 9 行，CSV 带 BOM 并转义', () => {
    const rows = monthlyRowsOf([find('S1.1')!, find('F1')!])
    expect(rows).toHaveLength(18)
    expect(rows[9][6]).toBe('2026年01月')
    const csv = toCSV(['编码', '说明'], [['F1', '含"引号",逗号']])
    expect(csv).toBe('﻿编码,说明\r\n' + 'F1,"含""引号"",逗号"')
  })
})

describe('单元格编辑与日期注入', () => {
  it('手工编辑 F2.x 后 recompute 不再覆盖；非数字抛错', () => {
    editCell('F2.1', 'actual', 1100)
    editCell('F1.1', 'actual', 3700)
    expect(act('F2.1')).toBe(1100)
    expect(() => editCell('F1', 'actual', '一万')).toThrow('请输入有效数字')
  })

  it('stamp 使用可注入的 today', () => {
    setToday(() => new Date(2026, 9, 28, 9, 5))
    expect(stamp()).toBe('20261028_0905')
    setToday(() => new Date())
  })
})

describe('charts：返回 SVG 字符串且文本经过转义', () => {
  it('标签中的 HTML 被转义', () => {
    const out = barChart([{ label: '<b>华东</b>', value: 120, target: 150 }, { label: "Lowe's", value: 80 }])
    expect(out.startsWith('<svg')).toBe(true)
    expect(out).toContain('&lt;b&gt;华东&lt;/b&gt;')
    expect(out).toContain('Lowe&#39;s')
    expect(out).not.toContain('<b>')
    expect(txt(0, 0, '毛利 & 费用')).toContain('毛利 &amp; 费用')
  })

  it('各图表可渲染、无 NaN', () => {
    const outs = [
      hBarChart([{ label: '运营部', value: 96.5 }, { label: '财务部', value: -3.2 }], { signed: true }),
      hBarChart([{ label: '运营部', value: 96.5, target: 100 }]),
      lineChart(['07月', '08月', '09月'], [{ name: '营销费用率', values: [5.6, 5.8, 5.7], color: '#2563eb' }], { endLabel: true }),
      stack100(['07月', '08月'], [{ name: 'Amazon', values: [36, 37], color: '#2563eb' }, { name: '独立站', values: [17, 18], color: '#0d9488' }]),
      donutChart([{ label: '北美', value: 7660 }, { label: '英国', value: 1380 }], { centerTop: '净销售额', centerVal: '9,840' }),
      gauge(87.3),
    ]
    outs.forEach((o) => {
      expect(o.startsWith('<svg')).toBe(true)
      expect(o).not.toContain('NaN')
    })
  })
})
