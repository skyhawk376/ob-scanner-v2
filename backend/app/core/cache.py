"""Candle cache — parquet when pyarrow is available, else plain pickle (no Arrow dtypes)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
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


def _to_plain_payload(df: pd.DataFrame) -> dict:
    """Numpy-only payload — unpickles without pyarrow."""
    clean = normalize_ohlc(df)
    if clean.empty:
        return {
            "ts": np.asarray([], dtype=np.int64),
            **{c: np.asarray([], dtype=np.float64) for c in OHLC_COLS},
        }
    ts = np.asarray([int(x.timestamp()) for x in clean.index], dtype=np.int64)
    return {
        "ts": ts,
        **{c: np.asarray(clean[c], dtype=np.float64) for c in OHLC_COLS},
    }


def _from_plain_payload(obj) -> pd.DataFrame:
    if isinstance(obj, pd.DataFrame):
        return normalize_ohlc(obj)
    if not isinstance(obj, dict) or "ts" not in obj:
        raise TypeError(f"unsupported cache payload: {type(obj)}")
    data = {c: obj[c] for c in OHLC_COLS}
    idx = pd.to_datetime(obj["ts"], unit="s", utc=True)
    return normalize_ohlc(pd.DataFrame(data, index=idx))


def _read_file(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    import pickle

    with path.open("rb") as f:
        obj = pickle.load(f)
    return _from_plain_payload(obj)


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
        import pickle

        with path.open("wb") as f:
            pickle.dump(_to_plain_payload(clean), f, protocol=4)
    return path


def merge_cache(
    cache_dir: Path, symbol: str, tf: str, new_df: pd.DataFrame, *, max_bars: int = 0
) -> pd.DataFrame:
    """Idempotent merge on timestamp; last write wins for duplicates.

    max_bars > 0 keeps only the newest N bars (low-TF retention)."""
    existing = read_cache(cache_dir, symbol, tf)
    incoming = normalize_ohlc(new_df)
    if existing.empty:
        merged = incoming
    elif incoming.empty:
        merged = existing
    else:
        merged = pd.concat([existing, incoming])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    if max_bars and len(merged) > max_bars:
        merged = merged.iloc[-int(max_bars):]
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


def cache_freshness(cache_dir: Path, tf: str = "H1", sample_limit: int = 40) -> dict:
    """Return last candle time across cache files for a TF (for UI stale badge).

    Scans up to sample_limit files matching *_TF.pkl / *_TF.parquet.
    """
    from datetime import datetime, timezone

    cache_dir = Path(cache_dir)
    if not cache_dir.is_dir():
        return {"tf": tf, "last_candle": None, "age_sec": None, "n_files": 0, "symbol": None}

    tf_u = tf.upper()
    files = sorted(
        list(cache_dir.glob(f"*_{tf_u}.pkl")) + list(cache_dir.glob(f"*_{tf_u}.parquet"))
    )
    best_ts = None
    best_sym = None
    checked = 0
    for path in files[: max(1, sample_limit)]:
        checked += 1
        try:
            if path.suffix == ".parquet":
                df = pd.read_parquet(path)
            else:
                df = _read_file(path)
            df = normalize_ohlc(df)
            if df.empty:
                continue
            ts = df.index[-1]
            if best_ts is None or ts > best_ts:
                best_ts = ts
                # stem like XAUUSD_H1
                best_sym = path.stem.rsplit("_", 1)[0]
        except Exception:
            continue

    if best_ts is None:
        return {"tf": tf_u, "last_candle": None, "age_sec": None, "n_files": checked, "symbol": None}

    if getattr(best_ts, "tzinfo", None) is None:
        best_ts = best_ts.tz_localize("UTC")
    else:
        best_ts = best_ts.tz_convert("UTC")
    now = datetime.now(timezone.utc)
    age = (now - best_ts.to_pydatetime()).total_seconds()
    return {
        "tf": tf_u,
        "last_candle": best_ts.isoformat(),
        "age_sec": int(age),
        "n_files": checked,
        "n_total": len(files),
        "symbol": best_sym,
    }
