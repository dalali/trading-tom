/**
 * RSI sweep v2 — adds volume confirmation filter + ATR-based stops.
 * Tests wider symbol universe. O(n) per config.
 * Usage: node scripts/backtest_sweep_v2.mjs
 */
import https from "https";

const SYMBOLS = ["SPY", "AAPL", "MSFT", "QQQ", "NVDA", "AMZN"];
const STARTING_CAPITAL = 10000;
const VAL_START   = "2024-05-28";
const VAL_END     = "2025-05-23";
const TRAIN_START = "2019-01-01";
const TRAIN_END   = "2024-05-27";

// ── Yahoo Finance ─────────────────────────────────────────────────────────────

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
            open:   q.open[i],
            high:   q.high[i],
            low:    q.low[i],
            close:  q.close[i],
            volume: q.volume[i],
          })).filter(b => b.open != null && b.close != null && b.volume != null);
          resolve(bars);
        } catch (e) { reject(e); }
      });
    }).on("error", reject);
  });
}

// ── Indicators ─────────────────────────────────────────────────────────────────

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

function atrAt(highs, lows, closes, period, end) {
  // Average True Range
  if (end < period + 1) return null;
  let sum = 0;
  for (let i = end - period; i < end; i++) {
    const hl = highs[i] - lows[i];
    const hc = Math.abs(highs[i] - closes[i - 1]);
    const lc = Math.abs(lows[i] - closes[i - 1]);
    sum += Math.max(hl, hc, lc);
  }
  return sum / period;
}

// ── Core backtest ──────────────────────────────────────────────────────────────

