import { rolling } from './format'
import type { DailyResponse } from './types'

export interface Trend {
  dates: string[]
  /** one absolute-revenue series per channel, in the API's channel order */
  series: { channel: string; values: number[] }[]
  /** true all-channel total per date. Computed from the data, never from which lines are visible. */
  totals: number[]
}

/**
 * Turn the /api/daily payload into chart series. Missing channel values count as 0 (same rule as the
 * rest of the dashboard). With `smooth`, every channel gets a trailing 7-day mean; because the mean is
 * linear, the smoothed total is exactly the sum of the smoothed channels (no double counting).
 */
export function buildTrend(day: DailyResponse, smooth: boolean, windowDays = 7): Trend {
  const series = day.channels.map((channel) => {
    const raw = day.days.map((d) => d.by_channel[channel]?.revenue ?? 0)
    return { channel, values: smooth ? rolling(raw, windowDays) : raw }
  })
  const totals = day.days.map((_, i) => series.reduce((s, x) => s + (x.values[i] ?? 0), 0))
  return { dates: day.days.map((d) => d.date), series, totals }
}
