import type { ReactNode } from 'react'
import type { GroupId, Timeframe } from '../lib/types'

const TFS: { id: Timeframe; label: string }[] = [
  { id: 'H1', label: 'H1' },
  { id: 'H4', label: '4h' },
  { id: 'D', label: 'Daily' },
  { id: 'W', label: 'Weekly' },
]

const GROUPS: { id: GroupId; label: string }[] = [
  { id: 'NQ100', label: 'NQ100' },
  { id: 'METAUX', label: 'Métaux' },
  { id: 'ENERGIE', label: 'Énergie' },
  { id: 'FOREX', label: 'Forex' },
  { id: 'CRYPTO', label: 'Crypto' },
]

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? 'rounded-full border border-blue-500/60 bg-blue-600/20 px-3 py-1 text-xs font-medium text-blue-200'
          : 'rounded-full border border-zinc-700 bg-zinc-900 px-3 py-1 text-xs text-zinc-400 hover:border-zinc-500 hover:text-zinc-200'
      }
    >
      {children}
    </button>
  )
}

export function FilterBar({
  tf,
  onTf,
  groups,
  onToggleGroup,
  search,
  onSearch,
  minScore,
  onMinScore,
}: {
  tf: Timeframe
  onTf: (t: Timeframe) => void
  groups: GroupId[]
  onToggleGroup: (g: GroupId) => void
  search: string
  onSearch: (s: string) => void
  minScore: number
  onMinScore: (n: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-zinc-800/80 px-4 py-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] uppercase tracking-wider text-zinc-500">TF</span>
        {TFS.map((t) => (
          <Chip key={t.id} active={tf === t.id} onClick={() => onTf(t.id)}>
            {t.label}
          </Chip>
        ))}
      </div>
      <div className="h-4 w-px bg-zinc-800" />
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[11px] uppercase tracking-wider text-zinc-500">Groupes</span>
        {GROUPS.map((g) => (
          <Chip
            key={g.id}
            active={groups.includes(g.id)}
            onClick={() => onToggleGroup(g.id)}
          >
            {g.label}
          </Chip>
        ))}
      </div>
      <div className="h-4 w-px bg-zinc-800" />
      <div className="flex items-center gap-1.5">
        <span className="text-[11px] uppercase tracking-wider text-zinc-500">Min ★</span>
        {[3, 4, 5].map((n) => (
          <Chip key={n} active={minScore === n} onClick={() => onMinScore(n)}>
            ≥{n}
          </Chip>
        ))}
      </div>
      <div className="ml-auto">
        <input
          value={search}
          onChange={(e) => onSearch(e.target.value)}
          placeholder="Rechercher... (ex: NVDA)"
          className="w-56 rounded-lg border border-zinc-700 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none focus:border-blue-500"
        />
      </div>
    </div>
  )
}
