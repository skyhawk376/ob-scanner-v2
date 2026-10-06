import { useCallback, useEffect, useMemo, useState } from 'react'
import { ClaudeTab } from './components/ClaudeTab'
import { FilterBar } from './components/FilterBar'
import { Mosaic } from './components/Mosaic'
import { ReactionTab } from './components/ReactionTab'
import { ScanButton } from './components/ScanButton'
import { TopNav } from './components/TopNav'
import { TouchesTab } from './components/TouchesTab'
import { fetchCacheStatus, fetchZones, health, runScan } from './lib/api'
import { filterZones, sortZones } from './lib/sortZones'
import type { GroupId, TabId, Timeframe, Zone } from './lib/types'

// Filtre B (prod): METAUX / FOREX / CRYPTO only, ≥4★ (backend STRATEGY_LOCK enforces it too)
const DEFAULT_GROUPS: GroupId[] = ['METAUX', 'FOREX', 'CRYPTO']

function formatCacheAge(ageSec: number | null | undefined, lastCandle?: string | null): string | null {
  if (ageSec == null && !lastCandle) return null
  if (ageSec == null) return 'cache ?'
  const h = Math.floor(ageSec / 3600)
  const m = Math.floor((ageSec % 3600) / 60)
  if (h >= 48) return `cache ${Math.floor(h / 24)}j`
  if (h >= 1) return `cache ${h}h${m > 0 ? String(m).padStart(2, '0') : ''}`
  return `cache ${m} min`
}

export default function App() {
  const [tab, setTab] = useState<TabId>('scanner')
  const [tf, setTf] = useState<Timeframe>('H1')
  const [groups, setGroups] = useState<GroupId[]>([...DEFAULT_GROUPS])
  const [search, setSearch] = useState('')
  const [minScore, setMinScore] = useState(4)
  const [zones, setZones] = useState<Zone[]>([])
  const [scanning, setScanning] = useState(false)
  const [hasScanned, setHasScanned] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState<number | null>(null)
  const [apiOk, setApiOk] = useState<boolean | null>(null)
  const [groupMap, setGroupMap] = useState<Record<string, string>>({})
  const [cacheAgeLabel, setCacheAgeLabel] = useState<string | null>(null)
  const [cacheStale, setCacheStale] = useState(false)

  const refreshCacheBadge = useCallback((timeframe: Timeframe) => {
    fetchCacheStatus(timeframe)
      .then((c) => {
        const label = formatCacheAge(c.age_sec, c.last_candle)
        setCacheAgeLabel(label)
        setCacheStale(c.age_sec != null && c.age_sec > 6 * 3600)
      })
      .catch(() => {
        // fallback health
        health()
          .then((h) => {
            const label = formatCacheAge(h.cache_age_sec ?? null, h.cache_last_candle)
            setCacheAgeLabel(label)
            setCacheStale((h.cache_age_sec ?? 0) > 6 * 3600)
          })
          .catch(() => {})
      })
  }, [])

  useEffect(() => {
    health()
      .then((h) => {
        setApiOk(true)
        const label = formatCacheAge(h.cache_age_sec ?? null, h.cache_last_candle)
        setCacheAgeLabel(label)
        setCacheStale((h.cache_age_sec ?? 0) > 6 * 3600)
      })
      .catch(() => setApiOk(false))
    fetch(`${import.meta.env.DEV ? '/api' : ''}/symbols`)
      .then((r) => r.json())
      .then((list: { id: string; group: string }[]) => {
        const m: Record<string, string> = {}
        for (const s of list) m[s.id] = s.group
        setGroupMap(m)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    refreshCacheBadge(tf)
  }, [tf, refreshCacheBadge])

  // TF / ★ / groups change → show the zones the scheduler already stored for that TF
  // (every TF is fetched + scanned in the background; « Scanner » re-runs it on demand).
  useEffect(() => {
    let cancelled = false
    fetchZones({ tf, minScore, limit: 300, activeOnly: true, groups })
      .then((z) => {
        if (cancelled) return
        setZones(sortZones(z))
        setHasScanned(true)
        setElapsed(null)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [tf, minScore, groups])

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
      // Backend auto-chains refresh (history=false). Reload active zones from store.
      let active = res.zones.filter((z) => !z.status || z.status === 'active')
      try {
        const stored = await fetchZones({
          tf,
          minScore,
          limit: 300,
          activeOnly: true,
          groups,
        })
        if (stored.length) active = stored
      } catch {
        /* keep scan payload */
      }
      setZones(sortZones(active.length ? active : res.zones))
      setElapsed(res.elapsed_sec)
      setHasScanned(true)
      refreshCacheBadge(tf)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setHasScanned(true)
    } finally {
      setScanning(false)
    }
  }, [tf, groups, minScore, search, refreshCacheBadge])

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
      <TopNav
        tab={tab}
        onTab={setTab}
        cacheAgeLabel={cacheAgeLabel}
        cacheStale={cacheStale}
      />

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
