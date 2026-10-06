// Runs the ORIGINAL v1 detectOrderBlocks (extracted verbatim from v1_snapshot/app.js) on a candle JSON file.
import fs from "fs";
const src = fs.readFileSync(new URL("./v1_snapshot/app.js", import.meta.url), "utf8");
const a = src.indexOf("  const BODY_LOOKBACK"), b = src.indexOf("  const state = {");
const s = src.indexOf("  // --- Scoring helpers ---"), e = src.indexOf("  // --- UI helpers ---");
const code = src.slice(a, b) + "\nconst state = {symbol:'X', tf:'X'};\n" + src.slice(s, e) + "\nreturn detectOrderBlocks;";
const detect = new Function(code)();
const data = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const obs = detect(data.candles, { symbol: "X", tf: "X", maxObs: 1e9 });
const idx = new Map(data.candles.map((c, i) => [c.time, i]));
console.log(JSON.stringify(obs.map(o => [o.dispIndex, idx.get(o.time), o.side === "bullish" ? 1 : -1,
  o.starFlags.fvg, o.starFlags.bos, o.starFlags.sweep, o.starFlags.fresh, o.starFlags.pd, o.entry, o.sl, o.tp])));
