import type { Zone } from './types'

/** XAUUSD pinned, then score desc, ★3, distance. */
export function sortZones(zones: Zone[]): Zone[] {
  return [...zones].sort((a, b) => {
    const pin = (z: Zone) => (z.symbol === 'XAUUSD' ? 0 : 1)
    if (pin(a) !== pin(b)) return pin(a) - pin(b)
    if (b.score !== a.score) return b.score - a.score
    if (Number(b.star3_fib) !== Number(a.star3_fib)) {
      return Number(b.star3_fib) - Number(a.star3_fib)
    }
    return a.distance_atr - b.distance_atr
  })
}

export function filterZones(
  zones: Zone[],
  opts: { search?: string; groups?: string[]; groupOf?: (symbol: string) => string | undefined },
): Zone[] {
  let out = zones
  const q = opts.search?.trim().toUpperCase()
  if (q) {
    out = out.filter((z) => z.symbol.includes(q))
  }
  if (opts.groups && opts.groups.length > 0 && opts.groupOf) {
    const set = new Set(opts.groups)
    out = out.filter((z) => {
      const g = opts.groupOf!(z.symbol)
      return g ? set.has(g) : true
    })
  }
  return out
}
