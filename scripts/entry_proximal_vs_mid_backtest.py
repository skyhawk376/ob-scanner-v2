#!/usr/bin/env python3
"""Config B: proximal OB-edge entry (bull=OB high / bear=OB low, SL beyond distal) vs legacy mid entry.

Params: min_score=4, METAUX+FOREX+CRYPTO, soft OFF (+1R), hold≤1 H1 bar.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts"))

import volume_options_backtest as vol  # noqa: E402
from app.engine.params import EngineParams, params_for_tf  # noqa: E402
from app.engine.detect import detect_zones  # noqa: E402
from app.core.lifecycle import simulate_lifecycle  # noqa: E402
from app.core.cache import read_cache  # noqa: E402

PARIS = ZoneInfo("Europe/Paris")
OUT = ROOT / "data" / "backtest"


def backtest_symbol_entry(
    symbol: str,
    group: str,
    cache_dir: str,
    tf: str,
    min_score: int,
    soft_reaction_r: float,
    reaction_r: float,
    max_hold_bars: int,
    warm_bars: int,
    entry_mode: str,
    require_entry_fill: bool,
) -> dict:
    import pandas as pd

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

    if df.index.tz is None:
        df = df.copy()
        df.index = df.index.tz_localize("UTC")
    else:
        df = df.copy()
        df.index = df.index.tz_convert("UTC")

    base = params_for_tf(tf)
    params = EngineParams(**{**base.__dict__, "entry_mode": entry_mode})
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
            det_i = len(sub) - 2 if len(sub) > 1 else len(sub) - 1
            det_ts = str(sub.index[det_i])
            life = simulate_lifecycle(
                df,
                zd,
                soft_reaction_r=soft_reaction_r,
                reaction_r=reaction_r,
                require_entry_fill=require_entry_fill,
            )
            exit_at = life.reacted_at or life.failed_at
            hold_bars = None
            hold_capped = False
            outcome = life.outcome or life.status
            r_mult = vol._r_for_outcome(life.outcome, life.reaction_threshold_r)

            if life.touched_at and exit_at and max_hold_bars is not None:
                try:
                    touch_ts = vol.pd_ts(life.touched_at)
                    exit_ts = vol.pd_ts(exit_at)
                    ti = int(df.index.get_indexer([touch_ts], method="nearest")[0])
                    ei = int(df.index.get_indexer([exit_ts], method="nearest")[0])
                    hold_bars = ei - ti
                except Exception:
                    hold_bars = None
                if hold_bars is not None and hold_bars > max_hold_bars - 1:
                    hold_capped = True
                    outcome = "timeout_hold"
                    r_mult = None

            trades.append(
                {
                    "symbol": symbol,
                    "group": group,
                    "tf": tf.upper(),
                    "direction": z.direction,
                    "ts_ob": z.ts_ob,
                    "detected_at": det_ts,
                    "score": int(z.score),
                    "session_label": z.session_label or "",
                    "star5_session": int(z.star5_session),
                    "entry": z.entry,
                    "sl": z.sl,
                    "entry_mode": entry_mode,
                    "outcome": outcome,
                    "status": life.status if not hold_capped else "timeout_hold",
                    "touched_at": life.touched_at or "",
                    "touched_session": life.touched_session or "",
                    "reacted_at": "" if hold_capped else (life.reacted_at or ""),
                    "failed_at": "" if hold_capped else (life.failed_at or ""),
                    "hold_bars": hold_bars if hold_bars is not None else "",
                    "hold_capped": int(hold_capped),
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
    return backtest_symbol_entry(*args)


def run_one(*, tag: str, entry_mode: str, require_entry_fill: bool, workers: int = 6) -> dict:
    from concurrent.futures import ProcessPoolExecutor, as_completed
    import csv

    instruments = vol.load_instruments(str(vol.YAML))
    gset = {"METAUX", "FOREX", "CRYPTO"}
    instruments = [i for i in instruments if i.group.upper() in gset]
    instruments = sorted(
        instruments,
        key=lambda i: (0 if i.group == "METAUX" else 1, -i.priority, i.id),
    )

    jobs = [
        (
            i.id,
            i.group,
            str(vol.CACHE),
            "H1",
            4,
            0.0,
            1.0,
            1,
            80,
            entry_mode,
            require_entry_fill,
        )
        for i in instruments
    ]
    print(
        f"[{tag}] symbols={len(jobs)} entry={entry_mode} fill={require_entry_fill}",
        flush=True,
    )
    t0 = time.time()
    results: list[dict] = []
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_worker, job): job[0] for job in jobs}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            if done % 15 == 0 or done == len(jobs):
                print(
                    f"  [{tag}] {done}/{len(jobs)} last={r['symbol']} sig={len(r['trades'])}",
                    flush=True,
                )

    results.sort(key=lambda r: (0 if r["group"] == "METAUX" else 1, r["symbol"]))
    all_trades: list[dict] = []
    for r in results:
        all_trades.extend(r["trades"])
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
    span = vol._span_days(coverage)
    # Prefer touch-window span for trades/day (like VOLUME_OPTIONS B)
    touched = [t for t in all_trades if t.get("touched_at")]
    if touched:
        ta = min(vol.pd_ts(t["touched_at"]) for t in touched)
        tb = max(vol.pd_ts(t["touched_at"]) for t in touched)
        touch_span = max((tb - ta).total_seconds() / 86400.0, 1e-9)
    else:
        touch_span = span
    summary = vol._agg(all_trades, touch_span)
    # also calendar from coverage
    summary["trades_per_day_cache_span"] = (
        (summary["closed"] / span) if span and summary["closed"] else None
    )
    summary["touch_span_days"] = touch_span
    weekdays = touch_span * 5 / 7
    summary["trades_per_weekday"] = (
        (summary["closed"] / weekdays) if weekdays > 0 and summary["closed"] else None
    )

    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / f"trades_{tag}.csv"
    if all_trades:
        fields = list(all_trades[0].keys())
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(all_trades)

    by_group = {
        g: vol._agg([t for t in all_trades if t["group"] == g], touch_span)
        for g in sorted({t["group"] for t in all_trades})
    }
    payload = {
        "meta": {
            "tag": tag,
            "generated_at": datetime.now(tz=PARIS).isoformat(),
            "entry_mode": entry_mode,
            "require_entry_fill": require_entry_fill,
            "min_score": 4,
            "groups": ["METAUX", "FOREX", "CRYPTO"],
            "soft_reaction_r": 0.0,
            "reaction_r": 1.0,
            "max_hold_bars": 1,
            "n_symbols": len(jobs),
            "span_days": span,
            "touch_span_days": touch_span,
            "elapsed_sec": round(time.time() - t0, 1),
        },
        "summary": summary,
        "by_group": by_group,
        "coverage": coverage,
    }
    (OUT / f"summary_{tag}.json").write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    print(
        f"[{tag}] closed={summary['closed']} WR={vol._fmt_pct(summary['winrate'])} "
        f"avgR={vol._fmt_r(summary['avg_r'])} tpd={vol._fmt_tpd(summary['trades_per_day'])} "
        f"({time.time()-t0:.1f}s)",
        flush=True,
    )
    return payload


def main():
    old = run_one(
        tag="vol_B_mfc_s4_hold1_mid",
        entry_mode="mid",
        require_entry_fill=False,
    )
    prox = run_one(
        tag="vol_B_mfc_s4_hold1_proximal",
        entry_mode="proximal",
        require_entry_fill=True,
    )

    cmp = {
        "generated_at": datetime.now(tz=PARIS).isoformat(),
        "config": "B min4 M+F+C soft OFF +1R hold<=1",
        "mid": old["summary"],
        "proximal": prox["summary"],
        "mid_meta": old["meta"],
        "proximal_meta": prox["meta"],
        "mid_by_group": old["by_group"],
        "proximal_by_group": prox["by_group"],
    }
    (OUT / "summary_entry_proximal_vs_mid.json").write_text(
        json.dumps(cmp, indent=2, default=str), encoding="utf-8"
    )

    def row(label, s):
        return (
            f"| {label} | {s['signals']} | {s['closed']} | {s['wins']}/{s['losses']} | "
            f"{vol._fmt_pct(s['winrate'])} | {vol._fmt_r(s['avg_r'])} | {s['sum_r']:.1f} | "
            f"{s['max_dd']:.1f} | {s['profit_factor']:.2f} | "
            f"{vol._fmt_tpd(s['trades_per_day'])} | {vol._fmt_tpd(s.get('trades_per_weekday'))} |"
        )

    lines = [
        "# Entrée proximale vs mid — config B",
        "",
        f"Generated: **{datetime.now(tz=PARIS).strftime('%Y-%m-%d %H:%M %Z')}** (Europe/Paris)",
        "",
        "Config B: `min_score=4`, METAUX+FOREX+CRYPTO (48 symboles H1), soft OFF (+1R), hold≤1 H1, OB vierge + FVG.",
        "",
        "| Mode | Signaux | Fermés | W/L | WR | Avg R | Sum R | Max DD | PF | Trades/jour | Trades/jour ouvré |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        row("mid (legacy)", old["summary"]),
        row("**proximal (live)** bull=haut OB / bear=bas OB", prox["summary"]),
        "",
        "## Par groupe",
        "",
        "| Groupe | Mode | Fermés | WR | Avg R | Sum R |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for g in sorted(set(old["by_group"]) | set(prox["by_group"])):
        for label, bg in (("mid", old["by_group"]), ("proximal", prox["by_group"])):
            s = bg.get(g)
            if s:
                lines.append(
                    f"| {g} | {label} | {s['closed']} | {vol._fmt_pct(s['winrate'])} | "
                    f"{vol._fmt_r(s['avg_r'])} | {s['sum_r']:.1f} |"
                )
    lines += [
        "",
        "- **proximal (code live)** : entrée bull=haut OB / bear=bas OB ; SL au-delà du bord distal (+0,05 ATR) ; R ≈ hauteur zone ; fill limite à l’entrée.",
        "- **mid (legacy)** : entrée 50 % (ou open si zone < 1 ATR) ; gestion dès contact zone.",
        "- Entrée bord distal (bull=bas / bear=haut) **retirée** du code (R ≈ buffer SL → WR 0 %).",
        "- Pas de spread/commission/slippage.",
        "",
    ]
    md = "\n".join(lines)
    (OUT / "ENTRY_PROXIMAL_VS_MID.md").write_text(md, encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
