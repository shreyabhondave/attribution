import type { Model } from '../types'

/** The resolved query every data tab shares (dates are always concrete here). */
export interface Query {
  from: string
  to: string
  model: Model
  window_days: number
  [key: string]: string | number
}

export interface TabProps {
  q: Query
  /** changes whenever the backend finished processing new data; used to re-fetch */
  version: string
}
