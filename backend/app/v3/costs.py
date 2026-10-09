"""Per-asset trading costs (price units) — extends scripts/strategy_research/common.costs
to the whole live universe. (spread, commission round trip, slippage per market/stop leg)."""
from __future__ import annotations

_FX_SPREAD_PIPS = {"EURUSD": 0.2, "GBPUSD": 0.4, "USDJPY": 0.3, "USDCAD": 0.5, "AUDUSD": 0.3,
                   "USDCHF": 0.5, "EURJPY": 0.6, "GBPJPY": 1.0, "EURGBP": 0.5}
_CRYPTO_MAJOR = {"BTC", "ETH", "SOL"}


def costs(sym: str, price: float, group: str = "") -> tuple[float, float, float]:
    s = sym.upper()
    g = (group or "").upper()
    if g == "FOREX" or (len(s) == 6 and s.isalpha() and g not in ("CRYPTO", "NQ100", "METAUX")):
        pip = 1e-2 if s.endswith("JPY") else 1e-4
        sp = _FX_SPREAD_PIPS.get(s, 1.2)          # crosses: ~1.2 pip raw spread
        return sp * pip, 0.6 * pip, 0.2 * pip
    if s == "XAUUSD":
        return 0.25, 0.07, 0.10
    if s == "XAGUSD":
        return 0.025, 0.004, 0.01
    if s in ("XPTUSD", "XPDUSD", "COPPER"):
        return 4e-4 * price, 0.0, 2e-4 * price
    if s == "NAS100":
        return 1.5, 0.0, 1.0
    if g == "CRYPTO" or s in _CRYPTO_MAJOR:
        if s in _CRYPTO_MAJOR:
            return 1e-4 * price, 5e-4 * price, 2e-4 * price
        return 3e-4 * price, 5e-4 * price, 3e-4 * price   # alts: wider book
    # NQ100 stocks / anything else: 2 bp spread, 1 bp slippage
    return 2e-4 * price, 0.0, 1e-4 * price


def cost_r(sym: str, entry: float, risk: float, group: str = "", stop_exit: bool = True) -> float:
    """Round-trip cost of one manual market-entry trade, in R."""
    if risk <= 0:
        return 0.0
    sp, comm, slip = costs(sym, entry, group)
    total = sp + comm + slip + (slip if stop_exit else 0.0)
    return total / risk
