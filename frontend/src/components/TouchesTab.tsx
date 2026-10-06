import { useEffect, useMemo, useState } from 'react'
import { fetchZones, refreshStatuses } from '../lib/api'
import type { Timeframe, Zone, ZoneStatus } from '../lib/types'
import { BiasBadge, TradeBadge } from './TradeBadges'

function fmtTs(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })
  } catch {
    return s
  }
}

const STATUS_LABEL: Record<string, string> = {
  touchee: 'En attente de réaction',
  reaction: 'Réaction',
  echec: 'Échec',
  active: 'Active',
  expiree: 'Expirée',
}

type StatusFilter = 'all' | 'touchee' | 'reaction' | 'echec'
type SessionFilter = 'all' | 'London' | 'NY' | 'none'

export function TouchesTab({ tf }: { tf: Timeframe }) {
  const [zones, setZones] = useState<Zone[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [minStars, setMinStars] = useState(4)
  const [sessionFilter, setSessionFilter] = useState<SessionFilter>('all')

  const load = () => {
    setLoading(true)
    fetchZones({ tf, minScore: 4, limit: 2000, statuses: 'touchee,reaction,echec' })
      .then((z) => {
        z.sort((a, b) => (b.touched_at || '').localeCompare(a.touched_at || ''))
        setZones(z)
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    load()
  }, [tf])

  const onRefresh = async () => {
    setRefreshing(true)
    setError(null)
    try {
      await refreshStatuses({ tf, history: true, minScore: 4 })
      load()
    } catch (e) {
      setError(String(e))
    } finally {
      setRefreshing(false)
    }
  }

  const filtered = useMemo(() => {
    let list = zones
    if (statusFilter !== 'all') {
      list = list.filter((z) => z.status === statusFilter)
    }
    if (minStars > 4) {
      list = list.filter((z) => (z.score ?? 0) >= minStars)
    }
    if (sessionFilter === 'London' || sessionFilter === 'NY') {
      list = list.filter((z) => z.touched_session === sessionFilter)
    } else if (sessionFilter === 'none') {
      list = list.filter((z) => !z.touched_session)
    }
    return list
  }, [zones, statusFilter, minStars, sessionFilter])

  return (
    <div className="px-4 py-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">OB Touchés</h2>
          <p className="text-xs text-zinc-500">
            Premier contact prix ↔ zone · session au touch (Europe/Paris) · tendance H4/D1 au touch (info) · trade réel = fill au mid requis, TP +2R / SL / 1h
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 hover:border-blue-500 disabled:opacity-50"
        >
          {refreshing ? 'Actualisation…' : 'Rafraîchir le cycle de vie'}
        </button>
      </div>

      <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-zinc-500">Statut</span>
        {(
          [
            ['all', 'Tous'],
            ['touchee', 'Attente'],
            ['reaction', 'Réaction'],
            ['echec', 'Échec'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setStatusFilter(id)}
            className={
              statusFilter === id
                ? 'rounded-full border border-blue-500/60 bg-blue-600/20 px-2.5 py-1 text-blue-200'
                : 'rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-zinc-400 hover:border-zinc-500'
            }
          >
            {label}
          </button>
        ))}
        <span className="ml-2 text-zinc-500">Min ★</span>
        {[4, 5].map((n) => (
          <button
            key={n}
            type="button"
            onClick={() => setMinStars(n)}
            className={
              minStars === n
                ? 'rounded-full border border-amber-500/60 bg-amber-600/20 px-2.5 py-1 text-amber-200'
                : 'rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-zinc-400'
            }
          >
            ≥{n}
          </button>
        ))}
        <span className="ml-2 text-zinc-500">Session</span>
        {(
          [
            ['all', 'Toutes'],
            ['London', 'Londres'],
            ['NY', 'NY'],
            ['none', 'Hors session'],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setSessionFilter(id)}
            className={
              sessionFilter === id
                ? 'rounded-full border border-emerald-500/60 bg-emerald-600/20 px-2.5 py-1 text-emerald-200'
                : 'rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-zinc-400'
            }
          >
            {label}
          </button>
        ))}
      </div>

      {error && (
        <div className="mb-3 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-zinc-500">Chargement…</p>
      ) : filtered.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-6 py-16 text-center text-sm text-zinc-500">
          Aucune zone touchée pour {tf}
          {zones.length > 0 ? ' avec ces filtres' : ''}. Lancez un rafraîchissement historique pour
          rejouer les bougies en cache.
        </div>
      ) : (
        <div className="overflow-hidden rounded-xl border border-zinc-800">
          <table className="w-full text-left text-sm">
            <thead className="bg-zinc-900 text-xs uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-3 py-2">Symbole</th>
                <th className="px-3 py-2">Sens</th>
                <th className="px-3 py-2">★</th>
                <th className="px-3 py-2">Touché</th>
                <th className="px-3 py-2">Session</th>
                <th className="px-3 py-2">Statut</th>
                <th className="px-3 py-2">Tendance H4/D1</th>
                <th className="px-3 py-2">Trade réel</th>
                <th className="px-3 py-2">Zone</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((z) => (
                <tr key={z.id} className="border-t border-zinc-800/80 hover:bg-zinc-900/50">
                  <td className="px-3 py-2 font-medium">
                    {z.symbol} <span className="text-zinc-500">{z.tf}</span>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        z.direction === 'bull' ? 'text-emerald-400' : 'text-red-400'
                      }
                    >
                      {z.direction === 'bull' ? 'ACHAT' : 'VENTE'}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-amber-400">{z.score}★</td>
                  <td className="px-3 py-2 text-zinc-300">{fmtTs(z.touched_at)}</td>
                  <td className="px-3 py-2 text-zinc-400">{z.touched_session || '—'}</td>
                  <td className="px-3 py-2 text-zinc-300">
                    {STATUS_LABEL[z.status as ZoneStatus] || z.status}
                  </td>
                  <td className="px-3 py-2">
                    <BiasBadge zone={z} />
                  </td>
                  <td className="px-3 py-2">
                    <TradeBadge zone={z} />
                  </td>
                  <td className="px-3 py-2 text-zinc-500">
                    {z.low.toPrecision(5)}–{z.high.toPrecision(5)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-zinc-800 px-3 py-2 text-xs text-zinc-500">
            {filtered.length} affichée(s) / {zones.length} touchée(s)
          </div>
        </div>
      )}
    </div>
  )
}
