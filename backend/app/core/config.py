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
    fetch_tfs: str = "H1"
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
    reaction_r: float = 1.0

    # Pipeline / API default groups when `group` omitted. "ALL" = every group (incl. NQ100).
    # UI can still enable NQ100 / ENERGIE explicitly.
    default_scan_groups: str = "METAUX,FOREX,CRYPTO"
    # Option B volume (~1 trade/jour ouvré): min stars for scan/pipeline/UI defaults.
    default_min_score: int = 4

    # Entry: proximal (bull=OB high / bear=OB low) | mid (legacy 50% / open)
    entry_mode: str = "mid"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()
