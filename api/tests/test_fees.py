"""
Unit tests for the fee calculator.

Success Criteria #5 (PRD §7): fee math is correct and ledger-consistent.
"""
import pytest
from unittest.mock import patch

from trading_tom.engine.fees import compute_fee, _sec_fee_cents, _finra_taf_cents


class TestSecFee:
    def test_zero_notional(self):
        assert _sec_fee_cents(0) == 0

    def test_rounds_up(self):
        # SEC_FEE_RATE = 0.0000229; notional = $1 = 100 cents
        # fee = 0.0000229 * 1.00 * 100 = 0.00229 cents → ceil = 1 cent
        result = _sec_fee_cents(100)
        assert result == 1

    def test_million_dollar_sell(self):
        # $1,000,000 notional → 0.0000229 * 1000000 = $22.90 → 2290 cents
        notional_cents = 100_000_000  # $1,000,000 in cents
        result = _sec_fee_cents(notional_cents)
        assert result == 2290

    def test_ten_thousand_dollar_sell(self):
        # $10,000 notional = 1_000_000 cents; fee = 0.0000229 * 10000 = $0.229 → 22.9 cents → ceil = 23
        notional_cents = 1_000_000
        result = _sec_fee_cents(notional_cents)
        assert result == 23


class TestFinraTaf:
    def test_small_trade(self):
        # 100 shares * $0.000145 = $0.0145 → 1.45 cents → round = 1 cent
        result = _finra_taf_cents(100)
        assert result == 1

    def test_cap_enforced(self):
        # 1,000,000 shares * $0.000145 = $145 → 14500 cents > cap (727)
        result = _finra_taf_cents(1_000_000)
        assert result == 727  # capped

    def test_just_below_cap(self):
        # 5,000 shares * $0.000145 = $0.725 → 72.5 cents → round = 73 cents (< 727)
        result = _finra_taf_cents(5_000)
        assert result == 73


class TestComputeFee:
    def test_buy_has_zero_regulatory_fees(self):
        """Buy trades only pay commission (default $0)."""
        fee = compute_fee("buy", shares=100, price_cents=18000)
        assert fee == 0

    def test_sell_has_sec_and_finra(self):
        """Sell trades include SEC + FINRA."""
        # 100 shares @ $180 = $18,000 notional
        # SEC: ceil(0.0000229 * 18000 * 100 / 100) ... wait, notional in cents = 100*18000=1_800_000 cents = $18,000
        # SEC = ceil(0.0000229 * 18000) * 100 / 100 ... let me re-trace:
        # notional_cents = 1_800_000; notional_dollars = 18000
        # fee_dollars = 0.0000229 * 18000 = 0.4122; fee_cents = 41.22 → ceil = 42
        # FINRA: 100 * 0.000145 = 0.0145 dollars = 1.45 cents → round = 1
        # Total = 0 + 42 + 1 = 43
        fee = compute_fee("sell", shares=100, price_cents=18000)
        assert fee == 43

    def test_sell_with_custom_commission(self):
        fee = compute_fee("sell", shares=100, price_cents=18000, commission_cents=50)
        # 50 + 42 + 1 = 93
        assert fee == 93

    def test_buy_with_custom_commission(self):
        fee = compute_fee("buy", shares=100, price_cents=18000, commission_cents=50)
        assert fee == 50

    def test_large_sell_finra_cap(self):
        """Very large sell: FINRA TAF is capped at 727 cents."""
        fee = compute_fee("sell", shares=100_000, price_cents=10000)
        # notional = 100_000 * 10_000 = 1_000_000_000 cents = $10,000,000
        # SEC = ceil(0.0000229 * 10_000_000) = ceil(229) = 229 dollars = 22900 cents
        # FINRA = cap = 727 cents
        # Total = 0 + 22900 + 727 = 23627
        assert fee == 23627

    def test_fee_is_integer(self):
        fee = compute_fee("sell", shares=53, price_cents=15237)
        assert isinstance(fee, int)
