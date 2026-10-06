export type Timeframe = 'M5' | 'M15' | 'M30' | 'H1' | 'H4' | 'D' | 'W'
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
  /** H4/D1 trend at touch (close vs EMA50, closed bars): 1 up, -1 down, 0 flat, null unknown */
  bias_h4?: number | null
  bias_d1?: number | null
  aligned_h4d1?: boolean | null
  bias_at?: string | null
  /** Realistic trade (fill at mid required, TP +2R / SL / time stop 1h) */
  trade_status?: 'pending' | 'unfilled' | 'open' | 'closed' | string | null
  trade_r?: number | null
  trade_exit?: 'tp' | 'sl' | 'time' | string | null
  trade_fill_at?: string | null
  trade_exit_at?: string | null
  trade_model?: string | null
  trade_tp?: number | null
}

export interface TradeSummary {
  n: number
  wins?: number
  wr: number | null
  avg_r: number | null
  sum_r?: number
  exits?: Record<string, number>
  trades_per_day?: number | null
}

export interface RealisticStats {
  method: string
  tp_r: number
  n_touched: number
  n_closed: number
  n_unfilled: number
  n_pending: number
  n_open: number
  n_unknown: number
  fill_rate: number | null
  wr: number | null
  avg_r: number | null
  sum_r: number
  exits: Record<string, number>
  weekdays: number
  trades_per_day: number | null
  aligned: TradeSummary
  not_aligned: TradeSummary
  n_aligned_unknown: number
  by_group: Record<string, TradeSummary>
  /** Realistic trades per zone TF (M5 … W) */
  by_tf?: Record<string, TradeSummary & { n_touched?: number; n_unfilled?: number }>
  models: Record<string, number>
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
  /** Alias of n_decided — réactions + échecs (trades fermés). */
  n_closed?: number
  reaction_rate: number | null
  reaction_rate_touched?: number | null
  denominator?: string
  /** Calendar span of closed trades (first→last), days. */
  span_days?: number | null
  /** n_closed / span_days when span is known. */
  trades_per_day?: number | null
  by_tf: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_score: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_group: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  by_session: Record<string, { n: number; reaction: number; echec: number; reaction_rate: number | null; reaction_rate_touched?: number | null }>
  realistic?: RealisticStats
  realistic_7d?: RealisticStats
  legacy_note?: string
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
