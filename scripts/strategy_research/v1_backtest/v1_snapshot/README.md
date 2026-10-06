# Order Block Scanner (prototype)

Local ICT-style **Order Block** scanner + web panel for Oscar, with **Kasper-style 0–5★ confluence** scoring.  
**Scan only** — no broker connection, no order placement. Not a trading system.

## Quick start

```bash
cd /workspace/ob-scanner
python3 server.py
# open http://127.0.0.1:8765/
```

Optional port: `python3 server.py 9000`

You can also serve static files with `npx serve` / `python -m http.server`, but **candle data needs `server.py`** (it proxies Yahoo + Coinbase and caches ~60s). Opening `index.html` as `file://` will not load market data.

## Panel

- **Left:** detected OBs with ★★★★☆ + flag badges (FVG / BOS / SWP / FR / PD). Click one → zone + price lines on the chart.
- **Right:** TradingView Lightweight Charts candlesticks. Dim overlays show all unmitigated OBs meeting **Min ★**; click focuses one at full opacity.
- **Controls:** symbol, M5 / M15 / H1, **Min ★** (default **5**), show mitigated, Refresh.

### Watchlist

| UI symbol | Data source | Notes |
|-----------|-------------|--------|
| BTCUSD | Coinbase `BTC-USD` | Works well from most networks |
| XAUUSD | Coinbase `PAXG-USD` | **Gold proxy** (PAXG), labeled in UI |
| XAUUSD_FUT | Yahoo `GC=F` | COMEX gold **futures** |
| EURUSD | Yahoo `EURUSD=X` | Via local proxy |
| NAS100 | Yahoo `NQ=F` | Nasdaq-100 **futures** proxy |
| GBPUSD | Yahoo `GBPUSD=X` | Via local proxy |
| USDJPY | Yahoo `USDJPY=X` | Via local proxy |
| AUDUSD | Yahoo `AUDUSD=X` | Via local proxy |
| US30 | Yahoo `YM=F` | Dow **futures** proxy |
| ETHUSD | Coinbase `ETH-USD` | Coinbase spot |
| NZDUSD | Yahoo `NZDUSD=X` | Via local proxy |
| USDCAD | Yahoo `USDCAD=X` | Via local proxy |
| USDCHF | Yahoo `USDCHF=X` | Via local proxy |
| EURJPY | Yahoo `EURJPY=X` | Via local proxy |
| GBPJPY | Yahoo `GBPJPY=X` | Via local proxy |
| SILVER | Yahoo `SI=F` | COMEX silver **futures** |
| OIL | Yahoo `CL=F` | WTI crude **futures** |
| RUSSELL | Yahoo `RTY=F` | E-mini Russell 2000 **futures** |
| SOLUSD | Coinbase `SOL-USD` | Coinbase spot |

Binance public klines are geo-blocked from some hosts (including this box); Coinbase / Yahoo are the working fallbacks.

## OB detection rules

On OHLC for the selected TF:

1. **Displacement candle** — body ≥ **1.5×** average body of the prior **20** bars, **or** close breaks the prior **10**-bar high (bull) / low (bear). Weak (body-only) candidates stay in the raw list; quality is handled by ★ scoring + Min ★ filter.
2. **Bullish OB** — last **bearish** candle before an upward displacement; zone = that candle’s **high–low**.
3. **Bearish OB** — last **bullish** candle before a downward displacement; zone = **high–low**.
4. **Mitigated** — a later close trades through the **50%** midline of the zone (below mid for bull OB, above mid for bear OB).
5. Keep up to **20** OBs per symbol/TF, ranked by **stars desc**, then unmitigated, then recent.

## 5★ checklist (Kasper / ICT confluence)

Each criterion awards **1 point** (max **5**). Stored as `stars` + `starFlags: { fvg, bos, sweep, fresh, pd }`.

| ★ | Flag | Rule (short) |
|---|------|----------------|
| 1 | **FVG** | Fair Value Gap involving the displacement bar (classic: bull `low[i+1] > high[i-1]`; bear inverse), or a clear gap in the next 1–3 bars. |
| 2 | **BOS** | Displacement **close** breaks the prior **20**-bar high (bull) / low (bear). Body-only displacement does **not** get this point. |
| 3 | **SWP** | Liquidity sweep heuristic: raid beyond prior range in the 5 bars into displacement vs the 10 bars before that, then reverse with displacement. |
| 4 | **FR** | **Fresh** — OB still unmitigated at detection time. |
| 5 | **PD** | **Premium / Discount** — bullish OB mid in the **lower** half of the local swing (discount); bearish mid in the **upper** half (premium). Swing ≈ min low of last 50 bars before disp → max high from OB through disp+5. |

