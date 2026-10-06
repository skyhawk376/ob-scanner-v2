import type { TabId } from '../lib/types'

const TABS: { id: TabId; label: string }[] = [
  { id: 'scanner', label: 'Scanner' },
  { id: 'touches', label: 'OB Touchés' },
  { id: 'reaction', label: 'Réaction' },
  { id: 'claude', label: 'Claude / MCP' },
]

export function TopNav({
  tab,
  onTab,
  cacheAgeLabel,
  cacheStale,
}: {
  tab: TabId
  onTab: (t: TabId) => void
  cacheAgeLabel?: string | null
  cacheStale?: boolean
}) {
  return (
    <header className="flex items-center justify-between border-b border-zinc-800 bg-zinc-950/90 px-4 py-3 backdrop-blur">
      <div className="flex items-center gap-6">
        <div className="flex items-center gap-2">
          <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-blue-600 text-xs font-bold">
            OB
          </span>
          <div>
            <div className="text-sm font-semibold tracking-wide">Scanner 5 étoiles</div>
            <div className="text-[11px] text-zinc-500">Order Blocks · Europe/Paris</div>
          </div>
        </div>
        <nav className="flex gap-1">
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => onTab(t.id)}
              className={
                tab === t.id
                  ? 'rounded-md bg-zinc-800 px-3 py-1.5 text-sm font-medium text-white'
                  : 'rounded-md px-3 py-1.5 text-sm text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200'
              }
            >
              {t.label}
            </button>
          ))}
        </nav>
      </div>
      <div className="flex items-center gap-3 text-xs">
        {cacheAgeLabel && (
          <span
            title="Âge de la dernière bougie en cache (TF sélectionné)"
            className={
              cacheStale
                ? 'rounded-full border border-amber-700/60 bg-amber-950/50 px-2.5 py-1 text-amber-200'
                : 'rounded-full border border-zinc-700 bg-zinc-900 px-2.5 py-1 text-zinc-400'
            }
          >
            {cacheAgeLabel}
            {cacheStale ? ' · périmé' : ''}
          </span>
        )}
        <span className="hidden text-zinc-500 sm:inline">Kasper-style · scan only</span>
      </div>
    </header>
  )
}
