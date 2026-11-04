/** Shapes returned by the FastAPI service (see app/reports.py). Money is INR, dates are UTC YYYY-MM-DD. */

export type Model = 'last_click' | 'first_click'

export interface Filters {
  from: string | null
  to: string | null
  model: Model
  windowDays: number
  /** true while the range simply follows the data (so new October data extends it automatically) */
  followData: boolean
}

export interface Status {
  data_from: string | null
  data_to: string | null
  events_stored: number
  orders_stored: number
  spend_rows: number
  sessions: number
  pending_refresh: boolean
  pending_visitors: number
  last_refresh_at: string | null
  last_refresh_ms: number
  refresh_count: number
  attribution_window_days: number
  version: string
  counters: Record<string, number>
}

export interface Metrics {
  orders: number
  revenue: number
  gross_orders: number
  refunded_orders: number
  refunded_revenue: number
  cancelled_orders: number
  cancelled_value: number
  spend: number
  roas: number | null
  aov: number | null
  cpa: number | null
}

export interface ChannelRow extends Metrics {
  channel: string
  is_paid: boolean
  sessions: number
  purchase_sessions: number
  session_cvr: number | null
  revenue_share: number
}

export interface Totals extends Omit<Metrics, 'roas'> {
  blended_roas: number | null
  paid_revenue: number
  paid_roas: number | null
  attributed_share: number | null
}

export interface ReportResponse {
  params: { from: string; to: string; model: Model; window_days: number }
  rows: ChannelRow[]
  totals: Totals
}

export interface DailyRow extends Metrics {
  date: string
  by_channel: Record<string, Metrics>
}
export interface DailyResponse {
  channels: string[]
  days: DailyRow[]
}

export interface CampaignRow extends Metrics {
  channel: string
  campaign: string
}
export interface CampaignsResponse {
  rows: CampaignRow[]
}

export interface FunnelResponse {
  funnel: { sessions: number; add_to_cart: number; checkout: number; purchase: number; visitors: number }
  days: { date: string; sessions: number; purchase_sessions: number }[]
}

export interface LagResponse {
  histogram: { bucket: string; orders: number }[]
  orders_with_journey: number
  orders_without_journey: number
  median_days: number | null
  mean_days: number | null
  share_within_window: number | null
}

export type AttributionReason = 'touch' | 'no_touch_in_window' | 'no_journey'

export interface OrderRow {
  order_id: string
  day: string
  created_at: string
  status: string
  total: number
  currency: string
  revenue_inr: number
  channel: string
  campaign: string | null
  reason: AttributionReason
  days_to_order: number | null
  n_touches: number
  person_id: string | null
}
export interface OrdersResponse {
  total: number
  rows: OrderRow[]
}

export interface AttributionDetail {
  channel: string
  campaign: string | null
  reason: AttributionReason
  days_to_order: number | null
  n_touches: number
}
export interface Touch {
  event_id: string
  ts_utc: string
  channel: string
  utm_campaign: string | null
  anonymous_id: string
  in_window: boolean
  is_last_click: boolean
  is_first_click: boolean
}
export interface OrderExplain {
  order: { order_id: string; financial_status: string; total: number; currency: string; total_inr: number }
  attribution: { last_click: AttributionDetail; first_click: AttributionDetail }
  person_id: string | null
  devices: { anonymous_id: string; sessions: number }[]
  touches: Touch[]
  webhook_history: { updated_at: string; financial_status: string }[]
  window_days: number
}

export type QualityLevel = 'fix' | 'exclude' | 'info' | 'warn'
export interface QualityItem {
  group: string
  title: string
  count: number
  detail: string
  action: string
  level: QualityLevel
}
export interface QualityResponse {
  items: QualityItem[]
}
