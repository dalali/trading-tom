"""add backtest account status

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-30
"""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_accounts_status", "accounts")
    op.create_check_constraint(
        "ck_accounts_status",
        "accounts",
        "status IN ('active','archived','backtest')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_accounts_status", "accounts")
    op.create_check_constraint(
        "ck_accounts_status",
        "accounts",
        "status IN ('active','archived')",
    )
