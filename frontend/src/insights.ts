import { pct, rx } from './format'
import type { ChannelRow, FunnelResponse } from './types'

const DIRECT = 'Direct / Unattributed'

export interface FunnelStep {
  name: string
  count: number
  /** % of all sessions (100 for the first step) */
  ofSessions: number
  /** % of the previous step; null for the first step */
  ofPrevious: number | null
}

const share = (n: number, d: number): number => (d > 0 ? (100 * n) / d : 0)

export function funnelSteps(f: FunnelResponse['funnel']): FunnelStep[] {
  const raw: [string, number][] = [['Sessions', f.sessions], ['Added to cart', f.add_to_cart], ['Started checkout', f.checkout], ['Purchased', f.purchase]]
  return raw.map(([name, count], i) => ({
    name,
    count,
    ofSessions: i === 0 ? 100 : share(count, f.sessions),
    ofPrevious: i === 0 ? null : share(count, raw[i - 1]![1]),
  }))
}

/** Paid channels that actually had spend, best ROAS first. */
export function paidEfficiency(rows: ChannelRow[]): ChannelRow[] {
  return rows.filter((r) => r.is_paid && r.spend > 0 && r.roas != null).sort((a, b) => (b.roas ?? 0) - (a.roas ?? 0))
}

/**
 * One-line, data-derived summary. Parts are only emitted when they are meaningful:
 * the top channel ignores the Direct bucket, and "most efficient" needs at least two paid channels to compare.
 */
export function headlineParts(rows: ChannelRow[], f: FunnelResponse['funnel']): { text: string; strong: string }[] {
  const parts: { text: string; strong: string }[] = []
  const top = rows.filter((r) => r.channel !== DIRECT && r.revenue > 0).sort((a, b) => b.revenue - a.revenue)[0]
  if (top) parts.push({ strong: top.channel, text: ` brings the most revenue (${pct(top.revenue_share)})` })
  const eff = paidEfficiency(rows)
  if (eff.length >= 2) parts.push({ strong: eff[0]!.channel, text: ` is the most efficient (${rx(eff[0]!.roas)} ROAS)` })
  if (f.sessions > 0) parts.push({ strong: pct(share(f.purchase, f.sessions)), text: ' of sessions end in a purchase' })
  return parts
}
