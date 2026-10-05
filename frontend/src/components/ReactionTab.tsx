import { useEffect, useState } from 'react'
import { fetchStats, fetchZones, refreshStatuses } from '../lib/api'
import type { StatsResponse, Timeframe, Zone } from '../lib/types'

function pct(r: number | null | undefined) {
  if (r == null || Number.isNaN(r)) return '—'
  return `${(r * 100).toFixed(1)} %`
}

function fmtTs(s?: string | null) {
  if (!s) return '—'
  try {
    return new Date(s).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })
  } catch {
    return s
  }
}

export function ReactionTab({ tf }: { tf: Timeframe }) {
  const [stats, setStats] = useState<StatsResponse | null>(null)
  const [zones, setZones] = useState<Zone[]>([])
  const [pending, setPending] = useState<Zone[]>([])
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  const load = async () => {
    setLoading(true)
    try {
      const [s, z, p] = await Promise.all([
        fetchStats(tf),
        fetchZones({ tf, minScore: 1, limit: 500, statuses: 'reaction,echec' }),
        fetchZones({ tf, minScore: 1, limit: 500, statuses: 'touchee' }),
      ])
      setStats(s)
      z.sort((a, b) =>
        (b.reacted_at || b.failed_at || '').localeCompare(a.reacted_at || a.failed_at || ''),
      )
      setZones(z)
      p.sort((a, b) => (b.touched_at || '').localeCompare(a.touched_at || ''))
      setPending(p)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [tf])

  const onRefresh = async () => {
    setRefreshing(true)
    try {
      await refreshStatuses({ tf, history: true, minScore: 4 })
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  return (
    <div className="px-4 py-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">Réaction</h2>
          <p className="text-xs text-zinc-500">
            Soft +0,5R (défaut) ou +1R sans SL = réaction · wick/clôture au SL uniquement = échec
          </p>
        </div>
        <button
          type="button"
          onClick={onRefresh}
          disabled={refreshing}
          className="rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-200 hover:border-blue-500 disabled:opacity-50"
        >
          {refreshing ? 'Calcul…' : 'Recalculer stats'}
        </button>
      </div>

      {loading || !stats ? (
        <p className="text-sm text-zinc-500">Chargement…</p>
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
            <StatCard label="Zones en base" value={String(stats.n)} sub="toutes" />
            <StatCard
              label="Touchées (dénominateur)"
              value={String(stats.n_touched)}
              sub="base des stats"
            />
            <StatCard
              label="Réactions"
              value={String(stats.n_reaction)}
              accent="text-emerald-400"
              sub={`${pending.length} en attente`}
            />
            <StatCard
              label="Taux (parmi décidés)"
              value={pct(stats.reaction_rate)}
              sub={`${stats.n_echec} échecs · ${stats.n_decided ?? stats.n_reaction + stats.n_echec} décidés · touchés ${pct(stats.reaction_rate_touched)}`}
              accent="text-blue-300"
            />
          </div>

          <div className="mb-6 grid gap-3 md:grid-cols-2">
            <BucketTable title="Par groupe (N = touchées)" data={stats.by_group} />
            <BucketTable title="Par score (N = touchées)" data={stats.by_score} />
            <BucketTable title="Par TF (N = touchées)" data={stats.by_tf} />
            <BucketTable title="Par session au touch (N = touchées)" data={stats.by_session} />
          </div>

          <h3 className="mb-2 text-sm font-medium text-zinc-300">
            En attente de réaction ({pending.length})
          </h3>
          {pending.length === 0 ? (
            <p className="mb-6 text-sm text-zinc-500">Aucune zone touchée en cours pour {tf}.</p>
          ) : (
            <div className="mb-6 overflow-hidden rounded-xl border border-amber-900/40">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase text-zinc-500">
                  <tr>
                    <th className="px-3 py-2">Symbole</th>
                    <th className="px-3 py-2">★</th>
                    <th className="px-3 py-2">Touché</th>
                    <th className="px-3 py-2">Session</th>
                    <th className="px-3 py-2">MFE</th>
                  </tr>
                </thead>
                <tbody>
                  {pending.slice(0, 80).map((z) => (
                    <tr key={z.id} className="border-t border-zinc-800/80">
                      <td className="px-3 py-2 font-medium">
                        {z.symbol} <span className="text-zinc-500">{z.tf}</span>
                      </td>
                      <td className="px-3 py-2 text-amber-400">{z.score}★</td>
                      <td className="px-3 py-2 text-zinc-400">{fmtTs(z.touched_at)}</td>
                      <td className="px-3 py-2 text-zinc-500">{z.touched_session || '—'}</td>
                      <td className="px-3 py-2 text-zinc-400">{z.mfe_r?.toFixed(2) ?? '—'}R</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <h3 className="mb-2 text-sm font-medium text-zinc-300">Détail réaction / échec</h3>
          {zones.length === 0 ? (
            <p className="text-sm text-zinc-500">Pas encore de résultats décidés pour {tf}.</p>
          ) : (
            <div className="overflow-hidden rounded-xl border border-zinc-800">
              <table className="w-full text-left text-sm">
                <thead className="bg-zinc-900 text-xs uppercase text-zinc-500">
                  <tr>
                    <th className="px-3 py-2">Symbole</th>
                    <th className="px-3 py-2">Résultat</th>
                    <th className="px-3 py-2">★</th>
                    <th className="px-3 py-2">MFE / MAE</th>
                    <th className="px-3 py-2">Session (touch)</th>
                  </tr>
                </thead>
                <tbody>
                  {zones.map((z) => (
                    <tr key={z.id} className="border-t border-zinc-800/80">
                      <td className="px-3 py-2 font-medium">
                        {z.symbol} <span className="text-zinc-500">{z.tf}</span>
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={
                            z.status === 'reaction' ? 'text-emerald-400' : 'text-red-400'
                          }
                        >
                          {z.status === 'reaction' ? 'Réaction' : 'Échec'}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-amber-400">{z.score}★</td>
                      <td className="px-3 py-2 text-zinc-400">
                        {z.mfe_r?.toFixed(2) ?? '—'}R / {z.mae_r?.toFixed(2) ?? '—'}R
                      </td>
                      <td className="px-3 py-2 text-zinc-500">{z.touched_session || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  accent,
}: {
  label: string
  value: string
  sub?: string
  accent?: string
}) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 px-4 py-3">
      <div className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${accent || 'text-zinc-100'}`}>{value}</div>
      {sub && <div className="text-xs text-zinc-500">{sub}</div>}
    </div>
  )
}

function BucketTable({
  title,
  data,
}: {
  title: string
  data: Record<
    string,
    {
      n: number
      reaction: number
      echec: number
      reaction_rate: number | null
      reaction_rate_touched?: number | null
    }
  >
}) {
  const rows = Object.entries(data)
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="mb-2 text-xs font-medium uppercase tracking-wider text-zinc-500">{title}</div>
      {rows.length === 0 ? (
        <p className="text-xs text-zinc-600">—</p>
      ) : (
        <table className="w-full text-xs">
          <thead className="text-zinc-500">
            <tr>
              <th className="py-1 text-left">Clé</th>
              <th className="py-1 text-right">N touch.</th>
              <th className="py-1 text-right">Réac.</th>
              <th className="py-1 text-right">Échec</th>
              <th className="py-1 text-right">Taux déc.</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k} className="border-t border-zinc-800/60">
                <td className="py-1 text-zinc-300">{k}</td>
                <td className="py-1 text-right text-zinc-400">{v.n}</td>
                <td className="py-1 text-right text-emerald-400">{v.reaction}</td>
                <td className="py-1 text-right text-red-400">{v.echec}</td>
                <td className="py-1 text-right text-zinc-300">{pct(v.reaction_rate)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
