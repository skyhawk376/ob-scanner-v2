import type { Candle, McpToolsResponse, ScanResponse, StatsResponse, Timeframe, Zone } from './types'

const _envApi = import.meta.env.VITE_API_URL as string | undefined
// Dev: Vite proxies /api → :8000. Prod (same origin): call API at root ('').
const API_BASE =
  _envApi !== undefined
    ? String(_envApi).replace(/\/$/, '')
    : import.meta.env.DEV
      ? '/api'
      : ''

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

async function postJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST' })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text.slice(0, 200)}`)
  }
  return res.json() as Promise<T>
}

export async function health(): Promise<{ phase: string; status: string; telegram_configured?: boolean }> {
  return getJson('/health')
}

export async function runScan(opts: {
  tf: Timeframe
  groups?: string[]
  symbols?: string
  minScore?: number
}): Promise<ScanResponse> {
  const q = new URLSearchParams()
  q.set('tf', opts.tf)
  q.set('min_score', String(opts.minScore ?? 4))
  if (opts.groups && opts.groups.length > 0 && opts.groups.length < 5) {
    q.set('group', opts.groups.join(','))
  }
  if (opts.symbols?.trim()) {
    q.set('symbols', opts.symbols.trim().toUpperCase())
  }
  return postJson(`/scan?${q.toString()}`)
}

export async function fetchZones(opts: {
  tf?: Timeframe
  groups?: string[]
  minScore?: number
  limit?: number
  status?: string
  statuses?: string
  activeOnly?: boolean
}): Promise<Zone[]> {
  const q = new URLSearchParams()
  if (opts.tf) q.set('tf', opts.tf)
  q.set('min_score', String(opts.minScore ?? 4))
  q.set('limit', String(opts.limit ?? 200))
  if (opts.groups && opts.groups.length > 0 && opts.groups.length < 5) {
    q.set('group', opts.groups.join(','))
  }
  if (opts.status) q.set('status', opts.status)
  if (opts.statuses) q.set('statuses', opts.statuses)
  if (opts.activeOnly) q.set('active_only', 'true')
  const data = await getJson<{ n: number; zones: Zone[] }>(`/zones?${q.toString()}`)
  return data.zones
}

export async function fetchCandles(
  symbol: string,
  tf: Timeframe,
  limit = 180,
): Promise<Candle[]> {
  const data = await getJson<{ candles: Candle[] }>(
    `/candles/${encodeURIComponent(symbol)}?tf=${tf}&limit=${limit}`,
  )
  return data.candles
}

export async function refreshStatuses(opts: {
  tf: Timeframe
  history?: boolean
  groups?: string[]
  minScore?: number
}): Promise<{ by_status: Record<string, number>; n_zones: number; elapsed_sec: number; notifications: number }> {
  const q = new URLSearchParams()
  q.set('tf', opts.tf)
  q.set('history', opts.history ? 'true' : 'false')
  q.set('min_score', String(opts.minScore ?? 4))
  q.set('dry_run', 'true')
  if (opts.groups && opts.groups.length > 0 && opts.groups.length < 5) {
    q.set('group', opts.groups.join(','))
  }
  return postJson(`/refresh?${q.toString()}`)
}

export async function fetchStats(tf?: Timeframe): Promise<StatsResponse> {
  const q = tf ? `?tf=${tf}` : ''
  return getJson(`/stats${q}`)
}

export async function fetchMcpTools(): Promise<McpToolsResponse> {
  return getJson('/mcp/tools')
}
