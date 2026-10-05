import type { KeyboardEvent } from 'react'
import type { Zone } from '../lib/types'
import { MiniChart } from './MiniChart'

function Stars({ z }: { z: Zone }) {
  const flags = [z.star1_fvg, z.star2_trend, z.star3_fib, z.star4_liquidity, z.star5_session]
  return (
    <div className="flex gap-0.5" title="★1 FVG · ★2 Tendance · ★3 Fib 0.5 · ★4 Liquidité · ★5 Session">
      {flags.map((on, i) => (
        <span key={i} className={on ? 'text-amber-400' : 'text-zinc-600'}>
          {on ? '★' : '☆'}
        </span>
      ))}
      {z.star5_pending && <span className="ml-1 text-[10px] text-zinc-500">★5…</span>}
    </div>
  )
}

function fmt(n: number | null | undefined, digits = 4): string {
  if (n == null || Number.isNaN(n)) return '—'
  if (Math.abs(n) >= 1000) return n.toFixed(1)
  if (Math.abs(n) >= 1) return n.toFixed(Math.min(digits, 3))
  return n.toFixed(digits)
}

export function ZoneCard({ zone, onOpen }: { zone: Zone; onOpen?: (z: Zone) => void }) {
  const buy = zone.direction === 'bull'
  const clickable = Boolean(onOpen)

  const onKeyDown = (e: KeyboardEvent<HTMLElement>) => {
    if (!onOpen) return
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onOpen(zone)
    }
  }

  return (
    <article
      className={`flex flex-col overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/60 shadow-sm shadow-black/40 transition ${
        clickable
          ? 'cursor-pointer hover:border-zinc-600 hover:bg-zinc-900/90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-400/60'
          : ''
      }`}
      role={clickable ? 'button' : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={clickable ? () => onOpen!(zone) : undefined}
      onKeyDown={clickable ? onKeyDown : undefined}
      aria-label={
        clickable
          ? `Ouvrir le détail ${zone.symbol} ${buy ? 'ACHAT' : 'VENTE'} ${zone.score} étoiles`
          : undefined
      }
    >
      <div className="flex items-start justify-between gap-2 border-b border-zinc-800/80 px-3 py-2">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold tracking-wide text-zinc-100">{zone.symbol}</h3>
            {zone.symbol === 'XAUUSD' && (
              <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-300">
                PRIORITÉ
              </span>
            )}
            <span className="text-[11px] text-zinc-500">{zone.tf}</span>
            <span
              className={
                buy
                  ? 'rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-300'
                  : 'rounded bg-red-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-red-300'
              }
            >
              {buy ? 'ACHAT' : 'VENTE'}
            </span>
          </div>
          <div className="mt-0.5 text-[11px] text-zinc-500">
            score {zone.score}/5 · {zone.distance_atr.toFixed(2)} ATR ·{' '}
            {zone.session_label ?? (zone.star5_pending ? 'session à l’impact' : 'hors session')}
          </div>
        </div>
        <Stars z={zone} />
      </div>

      <MiniChart zone={zone} height={190} />

      <div className="grid grid-cols-4 gap-1 border-t border-zinc-800/80 px-3 py-2 text-[11px]">
        <div>
          <div className="text-zinc-500">Entrée</div>
          <div className="font-medium text-blue-300">{fmt(zone.entry)}</div>
        </div>
        <div>
          <div className="text-zinc-500">SL</div>
          <div className="font-medium text-orange-300">{fmt(zone.sl)}</div>
        </div>
        <div>
          <div className="text-zinc-500">TP1</div>
          <div className="font-medium text-zinc-200">{fmt(zone.tp1)}</div>
        </div>
        <div>
          <div className="text-zinc-500">RR</div>
          <div className="font-medium text-zinc-200">
            {zone.rr_tp1 != null ? zone.rr_tp1.toFixed(1) : '—'} · 2R
          </div>
        </div>
      </div>
    </article>
  )
}
