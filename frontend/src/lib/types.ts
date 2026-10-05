export type Timeframe = 'H1' | 'H4' | 'D' | 'W'
export type GroupId = 'NQ100' | 'METAUX' | 'ENERGIE' | 'FOREX' | 'CRYPTO'
export type TabId = 'scanner' | 'touches' | 'reaction' | 'claude'
export type ZoneStatus = 'active' | 'touchee' | 'reaction' | 'echec' | 'expiree' | string

export interface Zone {
  id: string
  symbol: string
  tf: string
  direction: 'bull' | 'bear' | string
  ob_index: number
  bos_index: number
  leg_index: number
  ts_ob: string
  ts_bos: string
  low: number
  high: number
  open: number
  close: number
  star1_fvg: boolean
  star2_trend: boolean
  star3_fib: boolean
  star4_liquidity: boolean
  star5_session: boolean
  star5_pending: boolean
  score: number
  fresh: boolean
  trend: string
  entry: number
  sl: number
  tp1: number | null
  tp2: number
  rr_tp1: number | null
  rr_tp2: number
  atr: number
  fib_eq: number
  swing_low: number
  swing_high: number
  distance_atr: number
  last_close: number
  session_label: string | null
  sweep: boolean
  status?: ZoneStatus
  touched_at?: string | null
  touched_session?: string | null
  reacted_at?: string | null
  failed_at?: string | null
  expired_at?: string | null
  outcome?: string | null
  mfe_r?: number
  mae_r?: number
  star5_at_touch?: boolean | null
}

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
}

export interface ScanResponse {
  tf: string
  elapsed_sec: number
  n_zones: number
  symbols_scanned: number
  symbols_ok: number
  zones: Zone[]
  refresh?: { mode?: string; updated?: number; by_status?: Record<string, number>; elapsed_sec?: number; error?: string }
}

export interface StatsResponse {
  n: number
  by_status: Record<string, number>
  n_touched: number
  n_reaction: number
  n_echec: number
  n_decided?: number
  reaction_rate: number | null
  reaction_rate_touched?: number | null
  denominator?: string
  by_tf: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_score: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_group: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_session: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
}

export interface HealthResponse {
  status: string
  phase: string
  cache_last_candle?: string | null
  cache_age_sec?: number | null
  telegram_configured?: boolean
}

export interface CacheStatus {
  tf: string
  last_candle: string | null
  age_sec: number | null
  n_files?: number
  symbol?: string | null
}

export interface McpToolsResponse {
  status: string
  phase: string
  tools: { name: string; args: string[]; description?: string }[]
  note: string
  run?: { command: string; args: string[]; cwd: string }
  claude_desktop?: { mcpServers: Record<string, { command: string; args: string[]; cwd: string }> }
}
