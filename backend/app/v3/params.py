"""Every v3 « Kasper » parameter in one place (documented in STRATEGY_V3.md)."""
from __future__ import annotations

# ---------------------------------------------------------------- OB + impulse + FVG
ATR_LEN = 14                 # Wilder ATR on the zone TF
IMPULSE_BARS = 3             # violent move must happen within the 3 bars after the OB
IMPULSE_ATR = 1.0            # extreme of those 3 bars beyond the OB proximal edge >= 1.0 ATR
# FVG (mandatory): within the impulse, a 3-candle imbalance (k-1, k, k+1) with
# k-1 >= OB and k+1 <= OB+IMPULSE_BARS where low[k+1] > high[k-1] (bull) / high[k+1] < low[k-1] (bear).
# The zone is "armed" (touches count) from bar k+2 on.

# ---------------------------------------------------------------- stars
PIVOT_N = 3                  # fractal pivots: N bars left/right, confirmed at p+N (no repaint)
# ★ Tendance (Dow): last two confirmed swing highs AND last two swing lows at the OB bar:
#   bull = HH and HL ; bear = LH and LL ; anything else = range -> no star.
LIQ_LOOKBACK = 30            # ★ Liquidité prise: confirmed pivot low (bull) in [OB-30, OB-SWEEP_WIN]
SWEEP_WIN = 3                #   untaken until the sweep window, then pierced by a low of bars [OB-2 .. OB]
                             #   (equal lows are pivots too -> covered). Mirror for bear.
FIB_LEVEL = 0.5              # ★ Fibo: leg = OB extreme -> impulse extreme (up to the evaluation bar);
                             #   bull zone proximal (high) <= 0.5 level (whole zone in discount), bear mirror.
SESSION_START = (8, 0)       # ★ Session: OB candle OPENS Mon–Fri in [08:00, 21:00) Europe/Paris (DST-aware)
SESSION_END = (21, 0)
SESSION_TFS = ("M5", "M15", "M30", "H1", "H4")   # D/W candles span all sessions -> star never given
MIN_STARS = 4                # zones shown / alerted only with >= 4 stars (out of 5)

# ---------------------------------------------------------------- lifecycle
MAX_AGE_BARS = 300           # untouched/waiting zone expires 300 zone-TF bars after the OB
WINDOW_BARS = 3              # after a touch, reversal trigger must close within 3 zone-TF bars
AT_ZONE_ATR = 0.10           # trigger candle must reach the zone (low <= proximal + 0.10 ATR for bull)
SL_BUFFER_ATR = 0.05         # SL = distal edge -/+ 0.05 ATR (zone TF)
TP_R = 2.0                   # TP = entry +/- 2R
BE_AT_R = 1.0                # at +1R: "Passe ton SL au point d'entrée" and SL -> entry
MAX_TOUCH_ALERTS = 2         # at most 2 "Zone touchée" messages per zone (re-touch after leaving it)

# Reversal trigger (on the next lower TF, closed candles only)
PIN_WICK_BODY = 2.0          # hammer/pin: wick toward the zone >= 2x body
PIN_CLOSE_THIRD = 1.0 / 3.0  # close in the upper third (bull) / lower third (bear) of the range
MIN_BODY_FRAC = 0.05         # body floor = 5 % of range (doji handling)

LOWER_TF = {"M5": "M1", "M15": "M5", "M30": "M15", "H1": "M15", "H4": "H1", "D": "H4", "W": "D"}

TF_MIN = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D": 1440, "W": 10080}

# ---------------------------------------------------------------- alerts
ALERT_MIN_AGE_MIN = 30       # touch / entry alerts dropped if older than max(30 min, 2 lower-TF bars)
MAX_TOUCH_ALERTS_PER_CYCLE = 8   # anti-burst for "Zone touchée"; entries/results are never capped
