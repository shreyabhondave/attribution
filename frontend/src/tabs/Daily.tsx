import { useApi } from '../hooks'
import { inr, num } from '../format'
import { Await, Card, RoasBadge } from '../ui'
import { DailyOrders, DailyRoas } from '../charts/other'
import type { DailyResponse } from '../types'
import type { TabProps } from './types'

export default function Daily({ q, version }: TabProps) {
  const daily = useApi<DailyResponse>('/api/daily', q, version)
  return (
    <Await state={daily}>
      {(d) => (
        <>
          <div className="grid g2">
            <Card title="Daily ROAS by paid channel" description="Revenue ÷ spend each day · noisy on low-spend days"><DailyRoas day={d} /></Card>
            <Card title="Daily orders by channel" description="Paid orders credited to each channel"><DailyOrders day={d} /></Card>
          </div>
          <Card title="Day by day" description="Totals across all channels">
            <div className="scroll" style={{ maxHeight: 520 }}>
              <table>
                <thead><tr><th>Date</th><th>Orders</th><th>Revenue</th><th>Ad spend</th><th>Blended ROAS</th><th>Refunded</th><th>Cancelled</th></tr></thead>
                <tbody>
                  {[...d.days].reverse().map((x) => (
                    <tr key={x.date}>
                      <td>{x.date}</td><td>{num(x.orders)}</td><td>{inr(x.revenue)}</td><td>{inr(x.spend)}</td>
                      <td><RoasBadge roas={x.roas} /></td><td>{num(x.refunded_orders)}</td><td>{num(x.cancelled_orders)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </Await>
  )
}
