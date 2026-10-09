import { useEffect, useMemo, useState } from 'react'
import { fetchZones } from '../lib/api'
import type { Timeframe, Zone } from '../lib/types'
import { STATUS_FR, TradeBadge } from './TradeBadges'

function fmtTs(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('fr-FR', { timeZone: 'Europe/Paris', dateStyle: 'short', timeStyle: 'short' })
  } catch {
    return s
  }
}

type Filter = 'all' | 'touchee' | 'en_position' | 'closed' | 'invalidee'
const FILTERS: { id: Filter; label: string }[] = [
  { id: 'all', label: 'Tous' },
  { id: 'touchee', label: 'Touchées' },
  { id: 'en_position', label: 'En position' },
  { id: 'closed', label: 'Clôturés' },
  { id: 'invalidee', label: 'Invalidées' },
]

export function TouchesTab({ tf }: { tf: Timeframe }) {
  const [zones, setZones] = useState<Zone[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [search, setSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    fetchZones({ tf, minScore: 4, limit: 2000, statuses: 'touchee,en_position,tp,sl,be,invalidee' })
      .then((z) => setZones(z.filter((x) => x.touched_at)))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false))
  }, [tf])

  const list = useMemo(() => {
    let l = zones
    if (filter === 'closed') l = l.filter((z) => ['tp', 'sl', 'be'].includes(String(z.status)))
    else if (filter !== 'all') l = l.filter((z) => z.status === filter)
    const q = search.trim().toUpperCase()
    if (q) l = l.filter((z) => z.symbol.includes(q))
    return l
  }, [zones, filter, search])

  return (
    <div className="px-4 py-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="mr-2 text-sm font-semibold text-zinc-200">OB touchés · {tf}</h2>
        {FILTERS.map((f) => (
          <button
            key={f.id}
            type="button"
            onClick={() => setFilter(f.id)}
            className={
              filter === f.id
                ? 'rounded-full border border-blue-500/60 bg-blue-600/20 px-3 py-1 text-xs text-blue-200'
                : 'rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-400 hover:text-zinc-200'
            }
          >
            {f.label}
          </button>
        ))}
        <input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Rechercher..."
          className="ml-auto w-44 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-100 outline-none focus:border-blue-500"
        />
      </div>
      {error && <div className="mb-2 text-xs text-red-400">{error}</div>}
      {loading ? (
        <div className="text-xs text-zinc-500">Chargement…</div>
      ) : list.length === 0 ? (
        <div className="text-xs text-zinc-500">Aucun OB ≥4★ touché sur {tf} pour l’instant.</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-zinc-800">
          <table className="w-full text-left text-xs">
            <thead className="bg-zinc-900/80 text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-3 py-2">Touché (Paris)</th>
                <th className="px-3 py-2">Actif</th>
                <th className="px-3 py-2">Sens</th>
                <th className="px-3 py-2">★</th>
                <th className="px-3 py-2">Zone</th>
                <th className="px-3 py-2">Statut</th>
                <th className="px-3 py-2">Trade</th>
              </tr>
            </thead>
            <tbody>
              {list.map((z) => (
                <tr key={z.id} className="border-t border-zinc-800/70 text-zinc-300">
                  <td className="px-3 py-1.5 whitespace-nowrap">{fmtTs(z.touched_at)}</td>
                  <td className="px-3 py-1.5 font-medium text-zinc-100">{z.symbol}</td>
                  <td className={`px-3 py-1.5 ${z.direction === 'bull' ? 'text-emerald-300' : 'text-red-300'}`}>
                    {z.direction === 'bull' ? 'ACHAT' : 'VENTE'}
                  </td>
                  <td className="px-3 py-1.5 text-amber-400">{'★'.repeat(z.score)}</td>
                  <td className="px-3 py-1.5 whitespace-nowrap">
                    {z.low} – {z.high}
                  </td>
                  <td className="px-3 py-1.5">{STATUS_FR[String(z.status)] ?? z.status}</td>
                  <td className="px-3 py-1.5">
                    <TradeBadge zone={z} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
