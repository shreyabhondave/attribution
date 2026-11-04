import { Bar, Line } from 'react-chartjs-2'
import type { ChartData, Plugin } from 'chart.js'
import { chColor, compact, css, dshort, inr, num, pct, PAID, rx } from '../format'
import { font, themed, useThemeTick } from '../chartKit'
import type { CampaignRow, ChannelRow, DailyResponse, LagResponse } from '../types'
import { ChartBox } from '../ui'

const yMoney = { beginAtZero: true, ticks: { callback: (v: string | number) => '₹' + compact(Number(v)) } }
const xHidden = { grid: { display: false } }
const gapped = { borderColor: css('--surface'), borderWidth: 1, borderRadius: 4 }

/** Grouped bars: spend next to attributed revenue for a list of entities. */
export function SpendRevenueBars({ labels, spend, revenue, extra, rotate = false }: {
  labels: string[]; spend: number[]; revenue: number[]; extra?: (i: number) => string; rotate?: boolean
}) {
  useThemeTick()
  const data: ChartData<'bar'> = {
    labels,
    datasets: [
      { label: 'Ad spend', data: spend, backgroundColor: css('--c2'), ...gapped },
      { label: 'Attributed revenue', data: revenue, backgroundColor: css('--c1'), ...gapped },
    ],
  }
  const options = themed<'bar'>({
    scales: { y: yMoney, x: { ...xHidden, ticks: { maxRotation: rotate ? 30 : 0, minRotation: 0 } } },
    plugins: { legend: { display: true }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${inr(c.parsed.y)}`, afterBody: (items) => (extra ? extra(items[0]!.dataIndex) : '') } } },
  })
  return <ChartBox label="Grouped bars comparing ad spend and attributed revenue"><Bar data={data} options={options} /></ChartBox>
}

export const campaignChart = (rows: CampaignRow[]) => (
  <SpendRevenueBars labels={rows.map((r) => r.campaign)} spend={rows.map((r) => r.spend)} revenue={rows.map((r) => r.revenue)} rotate
    extra={(i) => { const r = rows[i]!; return r.roas != null ? `ROAS ${rx(r.roas)} · ${num(r.orders)} orders` : `${num(r.orders)} orders` }} />
)

export function SessionsBars({ rows }: { rows: ChannelRow[] }) {
  useThemeTick()
  const sr = rows.filter((r) => r.sessions > 0)
  const data: ChartData<'bar'> = { labels: sr.map((r) => r.channel), datasets: [{ label: 'Sessions', data: sr.map((r) => r.sessions), backgroundColor: sr.map((r) => chColor(r.channel)), borderRadius: 4, barThickness: 22 }] }
  const labels: Plugin<'bar'> = {
    id: 'endLabels',
    afterDatasetsDraw(ch) {
      const { ctx } = ch
      ctx.save(); ctx.fillStyle = css('--ink'); ctx.font = font(600, 12); ctx.textBaseline = 'middle'
      ch.getDatasetMeta(0).data.forEach((b, i) => ctx.fillText(`${num(sr[i]!.sessions)}  · ${pct(sr[i]!.session_cvr)} CVR`, b.x + 6, b.y))
      ctx.restore()
    },
  }
  const options = themed<'bar'>({
    indexAxis: 'y',
    layout: { padding: { right: 120 } },
    scales: { x: { beginAtZero: true, grid: { display: false }, ticks: { callback: (v: string | number) => compact(Number(v)) } }, y: { grid: { display: false } } },
    plugins: { tooltip: { callbacks: { label: (c) => [` ${num(c.parsed.x)} sessions`, ` ${pct(sr[c.dataIndex]!.session_cvr)} bought in-session`] } } },
  })
  return <ChartBox label="Sessions by traffic channel"><Bar data={data} options={options} plugins={[labels]} /></ChartBox>
}

export function DailyRoas({ day }: { day: DailyResponse }) {
  useThemeTick()
  const paid = day.channels.filter((c) => PAID.includes(c))
  const data: ChartData<'line'> = {
    labels: day.days.map((d) => dshort(d.date)),
    datasets: paid.map((c) => ({ label: c, data: day.days.map((d) => d.by_channel[c]?.roas ?? null), borderColor: chColor(c), backgroundColor: chColor(c), borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.2, spanGaps: true })),
  }
  const options = themed<'line'>({
    interaction: { mode: 'index', intersect: false },
    scales: { x: { ...xHidden, ticks: { maxRotation: 0, maxTicksLimit: 10 } }, y: { beginAtZero: true, ticks: { callback: (v: string | number) => v + '×' } } },
    plugins: { legend: { display: true }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${rx(c.parsed.y)}` } } },
  })
  return <ChartBox tall label="Daily ROAS per paid channel"><Line data={data} options={options} /></ChartBox>
}

export function DailyOrders({ day }: { day: DailyResponse }) {
  useThemeTick()
  const data: ChartData<'bar'> = {
    labels: day.days.map((d) => dshort(d.date)),
    datasets: day.channels.map((c) => ({ label: c, data: day.days.map((d) => d.by_channel[c]?.orders ?? 0), backgroundColor: chColor(c), borderColor: css('--surface'), borderWidth: 1, stack: 's' })),
  }
  const options = themed<'bar'>({
    interaction: { mode: 'index', intersect: false },
    scales: { x: { stacked: true, grid: { display: false }, ticks: { maxRotation: 0, maxTicksLimit: 15 } }, y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } } },
    plugins: { legend: { display: true } },
  })
  return <ChartBox tall label="Paid orders per day stacked by channel"><Bar data={data} options={options} /></ChartBox>
}

export function LagHistogram({ lag }: { lag: LagResponse }) {
  useThemeTick()
  const data: ChartData<'bar'> = { labels: lag.histogram.map((h) => h.bucket), datasets: [{ label: 'Paid orders', data: lag.histogram.map((h) => h.orders), backgroundColor: css('--c1'), borderRadius: 4 }] }
  const labels: Plugin<'bar'> = {
    id: 'valueLabels',
    afterDatasetsDraw(ch) {
      const { ctx } = ch
      ctx.save(); ctx.fillStyle = css('--ink'); ctx.font = font(600, 12); ctx.textAlign = 'center'
      ch.getDatasetMeta(0).data.forEach((b, i) => { const v = lag.histogram[i]!.orders; if (v) ctx.fillText(num(v), b.x, b.y - 5) })
      ctx.restore()
    },
  }
  const options = themed<'bar'>({
    scales: { y: { beginAtZero: true, ticks: { precision: 0 } }, x: xHidden },
    plugins: { tooltip: { callbacks: { label: (c) => ` ${num(c.parsed.y)} orders` } } },
  })
  return <ChartBox label="Histogram of days from first visit to paid order"><Bar data={data} options={options} plugins={[labels]} /></ChartBox>
}
