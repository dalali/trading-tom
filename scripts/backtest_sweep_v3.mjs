/**
 * RSI sweep v3 — explore position sizing variants and RSI(2) ultra-short.
 * Also tests holding the position until RSI > 50 mid-line (vs fixed overbought).
 * Usage: node scripts/backtest_sweep_v3.mjs
 */
import https from "https";

const SYMBOLS = ["SPY", "AAPL", "MSFT", "QQQ", "NVDA", "AMZN"];
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
  let sum = 0;
  for (let i = end - n; i < end; i++) sum += arr[i];
  return sum / n;
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
      opens: all.map(b => b.open), highs: all.map(b => b.high),
      lows: all.map(b => b.low), volumes: all.map(b => b.volume),
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
            const sh = histIdx[s];
            const shi = sh.dates.lastIndexOf(today);
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

// ── Signal functions ───────────────────────────────────────────────────────────

// Best from v2: RSI(14) + volume 1.5x
function signalRSI_vol(closes, volumes, p) {
  const n = closes.length;
  const r = rsiAt(closes, p.period, n);
  if (r === null) return null;
  const volAvg = sma(volumes, p.vol_period, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * p.vol_mult);
  if (r > p.overbought) return "sell";
  if (r < p.oversold && volOk) return "buy";
  return null;
}

// RSI(2) — ultra-short, exit at midline (50)
function signalRSI2(closes, volumes, p) {
  const n = closes.length;
  const r = rsiAt(closes, 2, n);
  const rPrev = rsiAt(closes, 2, n - 1);
  if (r === null || rPrev === null) return null;
  const volAvg = sma(volumes, p.vol_period, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * p.vol_mult);
  // Buy on oversold RSI(2) below 10
  if (r < p.oversold && volOk) return "buy";
  // Exit when RSI(2) crosses above mid (50) or hits overbought
  if (r > p.overbought) return "sell";
  return null;
}

// Double RSI: RSI(14) oversold triggers, RSI(2) confirms (even lower)
function signalDoubleRSI(closes, volumes, p) {
  const n = closes.length;
  const r14 = rsiAt(closes, 14, n);
  const r2  = rsiAt(closes, 2, n);
  if (r14 === null || r2 === null) return null;
  const volAvg = sma(volumes, p.vol_period, n);
  const vol = volumes[n - 1];
  const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * p.vol_mult);
  // Buy: RSI(14) < oversold AND RSI(2) also confirms further drop
  if (r14 < p.oversold && r2 < p.r2_entry && volOk) return "buy";
  if (r14 > p.overbought) return "sell";
  return null;
}

// ── Grids ─────────────────────────────────────────────────────────────────────

// Best config from v2, varied position size
const SIZING_GRID = [];
for (const position_size of [0.15, 0.20, 0.25, 0.30, 0.35]) {
  for (const stop_loss of [0.05, 0.08]) {
    SIZING_GRID.push({
      period: 14, oversold: 30, overbought: 75,
      vol_period: 10, vol_mult: 1.5,
      stop_loss, position_size
    });
  }
}

// RSI(2) ultra-short
const RSI2_GRID = [];
for (const oversold of [5, 10, 15]) {
  for (const overbought of [50, 60, 70]) {
    for (const vol_period of [10, 20]) {
      for (const vol_mult of [1.0, 1.5]) {
        for (const stop_loss of [0.03, 0.05, 0.08]) {
          RSI2_GRID.push({ oversold, overbought, vol_period, vol_mult, stop_loss, position_size: 0.25 });
        }
      }
    }
  }
}

// Double RSI
const DOUBLE_RSI_GRID = [];
for (const oversold of [25, 30]) {
  for (const overbought of [70, 75]) {
    for (const r2_entry of [15, 20, 25]) {
      for (const vol_period of [10]) {
        for (const vol_mult of [1.5]) {
          for (const stop_loss of [0.05, 0.08]) {
            DOUBLE_RSI_GRID.push({ oversold, overbought, r2_entry, vol_period, vol_mult, stop_loss, position_size: 0.25 });
          }
        }
      }
    }
  }
}

// ── Main ──────────────────────────────────────────────────────────────────────

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
  console.log("Params                                        | Train%  | Val%    | Sharpe | WR%  | MaxDD%");
  console.log("----------------------------------------------|---------|---------|--------|------|-------");
  for (const r of results.slice(0, 5)) {
    const stop = r.params.stop_loss ? `sl=${(r.params.stop_loss*100).toFixed(0)}%` : "no-sl";
    const pCopy = { ...r.params }; delete pCopy.position_size; delete pCopy.stop_loss;
    const label = `${JSON.stringify(pCopy)} ${stop} ps=${(r.params.position_size*100).toFixed(0)}%`.padEnd(45);
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

const bestSizing    = sweep("RSI+Vol — position sizing",  signalRSI_vol,   SIZING_GRID);
const bestRSI2      = sweep("RSI(2) ultra-short",          signalRSI2,      RSI2_GRID);
const bestDoubleRSI = sweep("Double RSI (14+2)",            signalDoubleRSI, DOUBLE_RSI_GRID);

console.log("\n\n=== COMPARISON ===");
const all = [
  { name: "RSI+Vol sizing",  best: bestSizing },
  { name: "RSI(2)",          best: bestRSI2 },
  { name: "Double RSI",      best: bestDoubleRSI },
].sort((a, b) => b.best.val.sharpe - a.best.val.sharpe);

for (const { name, best } of all) {
  const { val, train, params } = best;
  const p = { ...params }; delete p.position_size;
  console.log(`\n${name}`);
  console.log(`  Params:       ${JSON.stringify(p)}`);
  console.log(`  Train return: ${(train.totalReturn*100).toFixed(2)}%  drawdown: ${(train.maxDrawdown*100).toFixed(1)}%`);
  console.log(`  Val return:   ${(val.totalReturn*100).toFixed(2)}%  drawdown: ${(val.maxDrawdown*100).toFixed(1)}%  sharpe: ${val.sharpe.toFixed(3)}  wr: ${(val.winRate*100).toFixed(0)}%`);
}
