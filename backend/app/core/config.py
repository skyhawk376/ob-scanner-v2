"""Runtime configuration (env-driven)."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    symbols_yaml: Path = ROOT / "symbols.yaml"
    cache_dir: Path = ROOT / "data" / "cache"
    results_dir: Path = ROOT / "data" / "results"

    oanda_api_key: str = ""
    oanda_account_id: str = ""
    oanda_env: str = "practice"
    oanda_api_url: str = ""

    binance_base_url: str = "https://api.binance.com"
    crypto_fallback_exchanges: str = "binance,kraken,coinbase"

    tz: str = "Europe/Paris"

    default_tfs: str = "H1,H4,D,W"
    yfinance_pause_sec: float = 0.35
    oanda_pause_sec: float = 0.05
    binance_pause_sec: float = 0.05

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_dry_run: bool = True
    telegram_max_per_hour: int = 30

    enable_scheduler: bool = False

    # Always-on host (Fly / Docker / VPS): live candle fetch + lifecycle pipeline.
    # PythonAnywhere free keeps these off (wsgi.py answers /fetch with 501 itself).
    enable_fetch: bool = True
    fetch_interval_min: int = 15
    # TFs handled by the live pipeline (fetch → scan → lifecycle). Fly sets all 7:
    # M5,M15,M30,H1,H4,D,W. Each TF runs at its own cadence (TF_SCHEDULE).
    fetch_tfs: str = "H1"
    # Per-TF cadence in minutes. The scheduler ticks every SCHED_TICK_MIN and runs the
    # TFs that are due (H1 first so the Filtre B / Telegram path keeps its latency).
    tf_schedule: str = "M5:5,M15:15,M30:30,H1:15,H4:60,D:120,W:360"
    sched_tick_min: int = 5
    # Low-TF cache retention (bars kept per symbol/TF; 0 = unlimited). Detection only
    # needs ~500 bars; lifecycle ≤ 200 bars after the OB.
    cache_max_bars: str = "M1:3000,M5:6000,M15:4000,M30:3000"
    # Expired low-TF zones (M5/M15/M30) are pruned from SQLite after N days.
    lowtf_expired_retention_days: float = 3.0
    # Telegram alerts only for zones of these TFs (default: all 7, user request
    # 2026-10-06). Narrow with e.g. ALERT_TFS=H1 — no code change needed. A TF that
    # starts alerting is armed after a silent warm-up run (no burst of old touches).
    alert_tfs: str = "M5,M15,M30,H1,H4,D,W"
    fetch_limit: int = 300
    bootstrap_limit: int = 800
    # Run a fetch right after boot when the newest H1 candle is older than this.
    bootstrap_stale_sec: int = 2 * 3600
    history_refresh_hour: int = 6
    history_refresh_minute: int = 30
    # Stale threshold reported by /health (fetch every 15 min → >3h = something is wrong)
    health_stale_sec: int = 3 * 3600

    # Soft reaction (also read directly in lifecycle via env); documented here for Settings.
    enable_soft_reaction: bool = False
    soft_reaction_r: float = 0.5
    reaction_r: float = 2.0
    # H4/D1 trend bias (info only, never filters): D1 candles fetched by the pipeline
    # at most every BIAS_D1_REFRESH_HOURS (no scan on D), H4 resampled from H1.
    bias_fetch_d1: bool = True
    bias_d1_refresh_hours: float = 6.0
    bias_d1_limit: int = 250

    # Pipeline / API default groups when `group` omitted. "ALL" = every group (incl. NQ100).
    # UI can still enable NQ100 / ENERGIE explicitly.
    default_scan_groups: str = "METAUX,FOREX,CRYPTO"
    # Option B volume (~1 trade/jour ouvré): min stars for scan/pipeline/UI defaults.
    default_min_score: int = 4

    # Filtre B hard lock (production): every API / UI / Telegram / stats path is
    # clamped to DEFAULT_SCAN_GROUPS and >= DEFAULT_MIN_SCORE. Set STRATEGY_LOCK=false
    # to get the old "explore everything" behaviour (local dev / research).
    strategy_lock: bool = True

    # ---- v3 « Kasper » engine (STRATEGY_V3.md) ----
    # Universe of the v3 scanner/alerts (independent of the old Filtre B DEFAULT_SCAN_GROUPS).
    v3_groups: str = "METAUX,FOREX,CRYPTO,NQ100"
    # NQ100 = the Nasdaq-100 index (NAS100, Yahoo NQ=F). true = also the ~60 stocks.
    v3_nq100_stocks: bool = False

    @property
    def v3_group_list(self) -> list[str]:
        return [g.strip().upper() for g in self.v3_groups.split(",") if g.strip()]

    # Entry: proximal (bull=OB high / bear=OB low) | mid (legacy 50% / open)
    entry_mode: str = "mid"

    @property
    def pipeline_tfs(self) -> list[str]:
        from .timeframes import by_priority, parse_tf_list

        return by_priority(parse_tf_list(self.fetch_tfs)) or ["H1"]

    @property
    def tf_cadence(self) -> dict[str, int]:
        from .timeframes import parse_schedule

        return parse_schedule(self.tf_schedule, self.pipeline_tfs)

    @property
    def alert_tf_list(self) -> list[str]:
        from .timeframes import parse_tf_list

        return parse_tf_list(self.alert_tfs)

    def tf_alerts_enabled(self, tf: str | None) -> bool:
        from .timeframes import normalize_tf

        return (normalize_tf(tf) or "") in self.alert_tf_list

    def cache_max_bars_for(self, tf: str) -> int:
        from .timeframes import normalize_tf

        want = normalize_tf(tf)
        for part in (self.cache_max_bars or "").split(","):
            if ":" not in part:
                continue
            k, v = part.split(":", 1)
            if normalize_tf(k) == want:
                try:
                    return max(0, int(v))
                except ValueError:
                    return 0
        return 0

    @property
    def oanda_base_url(self) -> str:
        if self.oanda_api_url:
            return self.oanda_api_url.rstrip("/")
        if self.oanda_env.lower() == "live":
            return "https://api-fxtrade.oanda.com"
        return "https://api-fxpractice.oanda.com"

    @property
    def oanda_configured(self) -> bool:
        return bool(self.oanda_api_key.strip())

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token.strip() and self.telegram_chat_id.strip())

    @property
    def db_path(self) -> Path:
        return Path(self.results_dir) / "zones.sqlite"

    @property
    def telegram_log_path(self) -> Path:
        return Path(self.results_dir) / "telegram_dryrun.log"


    def resolved_scan_groups(self, group: str | list[str] | None = None) -> list[str] | None:
        """Resolve scan/fetch group filter.

        - None / "" → default_scan_groups (METAUX,FOREX,CRYPTO unless overridden)
        - "ALL" → None (no filter = all symbols.yaml groups, including NQ100)
        - comma list or list → that set
        """
        if isinstance(group, (list, tuple, set)):
            parts = [str(g).strip().upper() for g in group if str(g).strip()]
        elif group is None or (isinstance(group, str) and not group.strip()):
            parts = [g.strip().upper() for g in self.default_scan_groups.split(",") if g.strip()]
        else:
            parts = [g.strip().upper() for g in str(group).split(",") if g.strip()]
        if not parts or parts == ["ALL"]:
            return None
        return parts


    # ---- Filtre B (live strategy universe) ----
    @property
    def strategy_groups(self) -> list[str]:
        return [g.strip().upper() for g in self.default_scan_groups.split(",") if g.strip()]

    def clamp_groups(self, group: str | list[str] | None = None) -> list[str] | None:
        """Groups allowed for a request.

        Lock OFF → same as resolved_scan_groups (None = all).
        Lock ON  → requested ∩ strategy groups; None/ALL → strategy groups.
        Returns [] when the request only asks for groups outside the strategy.
        """
        req = self.resolved_scan_groups(group)
        if not self.strategy_lock:
            return req
        allowed = self.strategy_groups
        if not allowed:
            return req
        if req is None:
            return list(allowed)
        return [g for g in req if g in allowed]

    def clamp_min_score(self, min_score: int | None = None) -> int:
        n = int(min_score if min_score is not None else self.default_min_score)
        if self.strategy_lock:
            n = max(n, int(self.default_min_score))
        return n

    def zone_in_strategy(self, group: str | None, score: int | float | None) -> bool:
        if not self.strategy_lock:
            return True
        if int(score or 0) < int(self.default_min_score):
            return False
        allowed = self.strategy_groups
        return (not allowed) or (str(group or "").upper() in allowed)


@lru_cache
def get_settings() -> Settings:
    return Settings()
