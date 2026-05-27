"""
Fee model — pure functions, all values in integer cents.

Fee schedule (configurable via env):
  - Commission: $0 default
  - SEC fee (sell only): ceil(SEC_FEE_RATE * notional_cents / 100) cents
    (SEC_FEE_RATE is the fraction of notional, e.g. 0.0000229)
  - FINRA TAF (sell only): min(round(FINRA_TAF_PER_SHARE * shares), cap)
    cap = FINRA_TAF_CAP_CENTS (default 727 = $7.27)

All arithmetic via Decimal; regulatory fees rounded UP (conservative).
"""
import math
from decimal import Decimal

from trading_tom.config import settings


def _sec_fee_cents(notional_cents: int) -> int:
    """SEC fee on sell notional. Rounds UP per regulations."""
    notional_dollars = Decimal(notional_cents) / Decimal("100")
    fee_dollars = Decimal(str(settings.sec_fee_rate)) * notional_dollars
    fee_cents = fee_dollars * Decimal("100")
    return math.ceil(float(fee_cents))


def _finra_taf_cents(shares: int) -> int:
    """FINRA TAF on sell. Rounds to nearest cent, capped at FINRA_TAF_CAP_CENTS."""
    fee_dollars = Decimal(str(settings.finra_taf_per_share)) * Decimal(shares)
    fee_cents = fee_dollars * Decimal("100")
    rounded = int(fee_cents.to_integral_value())
    return min(rounded, settings.finra_taf_cap_cents)


def compute_fee(
    side: str,
    shares: int,
    price_cents: int,
    commission_cents: int | None = None,
) -> int:
    """
    Compute total fee in cents for a trade.

    Args:
        side: 'buy' or 'sell'
        shares: number of shares (positive integer)
        price_cents: fill price per share in cents
        commission_cents: override from settings if None

    Returns:
        Total fee in integer cents.
    """
    if commission_cents is None:
        commission_cents = settings.commission_cents

    if side == "buy":
        return commission_cents

    # Sell: commission + SEC fee + FINRA TAF
    notional_cents = shares * price_cents
    sec = _sec_fee_cents(notional_cents)
    finra = _finra_taf_cents(shares)
    return commission_cents + sec + finra
