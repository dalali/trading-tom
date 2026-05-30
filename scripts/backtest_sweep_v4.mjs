/**
 * RSI sweep v4 — dynamic exit timing + trailing stops.
 * Best entry so far: RSI(14)<30 AND RSI(2)<20 AND vol>1.5x avg.
 * Test: exit when RSI(2) crosses midline (50) vs fixed RSI(14) overbought.
 * Also test trailing stop to reduce drawdown.
 * Usage: node scripts/backtest_sweep_v4.mjs
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

// ── Core backtest with trailing stop support ──────────────────────────────────

function runBacktest(barsBySymbol, params, startDate, endDate) {
  const positionSize  = params.position_size ?? 0.25;
  const stopLossPct   = params.stop_loss ?? null;
  const trailPct      = params.trail_pct ?? null;  // trailing stop %
  const exitMode      = params.exit_mode ?? "rsi14"; // "rsi14" or "rsi2_midline"

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
  // positions: sym → { qty, avgPrice, stopLevel }
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
      const todayOpen  = h.opens[hi];
      const todayClose = h.closes[hi];
      if (!todayOpen) continue;

      const pos = positions[sym];
      let sold = false;

      // Stop-loss / trailing stop check at open
      if (pos) {
        const stopLevel = pos.stopLevel ?? (stopLossPct !== null ? pos.avgPrice * (1 - stopLossPct) : null);
        if (stopLevel !== null && todayOpen < stopLevel) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
          sold = true;
        }
      }

      if (!sold) {
        const n = closes.length;
        const r14 = rsiAt(closes, 14, n);
        const r2  = rsiAt(closes, 2, n);
        const r2prev = rsiAt(closes, 2, n - 1);
        const volAvg = sma(volumes, params.vol_period ?? 10, n);
        const vol = volumes[n - 1];
        const volOk = volAvg === null || (volAvg > 0 && vol >= volAvg * (params.vol_mult ?? 1.5));

        const r2Confirmed = r2 === null || r2 < (params.rsi2_entry ?? 20);

        // Sell signal
        let sellSignal = false;
        if (pos) {
          if (exitMode === "rsi2_midline") {
            // Exit when RSI(2) crosses above 50
            sellSignal = r2 !== null && r2prev !== null && r2prev < 50 && r2 >= 50;
            // Also exit if RSI(14) hits overbought (safety)
            if (r14 !== null && r14 > (params.overbought ?? 75)) sellSignal = true;
          } else {
            // Standard: exit when RSI(14) > overbought
            sellSignal = r14 !== null && r14 > (params.overbought ?? 75);
          }
        }

        if (sellSignal && pos) {
          cash += pos.qty * todayOpen;
          closingPnls.push((todayOpen - pos.avgPrice) * pos.qty);
          delete positions[sym];
        } else if (pos && trailPct !== null && todayClose > pos.avgPrice) {
          // Update trailing stop level upward
          const newStop = todayClose * (1 - trailPct);
          if (!pos.stopLevel || newStop > pos.stopLevel) {
            pos.stopLevel = newStop;
          }
        } else if (!pos && r14 !== null && r14 < (params.oversold ?? 30) && r2Confirmed && volOk) {
          // Buy
          let equity = cash;
          for (const [s, p] of Object.entries(positions)) {
            const sh = histIdx[s];
            const shi = sh.dates.lastIndexOf(today);
            equity += p.qty * (shi >= 0 ? sh.closes[shi] : p.avgPrice);
          }
          const qty = Math.floor(equity * positionSize / todayOpen);
          if (qty > 0 && cash >= qty * todayOpen) {
            cash -= qty * todayOpen;
            const initStop = stopLossPct !== null ? todayOpen * (1 - stopLossPct) : null;
            positions[sym] = { qty, avgPrice: todayOpen, stopLevel: initStop };
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
  return { nTrades: closingPnls.length, winRate, totalReturn, maxDrawdown: maxDD, sharpe };
}

// ── Grids ─────────────────────────────────────────────────────────────────────

// Best config from v3 + trailing stop variants
const TRAIL_GRID = [];
for (const trail_pct of [null, 0.03, 0.05, 0.07]) {
  for (const stop_loss of [0.05, 0.08]) {
    TRAIL_GRID.push({
      oversold: 30, overbought: 75, rsi2_entry: 20,
      vol_period: 10, vol_mult: 1.5,
      stop_loss, trail_pct,
      exit_mode: "rsi14",
      position_size: 0.25,
    });
  }
}

// RSI(2) midline exit variants
const MIDLINE_GRID = [];
for (const rsi2_entry of [15, 20, 25]) {
  for (const overbought of [70, 75, 80]) {  // safety cap for midline mode
    for (const stop_loss of [0.05, 0.08]) {
      for (const trail_pct of [null, 0.05]) {
        MIDLINE_GRID.push({
          oversold: 30, overbought, rsi2_entry,
          vol_period: 10, vol_mult: 1.5,
          stop_loss, trail_pct,
          exit_mode: "rsi2_midline",
          position_size: 0.25,
        });
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

function sweep(name, grid) {
  process.stdout.write(`\n${name} (${grid.length} configs)... `);
  const results = [];
  for (const params of grid) {
    const train = runBacktest(barsBySymbol, params, TRAIN_START, TRAIN_END);
    const val   = runBacktest(barsBySymbol, params, VAL_START,   VAL_END);
    if (train && val) results.push({ params, train, val });
  }
  results.sort((a, b) => b.val.sharpe - a.val.sharpe);
  console.log("done");
  console.log("\nTop 5 by validation Sharpe:");
  console.log("Params                                        | Train%  | Val%    | Sharpe | WR%  | MaxDD%");
  console.log("----------------------------------------------|---------|---------|--------|------|-------");
  for (const r of results.slice(0, 5)) {
    const stop  = r.params.stop_loss ? `sl=${(r.params.stop_loss*100).toFixed(0)}%` : "no-sl";
    const trail = r.params.trail_pct ? ` tr=${(r.params.trail_pct*100).toFixed(0)}%` : "";
    const exit  = r.params.exit_mode === "rsi2_midline" ? " mid" : "";
    const label = `os=${r.params.oversold} ob=${r.params.overbought} r2=${r.params.rsi2_entry} ${stop}${trail}${exit}`.padEnd(45);
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

const bestTrail   = sweep("Trailing stop variants",       TRAIL_GRID);
const bestMidline = sweep("RSI(2) midline exit",          MIDLINE_GRID);

console.log("\n\n=== COMPARISON (vs v3 baseline: +31.5%, Sharpe 1.685, DD -9.1%) ===");
const all = [
  { name: "Trailing stop", best: bestTrail },
  { name: "RSI(2) midline exit", best: bestMidline },
].sort((a, b) => b.best.val.sharpe - a.best.val.sharpe);

for (const { name, best } of all) {
  const { val, train, params } = best;
  const p = { ...params }; delete p.position_size;
  console.log(`\n${name}`);
  console.log(`  Params:       ${JSON.stringify(p)}`);
  console.log(`  Train return: ${(train.totalReturn*100).toFixed(2)}%  drawdown: ${(train.maxDrawdown*100).toFixed(1)}%`);
  console.log(`  Val return:   ${(val.totalReturn*100).toFixed(2)}%  drawdown: ${(val.maxDrawdown*100).toFixed(1)}%  sharpe: ${val.sharpe.toFixed(3)}  wr: ${(val.winRate*100).toFixed(0)}%`);
}
