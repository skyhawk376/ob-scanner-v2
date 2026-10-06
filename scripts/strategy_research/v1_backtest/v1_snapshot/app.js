/**
 * OB Scanner front-end
 * - Fetches OHLC via local /api/candles proxy
 * - Detects ICT-style Order Blocks + Kasper-style 0–5★ confluence scoring
 * - Renders list + Lightweight Charts with click-to-draw zones
 */
(function () {
  "use strict";

  const WATCHLIST = [
    { id: "XAUUSD", label: "XAUUSD → PAXG (gold proxy)" },
    { id: "NAS100", label: "NAS100 → NQ=F" },
    { id: "SP500", label: "SP500 → ES=F" },
    { id: "BTCUSD", label: "BTCUSD (Coinbase)" },
    { id: "EURUSD", label: "EURUSD" },
    { id: "GBPUSD", label: "GBPUSD" },
    { id: "XAUUSD_FUT", label: "XAUUSD_FUT → GC=F" },
    { id: "USDJPY", label: "USDJPY" },
    { id: "AUDUSD", label: "AUDUSD" },
    { id: "US30", label: "US30 → YM=F" },
    { id: "ETHUSD", label: "ETHUSD (Coinbase)" },
    { id: "NZDUSD", label: "NZDUSD → NZDUSD=X" },
    { id: "USDCAD", label: "USDCAD → USDCAD=X" },
    { id: "USDCHF", label: "USDCHF → USDCHF=X" },
    { id: "EURJPY", label: "EURJPY → EURJPY=X" },
    { id: "GBPJPY", label: "GBPJPY → GBPJPY=X" },
    { id: "SILVER", label: "SILVER → SI=F (COMEX silver)" },
    { id: "OIL", label: "OIL → CL=F (WTI crude)" },
    { id: "RUSSELL", label: "RUSSELL → RTY=F (E-mini Russell 2000)" },
    { id: "SOLUSD", label: "SOLUSD → SOL-USD (Coinbase)" },
  ];

  const MAX_OBS = 40;
  /** Soft cap for retained OB lists after merge (scan monde + refresh). */
  const LIST_MERGE_CAP = 180;
  const BODY_LOOKBACK = 20;
  const BREAK_LOOKBACK = 10;
  const BOS_LOOKBACK = 20; // stricter lookback for BOS★ (break of structure)
  const BODY_MULT = 1.5;

  const state = {
    symbol: "XAUUSD",
    tf: "M15",
    candles: [],
    obs: [],
    selectedId: null,
    showMitigated: true,
    minStars: 5,
    sourceNote: "",
    // "multi" = Scan monde 5★ list; keep it when clicking a row to open a chart
    listMode: "single",
    multiObs: [],
    checkFilter: "all", // all | hide | only
  };

  // --- DOM ---
  const el = {
    symbolSelect: document.getElementById("symbolSelect"),
    obList: document.getElementById("obList"),
    obCount: document.getElementById("obCount"),
    status: document.getElementById("status"),
    chartTitle: document.getElementById("chartTitle"),
    sourceNote: document.getElementById("sourceNote"),
    errorBanner: document.getElementById("errorBanner"),
    btnPrimary: document.getElementById("btnPrimary"),
    btnScanWorld: document.getElementById("btnScanWorld"),
    minStars: document.getElementById("minStars"),
    filterText: document.getElementById("filterText"),
    btnClearChecked: document.getElementById("btnClearChecked"),
    syncCodeInput: document.getElementById("syncCodeInput"),
    btnSyncGenerate: document.getElementById("btnSyncGenerate"),
    btnSyncLink: document.getElementById("btnSyncLink"),
    syncStatus: document.getElementById("syncStatus"),
    chart: document.getElementById("chart"),
  };

  // --- Chart ---
  let chart, candleSeries, zonePrimitives = [];

  function initChart() {
    chart = LightweightCharts.createChart(el.chart, {
      layout: {
        background: { type: "solid", color: "#0b0f14" },
        textColor: "#8b9bb4",
      },
      grid: {
        vertLines: { color: "#1a222e" },
        horzLines: { color: "#1a222e" },
      },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: "#1e2836" },
      timeScale: { borderColor: "#1e2836", timeVisible: true, secondsVisible: false },
    });
    candleSeries = chart.addCandlestickSeries({
      upColor: "#26a69a",
      downColor: "#ef5350",
      borderVisible: false,
      wickUpColor: "#26a69a",
      wickDownColor: "#ef5350",
    });
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: el.chart.clientWidth, height: el.chart.clientHeight });
    });
    ro.observe(el.chart);
    chart.applyOptions({ width: el.chart.clientWidth, height: el.chart.clientHeight });
  }

  function clearZones() {
    if (candleSeries && zonePrimitives.priceLines) {
      zonePrimitives.priceLines.forEach((pl) => candleSeries.removePriceLine(pl));
    }
    zonePrimitives = { priceLines: [], boxes: [] };
    drawOverlayBoxes([]);
  }

  /** Simple absolute-position overlay for OB rectangles (LWC has no built-in box). */
  let overlayCanvas;
  function ensureOverlay() {
    if (overlayCanvas) return overlayCanvas;
    overlayCanvas = document.createElement("canvas");
    overlayCanvas.style.cssText =
      "position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:5;";
    el.chart.style.position = "relative";
    el.chart.appendChild(overlayCanvas);
    chart.timeScale().subscribeVisibleLogicalRangeChange(() => redrawOverlay());
    chart.subscribeCrosshairMove(() => redrawOverlay());
    window.addEventListener("resize", () => redrawOverlay());
    return overlayCanvas;
  }

  function drawOverlayBoxes(boxes) {
    const canvas = ensureOverlay();
    const w = el.chart.clientWidth;
    const h = el.chart.clientHeight;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.floor(w * dpr);
    canvas.height = Math.floor(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    boxes.forEach((b) => {
      const x1 = chart.timeScale().timeToCoordinate(b.timeFrom);
      const x2 = chart.timeScale().timeToCoordinate(b.timeTo);
      const y1 = candleSeries.priceToCoordinate(b.priceHigh);
      const y2 = candleSeries.priceToCoordinate(b.priceLow);
      if (x1 == null || y1 == null || y2 == null) return;
      const left = x1;
      const right = x2 == null ? w - 8 : Math.max(x2, left + 4);
      const top = Math.min(y1, y2);
      const height = Math.abs(y2 - y1);
      const fillA = b.dim ? (b.bull ? "rgba(38,166,154,0.08)" : "rgba(239,83,80,0.08)")
                         : (b.bull ? "rgba(38,166,154,0.18)" : "rgba(239,83,80,0.18)");
      const strokeA = b.dim ? (b.bull ? "rgba(38,166,154,0.35)" : "rgba(239,83,80,0.35)")
                           : (b.bull ? "rgba(38,166,154,0.85)" : "rgba(239,83,80,0.85)");
      ctx.fillStyle = fillA;
      ctx.strokeStyle = strokeA;
      ctx.lineWidth = b.dim ? 1 : 1.5;
      ctx.fillRect(left, top, Math.max(right - left, 6), Math.max(height, 2));
      ctx.strokeRect(left, top, Math.max(right - left, 6), Math.max(height, 2));
      if (!b.dim) {
        const midY = candleSeries.priceToCoordinate((b.priceHigh + b.priceLow) / 2);
        if (midY != null) {
          ctx.setLineDash([4, 4]);
          ctx.beginPath();
          ctx.moveTo(left, midY);
          ctx.lineTo(Math.max(right, left + 6), midY);
          ctx.stroke();
          ctx.setLineDash([]);
        }
      }
    });
  }

  let selectedObForDraw = null;

  function qualifyingObsForOverlay() {
    return state.obs.filter((o) => {
      if (o.mitigated || o.stars < state.minStars) return false;
      // Multi-scan list mixes symbols — only box zones for the chart on screen
      if (o.symbol && o.symbol !== state.symbol) return false;
      if (o.tf && o.tf !== state.tf) return false;
      return true;
    });
  }

  function redrawOverlay() {
    const lastT = state.candles.length
      ? state.candles[state.candles.length - 1].time
      : null;
    if (!lastT) {
      drawOverlayBoxes([]);
      return;
    }
    const boxes = [];
    const selectedId = selectedObForDraw ? selectedObForDraw.id : null;
    qualifyingObsForOverlay().forEach((ob) => {
      if (ob.id === selectedId) return; // draw selected last / full
      boxes.push({
        timeFrom: ob.time,
        timeTo: lastT,
        priceHigh: ob.high,
        priceLow: ob.low,
        bull: ob.side === "bullish",
        dim: true,
      });
    });
    if (selectedObForDraw) {
      boxes.push({
        timeFrom: selectedObForDraw.time,
        timeTo: lastT,
        priceHigh: selectedObForDraw.high,
        priceLow: selectedObForDraw.low,
        bull: selectedObForDraw.side === "bullish",
        dim: false,
      });
    }
    drawOverlayBoxes(boxes);
  }

  function drawObOnChart(ob) {
    // clear price lines only; overlay redrawn below
    if (candleSeries && zonePrimitives.priceLines) {
      zonePrimitives.priceLines.forEach((pl) => candleSeries.removePriceLine(pl));
    }
    zonePrimitives = { priceLines: [], boxes: [] };
    selectedObForDraw = ob;
    const color = ob.side === "bullish" ? "#26a69a" : "#ef5350";
    const plHigh = candleSeries.createPriceLine({
      price: ob.high,
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: ob.side === "bullish" ? "Bull OB H" : "Bear OB H",
    });
    const plLow = candleSeries.createPriceLine({
      price: ob.low,
      color,
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Solid,
      axisLabelVisible: true,
      title: ob.side === "bullish" ? "Bull OB L" : "Bear OB L",
    });
    const mid = ob.entry != null ? ob.entry : (ob.high + ob.low) / 2;
    const plMid = candleSeries.createPriceLine({
      price: mid,
      color: "#f0b429",
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: "Entry 50%",
    });
    const lines = [plHigh, plLow, plMid];
    if (ob.sl != null) {
      lines.push(
        candleSeries.createPriceLine({
          price: ob.sl,
          color: "#ff8a65",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: "SL",
        })
      );
    }
    if (ob.tp != null) {
      lines.push(
        candleSeries.createPriceLine({
          price: ob.tp,
          color: "#66bb6a",
          lineWidth: 1,
          lineStyle: LightweightCharts.LineStyle.Dotted,
          axisLabelVisible: true,
          title: "TP 2R",
        })
      );
    }
    zonePrimitives.priceLines = lines;

    const starTxt = "★".repeat(ob.stars) + "☆".repeat(5 - ob.stars);
    candleSeries.setMarkers([
      {
        time: ob.time,
        position: ob.side === "bullish" ? "belowBar" : "aboveBar",
        color,
        shape: ob.side === "bullish" ? "arrowUp" : "arrowDown",
        text: (ob.side === "bullish" ? "Bull" : "Bear") + " " + starTxt,
      },
      {
        time: ob.dispTime,
        position: "inBar",
        color: "#3d8bfd",
        shape: "circle",
        text: "Disp",
      },
    ]);

    const idx = state.candles.findIndex((c) => c.time === ob.time);
    if (idx >= 0) {
      const from = Math.max(0, idx - 30);
      const to = Math.min(state.candles.length - 1, idx + 80);
      chart.timeScale().setVisibleLogicalRange({ from, to });
    }
    redrawOverlay();
  }

  // --- Scoring helpers ---

  /**
   * FVG / imbalance involving displacement bar i as middle candle.
   * Bull: candles[i+1].low > candles[i-1].high
   * Bear: candles[i+1].high < candles[i-1].low
   * Also checks i-1 / i / i+1 shifts nearby (±1) if classic miss.
   */
  function scoreFvg(candles, i, bullish) {
    const checks = [i, i - 1, i + 1].filter(
      (m) => m >= 1 && m + 1 < candles.length
    );
    for (const m of checks) {
      const left = candles[m - 1];
      const right = candles[m + 1];
      if (bullish && right.low > left.high) return true;
      if (!bullish && right.high < left.low) return true;
    }
    // clear gap in 1–3 bars after i in direction
    for (let a = i + 1; a <= Math.min(candles.length - 1, i + 3); a++) {
      if (bullish && candles[a].low > candles[i].high) return true;
      if (!bullish && candles[a].high < candles[i].low) return true;
    }
    return false;
  }

  /**
   * BOS★ — displacement close breaks prior BOS_LOOKBACK extreme (not body-only).
   */
  function scoreBos(candles, i, bullish) {
    const start = Math.max(0, i - BOS_LOOKBACK);
    let priorHigh = -Infinity;
    let priorLow = Infinity;
    for (let j = start; j < i; j++) {
      priorHigh = Math.max(priorHigh, candles[j].high);
      priorLow = Math.min(priorLow, candles[j].low);
    }
    const c = candles[i];
    if (bullish) return c.close > priorHigh;
    return c.close < priorLow;
  }

  /**
   * Sweep / liquidity raid heuristic:
   * Bull: min(low i-5..i) < min(low i-15..i-6) then bullish displacement
   * Bear: max(high i-5..i) > max(high i-15..i-6) then bearish displacement
   */
  function scoreSweep(candles, i, bullish) {
    if (i < 15) return false;
    if (bullish) {
      let raidLow = Infinity;
      let priorLow = Infinity;
      for (let j = i - 5; j <= i; j++) raidLow = Math.min(raidLow, candles[j].low);
      for (let j = i - 15; j <= i - 6; j++) priorLow = Math.min(priorLow, candles[j].low);
      return raidLow < priorLow;
    }
    let raidHigh = -Infinity;
    let priorHigh = -Infinity;
    for (let j = i - 5; j <= i; j++) raidHigh = Math.max(raidHigh, candles[j].high);
    for (let j = i - 15; j <= i - 6; j++) priorHigh = Math.max(priorHigh, candles[j].high);
    return raidHigh > priorHigh;
  }

  /**
   * Premium / Discount vs local swing range.
   * Range: swingLow = min low of last 50 bars before disp;
   *        swingHigh = max high from OB index through disp+5.
   * Bullish ★ if OB.mid in lower half (discount); bearish ★ if OB.mid in upper half (premium).
   */
  function scorePremiumDiscount(candles, i, obIdx, mid, bullish) {
    const lookStart = Math.max(0, i - 50);
    let swingLow = Infinity;
    for (let j = lookStart; j < i; j++) {
      swingLow = Math.min(swingLow, candles[j].low);
    }
    const end = Math.min(candles.length - 1, i + 5);
    let swingHigh = -Infinity;
    const from = Math.min(obIdx, i);
    for (let j = from; j <= end; j++) {
      swingHigh = Math.max(swingHigh, candles[j].high);
    }
    if (!(swingHigh > swingLow)) return false;
    const half = swingLow + 0.5 * (swingHigh - swingLow);
    if (bullish) return mid <= half; // discount
    return mid >= half; // premium
  }

  function scoreOb(candles, i, obIdx, side, mitigated) {
    const bullish = side === "bullish";
    const mid = (candles[obIdx].high + candles[obIdx].low) / 2;
    const flags = {
      fvg: scoreFvg(candles, i, bullish),
      bos: scoreBos(candles, i, bullish),
      sweep: scoreSweep(candles, i, bullish),
      fresh: !mitigated,
      pd: scorePremiumDiscount(candles, i, obIdx, mid, bullish),
    };
    const stars =
      (flags.fvg ? 1 : 0) +
      (flags.bos ? 1 : 0) +
      (flags.sweep ? 1 : 0) +
      (flags.fresh ? 1 : 0) +
      (flags.pd ? 1 : 0);
    return { stars, starFlags: flags };
  }


  /**
   * Recommended SL/TP (scan-only, Oscar validated rules).
   * Bullish: entry = OB high; SL = low - buffer; R = entry - SL; TP = entry + 2R.
   * Bearish: entry = OB low;  SL = high + buffer; R = SL - entry; TP = entry - 2R.
   * Buffer = max(range * 0.075, abs(entry) * 1.5e-5).
   */
  function computeSlTp(high, low, side) {
    const entry = side === "bullish" ? high : low;
    const range = Math.max(0, high - low);
    const buffer = Math.max(range * 0.075, Math.abs(entry) * 1.5e-5);
    let sl, tp, r;
    if (side === "bullish") {
      sl = low - buffer;
      r = entry - sl;
      tp = entry + 2 * r;
    } else {
      sl = high + buffer;
      r = sl - entry;
      tp = entry - 2 * r;
    }
    return { entry, sl, tp, r };
  }

  // --- OB detection ---
  /**
   * ICT-style Order Block detection + Kasper-style 0–5★ confluence.
   *
   * Displacement (candidate find):
   *   body >= 1.5 × avg body of prior 20, OR close breaks prior 10-bar H/L.
   * OB candle = last opposing candle within 8 bars before displacement.
   * Mitigated = later close through 50% mid.
   *
   * Stars (1 each, max 5): FVG, BOS (break of 20-bar extreme), Sweep, Fresh, P/D.
   * Sorted by stars desc, then unmitigated, then recent; cap MAX_OBS.
   */
  function detectOrderBlocks(candles, opts) {
    opts = opts || {};
    const sym = opts.symbol != null ? opts.symbol : state.symbol;
    const timeframe = opts.tf != null ? opts.tf : state.tf;
    const maxObs = opts.maxObs != null ? opts.maxObs : MAX_OBS;
    const obs = [];
    if (!candles || candles.length < BODY_LOOKBACK + BREAK_LOOKBACK + 3) return obs;

    for (let i = BODY_LOOKBACK; i < candles.length; i++) {
      const c = candles[i];
      const body = Math.abs(c.close - c.open);
      let sum = 0;
      for (let j = i - BODY_LOOKBACK; j < i; j++) {
        sum += Math.abs(candles[j].close - candles[j].open);
      }
      const avgBody = sum / BODY_LOOKBACK;
      const strongBody = avgBody > 0 && body >= BODY_MULT * avgBody;

      let priorHigh = -Infinity;
      let priorLow = Infinity;
      const start = Math.max(0, i - BREAK_LOOKBACK);
      for (let j = start; j < i; j++) {
        priorHigh = Math.max(priorHigh, candles[j].high);
        priorLow = Math.min(priorLow, candles[j].low);
      }
      const bullDisp = c.close > c.open && (strongBody || c.close > priorHigh);
      const bearDisp = c.close < c.open && (strongBody || c.close < priorLow);
      if (!bullDisp && !bearDisp) continue;

      let obCandle = null;
      let obIdx = -1;
      if (bullDisp) {
        for (let k = i - 1; k >= Math.max(0, i - 8); k--) {
          if (candles[k].close < candles[k].open) {
            obCandle = candles[k];
            obIdx = k;
            break;
          }
        }
      } else {
        for (let k = i - 1; k >= Math.max(0, i - 8); k--) {
          if (candles[k].close > candles[k].open) {
            obCandle = candles[k];
            obIdx = k;
            break;
          }
        }
      }
      if (!obCandle) continue;

      const side = bullDisp ? "bullish" : "bearish";
      const high = obCandle.high;
      const low = obCandle.low;
      const mid = (high + low) / 2;

      let mitigated = false;
      let mitigatedAt = null;
      for (let m = i + 1; m < candles.length; m++) {
        const cl = candles[m].close;
        if (side === "bullish" && cl < mid) {
          mitigated = true;
          mitigatedAt = candles[m].time;
          break;
        }
        if (side === "bearish" && cl > mid) {
          mitigated = true;
          mitigatedAt = candles[m].time;
          break;
        }
      }

      if (obs.some((o) => o.time === obCandle.time && o.side === side)) continue;

      const scored = scoreOb(candles, i, obIdx, side, mitigated);

      const sltp = computeSlTp(high, low, side);

      obs.push({
        id: `${side}-${obCandle.time}-${i}`,
        side,
        time: obCandle.time,
        dispTime: c.time,
        dispIndex: i,
        obIndex: obIdx,
        high,
        low,
        mid,
        entry: sltp.entry,
        sl: sltp.sl,
        tp: sltp.tp,
        r: sltp.r,
        mitigated,
        mitigatedAt,
        symbol: sym,
        tf: timeframe,
        dispBody: body,
        avgBody,
        stars: scored.stars,
        starFlags: scored.starFlags,
      });
    }

    // Sort: stars desc, unmitigated first, then most recent (higher time)
    obs.sort((a, b) => {
      if (b.stars !== a.stars) return b.stars - a.stars;
      if (a.mitigated !== b.mitigated) return a.mitigated ? 1 : -1;
      return b.time - a.time;
    });

    const picked = [];
    for (const o of obs) {
      if (picked.length >= maxObs) break;
      if (picked.some((p) => p.time === o.time && p.side === o.side)) continue;
      picked.push(o);
    }
    return picked;
  }

  // --- UI helpers ---
  function setStatus(msg) {
    el.status.textContent = msg;
  }

  function showError(msg) {
    if (!msg) {
      el.errorBanner.classList.add("hidden");
      el.errorBanner.textContent = "";
      return;
    }
    el.errorBanner.textContent = msg;
    el.errorBanner.classList.remove("hidden");
  }

  function fmtPrice(n) {
    if (n == null || Number.isNaN(n)) return "—";
    const abs = Math.abs(n);
    const digits = abs >= 1000 ? 2 : abs >= 10 ? 3 : abs >= 1 ? 5 : 6;
    return n.toFixed(digits);
  }

  function fmtTime(t) {
    try {
      return new Date(t * 1000).toLocaleString("fr-FR", {
        timeZone: "Europe/Paris",
        month: "short",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      }) + " PT";
    } catch {
      return String(t);
    }
  }

  function starsHtml(n) {
    return `<span class="stars" title="${n}/5">` +
      "★".repeat(n) + "☆".repeat(5 - n) +
      `</span>`;
  }

  function flagsHtml(flags) {
    const tags = [
      ["fvg", "FVG"],
      ["bos", "BOS"],
      ["sweep", "SWP"],
      ["fresh", "FR"],
      ["pd", "PD"],
    ];
    return (
      '<span class="flag-row">' +
      tags
        .map(([k, label]) => {
          const on = flags && flags[k];
          return `<span class="flag ${on ? "on" : "off"}">${label}</span>`;
        })
        .join("") +
      "</span>"
    );
  }


  // --- Persist OBs across rescans (merge, don't wipe) ---
  function obMergeKey(ob) {
    const sym = ob.symbol != null ? ob.symbol : state.symbol;
    const tf = ob.tf != null ? ob.tf : state.tf;
    return `${sym}|${tf}|${ob.side}|${ob.time}`;
  }

  /**
   * Merge previous list with freshly detected OBs.
   * - Same key → update stars / mitigated / levels from fresh
   * - Only in prev → keep (esp. mitigated that fell out of detection)
   * - Cap: drop oldest mitigated first, then oldest by time
   */
  function mergeObLists(prev, fresh, opts) {
    opts = opts || {};
    const cap = opts.cap != null ? opts.cap : LIST_MERGE_CAP;
    const map = new Map();
    for (const o of prev || []) {
      if (!o || o.time == null || !o.side) continue;
      map.set(obMergeKey(o), o);
    }
    for (const o of fresh || []) {
      if (!o || o.time == null || !o.side) continue;
      const key = obMergeKey(o);
      const older = map.get(key);
      if (older) {
        map.set(key, Object.assign({}, older, o, {
          // keep stable id if fresh regenerated a different one
          id: older.id || o.id,
        }));
      } else {
        map.set(key, o);
      }
    }
    let merged = Array.from(map.values());
    const TF_RANK = { H1: 3, M15: 2, M5: 1 };
    merged.sort((a, b) => {
      if (b.stars !== a.stars) return b.stars - a.stars;
      const ra = TF_RANK[a.tf] || 0;
      const rb = TF_RANK[b.tf] || 0;
      if (rb !== ra) return rb - ra;
      if (a.mitigated !== b.mitigated) return a.mitigated ? 1 : -1;
      return b.time - a.time;
    });
    if (merged.length <= cap) return merged;
    // Evict oldest mitigated first, then oldest overall
    const keep = merged.slice();
    while (keep.length > cap) {
      let idx = -1;
      let oldest = Infinity;
      for (let i = 0; i < keep.length; i++) {
        const o = keep[i];
        if (o.mitigated && o.time < oldest) {
          oldest = o.time;
          idx = i;
        }
      }
      if (idx < 0) {
        oldest = Infinity;
        for (let i = 0; i < keep.length; i++) {
          if (keep[i].time < oldest) {
            oldest = keep[i].time;
            idx = i;
          }
        }
      }
      if (idx < 0) break;
      keep.splice(idx, 1);
    }
    return keep;
  }

  // --- Checked OBs (localStorage + optional cloud sync) ---
  const CHECKED_LS_KEY = "ob-scanner-checked-v1";
  const SYNC_CODE_LS_KEY = "ob-scanner-sync-code-v1";
  const SYNC_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789";
  const SYNC_CODE_RE = /^OB-[A-Z2-9]{8,12}$/;
  const SYNC_DEBOUNCE_MS = 400;

  let syncPushTimer = null;
  let syncBusy = false;

  function obCheckKey(ob) {
    const sym = ob.symbol != null ? ob.symbol : state.symbol;
    const tf = ob.tf != null ? ob.tf : state.tf;
    return `${sym}|${tf}|${ob.side}|${ob.time}`;
  }

  function loadCheckedMap() {
    try {
      const raw = localStorage.getItem(CHECKED_LS_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function saveCheckedMap(map) {
    try {
      localStorage.setItem(CHECKED_LS_KEY, JSON.stringify(map));
    } catch (e) {
      /* quota / private mode */
    }
  }

  function normalizeSyncCode(code) {
    if (!code || typeof code !== "string") return null;
    const c = code.trim().toUpperCase();
    return SYNC_CODE_RE.test(c) ? c : null;
  }

  function getStoredSyncCode() {
    try {
      return normalizeSyncCode(localStorage.getItem(SYNC_CODE_LS_KEY) || "");
    } catch (e) {
      return null;
    }
  }

  function setStoredSyncCode(code) {
    const n = normalizeSyncCode(code);
    try {
      if (n) localStorage.setItem(SYNC_CODE_LS_KEY, n);
      else localStorage.removeItem(SYNC_CODE_LS_KEY);
    } catch (e) { /* ignore */ }
    return n;
  }

  function generateSyncCode() {
    let body = "";
    const len = 10;
    if (window.crypto && crypto.getRandomValues) {
      const buf = new Uint8Array(len);
      crypto.getRandomValues(buf);
      for (let i = 0; i < len; i++) body += SYNC_ALPHABET[buf[i] % SYNC_ALPHABET.length];
    } else {
      for (let i = 0; i < len; i++) {
        body += SYNC_ALPHABET[Math.floor(Math.random() * SYNC_ALPHABET.length)];
      }
    }
    return "OB-" + body;
  }

  function setSyncStatus(msg, kind) {
    if (!el.syncStatus) return;
    el.syncStatus.textContent = msg || "";
    el.syncStatus.className = "sync-status" + (kind ? " " + kind : "");
  }


  async function fetchCloudChecks(code) {
    const n = normalizeSyncCode(code);
    if (!n) throw new Error("Code invalide");
    const res = await fetch("/api/checks?code=" + encodeURIComponent(n));
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error((data && data.error) || "Échec chargement sync");
    }
    return data;
  }

  async function pushCloudChecks(code, map) {
    const n = normalizeSyncCode(code);
    if (!n) return;
    const res = await fetch("/api/checks", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: n, checks: map || {} }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data.ok) {
      throw new Error((data && data.error) || "Échec envoi sync");
    }
    return data;
  }

  function scheduleCloudPush() {
    const code = getStoredSyncCode();
    if (!code) return;
    if (syncPushTimer) clearTimeout(syncPushTimer);
    syncPushTimer = setTimeout(() => {
      syncPushTimer = null;
      const map = loadCheckedMap();
      setSyncStatus("Sync…", "busy");
      pushCloudChecks(code, map)
        .then(() => setSyncStatus("Sync OK", "ok"))
        .catch((err) => setSyncStatus("Sync err", "err"));
    }, SYNC_DEBOUNCE_MS);
  }

  async function linkAndLoadSyncCode(rawCode, opts) {
    const options = opts || {};
    const n = normalizeSyncCode(rawCode);
    if (!n) {
      setSyncStatus("Code invalide", "err");
      return false;
    }
    if (syncBusy) return false;
    syncBusy = true;
    setSyncStatus("Chargement…", "busy");
    try {
      const data = await fetchCloudChecks(n);
      setStoredSyncCode(n);
      if (el.syncCodeInput) el.syncCodeInput.value = n;
      const cloud = (data && data.checks) || {};
      const cleanCloud = {};
      Object.keys(cloud).forEach((k) => {
        if (cloud[k]) cleanCloud[k] = 1;
      });
      const local = loadCheckedMap();
      const cloudEmpty = Object.keys(cleanCloud).length === 0;
      const localHas = Object.keys(local).some((k) => local[k]);
      if (cloudEmpty && localHas) {
        // First link / empty cloud: seed cloud from local (don't wipe device)
        saveCheckedMap(local);
        await pushCloudChecks(n, local);
      } else {
        // Cloud wins on load (toggle + reload stays consistent across devices)
        saveCheckedMap(cleanCloud);
      }
      setSyncStatus("Sync OK", "ok");
      if (!options.silent) renderList();
      return true;
    } catch (err) {
      setSyncStatus("Sync err", "err");
      return false;
    } finally {
      syncBusy = false;
    }
  }

  function isObChecked(ob) {
    const map = loadCheckedMap();
    return !!map[obCheckKey(ob)];
  }

  function setObChecked(ob, checked) {
    const map = loadCheckedMap();
    const key = obCheckKey(ob);
    if (checked) map[key] = 1;
    else delete map[key];
    saveCheckedMap(map);
    scheduleCloudPush();
  }

  function clearAllChecked() {
    try {
      localStorage.removeItem(CHECKED_LS_KEY);
    } catch (e) { /* ignore */ }
    scheduleCloudPush();
  }

  function filteredObs() {
    const q = (el.filterText.value || "").trim().toLowerCase();
    let items = state.obs.slice();
    items = items.filter((o) => o.stars >= state.minStars);
    if (!state.showMitigated) items = items.filter((o) => !o.mitigated);
    if (state.checkFilter === "hide") {
      items = items.filter((o) => !isObChecked(o));
    } else if (state.checkFilter === "only") {
      items = items.filter((o) => isObChecked(o));
    }
    if (q) {
      items = items.filter(
        (o) =>
          o.side.includes(q) ||
          (o.symbol && o.symbol.toLowerCase().includes(q)) ||
          o.tf.toLowerCase().includes(q) ||
          String(o.high).includes(q) ||
          String(o.stars).includes(q) ||
          (o.mitigated ? "mitigated" : "fresh").includes(q) ||
          (o.starFlags &&
            Object.keys(o.starFlags).some(
              (k) => o.starFlags[k] && k.includes(q)
            ))
      );
    }
    return items;
  }

  function renderList() {
    const items = filteredObs();
    const geMin = state.obs.filter((o) => o.stars >= state.minStars).length;
    el.obCount.textContent = String(items.length);
    el.obList.innerHTML = "";
    if (!items.length) {
      el.obList.innerHTML =
        `<li class="ob-item" style="cursor:default;opacity:0.7">No OBs with ≥${state.minStars}★ for this filter.</li>`;
      redrawOverlay();
      return;
    }
    items.forEach((ob) => {
      const checked = isObChecked(ob);
      const li = document.createElement("li");
      li.className =
        "ob-item " +
        (ob.side === "bullish" ? "bull" : "bear") +
        (ob.mitigated ? " mitigated" : "") +
        (state.selectedId === ob.id ? " active" : "") +
        (checked ? " checked" : "");
      const symLabel = ob.symbol
        ? `<span class="sym-tag">${ob.symbol}</span>`
        : `<span class="sym-tag">${state.symbol}</span>`;
      const tfLabel = `<span class="tf-tag">${ob.tf || state.tf}</span>`;
      li.innerHTML = `
        <input type="checkbox" class="ob-check" aria-label="Coché" ${checked ? "checked" : ""} />
        <div class="ob-body">
          <div class="row">
            <span class="side">${symLabel}${tfLabel}${ob.side === "bullish" ? "BULLISH OB" : "BEARISH OB"}
              <span class="tag ${ob.mitigated ? "dead" : "live"}">${ob.mitigated ? "mitigated" : "active"}</span>
            </span>
          </div>
          <div class="row stars-row">
            ${starsHtml(ob.stars)}
            ${flagsHtml(ob.starFlags)}
          </div>
          <div class="zone">${fmtPrice(ob.low)} — ${fmtPrice(ob.high)}</div>
          <div class="sltp">SL ${fmtPrice(ob.sl)} · TP ${fmtPrice(ob.tp)} · 2R</div>
          <div class="meta">OB ${fmtTime(ob.time)} · Disp ${fmtTime(ob.dispTime)}</div>
        </div>
      `;
      const cb = li.querySelector(".ob-check");
      cb.addEventListener("click", (ev) => {
        ev.stopPropagation();
      });
      cb.addEventListener("change", (ev) => {
        ev.stopPropagation();
        setObChecked(ob, cb.checked);
        if (state.checkFilter === "hide" || state.checkFilter === "only") {
          renderList();
        } else {
          li.classList.toggle("checked", cb.checked);
        }
      });
      li.addEventListener("click", () => {
        focusObFromList(ob);
      });
      el.obList.appendChild(li);
    });
    // keep overlay in sync when list refilters
    if (!selectedObForDraw || !items.some((o) => o.id === selectedObForDraw.id)) {
      // selection may be filtered out — clear focus lines but keep dim overlays
      if (selectedObForDraw && !items.some((o) => o.id === selectedObForDraw.id)) {
        if (candleSeries && zonePrimitives.priceLines) {
          zonePrimitives.priceLines.forEach((pl) => candleSeries.removePriceLine(pl));
        }
        zonePrimitives.priceLines = [];
        selectedObForDraw = null;
        candleSeries.setMarkers([]);
      }
    }
    redrawOverlay();
  }


  function setPrimaryDisabled(disabled) {
    const d = !!disabled;
    if (el.btnPrimary) el.btnPrimary.disabled = d;
    if (el.btnScanWorld) el.btnScanWorld.disabled = d;
  }

  async function loadData(opts) {
    opts = opts || {};
    const chartOnly = !!opts.chartOnly; // keep multi-scan list; only refresh candles/chart
    showError("");
    setStatus(`Chargement bougies ${state.symbol} ${state.tf}…`);
    if (!chartOnly) {
      el.chartTitle.textContent = `${state.symbol} · ${state.tf}`;
    }
    try {
      const url = `/api/candles?symbol=${encodeURIComponent(state.symbol)}&tf=${encodeURIComponent(state.tf)}`;
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok || data.error) {
        throw new Error(data.error || `HTTP ${res.status}`);
      }
      if (!data.candles || !data.candles.length) {
        throw new Error("No candles returned");
      }
      state.candles = data.candles;
      const stale = data.from_disk
        ? (data.stale ? " · DISK (refreshing)" : " · DISK")
        : "";
      state.sourceNote = `${data.source || ""} · ${data.count} bars${stale}`;
      if (data.note) state.sourceNote += ` · ${data.note}`;
      el.sourceNote.textContent = state.sourceNote;
      if (data.from_disk && data.live_error) {
        showError(`Live feed unavailable (${data.live_error}). Showing last cached candles.`);
      }

      candleSeries.setData(
        state.candles.map((c) => ({
          time: c.time,
          open: c.open,
          high: c.high,
          low: c.low,
          close: c.close,
        }))
      );
      candleSeries.setMarkers([]);
      clearZones();
      if (!chartOnly) {
        selectedObForDraw = null;
        const fresh = detectOrderBlocks(state.candles);
        // Keep prior OBs for this symbol/TF (mitigated etc.) instead of wiping
        const prevSame = (state.obs || []).filter((o) => {
          const sym = o.symbol != null ? o.symbol : state.symbol;
          const tf = o.tf != null ? o.tf : state.tf;
          return sym === state.symbol && tf === state.tf;
        });
        const merged = mergeObLists(prevSame, fresh, { cap: LIST_MERGE_CAP });
        state.obs = merged;
        state.selectedId = null;
        state.listMode = "single";
        state.multiObs = [];
        renderList();
        chart.timeScale().fitContent();
        const geMin = state.obs.filter((o) => o.stars >= state.minStars).length;
        const activeGe = state.obs.filter((o) => !o.mitigated && o.stars >= state.minStars).length;
        const retained = merged.length - fresh.length;
        setStatus(
          `${geMin} OB ≥${state.minStars}★ (${activeGe} active) · ${merged.length} kept` +
            (retained > 0 ? ` · +${retained} retained` : "")
        );
      } else {
        chart.timeScale().fitContent();
      }
    } catch (err) {
      console.error(err);
      showError(
        `Failed to load candles for ${state.symbol} ${state.tf}: ${err.message}. ` +
          `Is the local server running (python3 server.py)? Check network / API limits.`
      );
      setStatus("Error — see banner");
    }
  }


  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  function setTfButtons(tf) {
    document.querySelectorAll(".tf-group button").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-tf") === tf);
    });
  }

  /** Click a list row: switch symbol/TF if needed, load chart, select that OB. */
  async function focusObFromList(ob) {
    const keepMulti = state.listMode === "multi";
    const multiSnapshot = keepMulti
      ? (state.multiObs.length ? state.multiObs.slice() : state.obs.slice())
      : null;
    const targetSym = ob.symbol || state.symbol;
    const targetTf = ob.tf || state.tf;
    const needReload =
      targetSym !== state.symbol ||
      targetTf !== state.tf ||
      !state.candles.length;

    if (needReload) {
      state.symbol = targetSym;
      state.tf = targetTf;
      if (el.symbolSelect) el.symbolSelect.value = targetSym;
      setTfButtons(targetTf);
      setStatus(`Loading ${targetSym} ${targetTf} for selected OB…`);
      // chartOnly when multi-scan so we don't wipe the merged 5★ list
      await loadData({ chartOnly: keepMulti });
    }

    if (keepMulti && multiSnapshot) {
      state.listMode = "multi";
      state.multiObs = multiSnapshot;
      state.obs = multiSnapshot;
    }

    const match =
      state.obs.find((o) => o.id === ob.id) ||
      state.obs.find(
        (o) =>
          o.time === ob.time &&
          o.side === ob.side &&
          o.stars === ob.stars &&
          (!ob.symbol || o.symbol === ob.symbol)
      ) ||
      state.obs.find(
        (o) =>
          o.time === ob.time &&
          o.side === ob.side &&
          (!ob.symbol || o.symbol === ob.symbol)
      ) ||
      ob;

    state.selectedId = match.id;
    renderList();
    drawObOnChart(match);
    const multiNote = keepMulti
      ? ` · liste multi ${state.obs.length} OB conservée`
      : "";
    setStatus(
      `Drawing ${match.symbol || state.symbol} ${match.side} ${match.stars}★ OB @ ${fmtPrice(match.low)}–${fmtPrice(match.high)}` +
        multiNote
    );
    if (keepMulti) {
      el.chartTitle.textContent = `${state.symbol} · ${state.tf} (multi 5★)`;
      el.sourceNote.textContent =
        `Multi-scan list kept · ${state.obs.length} OB · click another row to switch chart`;
    }
  }

  async function fetchCandlesRaw(symbol, tf) {
    const url = `/api/candles?symbol=${encodeURIComponent(symbol)}&tf=${encodeURIComponent(tf)}`;
    const res = await fetch(url);
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || `HTTP ${res.status}`);
    }
    if (!data.candles || !data.candles.length) {
      throw new Error("No candles returned");
    }
    return data;
  }

  /**
   * World hunt: every watchlist symbol × M5 + M15 + H1.
   * Sequential (~350ms delay), stars===5; showMitigated controls mitigated inclusion.
   * Dedupe symbol|tf|side|time; MERGE with previous multi list (keep mitigated); cap LIST_MERGE_CAP.
   */
  async function scanWorldFiveStars() {
    const symbols = WATCHLIST.map((s) => s.id);
    const tfs = ["M5", "M15", "H1"];
    const showMit = state.showMitigated;
    const collected = [];
    // list cap via LIST_MERGE_CAP in mergeObLists
    const SCAN_DELAY_MS = 350;
    const jobs = [];
    for (const sym of symbols) {
      for (const tf of tfs) jobs.push({ sym, tf });
    }
    const total = jobs.length;

    setPrimaryDisabled(true);
    showError("");

    try {
      for (let i = 0; i < jobs.length; i++) {
        const { sym, tf } = jobs[i];
        setStatus(`Scanning ${sym} ${tf}… ${i + 1}/${total}`);
        try {
          const data = await fetchCandlesRaw(sym, tf);
          const obs = detectOrderBlocks(data.candles, { symbol: sym, tf });
          let five = obs.filter((o) => o.stars === 5);
          if (!showMit) five = five.filter((o) => !o.mitigated);
          collected.push(...five);
        } catch (err) {
          console.warn(`Scan monde ${sym} ${tf} failed:`, err);
        }
        if (i < jobs.length - 1) await sleep(SCAN_DELAY_MS);
      }

      // Dedupe this scan's detections first
      const seen = new Set();
      const freshOnly = [];
      for (const o of collected) {
        const key = obMergeKey(o);
        if (seen.has(key)) continue;
        seen.add(key);
        freshOnly.push(o);
      }

      // Merge with previous multi list so mitigated / fallen OBs stay visible
      const prevMulti =
        state.listMode === "multi" && state.multiObs && state.multiObs.length
          ? state.multiObs
          : state.listMode === "multi" && state.obs && state.obs.length
            ? state.obs
            : [];
      const merged = mergeObLists(prevMulti, freshOnly, { cap: LIST_MERGE_CAP });

      state.listMode = "multi";
      state.multiObs = merged;
      state.obs = merged;
      state.selectedId = null;
      selectedObForDraw = null;
      clearZones();
      if (candleSeries) candleSeries.setMarkers([]);

      if (state.minStars > 5) state.minStars = 5;
      if (el.minStars) el.minStars.value = String(state.minStars);

      renderList();
      const active = merged.filter((o) => !o.mitigated).length;
      const byTf = { M5: 0, M15: 0, H1: 0 };
      for (const o of merged) {
        if (byTf[o.tf] != null) byTf[o.tf]++;
      }
      const retained = Math.max(0, merged.length - freshOnly.length);
      setStatus(
        `Scan monde 5★: ${merged.length} kept (${freshOnly.length} this scan` +
          (retained ? `, +${retained} retained` : "") +
          `) · ${active} active · H1 ${byTf.H1} · M15 ${byTf.M15} · M5 ${byTf.M5}`
      );
      el.chartTitle.textContent = `Scan monde 5★ · M5+M15+H1`;
      el.sourceNote.textContent =
        `Merge keep · ${symbols.length} symbols × 3 TF · click a row to open chart`;
    } catch (err) {
      console.error(err);
      showError(`Scan monde failed: ${err.message}`);
      setStatus("Scan monde error — see banner");
    } finally {
      setPrimaryDisabled(false);
    }
  }

  function wireUi() {
    WATCHLIST.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = s.id;
      opt.textContent = s.label;
      el.symbolSelect.appendChild(opt);
    });
    el.symbolSelect.value = state.symbol;
    el.symbolSelect.addEventListener("change", () => {
      state.symbol = el.symbolSelect.value;
      loadData();
    });
    document.querySelectorAll(".tf-group button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tf-group button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.tf = btn.getAttribute("data-tf");
        loadData();
      });
    });
    if (el.btnPrimary) {
      el.btnPrimary.addEventListener("click", () => {
        loadData();
      });
    }
    if (el.btnScanWorld) {
      el.btnScanWorld.addEventListener("click", () => {
        scanWorldFiveStars();
      });
    }
    if (el.minStars) {
      el.minStars.value = String(state.minStars);
      el.minStars.addEventListener("change", () => {
        state.minStars = parseInt(el.minStars.value, 10) || 0;
        renderList();
        const geMin = state.obs.filter((o) => o.stars >= state.minStars).length;
        const shown = filteredObs().length;
        setStatus(`${shown} shown · ${geMin} OB ≥${state.minStars}★`);
      });
    }
    el.filterText.addEventListener("input", () => renderList());
    document.querySelectorAll(".check-filter button").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".check-filter button").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        state.checkFilter = btn.getAttribute("data-check-filter") || "all";
        renderList();
      });
    });
    if (el.btnClearChecked) {
      el.btnClearChecked.addEventListener("click", () => {
        clearAllChecked();
        renderList();
      });
    }
    if (el.syncCodeInput) {
      const existing = getStoredSyncCode();
      if (existing) el.syncCodeInput.value = existing;
      el.syncCodeInput.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          if (el.btnSyncLink) el.btnSyncLink.click();
        }
      });
    }
    if (el.btnSyncGenerate) {
      el.btnSyncGenerate.addEventListener("click", async () => {
        const code = generateSyncCode();
        setStoredSyncCode(code);
        if (el.syncCodeInput) el.syncCodeInput.value = code;
        setSyncStatus("Nouveau code…", "busy");
        try {
          // Seed cloud with current local map so Générer also starts syncing
          await pushCloudChecks(code, loadCheckedMap());
          setSyncStatus("Sync OK", "ok");
        } catch (err) {
          setSyncStatus("Sync err", "err");
        }
      });
    }
    if (el.btnSyncLink) {
      el.btnSyncLink.addEventListener("click", () => {
        const raw = el.syncCodeInput ? el.syncCodeInput.value : "";
        linkAndLoadSyncCode(raw);
      });
    }
  }

  // Expose for selftest / console
  window.__OB = { detectOrderBlocks, scoreOb, computeSlTp, scanWorldFiveStars, mergeObLists, obMergeKey, state, WATCHLIST };

  // boot — paint shell immediately, then load candles (don't feel blank)
  wireUi();
  initChart();
  setStatus("Chargement bougies…");
  if (el.chartTitle) el.chartTitle.textContent = `${state.symbol} · ${state.tf}`;
  renderList();
  (async function boot() {
    try {
      const code = getStoredSyncCode();
      if (code) {
        setStatus("Sync + chargement bougies…");
        await linkAndLoadSyncCode(code, { silent: true });
      }
      await loadData();
    } catch (err) {
      console.error(err);
      showError(`Démarrage: ${err.message || err}`);
      setStatus("Erreur au démarrage — voir bannière");
    }
  })();
})();
