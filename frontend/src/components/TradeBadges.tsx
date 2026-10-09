import type { Zone } from '../lib/types'
import { TP_R } from '../lib/strategy'

const EXIT_FR: Record<string, string> = { tp: `TP +${TP_R}R`, sl: 'SL −1R', be_exit: 'BE 0R' }

export const STATUS_FR: Record<string, string> = {
  active: 'Active',
  touchee: 'Touchée (attente bougie)',
  en_position: 'En position',
  tp: 'TP',
  sl: 'SL',
  be: 'Break-even',
  invalidee: 'Invalidée',
  expiree: 'Expirée',
}

/** v3 trade outcome: entry on LTF reversal candle, SL beyond OB, BE at +1R, TP +2R (R net of costs). */
export function TradeBadge({ zone }: { zone: Zone }) {
  const st = zone.trade_status
  if (!st) return <span className="text-zinc-600">pas d’entrée</span>
  if (st === 'closed' && zone.trade_r != null) {
    const r = zone.trade_r
    const cls = r > 0 ? 'text-emerald-400' : r < -0.5 ? 'text-red-400' : 'text-zinc-300'
    return (
      <span className={`whitespace-nowrap ${cls}`} title={`${zone.trade_trigger ?? ''} ${zone.ltf ?? ''} · entrée ${zone.trade_fill_at ?? ''}`}>
        {r > 0 ? '+' : ''}
        {r.toFixed(2)}R <span className="text-zinc-500">({EXIT_FR[zone.trade_exit || ''] || zone.trade_exit})</span>
      </span>
    )
  }
  return <span className="whitespace-nowrap text-blue-300">{st === 'be' ? 'en cours (SL à l’entrée)' : 'en cours'}</span>
}
