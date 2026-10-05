"""ATR and pivot helpers (numpy/pandas)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    n = len(close)
    tr = np.empty(n, dtype=float)
    tr[0] = high[0] - low[0]
    prev_close = close[:-1]
    tr[1:] = np.maximum(
        high[1:] - low[1:],
        np.maximum(np.abs(high[1:] - prev_close), np.abs(low[1:] - prev_close)),
    )
    return tr


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, length: int = 14) -> np.ndarray:
    tr = true_range(high, low, close)
    out = np.full(len(close), np.nan, dtype=float)
    if len(close) < length:
        return out
    # Wilder-style EMA of TR
    out[length - 1] = np.mean(tr[:length])
    alpha = 1.0 / length
    for i in range(length, len(close)):
        out[i] = out[i - 1] * (1 - alpha) + tr[i] * alpha
    # forward-fill early NaNs with first value for convenience
    first = out[length - 1]
    out[: length - 1] = first
    return out


def find_pivots(
    high: np.ndarray,
    low: np.ndarray,
    n: int,
    *,
    confirmed_only: bool = True,
    end: int | None = None,
) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Strict fractal pivots. Confirmed at i+n (anti-repaint).

    Returns (pivot_highs, pivot_lows) as lists of (index, price).
    Only pivots whose confirmation bar is <= end-1 (or len-1) are included
    when confirmed_only is True.
    """
    length = len(high)
    if end is None:
        end = length
    ph: list[tuple[int, float]] = []
    pl: list[tuple[int, float]] = []
    # last index we can confirm a pivot at i is i+n < end
    last_i = (end - 1 - n) if confirmed_only else (end - 1)
    for i in range(n, min(last_i, length - n - 1) + 1):
        window_h = high[i - n : i + n + 1]
        window_l = low[i - n : i + n + 1]
        # strict maximum / minimum
        if high[i] == np.max(window_h) and np.sum(window_h == high[i]) == 1:
            ph.append((i, float(high[i])))
        if low[i] == np.min(window_l) and np.sum(window_l == low[i]) == 1:
            pl.append((i, float(low[i])))
    return ph, pl


def arrays_from_df(df: pd.DataFrame) -> dict[str, np.ndarray]:
    return {
        "open": df["open"].to_numpy(dtype=float),
        "high": df["high"].to_numpy(dtype=float),
        "low": df["low"].to_numpy(dtype=float),
        "close": df["close"].to_numpy(dtype=float),
        "volume": (
            df["volume"].to_numpy(dtype=float)
            if "volume" in df.columns
            else np.zeros(len(df))
        ),
    }
