import { describe, expect, it } from 'vitest'
import { addDays, compact, dshort, inr, pct, rolling, rx } from './format'

describe('format', () => {
  it('formats rupees with Indian digit grouping', () => {
    expect(inr(3369084.96)).toBe('₹33,69,085')
    expect(inr(null)).toBe('–')
  })
  it('compacts to k / lakh / crore', () => {
    expect(compact(950)).toBe('950')
    expect(compact(1500)).toBe('1.5k')
    expect(compact(2000)).toBe('2k')
    expect(compact(337000)).toBe('3.4L')
    expect(compact(12500000)).toBe('1.3Cr')
  })
  it('never renders duplicate neighbouring axis labels (regression: 2k, 2k, 3k, 3k)', () => {
    const labels = [0, 500, 1000, 1500, 2000, 2500, 3000, 3500, 4000].map(compact)
    expect(new Set(labels).size).toBe(labels.length)
  })
  it('formats ratios and percentages, with a dash for missing values', () => {
    expect(rx(1.2849)).toBe('1.28×')
    expect(pct(30.46)).toBe('30.5%')
    expect(rx(null)).toBe('–')
  })
  it('does date maths in UTC', () => {
    expect(addDays('2026-09-30', 1)).toBe('2026-10-01')
    expect(addDays('2026-03-01', -1)).toBe('2026-02-28')
    expect(dshort('2026-09-05')).toBe('05 Sep')
  })
  it('computes a trailing mean with a shorter window at the start', () => {
    expect(rolling([2, 4, 6, 8], 2)).toEqual([2, 3, 5, 7])
  })
})
