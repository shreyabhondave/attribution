import { useEffect, useRef, useState } from 'react'
import { useApi } from '../hooks'
import { CH_ORDER, inr, num, pct } from '../format'
import { Await, Card, ChannelLabel } from '../ui'
import { LagHistogram } from '../charts/other'
import type { LagResponse, OrderExplain, OrderRow, OrdersResponse } from '../types'
import type { TabProps } from './types'

const PAGE = 12
const STATUS_BADGE: Record<string, string> = { paid: 'good', refunded: 'warn' }
const WHY: Record<string, string> = { no_touch_in_window: ' · no touch in window', no_journey: ' · no linked visit' }

function touchToOrder(d: number | null): string {
  if (d == null) return '–'
  if (d < 1 / 24) return '< 1 h'
  return d < 1 ? `${Math.round(d * 24)} h` : `${d.toFixed(1)} d`
}

export default function Journeys({ q, version }: TabProps) {
  const lag = useApi<LagResponse>('/api/conversion-lag', { from: q.from, to: q.to }, version)
  const [channel, setChannel] = useState('')
  const [status, setStatus] = useState('')
  const [search, setSearch] = useState('')
  const [debounced, setDebounced] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string | null>(null)

  useEffect(() => { const id = setTimeout(() => setDebounced(search.replace(/^#/, '')), 250); return () => clearTimeout(id) }, [search])
  useEffect(() => setOffset(0), [q.from, q.to, q.model, q.window_days, channel, status, debounced])

  const orders = useApi<OrdersResponse>('/api/orders', { ...q, channel, status, q: debounced, limit: PAGE, offset }, version)

  return (
    <>
      <div className="grid g2">
        <Card title="Days from first visit to paid order"
              description={<Await state={lag}>{(l) => l.median_days == null ? <>No journeys in range</>
                : <>Median {l.median_days} days · mean {l.mean_days} · {pct(l.share_within_window)} convert within {q.window_days} days · {num(l.orders_without_journey)} orders have no linkable journey</>}</Await>}>
          <Await state={lag}>{(l) => <LagHistogram lag={l} />}</Await>
        </Card>
        <Card title="How an order gets its channel" description="Click any order to see the evidence">
          <ol className="how">
            <li>Browsers are linked into a <b>person</b> through the buyer’s email hash and the order id on the purchase pixel.</li>
            <li>All marketing touches from <b>every device</b> of that person are collected.</li>
            <li>Only touches in the <b>{q.window_days}</b> days before the order count.</li>
            <li><b>Last click</b> gives the order to the latest touch (<b>first click</b>: the earliest). No touch → <i>Direct / Unattributed</i>.</li>
          </ol>
        </Card>
      </div>
      <Card title="Order explorer" description="Every order with its credited channel">
        <div className="toolbar">
          <div className="field"><label htmlFor="f-ch">Channel</label>
            <select id="f-ch" value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All</option>{CH_ORDER.map((c) => <option key={c}>{c}</option>)}</select></div>
          <div className="field"><label htmlFor="f-st">Status</label>
            <select id="f-st" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option>paid</option><option>refunded</option><option>cancelled</option></select></div>
          <div className="field"><label htmlFor="f-q">Search</label>
            <input id="f-q" type="search" placeholder="order id e.g. 100839" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        </div>
        <Await state={orders}>
          {(o) => (
            <>
              <OrderTable rows={o.rows} onSelect={setSelected} />
              <div className="pager">
                <span>{o.total ? `${offset + 1}–${Math.min(offset + PAGE, o.total)} of ${num(o.total)}` : '0 orders'}</span>
                <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>‹ Prev</button>
                <button type="button" disabled={offset + PAGE >= o.total} onClick={() => setOffset(offset + PAGE)}>Next ›</button>
              </div>
            </>
          )}
        </Await>
      </Card>
      <OrderDialog orderId={selected} windowDays={q.window_days} onClose={() => setSelected(null)} />
    </>
  )
}

function OrderTable({ rows, onSelect }: { rows: OrderRow[]; onSelect: (id: string) => void }) {
  return (
    <div className="scroll">
      <table>
        <thead><tr><th>Order</th><th>Placed (UTC)</th><th>Status</th><th>Value</th><th>Revenue (INR)</th><th>Credited channel</th><th>Campaign</th><th>Touch → order</th></tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={8} className="empty">No orders match</td></tr>}
          {rows.map((r) => (
            <tr key={r.order_id} className="click" tabIndex={0} onClick={() => onSelect(r.order_id)}
                onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && onSelect(r.order_id)}>
              <td>{r.order_id}</td>
              <td>{r.created_at.slice(0, 16).replace('T', ' ')}</td>
              <td><span className={`badge ${STATUS_BADGE[r.status] ?? 'mute'}`}>{r.status}</span></td>
              <td>{r.currency} {r.total.toLocaleString('en-IN')}</td>
              <td>{inr(r.revenue_inr)}</td>
              <td><ChannelLabel channel={r.channel} /><span className="muted">{WHY[r.reason] ?? ''}</span></td>
              <td>{r.campaign ?? '–'}</td>
              <td>{touchToOrder(r.days_to_order)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function OrderDialog({ orderId, windowDays, onClose }: { orderId: string | null; windowDays: number; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const detail = useApi<OrderExplain>(orderId ? `/api/orders/${encodeURIComponent(orderId)}` : null, { window_days: windowDays })
  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (orderId && !d.open) d.showModal()
    if (!orderId && d.open) d.close()
  }, [orderId])

  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="dlg-title">
      <div className="dh"><b id="dlg-title">Order {orderId}</b><button type="button" onClick={onClose}>Close</button></div>
      <div className="db">{orderId && <Await state={detail}>{(d) => <OrderEvidence d={d} windowDays={windowDays} />}</Await>}</div>
    </dialog>
  )
}

function OrderEvidence({ d, windowDays }: { d: OrderExplain; windowDays: number }) {
  const lc = d.attribution.last_click, fc = d.attribution.first_click, o = d.order
  const ago = lc.days_to_order == null ? '' : lc.days_to_order < 1 ? `${Math.round(lc.days_to_order * 24)} hours` : `${lc.days_to_order.toFixed(1)} days`
  return (
    <>
      <div className="explain">
        {lc.reason === 'touch' && <>Credited to <b>{lc.channel}</b>{lc.campaign && ` (${lc.campaign})`} by last click: the latest of {lc.n_touches} marketing touch(es) in the {windowDays} days before the order, {ago} earlier. First click would give <b>{fc.channel}</b>.</>}
        {lc.reason === 'no_touch_in_window' && <>We know this buyer’s visits, but none carried a marketing signal within {windowDays} days of the order, so it stays <b>Direct / Unattributed</b>.</>}
        {lc.reason === 'no_journey' && <>No browser journey could be linked to this order (email never seen on the site and no purchase pixel), so it is <b>Direct / Unattributed</b>. We do not guess.</>}
      </div>
      <div className="kv">
        <div><span>Status</span>{o.financial_status}</div>
        <div><span>Order value</span>{o.currency} {o.total.toLocaleString('en-IN')}</div>
        <div><span>Revenue (INR)</span>{inr(o.total_inr)}</div>
        <div><span>Devices linked to buyer</span>{d.devices.length}</div>
      </div>
      <h3 className="grp" style={{ marginTop: 6 }}>Order webhooks received</h3>
      {d.webhook_history.map((w) => <div className="muted" key={w.updated_at + w.financial_status}>{w.updated_at.slice(0, 19).replace('T', ' ')} → <b style={{ color: 'var(--ink)' }}>{w.financial_status}</b></div>)}
      <h3 className="grp">Marketing touches before the order (newest first)</h3>
      {d.touches.length === 0 ? <div className="muted">No marketing touches recorded for this buyer.</div> : (
        <div className="tl">
          {d.touches.map((t) => (
            <div key={t.event_id} className={`it ${t.is_last_click || t.is_first_click ? 'pick' : t.in_window ? 'win' : ''}`}>
              <b><ChannelLabel channel={t.channel} /></b>{' '}
              <span className="muted">{t.ts_utc.slice(0, 16).replace('T', ' ')} · device …{t.anonymous_id.slice(-4)}{t.utm_campaign ? ` · ${t.utm_campaign}` : ''}</span>
              {t.is_last_click && <span className="badge info">last click ✓</span>}
              {t.is_first_click && <span className="badge warn">first click</span>}
              {!t.in_window && <span className="badge mute">outside window</span>}
            </div>
          ))}
        </div>
      )}
    </>
  )
}
