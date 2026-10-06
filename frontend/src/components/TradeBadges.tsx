import type { Zone } from '../lib/types'
import { TP_R } from '../lib/strategy'

function dot(v: number | null | undefined) {
  if (v == null) return <span className="text-zinc-500">?</span>
  if (v > 0) return <span className="text-emerald-400">▲</span>
  if (v < 0) return <span className="text-red-400">▼</span>
  return <span className="text-zinc-400">•</span>
}

/** H4 / D1 trend at touch + alignment with the OB direction (info only, no filter). */
export function BiasBadge({ zone }: { zone: Zone }) {
  const al = zone.aligned_h4d1
  const cls =
    al === true
      ? 'border-emerald-700/60 bg-emerald-900/30 text-emerald-200'
      : al === false
        ? 'border-amber-700/60 bg-amber-900/30 text-amber-200'
        : 'border-zinc-700 bg-zinc-900 text-zinc-400'
  const label = al === true ? '✅ aligné' : al === false ? '⚠️ contre' : '❔'
  return (
    <span
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] ${cls}`}
      title="Tendance au touch : clôture vs EMA50 sur bougies fermées (H4, D1). Information seulement — aucun filtrage."
    >
      H4 {dot(zone.bias_h4)} D1 {dot(zone.bias_d1)} <span>{label}</span>
    </span>
  )
}

const EXIT_FR: Record<string, string> = { tp: `TP +${TP_R}R`, sl: 'SL', time: 'time stop 1h' }

/** Realistic trade outcome (fill at mid required, 1h max). */
export function TradeBadge({ zone }: { zone: Zone }) {
  const st = zone.trade_status
  if (!st) return <span className="text-zinc-600">—</span>
  if (st === 'closed' && zone.trade_r != null) {
    const r = zone.trade_r
    const cls = r > 0 ? 'text-emerald-400' : r < 0 ? 'text-red-400' : 'text-zinc-300'
    return (
      <span className={`whitespace-nowrap ${cls}`} title={`modèle ${zone.trade_model ?? '?'} · fill ${zone.trade_fill_at ?? ''}`}>
        {r > 0 ? '+' : ''}
        {r.toFixed(2)}R <span className="text-zinc-500">({EXIT_FR[zone.trade_exit || ''] || zone.trade_exit})</span>
      </span>
    )
  }
  const lbl: Record<string, string> = {
    unfilled: 'non rempli',
    pending: 'attente fill mid',
    open: 'en cours',
  }
  return <span className="whitespace-nowrap text-zinc-500">{lbl[st] || st}</span>
}
