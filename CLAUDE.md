# CLAUDE.md

## Project
trading-tom — A paper-trading simulation bot for US stocks with autonomous strategies and a trading-platform dashboard.

## Tech Stack
Python BE (trading engine + API) + React FE (dashboard) + Docker Compose

## Local Setup
```bash
cp .env.example .env   # edit as needed
./run.sh start
```

## Key Commands
- `./run.sh start` — start the app
- `./run.sh test`  — run tests
- `./run.sh logs`  — tail logs
- `./run.sh shell` — container shell

## Rules
- Keep changes minimal and focused
- Run tests before committing
- Trades are simulated only — no real money, no broker execution
- Anti-overfitting: keep strict train/validation/test data splits
