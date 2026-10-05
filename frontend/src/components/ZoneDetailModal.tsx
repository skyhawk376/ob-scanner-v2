import { useEffect } from 'react'
import type { Zone } from '../lib/types'
import { MiniChart } from './MiniChart'

function fmt(n: number | null | undefined, digits = 4): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return n.toFixed(1)
  if (Math.abs(n) >= 1) return n.toFixed(Math.min(digits, 3))
  return n.toFixed(digits)
}

const STAR_LABELS: { key: keyof Zone; label: string }[] = [
  { key: 'star1_fvg', label: 'FVG' },
  { key: 'star2_trend', label: 'Tendance' },
  { key: 'star3_fib', label: 'Fib 0.5' },
  { key: 'star4_liquidity', label: 'Liquidité' },
  { key: 'star5_session', label: 'Session' },
]

export function ZoneDetailModal({
  zone,
  onClose,
}: {
  zone: Zone
  onClose: () => void
}) {
  const buy = zone.direction === 'bull'

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-label={`Détail ${zone.symbol}`}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        aria-label="Fermer"
        onClick={onClose}
      />

      <div className="relative z-10 flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl border border-zinc-700/80 bg-zinc-950 shadow-2xl shadow-black/60 sm:max-h-[90vh] sm:max-w-2xl sm:rounded-2xl">
        <header className="flex shrink-0 items-start justify-between gap-3 border-b border-zinc-800 px-4 py-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold tracking-wide text-zinc-100">{zone.symbol}</h2>
              {zone.symbol === 'XAUUSD' && (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                  PRIORITÉ
                </span>
              )}
              <span className="text-xs text-zinc-500">{zone.tf}</span>
              <span
                className={
                  buy
                    ? 'rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300'
                    : 'rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-red-300'
                }
              >
                {buy ? 'ACHAT' : 'VENTE'}
              </span>
              <span className="text-sm text-amber-400">
                {'★'.repeat(Math.max(0, Math.min(5, zone.score)))}
                <span className="text-zinc-600">{'☆'.repeat(Math.max(0, 5 - zone.score))}</span>
                <span className="ml-1 text-xs text-zinc-500">{zone.score}/5</span>
              </span>
            </div>
            <p className="mt-1 text-[11px] text-zinc-500">
              {zone.session_label ?? (zone.star5_pending ? 'session à l’impact' : 'hors session')}
              {' · '}
              distance {zone.distance_atr.toFixed(2)} ATR
              {zone.fresh ? ' · frais' : ''}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800 hover:text-white"
            aria-label="Fermer"
          >
            <span className="text-lg leading-none">×</span>
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <div className="border-b border-zinc-800/80 px-3 py-3 sm:px-4">
            <MiniChart zone={zone} height={280} interactive />
          </div>

          <div className="space-y-4 px-4 py-4">
            <section>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Critères ★
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                {STAR_LABELS.map(({ key, label }, i) => {
                  const on = Boolean(zone[key])
                  return (
                    <div
                      key={key}
                      className={
                        on
                          ? 'rounded-lg border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-center'
                          : 'rounded-lg border border-zinc-800 bg-zinc-900/50 px-2 py-1.5 text-center'
                      }
                    >
                      <div className={on ? 'text-amber-400' : 'text-zinc-600'}>
                        {on ? '★' : '☆'}
                        <span className="ml-0.5 text-[10px]">{i + 1}</span>
                      </div>
                      <div className={`text-[10px] ${on ? 'text-amber-200/80' : 'text-zinc-600'}`}>
                        {label}
                        {key === 'star5_session' && zone.star5_pending ? '…' : ''}
                      </div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Niveaux
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Metric
                  label={buy ? 'Entrée (bas OB)' : 'Entrée (haut OB)'}
                  value={fmt(zone.entry)}
                  color="text-blue-300"
                />
                <Metric label="SL (bord opposé)" value={fmt(zone.sl)} color="text-orange-300" />
                <Metric label="TP1" value={fmt(zone.tp1)} color="text-zinc-200" />
                <Metric label="TP2" value={fmt(zone.tp2)} color="text-zinc-200" />
                <Metric
                  label="RR TP1"
                  value={zone.rr_tp1 != null ? zone.rr_tp1.toFixed(1) : '—'}
                  color="text-zinc-200"
                />
                <Metric label="RR TP2" value={zone.rr_tp2.toFixed(1)} color="text-zinc-200" />
              </div>
            </section>

            <section>
              <h3 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-zinc-500">
                Contexte
              </h3>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Metric label="ATR" value={fmt(zone.atr)} />
                <Metric label="Distance" value={`${zone.distance_atr.toFixed(2)} ATR`} />
                <Metric
                  label="Session"
                  value={
                    zone.session_label ?? (zone.star5_pending ? 'à l’impact' : 'hors session')
                  }
                />
                <Metric label="Tendance" value={zone.trend || '—'} />
                <Metric label="Dernier cours" value={fmt(zone.last_close)} />
                <Metric label="Fib EQ" value={fmt(zone.fib_eq)} />
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  color = 'text-zinc-200',
}: {
  label: string
  value: string
  color?: string
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-3 py-2">
      <div className="text-[10px] text-zinc-500">{label}</div>
      <div className={`text-sm font-medium ${color}`}>{value}</div>
    </div>
  )
}
