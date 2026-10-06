import { useEffect, useState } from 'react'
import { fetchStats, fetchZones, refreshStatuses } from '../lib/api'
import type { RealisticStats, StatsResponse, Timeframe, TradeSummary, Zone } from '../lib/types'
import { BiasBadge, TradeBadge } from './TradeBadges'

function pct(r: number | null | undefined) {
  if (r == null || Number.isNaN(r)) return '—'
  return `${(r * 100).toFixed(1)} %`
}

function fmtTpd(r: number | null | undefined) {
  if (r == null || Number.isNaN(r)) return null
  return `${r.toFixed(2)} / jour`
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
        fetchZones({ tf, minScore: 4, limit: 500, statuses: 'reaction,echec' }),
        fetchZones({ tf, minScore: 4, limit: 500, statuses: 'touchee' }),
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
            Entrée milieu OB (mid) · SL au-delà du bord distal · TP +2R · stats réelles : trade compté seulement si le mid est atteint, sortie TP / SL / time stop 1h
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
          {stats.realistic && <RealisticBlock title="Stats réelles (historique)" r={stats.realistic} />}
          {stats.realistic_7d && <RealisticBlock title="Stats réelles — 7 derniers jours" r={stats.realistic_7d} compact />}

          <h3 className="mb-2 mt-6 text-sm font-medium text-zinc-400">
            Ancienne méthode (géré dès le 1er contact, sans time stop — surestime)
          </h3>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
            <StatCard label="Zones en base" value={String(stats.n)} sub="toutes" />
            <StatCard
              label="Touchées"
              value={String(stats.n_touched)}
              sub={`dont ${pending.length} en attente`}
            />
            <StatCard
              label="Trades fermés"
              value={String(
                stats.n_closed ?? stats.n_decided ?? stats.n_reaction + stats.n_echec,
              )}
              accent="text-amber-300"
              sub={`${stats.n_reaction} réactions + ${stats.n_echec} échecs${
                fmtTpd(stats.trades_per_day)
                  ? ` · ${fmtTpd(stats.trades_per_day)}`
                  : ''
              }`}
            />
            <StatCard
              label="Réactions"
              value={String(stats.n_reaction)}
              accent="text-emerald-400"
              sub="parmi les fermés"
            />
            <StatCard
              label="Taux de réaction"
              value={pct(stats.reaction_rate)}
              sub={`dénominateur = trades fermés (${
                stats.n_closed ?? stats.n_decided ?? stats.n_reaction + stats.n_echec
              }) · parmi touchées ${pct(stats.reaction_rate_touched)}`}
              accent="text-blue-300"
            />
          </div>
          <p className="mb-4 text-xs text-zinc-500">
            Dénominateur du taux :{' '}
            <span className="text-zinc-300">
              {stats.denominator || 'décidés (réaction+échec = trades fermés)'}
            </span>
            {stats.span_days != null && stats.span_days > 0
              ? ` · fenêtre fermés ≈ ${stats.span_days.toFixed(1)} j`
              : ''}
          </p>

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
                    <th className="px-3 py-2">Tendance H4/D1</th>
                    <th className="px-3 py-2">Trade réel</th>
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
                      <td className="px-3 py-2"><BiasBadge zone={z} /></td>
                      <td className="px-3 py-2"><TradeBadge zone={z} /></td>
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
                    <th className="px-3 py-2">Résultat (ancien)</th>
                    <th className="px-3 py-2">Trade réel</th>
                    <th className="px-3 py-2">Tendance H4/D1</th>
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
                      <td className="px-3 py-2"><TradeBadge zone={z} /></td>
                      <td className="px-3 py-2"><BiasBadge zone={z} /></td>
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

function fmtR(r: number | null | undefined) {
  if (r == null || Number.isNaN(r)) return '—'
  return `${r > 0 ? '+' : ''}${r.toFixed(2)}R`
}

function SummaryRow({ label, s, wd }: { label: string; s: TradeSummary; wd?: number }) {
  const tpd = s.trades_per_day ?? (wd && wd >= 1 ? s.n / wd : null)
  return (
    <tr className="border-t border-zinc-800/60">
      <td className="py-1 text-zinc-300">{label}</td>
      <td className="py-1 text-right text-zinc-400">{s.n}</td>
      <td className="py-1 text-right text-zinc-200">{pct(s.wr)}</td>
      <td className={`py-1 text-right ${(s.avg_r ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{fmtR(s.avg_r)}</td>
      <td className="py-1 text-right text-zinc-400">{tpd != null ? tpd.toFixed(2) : '—'}</td>
    </tr>
  )
}

function RealisticBlock({ title, r, compact }: { title: string; r: RealisticStats; compact?: boolean }) {
  return (
    <div className="mb-4 rounded-xl border border-blue-900/50 bg-blue-950/10 p-3">
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div className="text-sm font-medium text-blue-200">{title}</div>
        <div className="text-[11px] text-zinc-500">{r.method}</div>
      </div>
      {!compact && (
        <div className="mb-3 grid grid-cols-2 gap-3 md:grid-cols-5">
          <StatCard label="Trades réels" value={String(r.n_closed)} accent="text-amber-300"
            sub={`${r.n_unfilled} non rempli(s) · ${r.n_pending + r.n_open} en attente/en cours`} />
          <StatCard label="Win rate" value={pct(r.wr)} accent="text-blue-300"
            sub={Object.entries(r.exits || {}).map(([k, v]) => `${k} ${v}`).join(' · ') || '—'} />
          <StatCard label="R moyen" value={fmtR(r.avg_r)} accent={(r.avg_r ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}
            sub={`Σ ${fmtR(r.sum_r)}`} />
          <StatCard label="Trades / jour ouvré" value={r.trades_per_day != null ? r.trades_per_day.toFixed(2) : '—'}
            sub={`fenêtre ≈ ${r.weekdays.toFixed(1)} j ouvrés`} />
          <StatCard label="Taux de fill" value={pct(r.fill_rate)} sub="mid atteint / (rempli + non rempli)" />
        </div>
      )}
      <table className="w-full text-xs">
        <thead className="text-zinc-500">
          <tr>
            <th className="py-1 text-left">Segment</th>
            <th className="py-1 text-right">Trades</th>
            <th className="py-1 text-right">WR</th>
            <th className="py-1 text-right">R moy.</th>
            <th className="py-1 text-right">/ jour</th>
          </tr>
        </thead>
        <tbody>
          <SummaryRow label="Tous" s={{ n: r.n_closed, wr: r.wr, avg_r: r.avg_r, trades_per_day: r.trades_per_day }} />
          <SummaryRow label="✅ Aligné H4+D1" s={r.aligned} />
          <SummaryRow label={`⚠️ Non aligné (dont ${r.n_aligned_unknown} inconnu)`} s={r.not_aligned} />
          {!compact &&
            Object.entries(r.by_group || {}).map(([g, v]) => (
              <SummaryRow key={g} label={g} s={v} wd={r.weekdays} />
            ))}
        </tbody>
      </table>
    </div>
  )
}
