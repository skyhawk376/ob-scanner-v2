import { useEffect, useState } from 'react'
import { fetchStats } from '../lib/api'
import type { Timeframe, V3Stats, V3Summary } from '../lib/types'

const pct = (x: number | null | undefined) => (x == null ? '—' : `${(x * 100).toFixed(0)} %`)
const r2 = (x: number | null | undefined) => (x == null ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(2)}R`)

function Card({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-zinc-800 bg-zinc-900/50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="text-lg font-semibold text-zinc-100">{value}</div>
      {sub && <div className="text-[10px] text-zinc-500">{sub}</div>}
    </div>
  )
}

function Table({ title, rows }: { title: string; rows?: Record<string, V3Summary> }) {
  const keys = Object.keys(rows || {})
  if (!keys.length) return null
  return (
    <div className="rounded-xl border border-zinc-800">
      <div className="border-b border-zinc-800 px-3 py-2 text-[11px] uppercase tracking-wider text-zinc-500">{title}</div>
      <table className="w-full text-xs">
        <thead className="text-zinc-500">
          <tr>
            <th className="px-3 py-1 text-left"> </th>
            <th className="px-3 py-1 text-right">Trades</th>
            <th className="px-3 py-1 text-right">WR (TP)</th>
            <th className="px-3 py-1 text-right">TP / BE / SL</th>
            <th className="px-3 py-1 text-right">R moyen net</th>
            <th className="px-3 py-1 text-right">Σ R net</th>
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => {
            const s = rows![k]
            return (
              <tr key={k} className="border-t border-zinc-800/60 text-zinc-300">
                <td className="px-3 py-1">{k}</td>
                <td className="px-3 py-1 text-right">{s.n}</td>
                <td className="px-3 py-1 text-right">{pct(s.wr)}</td>
                <td className="px-3 py-1 text-right">
                  {s.exits?.tp ?? 0} / {s.exits?.be_exit ?? 0} / {s.exits?.sl ?? 0}
                </td>
                <td className={`px-3 py-1 text-right ${(s.avg_r ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>{r2(s.avg_r)}</td>
                <td className="px-3 py-1 text-right">{s.sum_r?.toFixed(1)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function Block({ title, s, note }: { title: string; s: V3Summary; note?: string }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold text-zinc-200">{title}</h3>
      {note && <div className="text-[11px] text-zinc-500">{note}</div>}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Card label="Trades clôturés" value={String(s.n)} sub={`${s.open ?? 0} en cours`} />
        <Card label="WR (TP +2R)" value={pct(s.wr)} />
        <Card label="R moyen net" value={r2(s.avg_r)} sub="après frais" />
        <Card label="Σ R net" value={s.sum_r.toFixed(1)} />
        <Card label="Entrées / jour" value={s.entries_per_day == null ? '—' : String(s.entries_per_day)} sub="jours ouvrés" />
      </div>
      <div className="grid gap-2 lg:grid-cols-2">
        <Table title="Par TF" rows={s.by_tf} />
        <Table title="Par groupe" rows={s.by_group} />
      </div>
    </section>
  )
}

export function ReactionTab({ tf }: { tf: Timeframe }) {
  const [stats, setStats] = useState<V3Stats | null>(null)
  const [all, setAll] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStats(all ? undefined : tf)
      .then(setStats)
      .catch((e) => setError(String(e)))
  }, [tf, all])

  const bt = stats?.backtest
  return (
    <div className="space-y-5 px-4 py-4">
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-zinc-200">Réaction · trades v3 Kasper</h2>
        <button
          type="button"
          onClick={() => setAll((v) => !v)}
          className="rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-300"
        >
          {all ? 'Tous TF' : `TF ${tf}`}
        </button>
      </div>
      {error && <div className="text-xs text-red-400">{error}</div>}
      {stats && (
        <>
          <div className="text-[11px] text-zinc-500">{stats.method}</div>
          <Block title="Live (depuis la mise en service v3)" s={stats.live} note={stats.go_live ? `go-live ${new Date(stats.go_live).toLocaleString('fr-FR', { timeZone: 'Europe/Paris' })}` : undefined} />
          <Block title="Historique du cache (rejoué avec les mêmes règles)" s={stats.cache} note="Trades simulés sur les bougies en cache avant et après la mise en service — pas des alertes envoyées." />
          {bt?.all && (
            <section className="space-y-2">
              <h3 className="text-sm font-semibold text-zinc-200">Backtest de contrôle (M1 historique, {bt.period?.join(' → ')})</h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                <Card label="Trades" value={String(bt.all.n)} />
                <Card label="WR (TP)" value={pct(bt.all.wr_tp)} />
                <Card label="R moyen brut" value={r2(bt.all.avg_r_gross)} />
                <Card label="R moyen net" value={r2(bt.all.avg_r_net)} />
                <Card label="Trades / jour" value={String(bt.all.per_day)} />
              </div>
            </section>
          )}
        </>
      )}
    </div>
  )
}
