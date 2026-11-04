import { useEffect, useRef, useState } from 'react'
import { api, type Params } from './api'
import type { Status } from './types'

export interface Async<T> {
  data: T | null
  error: string | null
  /** true only for the very first load; later reloads keep showing the previous data (no flicker) */
  loading: boolean
  refreshing: boolean
}

/**
 * Fetch `path` whenever the (serialised) params or `reloadKey` change.
 * In-flight requests are aborted when inputs change or the component unmounts, so a slow response
 * for an old date range can never overwrite a newer one.
 */
export function useApi<T>(path: string | null, params: Params = {}, reloadKey = ''): Async<T> {
  const [state, setState] = useState<Async<T>>({ data: null, error: null, loading: true, refreshing: false })
  const key = path === null ? null : `${path}?${JSON.stringify(params)}#${reloadKey}`
  const paramsRef = useRef(params)
  paramsRef.current = params

  useEffect(() => {
    if (path === null) return
    const ctl = new AbortController()
    setState((s) => ({ ...s, error: null, refreshing: s.data !== null }))
    api<T>(path, paramsRef.current, ctl.signal)
      .then((data) => setState({ data, error: null, loading: false, refreshing: false }))
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return
        setState((s) => ({ ...s, error: e instanceof Error ? e.message : String(e), loading: false, refreshing: false }))
      })
    return () => ctl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return state
}

/** Poll /api/status; `version` changes whenever new data has been processed, which drives re-fetching. */
export function useStatus(intervalMs = 4000): { status: Status | null; offline: boolean } {
  const [status, setStatus] = useState<Status | null>(null)
  const [offline, setOffline] = useState(false)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const s = await api<Status>('/api/status')
        if (alive) { setStatus(s); setOffline(false) }
      } catch {
        if (alive) setOffline(true)
      }
    }
    void tick()
    const id = setInterval(tick, intervalMs)
    return () => { alive = false; clearInterval(id) }
  }, [intervalMs])
  return { status, offline }
}