**Default UI filter: Min ★ = 5** (show only high-confluence OBs). Lower the control to 0–5 to see noisier candidates.

Inspired by Kasper / ICT confluence ideas for **scanning only** — not a trading system and not financial advice.


## Recommended SL / TP (scan-only)

Aligned with Kasper/ICT + Oscar paper style. **Recommendations only** — not auto-orders.
**This is the live panel rule** (commit `03fe84b`): far-edge entry (bull high / bear low) + TP **2R** — not a proposal.

| Field | Rule |
|-------|------|
| **Entry** | Bull = OB **high**; bear = OB **low** (Oscar validated) |
| **SL** | Beyond OB extreme: bull → low − buffer; bear → high + buffer. Buffer JS = `max((high-low)*0.075, abs(entry)*1.5e-5)`; Pine = `max((high-low)*0.05, mintick*2)` |
| **TP** | Entry ± **2R** in trade direction, where `R = |entry - SL|` |
| **RR** | Fixed **1:2** (2R) for TP1 |

- Bull: entry = high; `SL = low - buffer`; `R = entry - SL`; `TP = entry + 2 * R`
- Bear: entry = low; `SL = high + buffer`; `R = SL - entry`; `TP = entry - 2 * R`

Surfaces: local list row (`SL … · TP … · 2R`), chart Entry/SL/TP lines when an OB is selected, Pine labels + optional lines (`showSlTp`), and alert messages (`SL=… TP=…`).

## API (local)

- `GET /api/health`
- `GET /api/symbols`
- `GET /api/candles?symbol=BTCUSD&tf=M15`

Responses are JSON; candles are `{ time, open, high, low, close, volume }` (unix seconds).

## Limits & caveats

- **No API keys**; free public endpoints only.
- In-memory cache ~**60 seconds** per symbol/TF.
- Coinbase returns a limited candle window (~300 bars).
- Yahoo chart data can throttle (HTTP 429); the server retries, then falls back to a **disk cache** under `cache/` (seeded snapshots for EURUSD / NAS100 / XAU). UI note shows when stale.
- Live Coinbase (BTC / PAXG) is preferred when available.
- Gold: **PAXG** proxy (`XAUUSD`) or **GC=F** futures (`XAUUSD_FUT`) — not Loco London XAUUSD from a bank feed.
- Times in the list are shown in **Europe/Paris (PT)**.
- Sweep / P-D heuristics are simplified; expect some false positives/negatives vs discretionary ICT marking.

## Stack

- `index.html` + `styles.css` + `app.js` (CDN: `lightweight-charts@4.2.1`)
- `server.py` — static + proxy (stdlib only)
- `selftest_stars.mjs` — offline star-count sanity check on `cache/*.json`


## TradingView (Pine)

Companion Pine v6 overlay: [`OB_5Star_Scanner.pine`](OB_5Star_Scanner.pine) — same Kasper-style 5★ OB rules as `app.js` (as close as Pine allows). Install + alert steps (FR): [`TRADINGVIEW.md`](TRADINGVIEW.md).

## Files

```
/workspace/ob-scanner/
  index.html
  styles.css
  app.js
  server.py
  README.md
  selftest_stars.mjs
  OB_5Star_Scanner.pine
  OB_Retest_Multi.pine
  RETEST_MULTI.md
  TRADINGVIEW.md
  cache/
```


## Sync des cochés (multi-appareils)

Dans la sidebar, sous les filtres de cochés : champ **Sync**, boutons **Générer** et **Lier / Charger**.

1. Sur l’appareil A : **Générer** → un code `OB-……` est créé et stocké localement + cloud.
2. Sur l’appareil B : coller le même code → **Lier / Charger** → union des clés cochées (local ∪ cloud).
3. Chaque coche / « Tout décocher » met à jour `localStorage` et pousse vers le cloud (~400 ms debounce).

Sans code, le comportement reste 100 % local (`ob-scanner-checked-v1`). Voir aussi `DEPLOY.md`.
