import { Component, type ErrorInfo, type ReactNode } from 'react'
import type { Async } from './hooks'
import { chColor, rx } from './format'

export function Card({ title, description, actions, className = '', children }: {
  title: string
  description?: ReactNode
  actions?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`card ${className}`}>
      <div className="cardhead">
        <div>
          <h2>{title}</h2>
          {description != null && <div className="d">{description}</div>}
        </div>
        {actions}
      </div>
      {children}
    </section>
  )
}

export const ChartBox = ({ tall = false, label, children }: { tall?: boolean; label: string; children: ReactNode }) => (
  <div className={`chart${tall ? ' tall' : ''}`} role="img" aria-label={label}>{children}</div>
)

export const ChannelLabel = ({ channel }: { channel: string }) => (
  <><span className="sw" style={{ background: chColor(channel) }} aria-hidden />{channel}</>
)

export function RoasBadge({ roas }: { roas: number | null }) {
  if (roas == null) return <span className="muted">–</span>
  return roas >= 1
    ? <span className="badge good" title="Earns back more than it costs">▲ {rx(roas)}</span>
    : <span className="badge bad" title="Earns back less than it costs">▼ {rx(roas)}</span>
}

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T
  options: { value: T; label: string }[]
  onChange: (v: T) => void
  label: string
}) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" className={o.value === value ? 'on' : ''} aria-pressed={o.value === value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

/** Renders loading / error / content for an async query, keeping stale data visible while refreshing. */
export function Await<T>({ state, children }: { state: Async<T>; children: (data: T) => ReactNode }) {
  if (state.error && !state.data) return <div className="explain" role="alert">Could not load data: {state.error}</div>
  if (!state.data) return <div className="empty" aria-busy="true">Loading…</div>
  return (
    <>
      {state.error && <div className="explain" role="alert">Showing previous data. Refresh failed: {state.error}</div>}
      {children(state.data)}
    </>
  )
}

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error(error, info.componentStack) }
  render() {
    return this.state.error
      ? <div className="wrap"><div className="explain" role="alert">Something went wrong rendering the dashboard: {this.state.error.message}</div></div>
      : this.props.children
  }
}
