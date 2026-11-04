import { useEffect, useState } from 'react'
import { Chart, registerables, type ChartOptions, type ChartType } from 'chart.js'
import { css } from './format'

Chart.register(...registerables)

/** Re-render charts when the OS light/dark preference flips (colours are read from CSS variables). */
export function useThemeTick(): number {
  const [tick, setTick] = useState(0)
  useEffect(() => {
    const m = window.matchMedia('(prefers-color-scheme: dark)')
    const f = () => setTick((t) => t + 1)
    m.addEventListener('change', f)
    return () => m.removeEventListener('change', f)
  }, [])
  return tick
}

/** The slice of Chart.js options we merge into; the caller's own (fully typed) options pass through untouched. */
interface Mergeable {
  plugins?: { legend?: { labels?: object } & object }
  scales?: Record<string, { grid?: object; ticks?: object }>
}

/** Shared look: no animation, recessive grid, ink-coloured ticks and legend, no axis borders. */
export function themed<T extends ChartType>(opts: ChartOptions<T>): ChartOptions<T> {
  const ink2 = css('--ink-2')
  const grid = css('--grid')
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily
  Chart.defaults.color = ink2
  const m = opts as Mergeable
  const scales: NonNullable<Mergeable['scales']> = {}
  for (const [k, ax] of Object.entries(m.scales ?? {})) {
    scales[k] = { ...ax, grid: { color: grid, drawTicks: false, ...ax.grid }, border: { display: false }, ticks: { color: ink2, padding: 6, ...ax.ticks } } as typeof ax
  }
  const legend = m.plugins?.legend
  const merged = {
    responsive: true,
    maintainAspectRatio: false,
    animation: false,
    interaction: { mode: 'nearest', intersect: true },
    ...opts,
    plugins: {
      ...m.plugins,
      legend: { display: false, ...legend, labels: { usePointStyle: true, pointStyle: 'rectRounded', boxWidth: 9, boxHeight: 9, padding: 14, color: ink2, ...legend?.labels } },
    },
    ...(m.scales ? { scales } : {}),
  }
  return merged as unknown as ChartOptions<T>
}

export const font = (weight: number | string, px: number): string => `${weight} ${px}px ${Chart.defaults.font.family}`
