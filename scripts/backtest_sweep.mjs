/**
 * Fast parameter sweep — O(n) per config using pre-indexed bars.
 * Finds best MA/RSI/GoldenCross params + optimal stop-loss.
 * Usage: node scripts/backtest_sweep.mjs
 */
import https from "https";

const SYMBOLS = ["SPY", "AAPL", "MSFT"];
const STARTING_CAPITAL = 10000;
const VAL_START  = "2024-05-28";
const VAL_END    = "2025-05-23";
const TRAIN_START = "2019-01-01";
const TRAIN_END  = "2024-05-27";

// ── Yahoo Finance ──────────────────────────────────────────────────────────

function fetchBars(symbol) {
  return new Promise((resolve, reject) => {
    const url = `https://query1.finance.yahoo.com/v8/finance/chart/${symbol}?interval=1d&range=7y`;
    https.get(url, { headers: { "User-Agent": "Mozilla/5.0" } }, (res) => {
      let data = "";
      res.on("data", c => data += c);
      res.on("end", () => {
        try {
          const r = JSON.parse(data).chart.result[0];
          const bars = r.timestamp.map((ts, i) => ({
            date: new Date(ts * 1000).toISOString().slice(0, 10),
            open:  r.indicators.quote[0].open[i],
            close: r.indicators.quote[0].close[i],
          })).filter(b => b.open != null && b.close != null);
          resolve(bars);
        } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

// ── Indicators (on raw arrays, fast) ──────────────────────────────────────

function sma(arr, n, end) {
  // SMA of arr[end-n .. end-1]
  if (end < n) return null;
  let sum = 0;
  for (let i = end - n; i < end; i++) sum += arr[i];
  return sum / n;
}

function rsiAt(closes, period, end) {
  // RSI using simple average (fast approximation)
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

// ── Core backtest (O(n_dates) per config) ─────────────────────────────────

function runBacktest(barsBySymbol, signalFn, params, startDate, endDate) {
  const positionSize = params.position_size ?? 0.25;
  const stopLossPct  = params.stop_loss ?? null;

  // Build sorted date list for the period
  const dateSet = new Set();
  for (const bars of Object.values(barsBySymbol)) {
    for (const b of bars) {
      if (b.date >= startDate && b.date <= endDate) dateSet.add(b.date);
    }
  }
  const dates = [...dateSet].sort();
  if (dates.length < 2) return null;

  // Pre-index: symbol → { dates[], closes[], opens[] } aligned to trading calendar
  const idx = {};
  for (const [sym, bars] of Object.entries(barsBySymbol)) {
    const filtered = bars.filter(b => b.date >= startDate && b.date <= endDate);
    idx[sym] = {
      dates:  filtered.map(b => b.date),
      closes: filtered.map(b => b.close),
      opens:  filtered.map(b => b.open),
    };
  }

  // We need history before startDate for indicator warmup — use all bars up to endDate
  const histIdx = {};
  for (const [sym, bars] of Object.entries(barsBySymbol)) {
    const all = bars.filter(b => b.date <= endDate);
    histIdx[sym] = {
      dates:  all.map(b => b.date),
      closes: all.map(b => b.close),
      opens:  all.map(b => b.open),
    };
  }

  let cash = STARTING_CAPITAL;
  const positions = {}; // sym → { qty, avgPrice }
  const closingPnls = [];
  const equitySeries = [];

  for (let di = 0; di < dates.length; di++) {
    const today = dates[di];

    for (const sym of Object.keys(barsBySymbol)) {
      const h = histIdx[sym];
      // Find index of today in full history
      const hi = h.dates.lastIndexOf(today);
      if (hi < 1) continue;

      const closesUpToYesterday = h.closes.slice(0, hi);  // yesterday's close is last
      const todayOpen = h.opens[hi];
      if (!todayOpen) continue;

      const pos = positions[sym];
      let sold = false;

      // Stop-loss check (at today's open, before strategy signal)
      if (pos && stopLossPct !== null && todayOpen < pos.avgPrice * (1 - stopLossPct)) {
        cash += pos.qty * todayOpen;
        closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
        delete positions[sym];
        sold = true;
      }

      if (!sold) {
        const signal = signalFn(closesUpToYesterday, params);
        if (signal === "sell" && pos) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
        } else if (signal === "buy" && !pos) {
          // Compute total equity for sizing
          let equity = cash;
          for (const [s, p] of Object.entries(positions)) {
            const sh = histIdx[s];
            const shi = sh.dates.lastIndexOf(today);
            equity += p.qty * (shi >= 0 ? sh.closes[shi] : p.avgPrice);
          }
          const target = equity * positionSize;
          const qty = Math.floor(target / todayOpen);
          if (qty > 0 && cash >= qty * todayOpen) {
            cash -= qty * todayOpen;
            positions[sym] = { qty, avgPrice: todayOpen };
          }
        }
      }
    }

    // Mark-to-market equity
    let equity = cash;
    for (const [sym, pos] of Object.entries(positions)) {
      const h = histIdx[sym];
      const hi = h.dates.lastIndexOf(today);
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

  return { nTrades: closingPnls.length, winRate, totalReturn, maxDrawdown: maxDD, sharpe,
           finalEquity: equitySeries.at(-1) ?? STARTING_CAPITAL };
}

// ── Signal functions ───────────────────────────────────────────────────────

function signalMA(closes, p) {
  const n = closes.length;
  if (n < p.slow + 1) return null;
  const fn = sma(closes, p.fast, n), fp = sma(closes, p.fast, n - 1);
  const sn = sma(closes, p.slow, n), sp = sma(closes, p.slow, n - 1);
  if (!fn || !fp || !sn || !sp) return null;
  if (fp <= sp && fn > sn) return "buy";
  if (fp >= sp && fn < sn) return "sell";
  return null;
}

function signalRSI(closes, p) {
  const n = closes.length;
  const r = rsiAt(closes, p.period, n);
  if (r === null) return null;
  if (r < p.oversold) return "buy";
  if (r > p.overbought) return "sell";
  return null;
}

function signalGC(closes, p) {
  const n = closes.length;
  if (n < p.slow + 1) return null;
  const fn = sma(closes, p.fast, n), fp = sma(closes, p.fast, n - 1);
  const sn = sma(closes, p.slow, n), sp = sma(closes, p.slow, n - 1);
  if (!fn || !fp || !sn || !sp) return null;
  if (fp <= sp && fn > sn) return "buy";
  if (fp >= sp && fn < sn) return "sell";
  return null;
}

// ── Grids ─────────────────────────────────────────────────────────────────

const STOPS = [null, 0.05, 0.08, 0.12, 0.15];

const MA_GRID = [];
for (const fast of [5, 8, 10, 12, 15, 20]) {
  for (const slow of [20, 30, 40, 50, 60]) {
    if (slow <= fast * 1.5) continue;
    for (const stop_loss of STOPS)
      MA_GRID.push({ fast, slow, stop_loss, position_size: 0.30 });
  }
}

const RSI_GRID = [];
for (const period of [7, 10, 14, 21]) {
  for (const oversold of [25, 30, 35]) {
    for (const overbought of [65, 70, 75]) {
      for (const stop_loss of STOPS)
        RSI_GRID.push({ period, oversold, overbought, stop_loss, position_size: 0.25 });
    }
  }
}

const GC_GRID = [];
for (const [fast, slow] of [[20,50],[50,100],[50,150],[50,200],[20,100]]) {
  for (const stop_loss of STOPS)
    GC_GRID.push({ fast, slow, stop_loss, position_size: 0.25 });
}

// ── Main ──────────────────────────────────────────────────────────────────

console.log("Fetching data...");
const barsBySymbol = {};
for (const sym of SYMBOLS) {
  process.stdout.write(`  ${sym}... `);
  barsBySymbol[sym] = await fetchBars(sym);
  console.log(`${barsBySymbol[sym].length} bars`);
}

function sweep(name, signalFn, grid) {
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
  console.log("Params                              | Train%  | Val%    | Sharpe | WR%  | MaxDD%");
  console.log("------------------------------------|---------|---------|--------|------|-------");
  for (const r of results.slice(0, 5)) {
    const stop = r.params.stop_loss ? `sl=${(r.params.stop_loss*100).toFixed(0)}%` : "no-sl";
    const base = JSON.stringify({...r.params, stop_loss: undefined, position_size: undefined});
    const label = `${base} ${stop}`.padEnd(35);
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

const bestMA  = sweep("MA Crossover (day)",   signalMA,  MA_GRID);
const bestRSI = sweep("RSI Swing",            signalRSI, RSI_GRID);
const bestGC  = sweep("Golden Cross (pos)",   signalGC,  GC_GRID);

console.log("\n\n=== FINAL RECOMMENDATION ===");
const ranked = [
  { name: "day   (MA cross)", best: bestMA },
  { name: "swing (RSI)",      best: bestRSI },
  { name: "pos   (GC)",       best: bestGC },
].sort((a, b) => b.best.val.totalReturn - a.best.val.totalReturn);

for (const { name, best } of ranked) {
  const { val, train, params } = best;
  const p = { ...params }; delete p.position_size;
  console.log(`\n${name}`);
  console.log(`  Params:       ${JSON.stringify(p)}`);
  console.log(`  Train return: ${(train.totalReturn*100).toFixed(2)}%  drawdown: ${(train.maxDrawdown*100).toFixed(1)}%`);
  console.log(`  Val return:   ${(val.totalReturn*100).toFixed(2)}%  drawdown: ${(val.maxDrawdown*100).toFixed(1)}%  sharpe: ${val.sharpe.toFixed(3)}  wr: ${(val.winRate*100).toFixed(0)}%`);
}
