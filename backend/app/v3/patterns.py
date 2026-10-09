"""Reversal candles on the lower TF (v3 entry trigger)."""
from __future__ import annotations

from . import params as P


def reversal_kind(bull: bool, po: float, pc: float, o: float, h: float, l: float, c: float) -> str | None:
    """'englobante' | 'marteau' (bull) / 'étoile filante' (bear) | None.

    Engulfing (bull): previous candle bearish, current bullish, current body engulfs the
    previous body (o <= pc and c >= po). Hammer / pin bar (bull): lower wick >= 2x body
    and close in the upper third of the range. Mirror for bear.
    """
    rng = h - l
    if rng <= 0:
        return None
    body = max(abs(c - o), P.MIN_BODY_FRAC * rng)
    if bull:
        if pc < po and c > o and o <= pc and c >= po:
            return "englobante"
        lower = min(o, c) - l
        if lower >= P.PIN_WICK_BODY * body and c >= h - P.PIN_CLOSE_THIRD * rng:
            return "marteau"
    else:
        if pc > po and c < o and o >= pc and c <= po:
            return "englobante"
        upper = h - max(o, c)
        if upper >= P.PIN_WICK_BODY * body and c <= l + P.PIN_CLOSE_THIRD * rng:
            return "étoile filante"
    return None
