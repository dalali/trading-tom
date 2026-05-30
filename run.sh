#!/usr/bin/env bash
set -euo pipefail

CMD=${1:-help}
API="http://localhost:8000/api"

# Load OPERATOR_TOKEN from .env if present
if [[ -f .env ]]; then
  export $(grep -E '^OPERATOR_TOKEN=' .env | xargs) 2>/dev/null || true
fi
OPERATOR_TOKEN=${OPERATOR_TOKEN:-}

_require_token() {
  if [[ -z "$OPERATOR_TOKEN" ]]; then
    echo "Error: OPERATOR_TOKEN not set. Add it to .env or export it."
    exit 1
  fi
}

_api_get() {
  local resp http_code
  resp=$(curl -s -w "\n%{http_code}" "$API$1")
  http_code=$(tail -1 <<< "$resp")
  body=$(sed '$d' <<< "$resp")
  if [[ "$http_code" -ge 400 ]]; then
    echo "Error $http_code: $body" >&2; return 1
  fi
  echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
}

_api_post() {
  local path=$1; shift
  _require_token
  local resp http_code body
  resp=$(curl -s -w "\n%{http_code}" -X POST "$API$path" \
    -H "Content-Type: application/json" \
    -H "X-Operator-Token: $OPERATOR_TOKEN" \
    -d "${1:-{\}}")
  http_code=$(tail -1 <<< "$resp")
  body=$(sed '$d' <<< "$resp")
  if [[ "$http_code" -ge 400 ]]; then
    echo "Error $http_code: $body" >&2; return 1
  fi
  echo "$body" | python3 -m json.tool 2>/dev/null || echo "$body"
}

case "$CMD" in

  # ── Infrastructure ─────────────────────────────────────────────────────────

  start|up)
    if [[ ! -f .env ]]; then
      echo "Error: .env not found. Run:  cp .env.example .env  and fill in OPERATOR_TOKEN."
      exit 1
    fi
    echo "Starting trading-tom..."
    docker compose up -d --build
    echo ""
    echo "Services:  http://localhost:3000  (dashboard)"
    echo "           http://localhost:8000  (API — internal only)"
    echo "Logs:      ./run.sh logs"
    ;;

  stop|down)
    docker compose down
    ;;

  restart)
    docker compose down && docker compose up -d --build
    ;;

  logs)
    docker compose logs -f "${2:-}"
    ;;

  build)
    docker compose build
    ;;

  status)
    echo "=== Containers ==="
    docker compose ps
    echo ""
    echo "=== Engine status ==="
    _api_get /engine/status 2>/dev/null || echo "(API not reachable — is the stack running?)"
    ;;

  test)
    docker compose run --rm api pytest "${@:2}"
    ;;

  shell)
    docker compose exec "${2:-api}" bash
    ;;

  psql)
    docker compose exec db psql -U "${POSTGRES_USER:-dev}" -d "${POSTGRES_DB:-trading_tom}" -p 5432
    ;;

  migrate)
    echo "Running migrations..."
    docker compose run --rm api alembic upgrade head
    ;;

  clean)
    echo "This will delete all containers AND the database volume (all trade history)."
    read -r -p "Are you sure? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 0
    docker compose down -v --remove-orphans
    ;;

  # ── Setup ──────────────────────────────────────────────────────────────────

  setup)
    if [[ -f .env ]]; then
      echo ".env already exists — skipping."
    else
      cp .env.example .env
      TOKEN=$(openssl rand -hex 32)
      if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/^OPERATOR_TOKEN=.*/OPERATOR_TOKEN=$TOKEN/" .env
      else
        sed -i "s/^OPERATOR_TOKEN=.*/OPERATOR_TOKEN=$TOKEN/" .env
      fi
      echo ".env created with a fresh OPERATOR_TOKEN."
    fi
    echo ""
    echo "Next: review .env, then run  ./run.sh start"
    ;;

  # ── Engine control ─────────────────────────────────────────────────────────

  engine-start)
    echo "Starting trading engine..."
    _api_post /engine/start
    ;;

  engine-stop)
    echo "Stopping trading engine..."
    _api_post /engine/stop
    ;;

  engine-status)
    _api_get /engine/status
    ;;

  # ── Data ───────────────────────────────────────────────────────────────────

  backfill)
    # Trigger a historical data backfill by restarting the engine
    # (the engine runs backfill on startup via APScheduler)
    echo "Triggering data backfill (runs inside engine container)..."
    docker compose exec engine python3 -c "
from trading_tom.db import SessionLocal
from trading_tom.data.ingest import backfill
session = SessionLocal()
try:
    backfill(session)
    print('Backfill complete.')
finally:
    session.close()
