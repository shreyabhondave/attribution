import { describe, expect, it } from 'vitest'
import { funnelSteps, headlineParts, paidEfficiency } from './insights'
import type { ChannelRow } from './types'

const row = (channel: string, o: Partial<ChannelRow>): ChannelRow => ({
  channel, is_paid: false, orders: 0, revenue: 0, gross_orders: 0, refunded_orders: 0, refunded_revenue: 0, cancelled_orders: 0, cancelled_value: 0,
  spend: 0, roas: null, aov: null, cpa: null, sessions: 0, purchase_sessions: 0, session_cvr: null, revenue_share: 0, ...o,
})

const rows = [
  row('Direct / Unattributed', { revenue: 900, revenue_share: 45 }),
  row('Meta Ads', { is_paid: true, revenue: 600, revenue_share: 30, spend: 500, roas: 1.2 }),
  row('TikTok Ads', { is_paid: true, revenue: 300, revenue_share: 15, spend: 100, roas: 3 }),
  row('Google Ads', { is_paid: true, revenue: 200, revenue_share: 10, spend: 0, roas: null }),
]

describe('funnelSteps', () => {
  it('computes share of sessions and of the previous step', () => {
    const s = funnelSteps({ sessions: 1000, add_to_cart: 250, checkout: 125, purchase: 50, visitors: 800 })
    expect(s.map((x) => x.ofSessions)).toEqual([100, 25, 12.5, 5])
    expect(s.map((x) => x.ofPrevious)).toEqual([null, 25, 50, 40])
  })
  it('never divides by zero', () => {
    const s = funnelSteps({ sessions: 0, add_to_cart: 0, checkout: 0, purchase: 0, visitors: 0 })
    expect(s.every((x) => Number.isFinite(x.ofSessions))).toBe(true)
    expect(s[1]!.ofPrevious).toBe(0)
  })
})

describe('paidEfficiency', () => {
  it('keeps only paid channels with spend, best ROAS first', () => {
    expect(paidEfficiency(rows).map((r) => r.channel)).toEqual(['TikTok Ads', 'Meta Ads'])
  })
})

describe('headlineParts', () => {
  const f = { sessions: 1000, add_to_cart: 250, checkout: 125, purchase: 80, visitors: 800 }
  it('ignores the Direct bucket when naming the top channel', () => {
    const p = headlineParts(rows, f)
    expect(p[0]!.strong).toBe('Meta Ads')
    expect(p[1]!.strong).toBe('TikTok Ads')
    expect(p[2]!.strong).toBe('8.0%')
  })
  it('omits "most efficient" when fewer than two paid channels can be compared', () => {
    const p = headlineParts([rows[0]!, rows[2]!], f)
    expect(p.some((x) => x.text.includes('efficient'))).toBe(false)
  })
  it('emits nothing misleading for an empty range', () => {
    expect(headlineParts([], { sessions: 0, add_to_cart: 0, checkout: 0, purchase: 0, visitors: 0 })).toEqual([])
  })
})
