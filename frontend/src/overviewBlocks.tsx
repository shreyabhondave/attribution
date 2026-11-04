import type { ReactNode } from 'react'
import { chColor, inr, num, pct, rx } from './format'
import { funnelSteps, headlineParts, paidEfficiency } from './insights'
import type { ChannelRow, FunnelResponse, Totals } from './types'
import { ChannelLabel } from './ui'

/** Flat section: small caps heading + hairline instead of another bordered box. */
export function Section({ title, hint, children, className = '' }: { title: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`ov-section ${className}`}>
      <h2 className="ov-h">{title}{hint && <span>{hint}</span>}</h2>
      {children}
    </section>
  )
}

export function KpiBand({ t }: { t: Totals }) {
  const items: [string, string, string][] = [
    ['Net revenue', inr(t.revenue), `${num(t.orders)} paid orders`],
    ['Ad spend', inr(t.spend), 'Meta + Google + TikTok'],
    ['Paid ROAS', rx(t.paid_roas), `${inr(t.paid_revenue)} from paid channels`],
    ['Blended ROAS', rx(t.blended_roas), 'all revenue ÷ all spend'],
    ['Avg order value', inr(t.aov), `${num(t.refunded_orders)} refunded · ${num(t.cancelled_orders)} cancelled`],
    ['Attributed revenue', pct(t.attributed_share), 'share not left as Direct'],
  ]
  return (
    <div className="ov-kpis">
      {items.map(([label, value, note]) => (
        <div className="ov-kpi" key={label}>
          <div className="l">{label}</div>
          <div className="v">{value}</div>
          <div className="n">{note}</div>
        </div>
      ))}
    </div>
  )
}

export function Headline({ rows, funnel }: { rows: ChannelRow[]; funnel: FunnelResponse['funnel'] }) {
  const parts = headlineParts(rows, funnel)
  if (!parts.length) return null
  return (
    <p className="ov-headline">
      {parts.map((p, i) => <span key={i}>{i > 0 && <span className="sep"> · </span>}<b>{p.strong}</b>{p.text}</span>)}
    </p>
  )
}

/** Paid channels side by side: spend → revenue, with a ROAS bar and a 1.0× break-even marker. */
export function EfficiencyList({ rows }: { rows: ChannelRow[] }) {
  const list = paidEfficiency(rows)
  if (!list.length) return <div className="muted">No paid spend in this range.</div>
  const max = Math.max(2, ...list.map((r) => r.roas ?? 0)) * 1.1
  return (
    <div className="eff" role="list">
      {list.map((r) => (
        <div className="eff-row" role="listitem" key={r.channel}>
          <div>
            <div className="eff-name"><ChannelLabel channel={r.channel} /></div>
            <div className="eff-sub">{inr(r.spend)} spend → {inr(r.revenue)} revenue</div>
          </div>
          <div className="eff-bar" role="img" aria-label={`${r.channel} ROAS ${rx(r.roas)} against break-even 1.00×`}>
            <div className="eff-fill" style={{ width: `${((r.roas ?? 0) / max) * 100}%`, background: chColor(r.channel) }} />
            <div className="eff-mark" style={{ left: `${(1 / max) * 100}%` }} title="Break-even: ₹1 back per ₹1 spent" />
          </div>
          <div className={`eff-val ${(r.roas ?? 0) >= 1 ? 'up' : 'down'}`}>{(r.roas ?? 0) >= 1 ? '▲' : '▼'} {rx(r.roas)}</div>
        </div>
      ))}
    </div>
  )
}

/** Four steps from sessions to purchase: counts and rates, with thin proportional bars (no canvas). */
export function ConversionStrip({ funnel }: { funnel: FunnelResponse['funnel'] }) {
  const steps = funnelSteps(funnel)
  return (
    <div className="cv" role="list">
      {steps.map((s) => (
        <div className="cv-step" role="listitem" key={s.name}>
          <div className="cv-name">{s.name}</div>
          <div className="cv-count">{num(s.count)}</div>
          <div className="cv-bar" aria-hidden><div style={{ width: `${Math.max(2, s.ofSessions)}%` }} /></div>
          <div className="cv-rate">{s.ofPrevious == null ? 'all human sessions' : <><b>{pct(s.ofPrevious)}</b> of previous step</>}</div>
          <div className="cv-rate">{s.ofPrevious == null ? ' ' : `${pct(s.ofSessions)} of sessions`}</div>
        </div>
      ))}
    </div>
  )
}
