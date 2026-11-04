export const CH_ORDER = ['Google Ads', 'Meta Ads', 'TikTok Ads', 'Email', 'Organic Search', 'Organic Social', 'Referral', 'Direct / Unattributed']
const CH_VAR = ['--c1', '--c2', '--c3', '--c4', '--c5', '--c6', '--c7', '--c-direct']
export const PAID = ['Google Ads', 'Meta Ads', 'TikTok Ads']

export const css = (v: string): string => getComputedStyle(document.documentElement).getPropertyValue(v).trim()
/** Colour follows the channel (fixed slot), never its rank, so filters don't repaint survivors. */
export const chColor = (c: string): string => css(CH_VAR[Math.max(0, CH_ORDER.indexOf(c))] ?? '--c-direct')

type N = number | null | undefined
export const inr = (n: N): string => (n == null ? '–' : '₹' + Math.round(n).toLocaleString('en-IN'))
export const num = (n: N): string => (n == null ? '–' : Math.round(n).toLocaleString('en-IN'))
export const rx = (n: N): string => (n == null ? '–' : n.toFixed(2) + '×')
export const pct = (n: N): string => (n == null ? '–' : n.toFixed(1) + '%')

/** Indian-style compact money: 1.2k, 3.4L (lakh), 1.5Cr (crore). */
export function compact(n: number): string {
  const a = Math.abs(n)
  const trim = (x: number, d: number) => x.toFixed(d).replace(/\.0$/, '')
  if (a >= 1e7) return trim(n / 1e7, 1) + 'Cr'
  if (a >= 1e5) return trim(n / 1e5, 1) + 'L'
  if (a >= 1e3) return trim(n / 1e3, n % 1000 ? 1 : 0) + 'k'
  return String(Math.round(n))
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function dshort(isoDate: string): string {
  const [, m, d] = isoDate.split('-')
  return `${d} ${MONTHS[Number(m) - 1]}`
}

/** 'Mon, 26 Sep' style label for tooltips (UTC, like all dates here). */
export function dlong(isoDate: string): string {
  const d = new Date(isoDate + 'T00:00:00Z')
  return `${d.toLocaleDateString('en-GB', { weekday: 'short', timeZone: 'UTC' })}, ${dshort(isoDate)}`
}

export function addDays(isoDate: string, n: number): string {
  const x = new Date(isoDate + 'T00:00:00Z')
  x.setUTCDate(x.getUTCDate() + n)
  return x.toISOString().slice(0, 10)
}

/** Trailing mean over up to `w` points (shorter window at the start of the series). */
export function rolling(values: number[], w: number): number[] {
  return values.map((_, i) => {
    const win = values.slice(Math.max(0, i - w + 1), i + 1)
    return win.reduce((s, x) => s + x, 0) / win.length
  })
}
