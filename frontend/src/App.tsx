import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClaudeTab } from './components/ClaudeTab'
import { FilterBar } from './components/FilterBar'
import { Mosaic } from './components/Mosaic'
import { ReactionTab } from './components/ReactionTab'
import { ScanButton } from './components/ScanButton'
import { TopNav } from './components/TopNav'
import { TouchesTab } from './components/TouchesTab'
import { fetchZones, health, runScan } from './lib/api'
import { filterZones, sortZones } from './lib/sortZones'
import type { GroupId, TabId, Timeframe, Zone } from './lib/types'

const ALL_GROUPS: GroupId[] = ['NQ100', 'METAUX', 'ENERGIE', 'FOREX', 'CRYPTO']

export default function App() {
  const [tab, setTab] = useState<TabId>('scanner')
  const [tf, setTf] = useState<Timeframe>('H1')
  const [groups, setGroups] = useState<GroupId[]>([...ALL_GROUPS])
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState(4)
  const [zones, setZones] = useState<Zone[]>([])
  const [scanning, setScanning] = useState(false)
  const [hasScanned, setHasScanned] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [groupMap, setGroupMap] = useState<Record<string, string>>({})

  useEffect(() => {
    health()
      .then(() => setApiOk(true))
      .catch(() => setApiOk(false))
    fetch('/api/symbols')
      .then((r) => r.json())
      .then((list: { id: string; group: string }[]) => {
        const m: Record<string, string> = {}
        for (const s of list) m[s.id] = s.group
        setGroupMap(m)
      })
      .catch(() => {})
    fetchZones({ tf: 'H1', minScore: 4, limit: 200, activeOnly: true })
      .then((z) => {
        if (z.length) {
          setZones(sortZones(z))
          setHasScanned(true)
        }
      })
      .catch(() => {})
  }, [])

  const toggleGroup = useCallback((g: GroupId) => {
    setGroups((prev) => {
      if (prev.includes(g)) {
        const next = prev.filter((x) => x !== g)
        return next.length ? next : prev
      }
      return [...prev, g]
    })
  }, [])

  const onScan = useCallback(async () => {
    setScanning(true)
    setError(null)
    try {
      const res = await runScan({
        tf,
        groups,
        minScore,
        symbols: search.trim() || undefined,
      })
      // Scanner tab: active/fresh only
      const active = res.zones.filter((z) => !z.status || z.status === 'active')
      setZones(sortZones(active.length ? active : res.zones))
      setElapsed(res.elapsed_sec)
      setHasScanned(true)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setHasScanned(true)
    } finally {
      setScanning(false)
    }
  }, [tf, groups, minScore, search])

  const visible = useMemo(() => {
    const list = filterZones(zones, {
      search,
      groups,
      groupOf: (sym) => groupMap[sym],
    })
    return list.slice(0, 48)
  }, [zones, search, groups, groupMap])

  return (
    <div className="flex min-h-full flex-col">
      <TopNav tab={tab} onTab={setTab} />

      {tab === 'scanner' && (
        <>
          <FilterBar
            tf={tf}
            onTf={setTf}
            groups={groups}
            onToggleGroup={toggleGroup}
            search={search}
            onSearch={setSearch}
            minScore={minScore}
            onMinScore={setMinScore}
          />
          {apiOk === false && (
            <div className="mx-4 mt-3 rounded-lg border border-amber-800/50 bg-amber-950/40 px-3 py-2 text-xs text-amber-200">
              API indisponible — lancez le backend sur le port 8000.
            </div>
          )}
          <ScanButton scanning={scanning} onClick={onScan} disabled={apiOk === false} />
          <Mosaic
            zones={visible}
            scanning={scanning}
            error={error}
            hasScanned={hasScanned}
            elapsed={elapsed}
          />
        </>
      )}

      {tab === 'touches' && <TouchesTab tf={tf} />}
      {tab === 'reaction' && <ReactionTab tf={tf} />}
      {tab === 'claude' && <ClaudeTab />}
    </div>
  )
}
