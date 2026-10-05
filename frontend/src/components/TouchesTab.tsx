import { useEffect, useState } from 'react'
import { fetchZones, refreshStatuses } from '../lib/api'
import type { Timeframe, Zone } from '../lib/types'

function fmtTs(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })
  } catch {
    return s
  }
}

export function TouchesTab({ tf }: { tf: Timeframe }) {
  const [zones, setZones] = useState<Zone[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    setLoading(true)
    fetchZones({ tf, minScore: 1, limit: 500, statuses: 'touchee,reaction,echec' })
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

  return (
    <div className="px-4 py-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-zinc-100">OB Touchés</h2>
          <p className="text-xs text-zinc-500">
            Premier contact prix ↔ zone · session au moment du touch (Europe/Paris)
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

      {error && (
        <div className="mb-3 rounded-lg border border-red-900/50 bg-red-950/40 px-3 py-2 text-sm text-red-200">
          {error}
        </div>
      )}

      {loading ? (
        <p className="text-sm text-zinc-500">Chargement…</p>
      ) : zones.length === 0 ? (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 px-6 py-16 text-center text-sm text-zinc-500">
          Aucune zone touchée pour {tf}. Lancez un rafraîchissement historique pour rejouer les bougies
          en cache.
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
                <th className="px-3 py-2">Zone</th>
              </tr>
            </thead>
            <tbody>
              {zones.map((z) => (
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
                  <td className="px-3 py-2 capitalize text-zinc-300">{z.status}</td>
                  <td className="px-3 py-2 text-zinc-500">
                    {z.low.toPrecision(5)}–{z.high.toPrecision(5)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-zinc-800 px-3 py-2 text-xs text-zinc-500">
            {zones.length} zone(s)
          </div>
        </div>
      )}
    </div>
  )
}
