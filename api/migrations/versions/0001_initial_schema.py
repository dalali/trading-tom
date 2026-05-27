"""initial schema + seed

Revision ID: 0001
Revises:
Create Date: 2026-05-27

"""
from typing import Sequence, Union
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- accounts ---
    op.create_table(
        "accounts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("close_reason", sa.String(), nullable=True),
        sa.Column("starting_capital_cents", sa.BigInteger(), nullable=False, server_default="1000000"),
        sa.Column("cash_cents", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_accounts_status"),
        sa.CheckConstraint(
            "close_reason IN ('bust','manual') OR close_reason IS NULL",
            name="ck_accounts_close_reason",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_accounts_status", "accounts", ["status"])
    # Partial unique index: at most one active account
    op.execute(
        "CREATE UNIQUE INDEX uq_one_active_account ON accounts (status) WHERE status = 'active'"
    )

    # --- positions ---
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("avg_entry_price_cents", sa.BigInteger(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("quantity >= 0", name="ck_positions_quantity"),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        "CREATE INDEX ix_positions_account_open ON positions (account_id, symbol) WHERE closed_at IS NULL"
    )

    # --- trades ---
    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("side", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("price_cents", sa.BigInteger(), nullable=False),
        sa.Column("fee_cents", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("realized_pnl_cents", sa.BigInteger(), nullable=True),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("data_split", sa.String(), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("backtest_run_id", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("side IN ('buy','sell')", name="ck_trades_side"),
        sa.CheckConstraint("quantity > 0", name="ck_trades_quantity"),
        sa.CheckConstraint(
            "data_split IN ('train','validation','test','live')",
            name="ck_trades_data_split",
        ),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trades_account_time", "trades", ["account_id", "executed_at"])
    op.create_index("ix_trades_split", "trades", ["data_split"])

    # --- price_bars ---
    op.create_table(
        "price_bars",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("symbol", sa.String(), nullable=False),
        sa.Column("interval", sa.String(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open_cents", sa.BigInteger(), nullable=False),
        sa.Column("high_cents", sa.BigInteger(), nullable=False),
        sa.Column("low_cents", sa.BigInteger(), nullable=False),
        sa.Column("close_cents", sa.BigInteger(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("split_label", sa.String(), nullable=False),
        sa.CheckConstraint("interval IN ('1d','1m')", name="ck_bars_interval"),
        sa.CheckConstraint(
            "split_label IN ('train','validation','test')",
            name="ck_bars_split_label",
        ),
        sa.UniqueConstraint("symbol", "interval", "ts", name="uq_bars_symbol_interval_ts"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_bars_lookup", "price_bars", ["symbol", "interval", "ts"])

    # --- backtest_runs ---
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("params", postgresql.JSONB(), nullable=False),
        sa.Column("data_split", sa.String(), nullable=False),
        sa.Column("symbols", postgresql.JSONB(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False, server_default="42"),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("final_evaluation", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "data_split IN ('train','validation','test')",
            name="ck_backtest_data_split",
        ),
        sa.CheckConstraint(
            "data_split <> 'test' OR final_evaluation = true",
            name="ck_backtest_test_requires_final_eval",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_backtests_created", "backtest_runs", ["created_at"])

    # --- equity_snapshots ---
    op.create_table(
        "equity_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.BigInteger(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("equity_cents", sa.BigInteger(), nullable=False),
        sa.Column("cash_cents", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"]),
        sa.UniqueConstraint("account_id", "ts", name="uq_equity_account_ts"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_equity_account_time", "equity_snapshots", ["account_id", "ts"])

    # --- engine_state ---
    op.create_table(
        "engine_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("desired_state", sa.String(), nullable=False, server_default="running"),
        sa.Column("actual_state", sa.String(), nullable=False, server_default="stopped"),
        sa.Column("last_tick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("id = 1", name="ck_engine_state_singleton"),
        sa.CheckConstraint("desired_state IN ('running','stopped')", name="ck_engine_state_desired"),
        sa.CheckConstraint(
            "actual_state IN ('running','stopped','starting')",
            name="ck_engine_state_actual",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # --- strategy_configs ---
    op.create_table(
        "strategy_configs",
        sa.Column("strategy_name", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("params", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("strategy_name"),
    )

    # --- Seed data ---
    # Engine state singleton
    op.execute(
        "INSERT INTO engine_state (id, desired_state, actual_state, updated_at) "
        "VALUES (1, 'running', 'stopped', now())"
    )

    # Default strategy configs
    op.execute(
        """
        INSERT INTO strategy_configs (strategy_name, enabled, params, updated_at) VALUES
        ('day', true,
         '{"fast_ma": 9, "slow_ma": 21, "position_size_pct": 0.05, "max_positions": 3}'::jsonb,
         now()),
        ('swing', true,
         '{"rsi_period": 14, "rsi_buy": 30, "rsi_sell": 60, "sma_trend": 50, "max_hold_days": 10,
           "position_size_pct": 0.10, "max_positions": 5}'::jsonb,
         now()),
        ('position', true,
         '{"sma_fast": 50, "sma_slow": 200, "position_size_pct": 0.20, "max_positions": 5}'::jsonb,
         now())
        """
    )

    # Seed the first account (id=1, balance=$10,000)
    op.execute(
        "INSERT INTO accounts (id, status, created_at, starting_capital_cents, cash_cents) "
        "VALUES (1, 'active', now(), 1000000, 1000000)"
    )
    # Reset the sequence so next auto-generated id picks up from 2
    op.execute("SELECT setval('accounts_id_seq', 1, true)")


def downgrade() -> None:
    op.drop_table("strategy_configs")
    op.drop_table("engine_state")
    op.drop_table("equity_snapshots")
    op.drop_table("backtest_runs")
    op.drop_table("price_bars")
    op.drop_table("trades")
    op.drop_table("positions")
    op.drop_table("accounts")