function runBacktest(barsBySymbol, signalFn, params, startDate, endDate) {
  const positionSize = params.position_size ?? 0.25;
  const stopLossPct  = params.stop_loss ?? null;
  const atrStopMult  = params.atr_stop ?? null; // if set, use ATR-based stop instead

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
      dates:   all.map(b => b.date),
      closes:  all.map(b => b.close),
      opens:   all.map(b => b.open),
      highs:   all.map(b => b.high),
      lows:    all.map(b => b.low),
      volumes: all.map(b => b.volume),
    };
  }

  let cash = STARTING_CAPITAL;
  const positions = {}; // sym → { qty, avgPrice, atrStop }
  const closingPnls = [];
  const equitySeries = [];

  for (let di = 0; di < dates.length; di++) {
    const today = dates[di];

    for (const sym of Object.keys(barsBySymbol)) {
      const h = histIdx[sym];
      const hi = h.dates.lastIndexOf(today);
      if (hi < 1) continue;

      const closesUpTo  = h.closes.slice(0, hi);
      const volumesUpTo = h.volumes.slice(0, hi);
      const todayOpen   = h.opens[hi];
      if (!todayOpen) continue;

      const pos = positions[sym];
      let sold = false;

      // ATR-based dynamic stop
      if (pos && atrStopMult !== null && pos.atrStop != null) {
        if (todayOpen < pos.atrStop) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
          sold = true;
        }
      } else if (pos && stopLossPct !== null) {
        // Fixed % stop
        if (todayOpen < pos.avgPrice * (1 - stopLossPct)) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
          sold = true;
        }
      }

      if (!sold) {
        const signal = signalFn(closesUpTo, volumesUpTo, h, hi, params);
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
          const target = equity * positionSize;
          const qty = Math.floor(target / todayOpen);
          if (qty > 0 && cash >= qty * todayOpen) {
            cash -= qty * todayOpen;
            // Compute ATR stop level if using ATR stops
            let atrStop = null;
            if (atrStopMult !== null) {
              const atr = atrAt(h.highs, h.lows, h.closes, 14, hi);
              if (atr) atrStop = todayOpen - atrStopMult * atr;
            }
            positions[sym] = { qty, avgPrice: todayOpen, atrStop };
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

// Baseline RSI (same as v1)
function signalRSI_baseline(closes, volumes, h, hi, p) {
  const n = closes.length;
  const r = rsiAt(closes, p.period, n);
  if (r === null) return null;
  if (r < p.oversold) return "buy";
  if (r > p.overbought) return "sell";
  return null;
}

// RSI + volume confirmation: only buy when volume > vol_sma_period SMA * vol_mult
function signalRSI_volFilter(closes, volumes, h, hi, p) {
  const n = closes.length;
  const r = rsiAt(closes, p.period, n);
  if (r === null) return null;
  if (r > p.overbought) return "sell";
  if (r < p.oversold) {
    // Volume check: current day's volume vs avg
    const volSma = sma(volumes, p.vol_period, n);
    if (volSma === null) return null;
    const currentVol = volumes[n - 1];
    if (currentVol < volSma * p.vol_mult) return null; // no confirmation
    return "buy";
  }
  return null;
}

// RSI + SMA trend filter: only buy above N-day SMA (already in swing.py but test strength)
function signalRSI_trendFilter(closes, volumes, h, hi, p) {
  const n = closes.length;
  const r = rsiAt(closes, p.period, n);
  if (r === null) return null;
  const trend = sma(closes, p.trend_period, n);
  if (trend === null) return null;
  const price = closes[n - 1];
  if (r > p.overbought) return "sell";
  if (r < p.oversold && price > trend) return "buy";
  return null;
}

// ── Grids ─────────────────────────────────────────────────────────────────────

// Baseline: replicate best from v1 + a few close variants
const BASELINE_GRID = [];
for (const period of [10, 14]) {
  for (const oversold of [25, 30]) {
    for (const overbought of [70, 75]) {
      for (const stop_loss of [null, 0.05, 0.08]) {
        BASELINE_GRID.push({ period, oversold, overbought, stop_loss, position_size: 0.25 });
      }
    }
  }
}

// Volume filter variants
const VOL_GRID = [];
for (const period of [10, 14]) {
  for (const oversold of [25, 30]) {
    for (const overbought of [70, 75]) {
      for (const vol_period of [10, 20]) {
        for (const vol_mult of [1.0, 1.2, 1.5]) {
          for (const stop_loss of [0.05, 0.08]) {
            VOL_GRID.push({ period, oversold, overbought, vol_period, vol_mult, stop_loss, position_size: 0.25 });
          }
        }
      }
    }
  }
}

// Trend filter variants
const TREND_GRID = [];
for (const period of [10, 14]) {
  for (const oversold of [25, 30]) {
    for (const overbought of [70, 75]) {
      for (const trend_period of [20, 50, 100]) {
        for (const stop_loss of [0.05, 0.08]) {
          for (const atr_stop of [null, 2.0, 3.0]) {
            TREND_GRID.push({ period, oversold, overbought, trend_period, stop_loss, atr_stop, position_size: 0.25 });
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
    const stop = r.params.atr_stop ? `atr${r.params.atr_stop}x` : (r.params.stop_loss ? `sl=${(r.params.stop_loss*100).toFixed(0)}%` : "no-sl");
    const base = JSON.stringify({
      period: r.params.period,
      os: r.params.oversold,
      ob: r.params.overbought,
      ...(r.params.vol_period ? { vp: r.params.vol_period, vm: r.params.vol_mult } : {}),
      ...(r.params.trend_period ? { trend: r.params.trend_period } : {}),
    });
    const label = `${base} ${stop}`.padEnd(45);
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

const bestBaseline = sweep("RSI Baseline (wider symbols)",    signalRSI_baseline,   BASELINE_GRID);
const bestVol      = sweep("RSI + Volume filter",             signalRSI_volFilter,  VOL_GRID);
const bestTrend    = sweep("RSI + Trend + ATR stop",          signalRSI_trendFilter, TREND_GRID);

console.log("\n\n=== FINAL COMPARISON ===");
const all = [
  { name: "RSI baseline",       best: bestBaseline },
  { name: "RSI + vol filter",   best: bestVol },
  { name: "RSI + trend filter", best: bestTrend },
].sort((a, b) => b.best.val.totalReturn - a.best.val.totalReturn);

for (const { name, best } of all) {
  const { val, train, params } = best;
  const p = { ...params }; delete p.position_size;
  console.log(`\n${name}`);
  console.log(`  Params:       ${JSON.stringify(p)}`);
  console.log(`  Train return: ${(train.totalReturn*100).toFixed(2)}%  drawdown: ${(train.maxDrawdown*100).toFixed(1)}%`);
  console.log(`  Val return:   ${(val.totalReturn*100).toFixed(2)}%  drawdown: ${(val.maxDrawdown*100).toFixed(1)}%  sharpe: ${val.sharpe.toFixed(3)}  wr: ${(val.winRate*100).toFixed(0)}%`);
}
