import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AchievementBar from './AchievementBar.vue'
import { achievementLevel, barPosition } from './achievement'

describe('达成条规则（DESIGN.md · 达成条）', () => {
  it('填充宽度 = min(实际÷预算, 120%) 映射到条宽：88.0% → 73.3%', () => {
    expect(barPosition('88.0')).toBe(73.3)
    expect(barPosition('91.5')).toBe(76.3)
    expect(barPosition('120')).toBe(100)
    expect(barPosition('156.2')).toBe(100) // 超过 120% 封顶
    expect(barPosition('-5')).toBe(0)
    expect(barPosition(null)).toBeNull()
  })

  it('费用类：超过时间进度 10 个百分点为琥珀、超过 100% 为红', () => {
    // 时间进度 33.3%（4 月末）
    expect(achievementLevel('expense', '43.2', '33.3')).toBe('neutral') // 只超 9.9 个百分点
    expect(achievementLevel('expense', '43.4', '33.3')).toBe('warn')
    expect(achievementLevel('expense', '100.0', '33.3')).toBe('warn')
    expect(achievementLevel('expense', '100.1', '33.3')).toBe('bad')
    expect(achievementLevel('expense', '30.0', '33.3')).toBe('neutral')
  })

  it('收入类：低于时间进度 10 个百分点为琥珀、低于 70% 为红', () => {
    expect(achievementLevel('revenue', '85.0', '91.7')).toBe('neutral') // 低 6.7 个百分点
    expect(achievementLevel('revenue', '81.6', '91.7')).toBe('warn')
    expect(achievementLevel('revenue', '69.9', '33.3')).toBe('bad')
    expect(achievementLevel('revenue', '70.0', '33.3')).toBe('neutral')
    expect(achievementLevel('revenue', '105.2', '100')).toBe('neutral')
  })

  it('无法计算（分母 ≤ 0 返回空值）时为中性', () => {
    expect(achievementLevel('revenue', null, '50')).toBe('neutral')
    expect(achievementLevel('neutral', '10', '50')).toBe('neutral')
  })
})

describe('AchievementBar 组件', () => {
  it('渲染填充宽度、时间进度刻度、颜色类与无障碍标签', () => {
    const w = mount(AchievementBar, { props: { rate: '88.0', progress: '33.3', kind: 'expense' } })
    const bar = w.get('.attain')
    expect(bar.attributes('data-level')).toBe('warn')
    expect(bar.classes()).toContain('is-warn')
    expect(w.get('.fill').attributes('style')).toContain('width: 73.3%')
    expect(w.get('.tick').attributes('style')).toContain('left: calc(27.8% - 1px)')
    expect(bar.attributes('aria-label')).toBe('达成 88.0%，时间进度 33.3%')
  })

  it('未传时间进度不画刻度；中性不加颜色类；服务端分级优先', () => {
    const w = mount(AchievementBar, { props: { rate: '91.5' } })
    expect(w.find('.tick').exists()).toBe(false)
    expect(w.get('.attain').classes()).not.toContain('is-good')
    expect(w.get('.attain').attributes('data-level')).toBe('neutral')

    const w2 = mount(AchievementBar, { props: { rate: '91.5', level: 'good', showValue: true } })
    expect(w2.get('.attain').classes()).toContain('is-good')
    expect(w2.get('.attain-value').text()).toBe('91.5%')
  })

  it('达成率为空时显示「—」且条为空', () => {
    const w = mount(AchievementBar, { props: { rate: null, showValue: true } })
    expect(w.get('.fill').attributes('style')).toContain('width: 0%')
    expect(w.get('.attain-value').text()).toBe('—')
  })
})
