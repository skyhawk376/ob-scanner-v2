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


@lru_cache
def get_settings() -> Settings:
    return Settings()
