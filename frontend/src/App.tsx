import { useEffect, useMemo, useState, type ComponentType } from 'react'
import Header, { TABS, type TabId } from './Header'
import { useStatus } from './hooks'
import type { Filters } from './types'
import type { Query, TabProps } from './tabs/types'
import Overview from './tabs/Overview'
import Channels from './tabs/Channels'
import Daily from './tabs/Daily'
import Campaigns from './tabs/Campaigns'
import Journeys from './tabs/Journeys'
import Quality from './tabs/Quality'

const PANELS: Record<TabId, ComponentType<TabProps>> = { overview: Overview, channels: Channels, daily: Daily, campaigns: Campaigns, journeys: Journeys, quality: Quality }

const tabFromHash = (): TabId => {
  const h = window.location.hash.slice(1)
  return (TABS.find((t) => t.id === h)?.id ?? 'overview') as TabId
}

export default function App() {
  const { status, offline } = useStatus()
  const [filters, setFilters] = useState<Filters>({ from: null, to: null, model: 'last_click', windowDays: 7, followData: true })
  const [tab, setTab] = useState<TabId>(tabFromHash)
  const [version, setVersion] = useState<string | null>(null)
  const [windowInit, setWindowInit] = useState(false)

  const patch = (p: Partial<Filters>) => setFilters((f) => ({ ...f, ...p }))
  const selectTab = (t: TabId) => { setTab(t); window.history.replaceState(null, '', `#${t}`) }

  // adopt the backend's default lookback once
  useEffect(() => {
    if (status && !windowInit) { setWindowInit(true); patch({ windowDays: status.attribution_window_days }) }
  }, [status, windowInit])

  // while "following the data", the range tracks the data: new October files extend it automatically
  const dataFrom = status?.data_from, dataTo = status?.data_to
  useEffect(() => {
    if (!dataFrom || !dataTo) return
    setFilters((f) => (f.from == null || f.followData ? { ...f, from: dataFrom, to: dataTo } : f))
  }, [dataFrom, dataTo])

  // only re-fetch once the backend has finished processing (not mid-refresh)
  useEffect(() => { if (status && !status.pending_refresh) setVersion(status.version) }, [status])

  const query = useMemo<Query | null>(
    () => (filters.from && filters.to ? { from: filters.from, to: filters.to, model: filters.model, window_days: filters.windowDays } : null),
    [filters.from, filters.to, filters.model, filters.windowDays],
  )
  const Panel = PANELS[tab]

  return (
    <>
      <Header filters={filters} onChange={patch} status={status} offline={offline} tab={tab} onTab={selectTab} />
      <div className="wrap">
        <main id="panel" role="tabpanel" aria-labelledby={`tab-${tab}`}>
          {query && version !== null
            ? <Panel q={query} version={version} />
            : <div className="empty">{status && !status.data_from ? <>No data yet. Run <code>python sender/send.py</code> to stream events into the service.</> : 'Loading…'}</div>}
        </main>
      </div>
    </>
  )
}
