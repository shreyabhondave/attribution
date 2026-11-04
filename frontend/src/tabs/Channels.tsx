import { useApi } from '../hooks'
import { inr, num, pct, rx } from '../format'
import { Await, Card, ChannelLabel, RoasBadge } from '../ui'
import { SessionsBars, SpendRevenueBars } from '../charts/other'
import type { ReportResponse } from '../types'
import type { TabProps } from './types'

const Dash = () => <span className="muted">–</span>

export default function Channels({ q, version }: TabProps) {
  const report = useApi<ReportResponse>('/api/report', q, version)
  return (
    <Await state={report}>
      {(r) => {
        const maxRev = Math.max(...r.rows.map((x) => x.revenue), 1)
        const t = r.totals
        const paid = r.rows.filter((x) => x.is_paid)
        return (
          <>
            <div className="explain">
              {q.model === 'last_click'
                ? <><b>Last click:</b> an order is credited to the <b>latest marketing touch</b> within <b>{q.window_days} days</b> before purchase, across all of the buyer’s devices. Direct visits never take credit from an earlier ad.</>
                : <><b>First click:</b> an order is credited to the <b>earliest marketing touch</b> within <b>{q.window_days} days</b> before purchase. Good for seeing which channels start journeys.</>}
            </div>
            <Card className="mb" title="Performance by channel" description="Orders and revenue are net of refunds & cancellations. ROAS only exists where there is ad spend.">
              <div className="scroll">
                <table>
                  <thead>
                    <tr><th>Channel</th><th>Orders</th><th>Revenue</th><th>Share</th><th>Ad spend</th><th>ROAS</th><th>AOV</th><th>Cost / order</th><th>Refunded</th><th>Cancelled</th><th>Sessions</th></tr>
                  </thead>
                  <tbody>
                    {r.rows.map((x) => (
                      <tr key={x.channel}>
                        <td><ChannelLabel channel={x.channel} /></td>
                        <td>{num(x.orders)}</td>
                        <td>{inr(x.revenue)}<span className="bar" style={{ width: Math.max(2, (70 * x.revenue) / maxRev) }} /></td>
                        <td>{pct(x.revenue_share)}</td>
                        <td>{x.spend ? inr(x.spend) : <Dash />}</td>
                        <td><RoasBadge roas={x.roas} /></td>
                        <td>{inr(x.aov)}</td>
                        <td>{inr(x.cpa)}</td>
                        <td>{x.refunded_orders ? <>{num(x.refunded_orders)} <span className="muted">({inr(x.refunded_revenue)})</span></> : <Dash />}</td>
                        <td>{x.cancelled_orders ? num(x.cancelled_orders) : <Dash />}</td>
                        <td>{num(x.sessions)}</td>
                      </tr>
                    ))}
                    <tr className="total">
                      <td>Total</td><td>{num(t.orders)}</td><td>{inr(t.revenue)}</td><td>100%</td><td>{inr(t.spend)}</td><td>{rx(t.blended_roas)}</td>
                      <td>{inr(t.aov)}</td><td>{inr(t.cpa)}</td><td>{num(t.refunded_orders)}</td><td>{num(t.cancelled_orders)}</td>
                      <td>{num(r.rows.reduce((s, x) => s + x.sessions, 0))}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </Card>
            <div className="grid g2">
              <Card title="Spend vs revenue (paid channels)" description="Where the money goes and what comes back">
                <SpendRevenueBars labels={paid.map((x) => x.channel)} spend={paid.map((x) => x.spend)} revenue={paid.map((x) => x.revenue)} />
              </Card>
              <Card title="Sessions by channel" description="Traffic source of each human session (first marketing touch)">
                <SessionsBars rows={r.rows} />
              </Card>
            </div>
          </>
        )
      }}
    </Await>
  )
}
