import { useRef, type KeyboardEvent } from 'react'
import { addDays, num } from './format'
import { Segmented } from './ui'
import type { Filters, Model, Status } from './types'

export const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'channels', label: 'Channels' },
  { id: 'daily', label: 'By day' },
  { id: 'campaigns', label: 'Campaigns' },
  { id: 'journeys', label: 'Orders & journeys' },
  { id: 'quality', label: 'Data quality' },
] as const
export type TabId = (typeof TABS)[number]['id']

const WINDOWS = [1, 3, 7, 14, 30]

function LiveChip({ status, offline }: { status: Status | null; offline: boolean }) {
  let text = 'connecting…'
  let busy = false
  if (offline) text = 'service unreachable'
  else if (status?.pending_refresh) { busy = true; text = `processing new data… (${num(status.pending_visitors)} visitors queued)` }
  else if (status) text = `Live · ${num(status.events_stored)} events · ${num(status.orders_stored)} orders · updated ${status.last_refresh_at ? new Date(status.last_refresh_at).toLocaleTimeString() : '–'}`
  return <span className="chip" role="status" aria-live="polite"><span className={`dot${busy || offline ? ' busy' : ''}`} />{text}</span>
}

export default function Header({ filters, onChange, status, offline, tab, onTab }: {
  filters: Filters
  onChange: (patch: Partial<Filters>) => void
  status: Status | null
  offline: boolean
  tab: TabId
  onTab: (t: TabId) => void
}) {
  const tabRefs = useRef<(HTMLButtonElement | null)[]>([])
  const lo = status?.data_from ?? undefined
  const hi = status?.data_to ?? undefined

  const setRange = (from: string, to: string, followData = false) => onChange({ from, to, followData })
  const setFrom = (v: string) => v && setRange(v, filters.to && v > filters.to ? v : filters.to ?? v)
  const setTo = (v: string) => v && setRange(filters.from && v < filters.from ? v : filters.from ?? v, v)
  const last = (n: number) => { if (lo && hi) { const f = addDays(hi, -(n - 1)); setRange(f < lo ? lo : f, hi) } }

  // WAI-ARIA tabs: arrow keys move between tabs
  const onKey = (e: KeyboardEvent, i: number) => {
    const d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0
    if (!d) return
    const n = (i + d + TABS.length) % TABS.length
    onTab(TABS[n]!.id)
    tabRefs.current[n]?.focus()
  }

  return (
    <header>
      <div className="wrap">
        <div className="top">
          <div className="logo" aria-hidden><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round"><path d="M4 17l5-6 4 4 7-9" /></svg></div>
          <div><h1>Urban Thread · Marketing attribution</h1><div className="sub">First-party data · which channels actually drive revenue</div></div>
          <div className="spacer" />
          <LiveChip status={status} offline={offline} />
        </div>
        <div className="filters">
          <div className="field"><label htmlFor="from">From</label><input id="from" type="date" min={lo} max={hi} value={filters.from ?? ''} onChange={(e) => setFrom(e.target.value)} /></div>
          <div className="field"><label htmlFor="to">To</label><input id="to" type="date" min={lo} max={hi} value={filters.to ?? ''} onChange={(e) => setTo(e.target.value)} /></div>
          <div className="presets" role="group" aria-label="Date presets">
            <button type="button" onClick={() => lo && hi && setRange(lo, hi, true)}>All data</button>
            <button type="button" onClick={() => last(7)}>Last 7 days</button>
            <button type="button" onClick={() => last(14)}>Last 14 days</button>
            <button type="button" onClick={() => lo && setRange(lo, addDays(lo, 14))}>First half</button>
          </div>
          <div className="spacer" />
          <Segmented<Model> label="Attribution model" value={filters.model} onChange={(model) => onChange({ model })}
                            options={[{ value: 'last_click', label: 'Last click' }, { value: 'first_click', label: 'First click' }]} />
          <div className="field" title="A touch only earns credit for orders placed within this many days after it">
            <label htmlFor="win">Window</label>
            <select id="win" value={filters.windowDays} onChange={(e) => onChange({ windowDays: Number(e.target.value) })}>
              {WINDOWS.map((w) => <option key={w} value={w}>{w} {w === 1 ? 'day' : 'days'}</option>)}
            </select>
          </div>
        </div>
        <div className="tabs" role="tablist" aria-label="Dashboard sections">
          {TABS.map((t, i) => (
            <button key={t.id} ref={(el) => { tabRefs.current[i] = el }} type="button" role="tab" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls="panel"
                    tabIndex={tab === t.id ? 0 : -1} className={tab === t.id ? 'on' : ''} onClick={() => onTab(t.id)} onKeyDown={(e) => onKey(e, i)}>{t.label}</button>
          ))}
        </div>
      </div>
    </header>
  )
}
