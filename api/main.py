"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from trading_tom.api.routers import accounts, trades, aggregates, engine, config, backtests

app = FastAPI(
    title="Trading Tom API",
    description="Paper trading simulation bot — REST API",
    version="1.0.0",
)

# CORS: allow Vite dev server; in prod SPA is same-origin via nginx
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health", tags=["health"])
def health():
    return {"status": "ok"}


# Mount routers under /api
app.include_router(accounts.router, prefix="/api")
app.include_router(trades.router, prefix="/api")
app.include_router(aggregates.router, prefix="/api")
app.include_router(engine.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(backtests.router, prefix="/api")
