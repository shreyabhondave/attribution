import { describe, expect, it } from 'vitest'
import { buildTrend } from './trend'
import type { DailyResponse, Metrics } from './types'

const m = (revenue: number): Metrics => ({
  orders: 0, revenue, gross_orders: 0, refunded_orders: 0, refunded_revenue: 0, cancelled_orders: 0, cancelled_value: 0, spend: 0, roas: null, aov: null, cpa: null,
})

// Email has no entry on day 2 (missing channel value) and Direct only exists on day 3.
const day: DailyResponse = {
  channels: ['Meta Ads', 'Email', 'Direct / Unattributed'],
  days: [
    { date: '2026-09-01', ...m(300), by_channel: { 'Meta Ads': m(100), Email: m(200), 'Direct / Unattributed': m(0) } },
    { date: '2026-09-02', ...m(50), by_channel: { 'Meta Ads': m(50), 'Direct / Unattributed': m(0) } },
    { date: '2026-09-03', ...m(70), by_channel: { 'Meta Ads': m(30), Email: m(10), 'Direct / Unattributed': m(30) } },
  ],
}

describe('buildTrend', () => {
  it('keeps one series per channel, in API order, with missing values as 0', () => {
    const t = buildTrend(day, false)
    expect(t.series.map((s) => s.channel)).toEqual(['Meta Ads', 'Email', 'Direct / Unattributed'])
    expect(t.series[1]!.values).toEqual([200, 0, 10])
  })

  it('totals equal the sum of all channels per date (no double counting)', () => {
    expect(buildTrend(day, false).totals).toEqual([300, 50, 70])
  })

  it('7-day mode averages each channel and the total stays the exact sum of the averages', () => {
    const t = buildTrend(day, true)
    expect(t.series[0]!.values).toEqual([100, 75, 60])
    expect(t.totals[2]).toBeCloseTo(t.series.reduce((s, x) => s + x.values[2]!, 0))
    expect(t.totals[2]).toBeCloseTo((300 + 50 + 70) / 3)
  })

  it('does not mutate the API payload', () => {
    const copy = structuredClone(day)
    buildTrend(day, true)
    expect(day).toEqual(copy)
  })
})
