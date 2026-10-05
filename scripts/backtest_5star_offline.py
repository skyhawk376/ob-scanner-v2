#!/usr/bin/env python3
"""
Offline Kasper-style OB 5★ backtest (v2 engine).

Causal walk-forward on candle cache:
  - detect_zones on expanding window (virgin + score filter at first sight)
  - simulate_lifecycle: entry on return to zone, SL beyond OB,
    TP = opposing liquidity OR reaction at +1R (soft 0.5R only if --soft-r > 0)

Does not fetch live data or deploy. Cache-only.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.core.cache import read_cache  # noqa: E402
from app.core.lifecycle import (  # noqa: E402
    STATUS_ECHEC,
    STATUS_REACTION,
    simulate_lifecycle,
)
from app.core.symbols import load_instruments  # noqa: E402
from app.engine.detect import detect_zones  # noqa: E402
from app.engine.params import params_for_tf  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")


def _r_for_outcome(outcome: str | None, reaction_threshold_r: float | None) -> float | None:
    if outcome == STATUS_ECHEC:
        return -1.0
    if outcome == STATUS_REACTION:
        return float(reaction_threshold_r) if reaction_threshold_r is not None else 1.0
    return None  # expiree / active / touchee → open/timeout


def backtest_symbol(
    symbol: str,
    group: str,
    cache_dir: str,
    tf: str,
    min_score: int,
    soft_reaction_r: float,
    reaction_r: float,
    warm_bars: int = 80,
) -> dict:
    df = read_cache(Path(cache_dir), symbol, tf)
    if df is None or len(df) < warm_bars + 30:
        return {
            "symbol": symbol,
            "group": group,
            "bars": 0 if df is None else len(df),
            "trades": [],
            "error": "insufficient_bars" if df is not None and not df.empty else "no_cache",
            "from": None,
            "to": None,
        }

    params = params_for_tf(tf)
    seen: set[tuple[str, str]] = set()
    trades: list[dict] = []

    for j in range(warm_bars, len(df)):
        sub = df.iloc[: j + 1]
        zones = detect_zones(
            sub,
            symbol=symbol,
            tf=tf,
            params=params,
            min_score=min_score,
            require_fresh=True,
            require_fvg=True,
        )
        for z in zones:
            key = (z.direction, z.ts_ob)
            if key in seen:
                continue
            seen.add(key)
            zd = z.to_dict()
            # detection time = last closed bar of this window (detect drops forming bar)
            det_i = len(sub) - 2 if len(sub) > 1 else len(sub) - 1
            det_ts = str(sub.index[det_i])
            life = simulate_lifecycle(
                df,
                zd,
                soft_reaction_r=soft_reaction_r,
                reaction_r=reaction_r,
            )
            r_mult = _r_for_outcome(life.outcome, life.reaction_threshold_r)
            trades.append(
                {
                    "symbol": symbol,
                    "group": group,
                    "tf": tf.upper(),
                    "direction": z.direction,
                    "ts_ob": z.ts_ob,
                    "ts_bos": z.ts_bos,
                    "detected_at": det_ts,
                    "score": int(z.score),
                    "star1_fvg": int(z.star1_fvg),
                    "star2_trend": int(z.star2_trend),
                    "star3_fib": int(z.star3_fib),
                    "star4_liquidity": int(z.star4_liquidity),
                    "star5_session": int(z.star5_session),
                    "session_label": z.session_label or "",
                    "entry": z.entry,
                    "sl": z.sl,
                    "tp1": z.tp1 if z.tp1 is not None else "",
                    "rr_tp1": z.rr_tp1 if z.rr_tp1 is not None else "",
                    "atr": z.atr,
                    "outcome": life.outcome or life.status,
                    "status": life.status,
                    "touched_at": life.touched_at or "",
                    "touched_session": life.touched_session or "",
                    "reacted_at": life.reacted_at or "",
                    "failed_at": life.failed_at or "",
                    "expired_at": life.expired_at or "",
                    "mfe_r": round(float(life.mfe_r), 4),
                    "mae_r": round(float(life.mae_r), 4),
                    "reaction_threshold_r": life.reaction_threshold_r
                    if life.reaction_threshold_r is not None
                    else "",
                    "r": r_mult if r_mult is not None else "",
                    "closed": int(r_mult is not None),
                }
            )

    return {
        "symbol": symbol,
        "group": group,
        "bars": len(df),
        "from": str(df.index.min()),
        "to": str(df.index.max()),
        "trades": trades,
        "error": None,
    }


def _worker(args: tuple) -> dict:
    return backtest_symbol(*args)


def _agg(trades: list[dict]) -> dict:
    closed = [t for t in trades if t.get("closed")]
    opens = [t for t in trades if not t.get("closed")]
    if not closed:
        return {
            "signals": len(trades),
            "closed": 0,
            "opens": len(opens),
            "wins": 0,
            "losses": 0,
            "winrate": None,
            "avg_r": None,
            "sum_r": 0.0,
            "expectancy": None,
            "max_dd": None,
            "profit_factor": None,
        }
    rs = [float(t["r"]) for t in closed]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    # equity / max DD in R
    eq = 0.0
    peak = 0.0
    max_dd = 0.0
    for r in rs:
        eq += r
        peak = max(peak, eq)
        max_dd = max(max_dd, peak - eq)
    sum_win = sum(wins) if wins else 0.0
    sum_loss = abs(sum(losses)) if losses else 0.0
    pf = (sum_win / sum_loss) if sum_loss > 0 else (float("inf") if sum_win > 0 else None)
    return {
        "signals": len(trades),
        "closed": len(closed),
        "opens": len(opens),
        "wins": len(wins),
        "losses": len(losses),
        "winrate": len(wins) / len(closed),
        "avg_r": sum(rs) / len(rs),
        "sum_r": sum(rs),
        "expectancy": sum(rs) / len(rs),
        "max_dd": max_dd,
        "profit_factor": pf,
    }


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{100.0 * x:.2f}%"


def _fmt_r(x: float | None) -> str:
    if x is None:
        return "—"
    if x == float("inf"):
        return "∞"
    return f"{x:.4f}"


def _to_paris(ts: str | None) -> str:
    if not ts:
        return "—"
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if t.tzinfo is None:
            from datetime import timezone

            t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(PARIS).strftime("%Y-%m-%d %H:%M %Z")
    except Exception:
        return str(ts)


def write_report(
    path: Path,
    *,
    meta: dict,
    all_trades: list[dict],
    coverage: list[dict],
) -> None:
    tot = _agg(all_trades)
    lines: list[str] = []
    lines.append("# Backtest OB 5★ Kasper-style (v2 engine, offline)")
    lines.append("")
    lines.append(f"Generated: **{_to_paris(meta['generated_at'])}** (Europe/Paris)")
    lines.append("")
    lines.append("## Method")
    lines.append("")
    lines.append(
        "- Engine: `ob-scanner-v2-fly` `detect_zones` + `simulate_lifecycle` "
        "(branch always-on)."
    )
    lines.append(
        "- OB = last opposite candle before impulse/BOS; stars = FVG / trend / "
        "Fib 0.5 / liquidity / session; virgin OB required at first causal sight."
    )
    lines.append(
        "- Entry = first return (wick intersect) to zone after OB+2; "
        "SL beyond OB (+ ATR buffer); TP = opposing liquidity **or** reaction "
        f"metric (+{meta['reaction_r']}R); soft reaction "
        f"**{meta['soft_reaction_r']}R** "
        + ("ON" if meta["soft_reaction_r"] > 0 else "OFF")
        + "."
    )
    lines.append(
        f"- Filter: `min_score={meta['min_score']}`, `require_fvg=True`, "
        f"`require_fresh=True`, TF=`{meta['tf']}`."
    )
    lines.append(
        "- Causal walk-forward: expanding window; each `(direction, ts_ob)` "
        "taken once at first appearance; lifecycle then run on full series."
    )
    lines.append(
        "- Closed trades only for WR / avg R / expectancy / max DD. "
        "Outcomes `expiree` / still `active` / `touchee` at end of cache = open "
        "(excluded from WR)."
    )
    lines.append(
        "- R attribution: `echec` = **-1R**; `reaction` = "
        f"**+reaction_threshold_r** (soft min → often +{meta['soft_reaction_r']}R "
        "when soft ON)."
    )
    lines.append("- No live fetch, no deploy, no invented fills.")
    lines.append("")
    lines.append("## Cache coverage")
    lines.append("")
    lines.append(f"- Cache dir: `{meta['cache_dir']}`")
    lines.append(f"- Symbols scanned: **{meta['n_symbols']}** (with data: **{meta['n_with_data']}**)")
    if coverage:
        mins = [c["from"] for c in coverage if c.get("from")]
        maxs = [c["to"] for c in coverage if c.get("to")]
        if mins and maxs:
            lines.append(
                f"- Global bar range (UTC): `{min(mins)}` → `{max(maxs)}` "
                f"(≈ {_to_paris(min(mins))} → {_to_paris(max(maxs))} Paris)"
            )
        bars = [c["bars"] for c in coverage if c.get("bars")]
        if bars:
            lines.append(
                f"- Bars/symbol: min={min(bars)}, max={max(bars)}, "
                f"median={sorted(bars)[len(bars)//2]}"
            )
    lines.append("")
    lines.append("| Group | Symbols w/ H1 |")
    lines.append("|---|---:|")
    by_g = defaultdict(int)
    for c in coverage:
        if c.get("bars", 0) > 0:
            by_g[c["group"]] += 1
    for g in sorted(by_g):
        lines.append(f"| {g} | {by_g[g]} |")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Signals (first sight) | {tot['signals']} |")
    lines.append(f"| Closed trades | {tot['closed']} |")
    lines.append(f"| Opens / timeouts | {tot['opens']} |")
    lines.append(f"| Wins | {tot['wins']} |")
    lines.append(f"| Losses | {tot['losses']} |")
    lines.append(f"| Win rate | {_fmt_pct(tot['winrate'])} |")
    lines.append(f"| Avg R / expectancy | {_fmt_r(tot['avg_r'])} |")
    lines.append(f"| Sum R | {_fmt_r(tot['sum_r'])} |")
    lines.append(f"| Max DD (R, cum.) | {_fmt_r(tot['max_dd'])} |")
    lines.append(f"| Profit factor | {_fmt_r(tot['profit_factor'])} |")
    lines.append("")

    # by group
    lines.append("## By group")
    lines.append("")
    lines.append(
        "| Group | Signals | Closed | WR | Avg R | Sum R | Max DD | Opens |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    groups = sorted({t["group"] for t in all_trades}) or sorted(by_g)
    for g in groups:
        a = _agg([t for t in all_trades if t["group"] == g])
        lines.append(
            f"| {g} | {a['signals']} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} | {_fmt_r(a['max_dd'])} | "
            f"{a['opens']} |"
        )
    lines.append("")

    # METAUX detail by symbol
    lines.append("## METAUX (priority) by symbol")
    lines.append("")
    lines.append("| Symbol | Signals | Closed | WR | Avg R | Sum R | Opens |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    meta_syms = sorted({t["symbol"] for t in all_trades if t["group"] == "METAUX"})
    # include coverage symbols with 0 trades
    cov_meta = sorted({c["symbol"] for c in coverage if c["group"] == "METAUX" and c.get("bars", 0) > 0})
    for s in sorted(set(meta_syms) | set(cov_meta)):
        a = _agg([t for t in all_trades if t["symbol"] == s])
        lines.append(
            f"| {s} | {a['signals']} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} | {a['opens']} |"
        )
    lines.append("")

    # by score
    lines.append("## By score (at detection)")
    lines.append("")
    lines.append("| Score | Signals | Closed | WR | Avg R | Sum R |")
    lines.append("|---:|---:|---:|---:|---:|---:|")
    for sc in sorted({int(t["score"]) for t in all_trades}):
        a = _agg([t for t in all_trades if int(t["score"]) == sc])
        lines.append(
            f"| {sc} | {a['signals']} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} |"
        )
    lines.append("")

    # by session at OB (star5 label) and at touch
    lines.append("## By session label (OB / ★5)")
    lines.append("")
    lines.append("| Session (OB) | Signals | Closed | WR | Avg R | Sum R |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    sess_keys = sorted({(t.get("session_label") or "—") for t in all_trades})
    for sk in sess_keys:
        a = _agg([t for t in all_trades if (t.get("session_label") or "—") == sk])
        lines.append(
            f"| {sk} | {a['signals']} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} |"
        )
    lines.append("")
    lines.append("## By touched session")
    lines.append("")
    lines.append("| Touched session | Closed | WR | Avg R | Sum R |")
    lines.append("|---|---:|---:|---:|---:|")
    touched = [t for t in all_trades if t.get("closed")]
    tkeys = sorted({(t.get("touched_session") or "—") for t in touched})
    for sk in tkeys:
        a = _agg([t for t in touched if (t.get("touched_session") or "—") == sk])
        lines.append(
            f"| {sk} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} |"
        )
    lines.append("")

    # by direction
    lines.append("## By direction")
    lines.append("")
    lines.append("| Direction | Signals | Closed | WR | Avg R | Sum R |")
    lines.append("|---|---:|---:|---:|---:|---:|")
    for d in ("bull", "bear"):
        a = _agg([t for t in all_trades if t["direction"] == d])
        lines.append(
            f"| {d} | {a['signals']} | {a['closed']} | {_fmt_pct(a['winrate'])} | "
            f"{_fmt_r(a['avg_r'])} | {_fmt_r(a['sum_r'])} |"
        )
    lines.append("")

    # outcome breakdown
    lines.append("## Outcomes")
    lines.append("")
    oc = defaultdict(int)
    for t in all_trades:
        oc[t.get("outcome") or "?"] += 1
    lines.append("| Outcome | Count |")
    lines.append("|---|---:|")
    for k in sorted(oc):
        lines.append(f"| {k} | {oc[k]} |")
    lines.append("")

    lines.append("## Caveats")
    lines.append("")
    lines.append(
        "- Short cache window (~weeks–months of H1, typically ~800 bars/symbol); "
        "not a multi-year study."
    )
    lines.append(
        "- Soft 0.5R ON credits winners at +0.5R while losers are -1R → "
        "need WR > ~67% for positive expectancy under this attribution."
    )
    lines.append(
        "- Same-bar SL vs reaction ambiguity: lifecycle checks SL before reaction "
        "on each bar (conservative)."
    )
    lines.append(
        "- Fib / liquidity scored with data available at first causal sight "
        "(expanding window); live rescans can update scores."
    )
    lines.append(
        "- No costs, slippage, or spread modeled. Yahoo/OANDA/Binance cache "
        "quality varies by symbol."
    )
    lines.append(
        "- Historical v1 `backtest_5star.py` used a different star model "
        "(app.js port) and fixed RR TP — **not directly comparable**."
    )
    lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--cache-dir",
        default=str(
            Path("/workspace/ob-scanner-v2/data/cache")
            if Path("/workspace/ob-scanner-v2/data/cache").is_dir()
            else ROOT / "data" / "cache"
        ),
    )
    ap.add_argument("--symbols-yaml", default=str(ROOT / "symbols.yaml"))
    ap.add_argument("--tf", default="H1")
    ap.add_argument("--min-score", type=int, default=5)
    ap.add_argument("--soft-r", type=float, default=0.0)
    ap.add_argument("--reaction-r", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument(
        "--groups",
        default="ALL",
        help="Comma list e.g. METAUX,FOREX or ALL",
    )
    ap.add_argument(
        "--out-dir",
        default=str(ROOT / "data" / "backtest"),
    )
    ap.add_argument("--tag", default="h1_hard1r")
    args = ap.parse_args()

    instruments = load_instruments(args.symbols_yaml)
    groups_filter = None
    if args.groups.strip().upper() != "ALL":
        groups_filter = {g.strip().upper() for g in args.groups.split(",") if g.strip()}
        instruments = [i for i in instruments if i.group.upper() in groups_filter]

    # priority: METAUX first (XAU priority field), then others
    instruments = sorted(
        instruments,
        key=lambda i: (0 if i.group == "METAUX" else 1, -i.priority, i.id),
    )

    cache_dir = args.cache_dir
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    jobs = [
        (
            i.id,
            i.group,
            cache_dir,
            args.tf,
            args.min_score,
            args.soft_r,
            args.reaction_r,
        )
        for i in instruments
    ]

    print(
        f"[backtest] symbols={len(jobs)} tf={args.tf} min_score={args.min_score} "
        f"soft_r={args.soft_r} reaction_r={args.reaction_r} workers={args.workers}",
        flush=True,
    )
    t0 = time.time()
    results: list[dict] = []
    if args.workers <= 1:
        for job in jobs:
            r = backtest_symbol(*job)
            results.append(r)
            print(
                f"  {r['symbol']}: bars={r['bars']} signals={len(r['trades'])} "
                f"err={r.get('error')}",
                flush=True,
            )
    else:
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_worker, job): job[0] for job in jobs}
            done = 0
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                done += 1
                if done % 10 == 0 or done == len(jobs):
                    print(
                        f"  progress {done}/{len(jobs)} "
                        f"last={r['symbol']} signals={len(r['trades'])}",
                        flush=True,
                    )

    results.sort(key=lambda r: (0 if r["group"] == "METAUX" else 1, r["symbol"]))
    all_trades: list[dict] = []
    for r in results:
        all_trades.extend(r["trades"])

    # chronological order for DD
    all_trades.sort(key=lambda t: (t.get("touched_at") or t.get("detected_at") or t["ts_ob"]))

    coverage = [
        {
            "symbol": r["symbol"],
            "group": r["group"],
            "bars": r["bars"],
            "from": r.get("from"),
            "to": r.get("to"),
            "error": r.get("error"),
        }
        for r in results
    ]

    tag = args.tag
    csv_path = out_dir / f"trades_{tag}.csv"
    if all_trades:
        fields = list(all_trades[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(all_trades)
    else:
        csv_path.write_text("", encoding="utf-8")

    summary = _agg(all_trades)
    meta = {
        "generated_at": datetime.now(tz=PARIS).isoformat(),
        "cache_dir": cache_dir,
        "tf": args.tf.upper(),
        "min_score": args.min_score,
        "soft_reaction_r": args.soft_r,
        "reaction_r": args.reaction_r,
        "n_symbols": len(jobs),
        "n_with_data": sum(1 for c in coverage if c.get("bars", 0) > 0),
        "elapsed_sec": round(time.time() - t0, 1),
        "summary": summary,
    }
    json_path = out_dir / f"summary_{tag}.json"
    json_path.write_text(
        json.dumps({"meta": meta, "coverage": coverage, "summary": summary}, indent=2, default=str),
        encoding="utf-8",
    )

    report_path = out_dir / f"BACKTEST_REPORT_{tag}.md"
    write_report(report_path, meta=meta, all_trades=all_trades, coverage=coverage)
    # also canonical path requested
    canonical = ROOT / "BACKTEST_REPORT.md"
    canonical.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    print(
        f"[backtest] done in {meta['elapsed_sec']}s — signals={summary['signals']} "
        f"closed={summary['closed']} WR={summary['winrate']} avgR={summary['avg_r']}",
        flush=True,
    )
    print(f"[backtest] report={canonical}", flush=True)
    print(f"[backtest] csv={csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