"
    ;;

  # ── Backtesting ────────────────────────────────────────────────────────────

  backtest)
    # Usage: ./run.sh backtest <strategy> [symbol1 symbol2 ...]
    STRATEGY=${2:-day_ma_cross}
    shift 2 || shift $#
    SYMBOLS=("$@")
    if [[ ${#SYMBOLS[@]} -eq 0 ]]; then
      SYMBOLS=("SPY" "AAPL" "MSFT")
    fi

    # Build JSON array of symbols
    SYMBOLS_JSON=$(printf '%s\n' "${SYMBOLS[@]}" | python3 -c "
import sys, json
print(json.dumps([l.strip() for l in sys.stdin]))
")

    echo "Running backtest: strategy=$STRATEGY symbols=${SYMBOLS[*]}"
    _api_post /backtests "{\"strategy\": \"$STRATEGY\", \"symbols\": $SYMBOLS_JSON}"
    ;;

  optimize)
    # Usage: ./run.sh optimize <strategy> [symbol1 symbol2 ...]
    STRATEGY=${2:-day_ma_cross}
    shift 2 || shift $#
    SYMBOLS=("$@")
    if [[ ${#SYMBOLS[@]} -eq 0 ]]; then
      SYMBOLS=("SPY" "AAPL" "MSFT")
    fi
    SYMBOLS_JSON=$(printf '%s\n' "${SYMBOLS[@]}" | python3 -c "
import sys, json
print(json.dumps([l.strip() for l in sys.stdin]))
")

    echo "Running optimizer: strategy=$STRATEGY  (train + validation splits only)"
    _api_post /backtests "{\"strategy\": \"$STRATEGY\", \"symbols\": $SYMBOLS_JSON, \"optimize\": true}"
    ;;

  final-eval)
    # Usage: ./run.sh final-eval <strategy> [symbol1 symbol2 ...]
    STRATEGY=${2:-day_ma_cross}
    shift 2 || shift $#
    SYMBOLS=("$@")
    if [[ ${#SYMBOLS[@]} -eq 0 ]]; then
      SYMBOLS=("SPY" "AAPL" "MSFT")
    fi
    SYMBOLS_JSON=$(printf '%s\n' "${SYMBOLS[@]}" | python3 -c "
import sys, json
print(json.dumps([l.strip() for l in sys.stdin]))
")

    echo "WARNING: This runs the honest out-of-sample evaluation on the TEST split."
    echo "Only do this once per strategy version — peeking burns the test set."
    read -r -p "Confirm? [y/N] " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 0

    _api_post /backtests/final-evaluation \
      "{\"strategy\": \"$STRATEGY\", \"symbols\": $SYMBOLS_JSON, \"confirm\": true}"
    ;;

  backtests)
    echo "=== Backtest runs ==="
    _api_get /backtests
    ;;

  # ── Accounts ───────────────────────────────────────────────────────────────

  accounts)
    echo "=== All accounts ==="
    _api_get /accounts
    ;;

  account)
    ID=${2:?"Usage: ./run.sh account <id>"}
    echo "=== Account $ID ==="
    _api_get "/accounts/$ID"
    echo ""
    echo "=== Recent trades ==="
    _api_get "/accounts/$ID/trades?page_size=20"
    ;;

  daily)
    DATE=${2:-$(date +%Y-%m-%d)}
    ACCOUNT_ID=${3:-}
    QUERY="date=$DATE"
    [[ -n "$ACCOUNT_ID" ]] && QUERY="$QUERY&account_id=$ACCOUNT_ID"
    echo "=== Daily summary: $DATE ==="
    _api_get "/dashboard/daily?$QUERY"
    ;;

  weekly)
    # Monday of current week
    WEEK_START=${2:-$(date -d 'last monday' +%Y-%m-%d 2>/dev/null || date -v-Mon +%Y-%m-%d)}
    ACCOUNT_ID=${3:-}
    QUERY="week_start=$WEEK_START"
    [[ -n "$ACCOUNT_ID" ]] && QUERY="$QUERY&account_id=$ACCOUNT_ID"
    echo "=== Weekly summary: week of $WEEK_START ==="
    _api_get "/dashboard/weekly?$QUERY"
    ;;

  # ── Help ───────────────────────────────────────────────────────────────────

  help|*)
    cat <<'EOF'
Usage: ./run.sh <command> [args]

Infrastructure:
  setup               Create .env with a fresh OPERATOR_TOKEN
  start | up          Build and start all services
  stop | down         Stop all services
  restart             Stop and start
  build               Build Docker images without starting
  status              Container status + engine state
  logs [service]      Tail logs (all services or one: api / engine / db / frontend)
  test [pytest-args]  Run the test suite
  shell [service]     Open a bash shell (default: api)
  psql                Open a psql shell in the db container
  migrate             Run Alembic migrations manually
  clean               Remove containers + database volume (destructive)

Engine:
  engine-start        Start the paper-trading engine
  engine-stop         Pause the paper-trading engine
  engine-status       Show engine state (running/stopped, last tick, last error)

Data:
  backfill            Fetch historical OHLCV data for the watchlist

Backtesting:
  backtest <strategy> [symbols...]     Run backtest on train+validation data
  optimize <strategy> [symbols...]     Grid-search strategy params (train+val only)
  final-eval <strategy> [symbols...]   Honest out-of-sample eval on test split (once only!)
  backtests                            List all past backtest runs

Strategies: day_ma_cross | swing_rsi | position_golden_cross

Accounts & Dashboard:
  accounts                     List all accounts (active + archived)
  account <id>                 Account detail + recent trades
  daily [date] [account_id]    Daily P&L summary (default: today)
  weekly [week_start] [id]     Weekly summary (default: current week)

Examples:
  ./run.sh setup
  ./run.sh start
  ./run.sh backfill
  ./run.sh backtest day_ma_cross SPY AAPL MSFT
  ./run.sh optimize swing_rsi SPY
  ./run.sh final-eval position_golden_cross SPY AAPL
  ./run.sh daily 2025-05-27
  ./run.sh weekly 2025-05-26
  ./run.sh logs engine
EOF
    ;;

esac
