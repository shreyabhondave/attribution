import { useState } from 'react'
import { useApi } from '../hooks'
import { Await, Card, Segmented } from '../ui'
import { ChannelLegend, RevenueDonut, RevenueTrend } from '../charts/overview'
import { ConversionStrip, EfficiencyList, Headline, KpiBand, Section } from '../overviewBlocks'
import type { DailyResponse, FunnelResponse, ReportResponse } from '../types'
import type { TabProps } from './types'

export default function Overview({ q, version }: TabProps) {
  const report = useApi<ReportResponse>('/api/report', q, version)
  const daily = useApi<DailyResponse>('/api/daily', q, version)
  const funnel = useApi<FunnelResponse>('/api/funnel', { from: q.from, to: q.to }, version)
  const [smooth, setSmooth] = useState(false)
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set())
  const toggle = (channel: string) => setHidden((h) => { const n = new Set(h); if (!n.delete(channel)) n.add(channel); return n })
  const modelLabel = q.model === 'last_click' ? 'Last-click' : 'First-click'

  return (
    <>
      <Await state={report}>
        {(r) => (
          <>
            <KpiBand t={r.totals} />
            <Await state={funnel}>{(f) => <Headline rows={r.rows} funnel={f.funnel} />}</Await>
          </>
        )}
      </Await>

      <Section title="Revenue" hint={`${modelLabel} · ${q.window_days}-day window · net of refunds & cancellations`}>
        <div className="ov-revenue">
          <Card
            className="ov-trend"
            title="Revenue trend by channel"
            description={smooth ? 'Trailing 7-day average per channel. Click a channel to hide it.' : 'Daily revenue per channel. Click a channel to hide it.'}
            actions={<Segmented label="Smoothing" value={smooth ? 'avg' : 'daily'} onChange={(v) => setSmooth(v === 'avg')}
                                options={[{ value: 'daily', label: 'Daily' }, { value: 'avg', label: '7-day average' }]} />}
          >
            <Await state={daily}>
              {(d) => (
                <>
                  <Await state={report}>
                    {(r) => <ChannelLegend channels={d.channels} rows={r.rows} hidden={hidden} onToggle={toggle} model={q.model} windowDays={q.window_days} from={q.from} to={q.to} />}
                  </Await>
                  <RevenueTrend day={d} smooth={smooth} hidden={hidden} />
                </>
              )}
            </Await>
          </Card>
          <Card className="ov-flat ov-donut" title="Revenue share" description="Share of net revenue by channel">
            <Await state={report}>{(r) => <RevenueDonut rows={r.rows.filter((x) => x.revenue > 0)} />}</Await>
          </Card>
        </div>
      </Section>

      <div className="ov-row2">
        <Section title="Paid channel efficiency" hint="ROAS · marker = break-even (₹1 back per ₹1 spent)">
          <Await state={report}>{(r) => <EfficiencyList rows={r.rows} />}</Await>
        </Section>
        <Section title="Conversion" hint="Human sessions, bots removed">
          <Await state={funnel}>{(f) => <ConversionStrip funnel={f.funnel} />}</Await>
        </Section>
      </div>
    </>
  )
}
