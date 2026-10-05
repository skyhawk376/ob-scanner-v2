import type { Zone } from '../lib/types'
import { ZoneCard } from './ZoneCard'

export function Mosaic({
  zones,
  scanning,
  error,
  hasScanned,
  elapsed,
}: {
  zones: Zone[]
  scanning: boolean
  error: string | null
  hasScanned: boolean
  elapsed: number | null
}) {
  if (scanning) {
    return (
      <div className="px-4 pb-8 text-center text-sm text-zinc-500">
        Analyse des OrderBlocks en cours…
      </div>
    )
  }

  if (error) {
    return (
      <div className="mx-4 rounded-lg border border-red-900/50 bg-red-950/40 px-4 py-3 text-sm text-red-200">
        {error}
      </div>
    )
  }

  if (!hasScanned) {
    return (
      <div className="mx-auto max-w-md px-6 py-16 text-center">
        <p className="text-sm text-zinc-500">
          Choisissez les timeframes et groupes, puis cliquez sur{' '}
          <span className="text-zinc-300">Scanner les OrderBlocks</span> pour afficher la mosaïque.
        </p>
      </div>
    )
  }

  if (zones.length === 0) {
    return (
      <div className="mx-auto max-w-md px-6 py-16 text-center text-sm text-zinc-500">
        Aucune zone fraîche ≥ seuil pour ces filtres. Essayez un autre TF, baissez le minimum d’étoiles,
        ou élargissez les groupes.
      </div>
    )
  }

  return (
    <div className="px-4 pb-10">
      <div className="mb-3 flex items-center justify-between text-xs text-zinc-500">
        <span>
          {zones.length} zone{zones.length > 1 ? 's' : ''} · tri score / Fib / distance
          {elapsed != null ? ` · ${elapsed.toFixed(1)}s` : ''}
        </span>
        <span className="text-zinc-600">Vert = ZONE ACHAT · Rouge = ZONE VENTE</span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {zones.map((z) => (
          <ZoneCard key={z.id} zone={z} />
        ))}
      </div>
    </div>
  )
}
