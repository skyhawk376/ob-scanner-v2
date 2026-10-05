"""Candle cache — parquet when pyarrow is available, else pickle (PA free)."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

OHLC_COLS = ["open", "high", "low", "close", "volume"]

try:
    import pyarrow  # noqa: F401

    _HAS_PYARROW = True
except ImportError:
    _HAS_PYARROW = False


def _safe_stem(symbol: str, tf: str) -> str:
    safe = symbol.replace("/", "_").replace("=", "_")
    return f"{safe}_{tf.upper()}"


def cache_path(cache_dir: Path, symbol: str, tf: str) -> Path:
    ext = ".parquet" if _HAS_PYARROW else ".pkl"
    return Path(cache_dir) / f"{_safe_stem(symbol, tf)}{ext}"


def _candidate_paths(cache_dir: Path, symbol: str, tf: str) -> list[Path]:
    stem = _safe_stem(symbol, tf)
    preferred = cache_path(cache_dir, symbol, tf)
    other = Path(cache_dir) / f"{stem}{'.pkl' if preferred.suffix == '.parquet' else '.parquet'}"
    return [preferred, other]


def normalize_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure UTC DatetimeIndex named 'ts' and standard OHLC columns."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLC_COLS)

    out = df.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        if "ts" in out.columns:
            out["ts"] = pd.to_datetime(out["ts"], utc=True)
            out = out.set_index("ts")
        elif "timestamp" in out.columns:
            out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)
            out = out.set_index("timestamp")
        else:
            raise ValueError("DataFrame has no DatetimeIndex or ts/timestamp column")

    if out.index.tz is None:
        out.index = out.index.tz_localize("UTC")
    else:
        out.index = out.index.tz_convert("UTC")
    out.index.name = "ts"

    rename = {c: c.lower() for c in out.columns}
    out = out.rename(columns=rename)
    for col in OHLC_COLS:
        if col not in out.columns:
            out[col] = 0.0 if col == "volume" else float("nan")
    out = out[OHLC_COLS].astype(float)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    out = out.dropna(subset=["open", "high", "low", "close"])
    return out


def _read_file(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    return pd.read_pickle(path)


def read_cache(cache_dir: Path, symbol: str, tf: str) -> pd.DataFrame:
    for path in _candidate_paths(cache_dir, symbol, tf):
        if not path.exists():
            continue
        try:
            return normalize_ohlc(_read_file(path))
        except Exception:
            continue
    return pd.DataFrame(columns=OHLC_COLS)


def write_cache(cache_dir: Path, symbol: str, tf: str, df: pd.DataFrame) -> Path:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(cache_dir, symbol, tf)
    clean = normalize_ohlc(df)
    if path.suffix == ".parquet":
        clean.to_parquet(path)
    else:
        clean.to_pickle(path)
    return path


def merge_cache(cache_dir: Path, symbol: str, tf: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """Idempotent merge on timestamp; last write wins for duplicates."""
    existing = read_cache(cache_dir, symbol, tf)
    incoming = normalize_ohlc(new_df)
    if existing.empty:
        merged = incoming
    elif incoming.empty:
        merged = existing
    else:
        merged = pd.concat([existing, incoming])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    write_cache(cache_dir, symbol, tf, merged)
    return merged


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample OHLC (e.g. H1 -> 4h, D -> W-MON)."""
    if df is None or df.empty:
        return pd.DataFrame(columns=OHLC_COLS)
    clean = normalize_ohlc(df)
    agg = clean.resample(rule, label="left", closed="left").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    return agg.dropna(subset=["open", "high", "low", "close"])
