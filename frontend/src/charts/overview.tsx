import { useMemo } from 'react'
import { Doughnut, Line } from 'react-chartjs-2'
import type { ChartData, Plugin } from 'chart.js'
import { chColor, compact, css, dlong, dshort, inr, num, pct } from '../format'
import { font, themed, useThemeTick } from '../chartKit'
import { buildTrend } from '../trend'
import type { ChannelRow, DailyResponse, Model } from '../types'
import { ChartBox } from '../ui'

const yMoney = { beginAtZero: true, ticks: { callback: (v: string | number) => '₹' + compact(Number(v)) } }

/** Compact revenue-share donut. No legend: the channel chips above the trend carry names, colours and shares. */
export function RevenueDonut({ rows }: { rows: ChannelRow[] }) {
  useThemeTick()
  const data: ChartData<'doughnut'> = {
    labels: rows.map((r) => r.channel),
    datasets: [{ label: 'Revenue', data: rows.map((r) => r.revenue), backgroundColor: rows.map((r) => chColor(r.channel)), borderColor: css('--bg'), borderWidth: 2, hoverOffset: 6 }],
  }
  const total = rows.reduce((s, r) => s + r.revenue, 0)
  const centre: Plugin<'doughnut'> = {
    id: 'centre',
    afterDraw(ch) {
      const { ctx, chartArea: a } = ch
      const x = (a.left + a.right) / 2, y = (a.top + a.bottom) / 2
      ctx.save()
      ctx.textAlign = 'center'
      ctx.fillStyle = css('--ink'); ctx.font = font(700, 20); ctx.fillText('₹' + compact(total), x, y + 2)
      ctx.fillStyle = css('--ink-3'); ctx.font = font(400, 11); ctx.fillText('net revenue', x, y + 20)
      ctx.restore()
    },
  }
  const options = themed<'doughnut'>({
    cutout: '68%',
    layout: { padding: 4 },
    plugins: {
      tooltip: { callbacks: { label: (c) => { const r = rows[c.dataIndex]!; return [` ${r.channel}: ${inr(r.revenue)} (${pct(r.revenue_share)})`, ` ${num(r.orders)} orders · AOV ${inr(r.aov)}`] } } },
    },
  })
  return <ChartBox label="Donut chart of net revenue share by channel"><Doughnut data={data} options={options} plugins={[centre]} /></ChartBox>
}

/** Dashed vertical line through the hovered date (the shared-tooltip crosshair). */
const crosshair: Plugin<'line'> = {
  id: 'crosshair',
  afterDatasetsDraw(ch) {
    const active = ch.tooltip?.getActiveElements() ?? []
    if (!active.length) return
    const { ctx, chartArea: a } = ch
    const x = active[0]!.element.x
    ctx.save()
    ctx.strokeStyle = css('--ink-3'); ctx.lineWidth = 1; ctx.setLineDash([4, 4])
    ctx.beginPath(); ctx.moveTo(x, a.top); ctx.lineTo(x, a.bottom); ctx.stroke()
    ctx.restore()
  },
}

/**
 * One smooth line per channel (absolute revenue, no fills, no stacking). Hovering a date highlights that
 * date on every line and shows a shared tooltip: each visible channel sorted high to low, then the true
 * all-channel total (computed from the data, so hiding a line never changes it). Visibility is controlled by
 * the parent through `hidden`; the channel chips are the legend.
 */
export function RevenueTrend({ day, smooth, hidden }: { day: DailyResponse; smooth: boolean; hidden: ReadonlySet<string> }) {
  useThemeTick()
  const trend = useMemo(() => buildTrend(day, smooth), [day, smooth])
  const data: ChartData<'line'> = {
    labels: trend.dates.map(dshort),
    datasets: trend.series.map((s) => ({
      label: s.channel, data: s.values, hidden: hidden.has(s.channel), borderColor: chColor(s.channel), backgroundColor: chColor(s.channel), borderWidth: 2, fill: false,
      cubicInterpolationMode: 'monotone', pointRadius: 0, pointHoverRadius: 5, pointHoverBorderWidth: 2,
      pointHoverBackgroundColor: css('--surface'), pointHoverBorderColor: chColor(s.channel),
    })),
  }
  const options = themed<'line'>({
    interaction: { mode: 'index', intersect: false },
    scales: { x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } }, y: yMoney },
    plugins: {
      tooltip: {
        backgroundColor: '#181817', borderColor: 'rgba(255,255,255,.12)', borderWidth: 1, titleColor: '#fff', bodyColor: '#e7e6e1', footerColor: '#fff',
        padding: 12, boxPadding: 4, usePointStyle: true,
        itemSort: (a, b) => (b.parsed.y ?? 0) - (a.parsed.y ?? 0),
        callbacks: {
          title: (items) => dlong(trend.dates[items[0]!.dataIndex]!),
          label: (c) => ` ${c.dataset.label}: ₹${compact(c.parsed.y ?? 0)}`,
          footer: (items) => `Total (all channels): ₹${compact(trend.totals[items[0]!.dataIndex] ?? 0)}`,
        },
      },
    },
  })
  return <ChartBox tall label="Line chart of revenue per channel over time"><Line data={data} options={options} plugins={[crosshair]} /></ChartBox>
}

/**
 * Channel chips = legend + range totals. Each shows the channel's net revenue for the selected range (same
 * numbers as the donut and KPI cards) and its share; clicking shows/hides that channel's line.
 */
export function ChannelLegend({ channels, rows, hidden, onToggle, model, windowDays, from, to }: {
  channels: string[]; rows: ChannelRow[]; hidden: ReadonlySet<string>; onToggle: (channel: string) => void
  model: Model; windowDays: number; from: string; to: string
}) {
  const byChannel = new Map(rows.map((r) => [r.channel, r]))
  const modelName = model === 'last_click' ? 'last click' : 'first click'
  return (
    <div className="ov-chips" role="group" aria-label="Channels: net revenue for the selected range. Click to show or hide a line.">
      {channels.map((c) => {
        const r = byChannel.get(c)
        const off = hidden.has(c)
        return (
          <button type="button" key={c} className={`ov-chip${off ? ' off' : ''}`} aria-pressed={!off}
                  title={`Net revenue credited to ${c} (${modelName}, ${windowDays}-day window), ${from} to ${to}. Excludes refunded and cancelled orders. Click to ${off ? 'show' : 'hide'} this line.`}
                  onClick={() => onToggle(c)}>
            <span className="ov-chip-name"><span className="sw" style={{ background: chColor(c) }} aria-hidden />{c}</span>
            <span className="ov-chip-val">₹{compact(r?.revenue ?? 0)}<span className="ov-chip-share">{pct(r?.revenue_share ?? 0)}</span></span>
          </button>
        )
      })}
    </div>
  )
}
