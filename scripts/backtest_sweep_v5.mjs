/**
 * RSI sweep v5 — sector ETF robustness test + momentum filter.
 * Best config so far: RSI(14)<30, RSI(2)<20, vol>1.5x, sl=5%, ps=25% → +31.5% val, Sharpe 1.685
 * New tests:
 *   1. Momentum filter: only enter if N-day return > 0 (stock still in uptrend despite dip)
 *   2. Sector ETF universe: XLK, XLE, XLF, XLV, XLI, XLB, XLU
 * Usage: node scripts/backtest_sweep_v5.mjs
 */
import https from "https";

const TECH_SYMBOLS    = ["SPY", "AAPL", "MSFT", "QQQ", "NVDA", "AMZN"];
const SECTOR_SYMBOLS  = ["XLK", "XLF", "XLV", "XLI", "XLE", "XLB", "XLU", "XLRE"];
const STARTING_CAPITAL = 10000;
const VAL_START   = "2024-05-28";
const VAL_END     = "2025-05-23";
const TRAIN_START = "2019-01-01";
const TRAIN_END   = "2024-05-27";

function fetchBars(symbol) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1d&range=7y`;
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", () => {
        try {
          const r = JSON.parse(data).chart.result[0];
          const q = r.indicators.quote[0];
          const bars = r.timestamp.map((ts, i) => ({
            date:   new Date(ts * 1000).toISOString().slice(0, 10),
            open:   q.open[i], high: q.high[i], low: q.low[i],
            close:  q.close[i], volume: q.volume[i],
          })).filter(b => b.open != null && b.close != null && b.volume != null);
          resolve(bars);
        } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

function sma(arr, n, end) {
  if (end < n) return null;
  let s = 0;
  for (let i = end - n; i < end; i++) s += arr[i];
  return s / n;
}

function rsiAt(closes, period, end) {
  if (end < period + 1) return null;
  let gains = 0, losses = 0;
  for (let i = end - period; i < end; i++) {
    const d = closes[i] - closes[i - 1];
    if (d > 0) gains += d; else losses -= d;
  }
  const ag = gains / period, al = losses / period;
  if (al === 0) return 100;
  return 100 - 100 / (1 + ag / al);
}

function runBacktest(barsBySymbol, signalFn, params, startDate, endDate) {
  const positionSize = params.position_size ?? 0.25;
  const stopLossPct  = params.stop_loss ?? null;

  const dateSet = new Set();
  for (const bars of Object.values(barsBySymbol))
    for (const b of bars)
      if (b.date >= startDate && b.date <= endDate) dateSet.add(b.date);
  const dates = [...dateSet].sort();
  if (dates.length < 2) return null;

  const histIdx = {};
  for (const [sym, bars] of Object.entries(barsBySymbol)) {
    const all = bars.filter(b => b.date <= endDate);
    histIdx[sym] = {
      dates: all.map(b => b.date), closes: all.map(b => b.close),
      opens: all.map(b => b.open), volumes: all.map(b => b.volume),
    };
  }

  let cash = STARTING_CAPITAL;
  const positions = {};
  const closingPnls = [];
  const equitySeries = [];

  for (let di = 0; di < dates.length; di++) {
    const today = dates[di];
    for (const sym of Object.keys(barsBySymbol)) {
      const h = histIdx[sym];
      const hi = h.dates.lastIndexOf(today);
      if (hi < 1) continue;
      const closes  = h.closes.slice(0, hi);
      const volumes = h.volumes.slice(0, hi);
      const todayOpen = h.opens[hi];
      if (!todayOpen) continue;

      const pos = positions[sym];
      let sold = false;
      if (pos && stopLossPct !== null && todayOpen < pos.avgPrice * (1 - stopLossPct)) {
        cash += pos.qty * todayOpen;
        closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
        delete positions[sym];
        sold = true;
      }
      if (!sold) {
        const signal = signalFn(closes, volumes, params);
        if (signal === "sell" && pos) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
        } else if (signal === "buy" && !pos) {
          let equity = cash;
          for (const [s, p] of Object.entries(positions)) {
            const sh = histIdx[s]; const shi = sh.dates.lastIndexOf(today);
            equity += p.qty * (shi >= 0 ? sh.closes[shi] : p.avgPrice);
          }
          const qty = Math.floor(equity * positionSize / todayOpen);
          if (qty > 0 && cash >= qty * todayOpen) {
            cash -= qty * todayOpen;
            positions[sym] = { qty, avgPrice: todayOpen };
          }
        }
      }
    }
    let equity = cash;
    for (const [sym, pos] of Object.entries(positions)) {
      const h = histIdx[sym]; const hi = h.dates.lastIndexOf(today);
      equity += pos.qty * (hi >= 0 ? h.closes[hi] : pos.avgPrice);
    }
    equitySeries.push(equity);
  }

  const wins = closingPnls.filter(p => p > 0).length;
  const totalReturn = (equitySeries.at(-1) ?? STARTING_CAPITAL) / STARTING_CAPITAL - 1;
  const winRate = closingPnls.length ? wins / closingPnls.length : 0;
  let peak = -Infinity, maxDD = 0;
  for (const e of equitySeries) {
    if (e > peak) peak = e;
    const dd = (e - peak) / peak;
    if (dd < maxDD) maxDD = dd;
  }
  const returns = equitySeries.map((e, i) => i === 0 ? 0 : (e - equitySeries[i-1]) / equitySeries[i-1]).slice(1);
  const meanR = returns.reduce((a, b) => a + b, 0) / (returns.length || 1);
  const variance = returns.reduce((a, b) => a + (b - meanR) ** 2, 0) / (returns.length || 1);
  const sharpe = variance > 0 ? (meanR / Math.sqrt(variance)) * Math.sqrt(252) : 0;
  return { nTrades: closingPnls.length, winRate, totalReturn, maxDrawdown: maxDD, sharpe };
}

// ── Signal functions ───────────────────────────────────────────────────────────

// Best config from v3 (baseline)
function signalDoubleRSI_vol(closes, volumes, p) {
  const n = closes.length;
  const r14 = rsiAt(closes, 14, n);
  const r2  = rsiAt(closes, 2, n);
  if (r14 === null) return null;
  const volAvg = sma(volumes, p.vol_period ?? 10, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * (p.vol_mult ?? 1.5));
  const r2Ok  = r2 === null || r2 < (p.rsi2_entry ?? 20);
  if (r14 > (p.overbought ?? 75)) return "sell";
  if (r14 < (p.oversold ?? 30) && r2Ok && volOk) return "buy";
  return null;
}

// Momentum filter: only buy if N-day return is positive (short-term dip in uptrend)
function signalDoubleRSI_vol_momentum(closes, volumes, p) {
  const n = closes.length;
  const r14 = rsiAt(closes, 14, n);
  const r2  = rsiAt(closes, 2, n);
  if (r14 === null) return null;
  const volAvg = sma(volumes, p.vol_period ?? 10, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * (p.vol_mult ?? 1.5));
  const r2Ok  = r2 === null || r2 < (p.rsi2_entry ?? 20);
  // Momentum: price now > price N days ago
  const momPeriod = p.mom_period ?? 20;
  const momOk = n <= momPeriod || closes[n - 1] > closes[n - 1 - momPeriod];
  if (r14 > (p.overbought ?? 75)) return "sell";
  if (r14 < (p.oversold ?? 30) && r2Ok && volOk && momOk) return "buy";
  return null;
}

// Anti-momentum filter: only buy when falling (contrarian — price < N-day ago)
function signalDoubleRSI_vol_contrarian(closes, volumes, p) {
  const n = closes.length;
  const r14 = rsiAt(closes, 14, n);
  const r2  = rsiAt(closes, 2, n);
  if (r14 === null) return null;
  const volAvg = sma(volumes, p.vol_period ?? 10, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * (p.vol_mult ?? 1.5));
  const r2Ok  = r2 === null || r2 < (p.rsi2_entry ?? 20);
  // Anti-momentum: price now < price N days ago (deeper oversold, more mean-reversion potential)
  const momPeriod = p.mom_period ?? 20;
  const contraOk = n <= momPeriod || closes[n - 1] < closes[n - 1 - momPeriod];
  if (r14 > (p.overbought ?? 75)) return "sell";
  if (r14 < (p.oversold ?? 30) && r2Ok && volOk && contraOk) return "buy";
  return null;
}

// ── Grids ─────────────────────────────────────────────────────────────────────

// Baseline on tech symbols (v3 best config)
const BASELINE_PARAMS = {
  oversold: 30, overbought: 75, rsi2_entry: 20,
  vol_period: 10, vol_mult: 1.5, stop_loss: 0.05, position_size: 0.25
};

// Momentum filter grid
const MOM_GRID = [];
for (const mom_period of [10, 20, 40, 60]) {
  for (const oversold of [25, 30]) {
    for (const rsi2_entry of [15, 20]) {
      for (const stop_loss of [0.05, 0.08]) {
        MOM_GRID.push({ ...BASELINE_PARAMS, mom_period, oversold, rsi2_entry, stop_loss });
      }
    }
  }
}

// Anti-momentum grid (same params, different signal)
const CONTRA_GRID = [];
for (const mom_period of [10, 20, 40]) {
  for (const oversold of [25, 30]) {
    for (const stop_loss of [0.05, 0.08]) {
      CONTRA_GRID.push({ ...BASELINE_PARAMS, mom_period, oversold, stop_loss });
    }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

// Fetch both universes
console.log("Fetching tech symbols...");
const techBars = {};
for (const sym of TECH_SYMBOLS) {
  process.stdout.write(`  ${sym}... `);
  techBars[sym] = await fetchBars(sym);
  console.log(`${techBars[sym].length} bars`);
}

console.log("\nFetching sector ETFs...");
const sectorBars = {};
for (const sym of SECTOR_SYMBOLS) {
  process.stdout.write(`  ${sym}... `);
  try {
    sectorBars[sym] = await fetchBars(sym);
    console.log(`${sectorBars[sym].length} bars`);
  } catch (e) {
    console.log(`FAILED: ${e.message}`);
  }
}

function sweep(name, barsBySymbol, signalFn, grid) {
  process.stdout.write(`\n${name} (${grid.length} configs)... `);
  const results = [];
  for (const params of grid) {
    const train = runBacktest(barsBySymbol, signalFn, params, TRAIN_START, TRAIN_END);
    const val   = runBacktest(barsBySymbol, signalFn, params, VAL_START,   VAL_END);
    if (train && val) results.push({ params, train, val });
  }
  results.sort((a, b) => b.val.sharpe - a.val.sharpe);
  console.log("done");
  console.log("\nTop 5 by validation Sharpe:");
  console.log("Params                                        | Train%  | Val%    | Sharpe | WR%  | MaxDD%");
  console.log("----------------------------------------------|---------|---------|--------|------|-------");
  for (const r of results.slice(0, 5)) {
    const p = r.params;
    const stop = `sl=${(p.stop_loss*100).toFixed(0)}%`;
    const mom  = p.mom_period ? ` mom${p.mom_period}d` : "";
    const label = `os=${p.oversold} r2=${p.rsi2_entry ?? 20} ${stop}${mom}`.padEnd(45);
    const tr = (r.train.totalReturn*100).toFixed(1).padStart(6)+"%";
    const vr = (r.val.totalReturn*100).toFixed(1).padStart(6)+"%";
    const sh = r.val.sharpe.toFixed(3).padStart(6);
    const wr = (r.val.winRate*100).toFixed(0).padStart(4)+"%";
    const dd = (r.val.maxDrawdown*100).toFixed(1).padStart(6)+"%";
    console.log(`${label} | ${tr} | ${vr} | ${sh} | ${wr} | ${dd}`);
  }
  const profitable = results.filter(r => r.val.totalReturn > 0).length;
  console.log(`Profitable on validation: ${profitable}/${results.length}`);
  return results[0];
}

// Sector ETF baseline (same v3 params, new universe — robustness test)
const sectorBaseline = runBacktest(sectorBars, signalDoubleRSI_vol, BASELINE_PARAMS, TRAIN_START, TRAIN_END);
const sectorVal      = runBacktest(sectorBars, signalDoubleRSI_vol, BASELINE_PARAMS, VAL_START, VAL_END);
console.log("\n=== SECTOR ETF ROBUSTNESS (v3 params, new universe) ===");
if (sectorBaseline && sectorVal) {
  console.log(`Train: ${(sectorBaseline.totalReturn*100).toFixed(2)}%  sharpe: ${sectorBaseline.sharpe.toFixed(3)}  DD: ${(sectorBaseline.maxDrawdown*100).toFixed(1)}%`);
  console.log(`Val:   ${(sectorVal.totalReturn*100).toFixed(2)}%  sharpe: ${sectorVal.sharpe.toFixed(3)}  DD: ${(sectorVal.maxDrawdown*100).toFixed(1)}%  WR: ${(sectorVal.winRate*100).toFixed(0)}%`);
} else {
  console.log("Not enough data.");
}

// Combined universe
const allBars = { ...techBars, ...sectorBars };
const allBaseline = runBacktest(allBars, signalDoubleRSI_vol, BASELINE_PARAMS, TRAIN_START, TRAIN_END);
const allVal      = runBacktest(allBars, signalDoubleRSI_vol, BASELINE_PARAMS, VAL_START, VAL_END);
console.log("\n=== COMBINED UNIVERSE (tech + sectors, v3 params) ===");
if (allBaseline && allVal) {
  console.log(`Train: ${(allBaseline.totalReturn*100).toFixed(2)}%  sharpe: ${allBaseline.sharpe.toFixed(3)}  DD: ${(allBaseline.maxDrawdown*100).toFixed(1)}%`);
  console.log(`Val:   ${(allVal.totalReturn*100).toFixed(2)}%  sharpe: ${allVal.sharpe.toFixed(3)}  DD: ${(allVal.maxDrawdown*100).toFixed(1)}%  WR: ${(allVal.winRate*100).toFixed(0)}%`);
} else {
  console.log("Not enough data.");
}

const bestMom    = sweep("Momentum filter (tech)",    techBars,   signalDoubleRSI_vol_momentum,   MOM_GRID);
const bestContra = sweep("Anti-momentum (tech)",      techBars,   signalDoubleRSI_vol_contrarian, CONTRA_GRID);

console.log("\n\n=== FINAL COMPARISON (v3 baseline: +31.5%, Sharpe 1.685, DD -9.1%) ===");
const rows = [
  { name: "Sector ETF (v3 params)",    ret: sectorVal?.totalReturn, sh: sectorVal?.sharpe, dd: sectorVal?.maxDrawdown, wr: sectorVal?.winRate },
  { name: "Combined universe (v3)",    ret: allVal?.totalReturn,    sh: allVal?.sharpe,    dd: allVal?.maxDrawdown,    wr: allVal?.winRate },
  { name: "Momentum filter",           ret: bestMom?.val.totalReturn,    sh: bestMom?.val.sharpe,    dd: bestMom?.val.maxDrawdown,    wr: bestMom?.val.winRate, p: bestMom?.params },
  { name: "Anti-momentum filter",      ret: bestContra?.val.totalReturn, sh: bestContra?.val.sharpe, dd: bestContra?.val.maxDrawdown, wr: bestContra?.val.winRate, p: bestContra?.params },
].sort((a, b) => (b.sh ?? 0) - (a.sh ?? 0));

for (const r of rows) {
  const pStr = r.p ? `  params: ${JSON.stringify({ ...r.p, position_size: undefined })}` : "";
  console.log(`\n${r.name}`);
  console.log(`  Val return: ${((r.ret??0)*100).toFixed(2)}%  sharpe: ${(r.sh??0).toFixed(3)}  DD: ${((r.dd??0)*100).toFixed(1)}%  WR: ${((r.wr??0)*100).toFixed(0)}%${pStr}`);
}
