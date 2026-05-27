# UI/UX Design — Trading Tom

**Version:** 1.0 (MVP)
**Status:** Draft for architecture
**Author:** UI/UX Designer (PM pipeline)
**Date:** 2026-05-27
**Source:** Derived from `docs/PRD.md` v1.0

---

## 0. Design Principles & Assumptions

Trading Tom's dashboard is a **read-first analytics surface** for a single operator reviewing what an autonomous bot did. It is not a live order-entry terminal — there are no "Buy/Sell" buttons, no order tickets, no real money. This shapes every decision below: density over decoration, clarity over interactivity, trust signals over flash.

**Design principles**

1. **Glanceability.** The operator should answer "how is the bot doing today?" in under 3 seconds without scrolling. Hero numbers (balance, today's net P&L) dominate the top of every view.
2. **Trust through transparency.** Anti-overfitting is the product's reason to exist. The UI surfaces the data split (`train/validation/test`) on every trade and run, so the operator can audit that results are honest. Simulation status is always visible — never let the user forget this is paper.
3. **Numbers are the hero, charts are the supporting cast.** This is a performance-review tool. Tables and big stat numbers carry the load; charts contextualize trends.
4. **Calm by default, signal on demand.** A dark, low-contrast canvas keeps green/red P&L coloring as the only loud element. Profit and loss are the only things that "shout."
5. **Desktop-first, responsive-graceful.** The operator reviews on a laptop/desktop. Mobile is supported (responsive) but not optimized for trade entry — there is none.

**Assumptions (carried from PRD, restated for design)**

- DA-1. Single trusted operator; no login/registration UI in MVP scope. (If the VPS dashboard is internet-exposed, a minimal token gate is the only auth surface — see §8.)
- DA-2. "Today"/"this week" and market hours are US Eastern (ET); all timestamps render in ET with an explicit `ET` suffix.
- DA-3. Exactly one account is `active`; all others `archived`. The account switcher always badges the active one.
- DA-4. Monetary values arrive from the API as integer cents; the frontend formats to `$X,XXX.XX`. The FE never does money math beyond display formatting (the ledger is authoritative on the backend).
- DA-5. The dashboard polls the API on an interval (default 30s) rather than using websockets for MVP — simpler, sufficient for a simulation that ticks at most once per minute.
- DA-6. Long-only, no short positions in MVP, so position rows never show negative quantity.

---

## 1. Information Architecture

### 1.1 Navigation model

A persistent **left sidebar** (collapsible) + a **top context bar**. The sidebar holds primary navigation; the top bar holds the account switcher and global status. This mirrors Binance/eToro's layout where a left rail organizes sections and a top strip carries account/portfolio context.

```
┌────────────┬─────────────────────────────────────────────────┐
│            │  TOP CONTEXT BAR (account switcher · engine · ET) │
│  SIDEBAR   ├─────────────────────────────────────────────────┤
│  (nav)     │                                                   │
│            │              MAIN CONTENT AREA                    │
│            │              (selected view)                      │
│            │                                                   │
└────────────┴─────────────────────────────────────────────────┘
```

### 1.2 Page / view map

| # | View | Route | Purpose | PRD refs |
|---|------|-------|---------|----------|
| 1 | **Daily Dashboard** | `/` (default) | Today's trades, per-trade P&L, running balance, fees, open positions | D1–D3, FR-25 |
| 2 | **Weekly Dashboard** | `/weekly` | Week summary stats, win rate, net P&L, equity chart | E1–E2, FR-26 |
| 3 | **Accounts** | `/accounts` | Browse all accounts (active + archived); switch the active scope | F1, F3, FR-27 |
| 4 | **Account Detail** | `/accounts/:id` | Full trade history + lifetime summary for one account | F2, FR-28 |
| 5 | **Backtests** | `/backtests` | List backtest runs + a run detail panel (metrics, split used) | FR-20, FR-22, C2 |
| 6 | **Settings / Strategy Config** | `/settings` | View & edit strategy params, fee model, watchlist; engine control | B2, FR-13, FR-24 |

The **account switcher** (top bar) is a global control: it sets the "current account" that views 1, 2, and 4 are scoped to. Selecting an archived account re-scopes the Daily/Weekly views to that account's lifetime "last day"/"last week" of activity and clearly marks them as historical (banner: "Viewing archived account #N — closed 2026-05-12").

### 1.3 Sidebar contents

```
TRADING TOM            (logo + "PAPER" pill)
─────────────
◉  Daily
   Weekly
   Accounts
   Backtests
─────────────
   Settings
─────────────
●  Engine: RUNNING     (status dot + label, links to Settings)
   Mkt: OPEN 14:32 ET  (market-hours indicator)
```

The bottom status block (engine + market state) is always visible — it is the operator's at-a-glance "is the bot alive and is the market open?" signal (NFR-12 surfaced in UI).

---

## 2. Visual Design Language

### 2.1 Mood

Dark-mode-first, professional trading desk. References: **Robinhood** (generous whitespace, one accent color, calm), **Binance** (dense data tables, amber accent, dark slate), **eToro** (card-based portfolio summaries), **Exodus** (soft gradients on balance cards, rounded surfaces). We blend Robinhood's calm hierarchy with Binance's data density.

### 2.2 Color palette (dark theme — primary)

Semantic tokens (CSS custom properties). Light theme is a stretch goal; tokens are structured so a light palette can be swapped without touching components.

| Token | Hex | Use |
|-------|-----|-----|
| `--bg-base` | `#0B0E11` | App background (near-black slate, Binance-like) |
| `--bg-surface` | `#151A21` | Cards, sidebar, panels |
| `--bg-surface-2` | `#1C232C` | Nested surfaces, table header, hover rows |
| `--border-subtle` | `#2A323D` | Dividers, card borders, table gridlines |
| `--text-primary` | `#EAECEF` | Headlines, primary numbers |
| `--text-secondary` | `#9AA4B2` | Labels, captions, axis ticks |
| `--text-muted` | `#5C6773` | Disabled, timestamps, footnotes |
| `--accent` | `#4C8DFF` | Primary accent (links, active nav, focus rings, primary buttons) |
| `--profit` | `#16C784` | Positive P&L, buys-in-profit, up sparklines |
| `--loss` | `#EA3943` | Negative P&L, losses, down sparklines |
| `--warning` | `#F0B90B` | Account near floor, market-closed, data-stale |
| `--info` | `#7B8FF7` | Neutral badges (data split, strategy tags) |
| `--paper-pill` | `#F0B90B` on `#2A2410` | "PAPER / SIMULATED" badge — always visible |

**Color rules**

- Green = `--profit`, Red = `--loss`. Never reuse these two for anything non-monetary (no green "save" buttons — use `--accent`). This keeps P&L scanning instant.
- The "PAPER" pill uses warning-amber to constantly remind the operator nothing is real money (trust/safety, NFR-16).
- Accent blue is the single interactive color (Robinhood discipline: one accent).
- Background uses a cool near-black slate (`#0B0E11`), not pure black, to reduce eye strain on an always-on monitor.

### 2.3 Typography

| Role | Family | Size / weight | Notes |
|------|--------|---------------|-------|
| Brand / page title | Inter (or system UI) | 20–24px / 600 | |
| Section headings | Inter | 16px / 600 | |
| Body / labels | Inter | 13–14px / 400–500 | |
| **Numeric data** | **JetBrains Mono** (or `ui-monospace`) | 13–15px / 500 | Tabular figures so columns of money align |
| Hero numbers (balance, net P&L) | JetBrains Mono | 32–40px / 600 | |
| Captions / timestamps | Inter | 11–12px / 400 | `--text-muted` |

**Rule:** all currency, quantity, percentage, and price values render in a **monospaced, tabular-figures** font so decimal points and digit columns line up in tables — essential for scanning a trade ledger. This is a deliberate borrow from Binance/order-book UIs.

### 2.4 Spacing & layout grid

- 8px base spacing scale: `4, 8, 12, 16, 24, 32, 48`.
- Card padding: `16px` (compact tables) to `24px` (hero cards).
- Card radius: `12px` (Exodus-soft); pills/badges `999px`; buttons `8px`.
- Content max-width: `1440px`, centered, with the sidebar fixed at `240px` (collapsed `64px`).
- Table row height: `40px` desktop (dense but tappable), `48px` on touch.
- Elevation: subtle 1px `--border-subtle` borders + a faint shadow (`0 1px 2px rgba(0,0,0,.4)`) rather than heavy material shadows.

### 2.5 Chart style

- **Dark canvas, no chart background fill** beyond a faint baseline grid (`--border-subtle` at ~30% opacity, horizontal lines only).
- Equity/balance line: 2px `--accent` stroke with a soft vertical gradient fill beneath (accent → transparent) — the Robinhood/Exodus signature look.
- Up/down coloring on the equity line is **single-color accent** for the line, but the **week's net result** colors the headline number green/red. (We do not color the line itself green/red to avoid visual noise; the number carries the verdict.)
- Sparklines (per-trade or per-account mini trends): 1.5px stroke, profit/loss-colored, no axes, no grid.
- Tooltips: dark surface card, monospaced values, show `date · balance · Δ from start`.
- Axes: minimal — `--text-muted` ticks, no axis lines, abbreviated currency (`$10.4k`).

### 2.6 Iconography & motion

- Icon set: a single lightweight set (Lucide / Phosphor) for consistency; 16–20px, `--text-secondary` default, `--accent` when active.
- Motion: restrained. 150ms ease for hover/nav; numbers that update on poll do a subtle 200ms color flash (green up / red down, then settle) — the classic ticker "tick" feedback. No bouncing, no confetti.

---

## 3. Key Screen Layouts (wireframes)

ASCII wireframes below are structural, not pixel-accurate. `[ ]` = card/panel, `▸` = interactive, `███` = chart area.

### 3.1 Daily Dashboard (`/`) — D1–D3, FR-25

```
┌─ TOP BAR ──────────────────────────────────────────────────────────────────┐
│ TRADING TOM [PAPER]      Account: ▸ #14 (ACTIVE) ▾    ● Engine RUNNING  ●OPEN │
│                                                              Fri 27 May 14:32 ET│
├─ SIDEBAR ─┬─ MAIN: DAILY ──────────────────────────────────────────────────┤
│ ◉ Daily   │  Today · Fri 27 May 2026                          [ Today ▾ ]    │
│   Weekly  │                                                                  │
│   Accounts│  ┌─ BALANCE ────────┐ ┌─ TODAY NET P&L ──┐ ┌─ FEES TODAY ─────┐ │
│   Backtests│ │ $10,247.18       │ │ ▲ +$247.18       │ │ $1.43            │ │
│   ───────  │ │ equity (cash+pos)│ │  +2.47%   green  │ │ 6 sells          │ │
│   Settings │ │ cash $8,910.02   │ │ ▁▂▄▆█ sparkline  │ │ SEC+TAF est.     │ │
│   ───────  │ └──────────────────┘ └──────────────────┘ └──────────────────┘ │
│ ● RUNNING  │                                                                  │
│   OPEN ET  │  ┌─ OPEN POSITIONS (2) ───────────────────────────────────────┐ │
│           │  │ SYM   QTY   AVG ENTRY   LAST    MKT VALUE   UNREAL P&L  STRAT│ │
│           │  │ AAPL   10    $182.40   $184.10  $1,841.00  ▲+$17.00   swing │ │
│           │  │ MSFT    5    $410.10   $408.90  $2,044.50  ▼−$6.00    day   │ │
│           │  └────────────────────────────────────────────────────────────┘ │
│           │                                                                  │
│           │  ┌─ TODAY'S TRADES (8) ──────────────────  [ all ▾ ][split: ▾ ]┐ │
│           │  │ TIME ET  SYM  SIDE  QTY   PRICE     FEE    REAL P&L  STRAT   │ │
│           │  │ 09:31    AAPL BUY   10   $182.40   $0.00     —       swing   │ │
│           │  │ 10:02    MSFT BUY    5   $410.10   $0.00     —       day     │ │
│           │  │ 11:15    NVDA SELL   3   $920.00   $0.41   ▲+$54.00  day     │ │
│           │  │ 14:20    TSLA SELL   8   $172.30   $0.22   ▼−$12.40  swing   │ │
│           │  │ …                                                            │ │
│           │  │                                       [test] split badge/row │ │
│           │  └────────────────────────────────────────────────────────────┘ │
└───────────┴──────────────────────────────────────────────────────────────────┘
```

Notes:
- Three hero **balance/stat cards** lead (Robinhood/eToro pattern): equity, today net P&L (green/red + %), fees.
- Open positions table shows **unrealized** P&L (D2); trades table shows **realized** P&L on closing (sell) rows, `—` on opens.
- Each trade row carries its `strategy` and a **data-split badge** (transparency, C2). Empty state: "No trades today — market closed / engine idle."

### 3.2 Weekly Dashboard (`/weekly`) — E1–E2, FR-26

```
├─ MAIN: WEEKLY ───────────────────────────────────────────────────────────────┤
│  Week · Mon 23 – Fri 27 May 2026                       [ ◂ prev ][ this wk ▾ ]│
│                                                                               │
│  ┌─ EQUITY THIS WEEK ─────────────────────────────────────────────────────┐ │
│  │  $10,247  ▲ +$247 (+2.47%)            net for week (green)              │ │
│  │  ███████████████████████████████████████████████████████  accent line  │ │
│  │  ██▁▂▃▄▅▆▇█  gradient fill under line                                   │ │
│  │  Mon    Tue    Wed    Thu    Fri                                        │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ SUMMARY ────────────────────────────────────────────────────────────┐   │
│  │  TRADES   WIN RATE   GROSS P&L   FEES      NET P&L     AVG WIN / LOSS  │   │
│  │   42       57.1%      +$261.40   $14.22    +$247.18    +$31 / −$18     │   │
│  │            ▓▓▓▓▓░░░    green                green       (small bars)    │   │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ DAILY BREAKDOWN ──────────────────────────────────────────────────────┐ │
│  │ DAY   TRADES   WIN%   NET P&L   FEES    bar                             │ │
│  │ Mon     9      55%    +$80.10   $2.10   ▇▇▇▇                            │ │
│  │ Tue     7      71%    +$112.00  $3.00   ▇▇▇▇▇▇                          │ │
│  │ Wed     8      50%    −$34.50   $4.10   ▂▂ (red)                        │ │
│  │ Thu    11      54%    +$61.30   $2.90   ▇▇▇                             │ │
│  │ Fri     7      57%    +$28.28   $2.12   ▇▇                              │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

Notes:
- Equity chart spans the trading week (Mon–Fri ET per Q-6 default); headline = net for week colored by sign.
- Summary row delivers E1's required metrics (trades, win rate, gross, fees, net). Win rate gets a small progress bar.
- Daily breakdown table doubles as a mini bar chart per day for quick scanning.

### 3.3 Accounts — switcher & history (`/accounts`) — F1, F3, FR-27

```
├─ MAIN: ACCOUNTS ─────────────────────────────────────────────────────────────┤
│  Accounts (14)                                            [ search ▾ sort ▾ ] │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │ #   STATUS     OPENED       CLOSED       START     FINAL     RETURN  ▸   │ │
│  │ 14  ● ACTIVE   12 May 26    —            $10,000   $10,247   ▲+2.47% ▸   │ │
│  │ 13  ARCHIVED   28 Apr 26    12 May 26    $10,000   $0.00     ▼−100%  ▸   │ │
│  │ 12  ARCHIVED   10 Apr 26    28 Apr 26    $10,000   $14,310   ▲+43.1% ▸   │ │
│  │ 11  ARCHIVED   …            …            $10,000   $0.00     ▼−100%  ▸   │ │
│  │ …                                                                       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│   ● ACTIVE badge = accent/green dot; busted accounts show −100% in red.        │
│   Row ▸ → /accounts/:id . "Set as dashboard scope" action on hover.            │
```

Notes:
- Active account is badged (F3) with a glowing dot and pinned to the top.
- A busted (`$0`, auto-archived per A2/FR-3) account is visually distinct: `−100% RETURN` in `--loss`, plus a small "BUST" tag.
- Clicking a row sets the global account scope (affects Daily/Weekly) AND/OR opens detail; the row offers both: click name = scope, click `▸` = detail.

### 3.4 Account Detail (`/accounts/:id`) — F2, FR-28

```
├─ MAIN: ACCOUNT #12 (ARCHIVED) ───────────────────────────────────────────────┤
│  ◂ Accounts / Account #12        [ARCHIVED]  opened 10 Apr · closed 28 Apr 26 │
│                                                                               │
│  ┌─ LIFETIME SUMMARY ─────────────────────────────────────────────────────┐ │
│  │ START    PEAK      FINAL    RETURN    TRADES  WIN%   MAX DD   SHARPE     │ │
│  │ $10,000  $15,002   $14,310  ▲+43.1%   318     55%    −12.4%   1.41       │ │
│  │  ████ lifetime equity curve (accent line + gradient) ███████            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ TRADE HISTORY (318) ─────────────────  [date ▾][sym ▾][side ▾][split ▾]┐ │
│  │ DATE/TIME ET    SYM  SIDE  QTY  PRICE    FEE    REAL P&L  STRAT  SPLIT   │ │
│  │ 10 Apr 09:31    AAPL BUY   10  $170.10  $0.00     —       swing  [test]  │ │
│  │ 11 Apr 15:55    AAPL SELL  10  $176.40  $0.34  ▲+$62.66  swing  [test]  │ │
│  │ …  (paginated / virtualized; 50/page)                                   │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
```

Notes:
- Lifetime summary mirrors backtest metrics (return, win rate, max drawdown, Sharpe — FR-20 set) so live accounts and backtests read consistently.
- Full trade table is filterable by date/symbol/side/**split** (C2 audit). Virtualized for the NFR-1 "10k trades < 500ms" expectation (server paginates; FE virtualizes).
- Every row shows the **data split** it ran against — the core anti-overfitting trust signal.

### 3.5 Settings / Strategy Config (`/settings`) — B2, FR-13, FR-24

Kept intentionally simple for MVP. Two zones: **Engine control** (operator-token-gated mutations) and **Read/edit config**.

```
├─ MAIN: SETTINGS ─────────────────────────────────────────────────────────────┤
│  Settings                                                                     │
│                                                                               │
│  ┌─ ENGINE CONTROL ───────────────────────────────────────────────────────┐ │
│  │  Status: ● RUNNING (since 12 May 09:30 ET)                              │ │
│  │  [ Stop Engine ]  [ Restart ]    Operator token: [••••••••] (required)   │ │
│  │  [ Run Backtest ▾ ]  strategy: [Swing ▾]  split: [validation ▾]         │ │
│  │     ⚠ "test" split requires Final-Evaluation mode (confirm dialog)       │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ STRATEGY PARAMETERS ──────────────────────────────────────────────────┐ │
│  │  Strategy ▾ [ Day | Swing | Position ]                                  │ │
│  │   ┌ Day ────────────────────────────────┐                              │ │
│  │   │ enabled            [✓]               │                              │ │
│  │   │ fast/slow MA       [ 9 ] / [ 21 ]    │                              │ │
│  │   │ position size %    [ 5 % of equity ] │                              │ │
│  │   │ max positions      [ 3 ]             │                              │ │
│  │   └──────────────────────────────────────┘   [ Save ] (token-gated)     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                                                               │
│  ┌─ FEE MODEL ──────────┐  ┌─ WATCHLIST ─────────────────────────────────┐  │
│  │ commission  [$0.00]  │  │ AAPL  MSFT  NVDA  TSLA  AMZN  +add  ×remove │  │
│  │ SEC fee     [editable]│  │                                            │  │
│  │ FINRA TAF   [editable]│  └─────────────────────────────────────────────┘  │
│  └──────────────────────┘                                                     │
```

Notes:
- All **mutations** (save config, start/stop engine, run backtest) require the operator token (NFR-15, FR-24); read views never expose it.
- Selecting `test` split for a backtest triggers an explicit **Final-Evaluation confirm dialog** that surfaces the anti-overfitting contract (FR-18, C3) — the UI enforces the discipline at the human layer to complement backend enforcement.
- Parameters are simple typed inputs sourced from config (FR-13); no code editing in UI.

### 3.6 Global states

- **Empty:** friendly centered message + icon ("No accounts yet — start the engine in Settings").
- **Loading:** skeleton rows/cards (shimmer on `--bg-surface-2`), never a blocking spinner over content.
- **Error / stale data:** amber banner ("Market data is stale — last bar 13:58 ET" or "API unreachable — retrying") aligned to NFR-13. Last-good data stays visible behind the banner.
- **Market closed:** the OPEN indicator flips to `● CLOSED` (muted) and Daily view shows "Market closed — engine idle."

---

## 4. Component Library Sketch

Reusable React components (presentational unless noted). Grouped by tier.

**Primitives**
- `Money` — formats integer cents → `$X,XXX.XX`, tabular-figures, optional sign coloring.
- `PnLValue` — `Money`/percent with `▲/▼` glyph and `--profit`/`--loss`/neutral color; central P&L renderer reused everywhere.
- `Badge` / `Pill` — status (ACTIVE/ARCHIVED/BUST), data-split (train/validation/test), strategy tag, PAPER pill.
- `StatusDot` — colored dot for engine/market/account status.
- `Button` — primary (accent) / secondary (surface) / danger (loss); `TokenButton` variant requires operator token.

**Data display**
- `StatCard` / `BalanceCard` — hero number + label + optional sparkline + delta (the three top cards).
- `Sparkline` — tiny SVG line, profit/loss colored, no axes (per-trade/per-account trends).
- `EquityChart` — the main accent line + gradient-fill area chart (week / lifetime). Wraps the chart lib (§6).
- `DataTable` — generic sortable/filterable table with sticky header, zebra hover, **virtualized rows** for large histories; column renderers plug in `Money`/`PnLValue`/`Badge`.
  - `TradeRow` — specialized row: time, symbol, side pill, qty, price, fee, realized P&L, strategy, split badge.
  - `PositionRow` — open position: symbol, qty, avg entry, last, market value, unrealized P&L, strategy.
  - `AccountRow` — account list row: id, status badge, dates, start/final, return, actions.
- `SummaryStrip` — horizontal metric row (trades / win rate / gross / fees / net) used on Weekly & Account Detail.
- `MetricTile` — single labeled metric (return, Sharpe, max DD).
- `WinRateBar` — small progress bar for win %.

**Navigation & layout**
- `Sidebar` (collapsible) + `NavItem`.
- `TopBar` — wraps `AccountSwitcher` + `EngineStatus` + `MarketClock`.
- `AccountSwitcher` — dropdown/searchable list, active badged; sets global scope (context provider).
- `EngineStatus` / `MarketClock` — live-ish status from polling.
- `PageHeader` — title + date-range selector + filters.

**Controls / feedback**
- `DateRangePicker` — Today / This Week / prev-next stepper.
- `FilterBar` — symbol/side/split/strategy filters for tables.
- `ConfirmDialog` — generic; specialized `FinalEvaluationDialog` for test-split runs.
- `Banner` — info/warning/error (stale data, market closed, errors).
- `SkeletonRow` / `SkeletonCard` — loading states.
- `Toast` — success/failure for token-gated actions.

**State / data (non-visual)**
- `AccountScopeProvider` — React context holding the currently-scoped account id.
- `usePolling(fetcher, interval)` — hook driving the 30s refresh (DA-5).
- `api` client — typed wrappers over the FR-23 endpoints.

---

## 5. Responsive Strategy

**Desktop-first** (operator's primary device). Defined breakpoints (mobile-friendly, not mobile-optimized):

| Breakpoint | Width | Behavior |
|------------|-------|----------|
| `xl` desktop | ≥ 1280px | Full layout: 240px sidebar, 3-up stat cards, wide tables with all columns. |
| `lg` laptop | 1024–1279px | Sidebar 240px; tables may horizontally scroll low-priority columns; charts full width. |
| `md` tablet | 768–1023px | Sidebar collapses to 64px icon rail; stat cards 2-up then wrap; tables drop secondary columns (e.g., strategy/split move into an expandable row). |
| `sm` mobile | < 768px | Sidebar becomes a bottom tab bar or hamburger drawer; stat cards stack 1-up; tables render as **stacked cards** (label: value pairs) instead of horizontal rows; charts shrink, tooltips on tap. |

**Rules**
- Money/numeric columns never wrap mid-value; on small screens, tables degrade to card lists rather than squeezing columns.
- The account switcher and PAPER pill remain visible at all breakpoints (always-on trust/context).
- Charts use a responsive container (width 100%, fixed aspect ratio) so they reflow without JS resize handling.
- Touch targets ≥ 44px on `sm`/`md`.

---

## 6. Chart Library Recommendation

**Recommendation: Recharts** for the MVP.

| Library | Pros | Cons | Fit |
|---------|------|------|-----|
| **Recharts** ✅ | React-native (declarative SVG components), trivial to theme with our tokens, gradient-fill area charts (the Robinhood look) out of the box, responsive container, small learning curve, MIT. | Not ideal for tick-level/candlestick high-frequency rendering at scale. | **Best fit.** Our charts are equity/balance line + area and simple bar breakdowns over daily/weekly granularity — exactly Recharts' sweet spot. SVG keeps it crisp and easy to style in dark mode. |
| TradingView Lightweight Charts | Purpose-built for financial time series, candlesticks, very performant on large series, canvas-rendered. | Imperative API (not React-idiomatic), heavier mental model, candlestick focus is overkill — we show **equity curves**, not OHLC price charts; theming is more manual. | Over-engineered for MVP. Revisit only if we later add per-symbol candlestick price views. |
| Chart.js (react-chartjs-2) | Popular, canvas, decent perf. | Canvas (harder pixel-perfect dark theming than SVG), more config boilerplate for the gradient-area aesthetic, less React-idiomatic than Recharts. | Acceptable alternative; no advantage over Recharts for our needs. |

**Rationale:** Trading Tom's charts are **performance/equity curves and simple per-day bars at daily/weekly granularity**, not live candlestick price charts. Recharts gives us the exact Robinhood/Exodus gradient-area line look with declarative, themeable React components and a responsive container — fastest path to a polished result with the least code. We wrap it in a single `EquityChart` component so the library can be swapped later (e.g., to TradingView Lightweight Charts) if we ever add candlestick price views, without touching call sites.

**Sparklines:** render with a minimal Recharts `<LineChart>` (no axes/grid) or a hand-rolled inline SVG `<polyline>` for the tiny per-row sparks — the latter avoids chart-instance overhead in long virtualized tables. Decision deferred to implementation; the `Sparkline` component hides the choice.

---

## 7. Accessibility & Quality Notes

- Color is never the *only* signal: P&L pairs color with `▲/▼` glyphs and a sign; status uses dot + text label.
- Contrast: body text on surfaces meets WCAG AA (4.5:1); the chosen `--text-primary`/`--bg-surface` pair clears it.
- All interactive elements have visible `--accent` focus rings; tables are keyboard-navigable; the account switcher is an accessible listbox.
- Respect `prefers-reduced-motion`: disable the tick color-flash and chart animations.
- Time always shown in ET with explicit suffix to avoid ambiguity (DA-2).

---

## 8. Auth / Access Surface (MVP)

Per PRD §A-1 and NFR-15, there is **no login UI** in MVP. The only auth surface is the **operator token field** on Settings, used to authorize mutating control actions (start/stop engine, run backtest, save config). Read views are open on the trusted VPS network. If the dashboard is later internet-exposed, a single minimal token gate (one password screen) is the smallest addition — designed for but not built in MVP.

---

## 9. Traceability (PRD → design)

| PRD requirement | Addressed by |
|-----------------|--------------|
| D1–D3 (daily) | §3.1 Daily Dashboard (trades, per-trade P&L, balance, fees, positions) |
| E1–E2 (weekly) | §3.2 Weekly (summary strip + equity chart) |
| F1, F3 (switcher) | §1.2 global account switcher, §3.3 Accounts (active badged) |
| F2 (history) | §3.4 Account Detail (lifetime summary + full trade table) |
| G1 (look & feel) | §2 dark trading-platform language; Robinhood/eToro/Binance/Exodus refs |
| B2/FR-13 (config) | §3.5 Settings strategy params |
| FR-24 (control auth) | §3.5 + §8 operator token on mutations |
| C2 (audit split) | data-split badge on every trade row (§3.1, §3.4); Final-Evaluation dialog (§3.5) |
| NFR-1 (10k trades) | virtualized `DataTable` + server pagination (§4) |
| NFR-13 (data failures) | stale/error banners (§3.6) |
| NFR-16 (paper only) | always-visible PAPER pill (§2.2) |

---

## 10. Open Design Questions (with defaults)

- **DQ-1.** Light theme in MVP? **Default:** dark-only; tokens structured to add light later. (G1 says "dark-mode capable" — dark is primary, light deferred.)
- **DQ-2.** Real-time updates via websocket vs. polling? **Default:** 30s polling (DA-5); revisit if engine tick frequency demands it.
- **DQ-3.** Sparkline rendering (Recharts vs. inline SVG)? **Default:** inline SVG for table rows, Recharts for hero cards; hidden behind `Sparkline`. (§6)
- **DQ-4.** Account switcher click semantics (scope vs. navigate)? **Default:** name = set scope, `▸` = open detail (§3.3); confirm in implementation if it confuses.
- **DQ-5.** Show unrealized P&L on archived accounts? **Default:** no — archived accounts have no open positions; show realized lifetime only.
```
