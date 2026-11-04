import { useApi } from '../hooks'
import { inr, num } from '../format'
import { Await, Card, ChannelLabel, RoasBadge } from '../ui'
import { campaignChart } from '../charts/other'
import type { CampaignsResponse } from '../types'
import type { TabProps } from './types'

export default function Campaigns({ q, version }: TabProps) {
  const camps = useApi<CampaignsResponse>('/api/campaigns', q, version)
  return (
    <Await state={camps}>
      {({ rows }) => (
        <>
          <Card className="mb" title="Campaign spend vs attributed revenue"
                description="Campaign comes from the utm_campaign of the credited touch. Landings with only a click id have no campaign tag.">
            {campaignChart(rows.filter((r) => r.spend > 0 || r.revenue > 0))}
          </Card>
          <Card title="All campaigns" description="Sorted by spend">
            <div className="scroll">
              <table>
                <thead><tr><th>Campaign</th><th>Channel</th><th>Ad spend</th><th>Orders</th><th>Revenue</th><th>ROAS</th><th>Cost / order</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={`${r.channel}/${r.campaign}`}>
                      <td>{r.campaign}</td><td><ChannelLabel channel={r.channel} /></td>
                      <td>{r.spend ? inr(r.spend) : <span className="muted">–</span>}</td><td>{num(r.orders)}</td><td>{inr(r.revenue)}</td>
                      <td><RoasBadge roas={r.roas} /></td><td>{inr(r.cpa)}</td>
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
