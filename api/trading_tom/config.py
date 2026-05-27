"""Application settings loaded from environment variables."""
from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql://dev:dev@db:5432/trading_tom"

    # App
    app_env: str = "development"
    debug: bool = False

    # Operator auth
    operator_token: str = "changeme"

    # Trading simulation
    starting_capital_cents: int = 1_000_000  # $10,000 in cents
    account_floor_cents: int = 0

    # Data mode for the engine (development | final_eval | live)
    data_mode: str = "live"

    # Market data provider
    data_provider: str = "yfinance"
    alpaca_api_key: Optional[str] = None
    alpaca_api_secret: Optional[str] = None

    # Fee model (all in cents or rate)
    commission_cents: int = 0
    sec_fee_rate: float = 0.0000229    # $22.90 per $1M notional
    finra_taf_per_share: float = 0.000145
    finra_taf_cap_cents: int = 727     # $7.27

    # Split ratios (must sum to 1.0)
    split_train_ratio: float = 0.60
    split_validation_ratio: float = 0.20
    # test ratio is the remainder

    # Default watchlist (comma-separated)
    watchlist: str = "AAPL,MSFT,NVDA,TSLA,AMZN,GOOGL,META,SPY"

    # Claude integration (optional)
    enable_claude_summary: bool = False
    anthropic_api_key: Optional[str] = None

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def watchlist_tickers(self) -> list[str]:
        return [t.strip() for t in self.watchlist.split(",") if t.strip()]


settings = Settings()
