"""
Test that BarRepository raises SplitAccessError when DEVELOPMENT mode
tries to access test-split bars.

Success Criteria #3 (PRD §7).
"""
import pytest
from datetime import datetime, timezone

from trading_tom.data.repository import BarRepository, DataMode, SplitAccessError
from trading_tom.models.market import PriceBar


def _make_bar(session, symbol: str, split_label: str, ts_offset_days: int = 0) -> PriceBar:
    """Insert a minimal PriceBar row into the test DB."""
    ts = datetime(2020, 1, 1 + ts_offset_days, tzinfo=timezone.utc)
    bar = PriceBar(
        symbol=symbol,
        interval="1d",
        ts=ts,
        open_cents=10000,
        high_cents=10100,
        low_cents=9900,
        close_cents=10050,
        volume=1000,
        split_label=split_label,
    )
    session.add(bar)
    session.commit()
    return bar


class TestDevelopmentModeCannotReadTestSplit:
    def test_raises_on_test_split_explicit(self, db_session):
        """Requesting the 'test' split in DEVELOPMENT mode must raise."""
        _make_bar(db_session, "AAPL", "test", ts_offset_days=0)
        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        with pytest.raises(SplitAccessError) as exc_info:
            repo.get_bars("AAPL", "1d", splits={"test"})
        assert "test" in str(exc_info.value)

    def test_raises_on_mixed_splits_with_test(self, db_session):
        """Requesting train+test in DEVELOPMENT mode must still raise."""
        _make_bar(db_session, "MSFT", "train", ts_offset_days=0)
        _make_bar(db_session, "MSFT", "test", ts_offset_days=1)
        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        with pytest.raises(SplitAccessError):
            repo.get_bars("MSFT", "1d", splits={"train", "test"})

    def test_allows_train_split(self, db_session):
        """DEVELOPMENT mode can read train bars without error."""
        _make_bar(db_session, "NVDA", "train", ts_offset_days=0)
        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        bars = repo.get_bars("NVDA", "1d", splits={"train"})
        assert len(bars) == 1
        assert bars[0].split_label == "train"

    def test_allows_validation_split(self, db_session):
        """DEVELOPMENT mode can read validation bars without error."""
        _make_bar(db_session, "TSLA", "validation", ts_offset_days=0)
        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        bars = repo.get_bars("TSLA", "1d", splits={"validation"})
        assert len(bars) == 1
        assert bars[0].split_label == "validation"

    def test_default_splits_excludes_test(self, db_session):
        """Default (no splits arg) in DEVELOPMENT mode excludes test bars."""
        _make_bar(db_session, "AAPL", "train", ts_offset_days=0)
        _make_bar(db_session, "AAPL", "validation", ts_offset_days=1)
        _make_bar(db_session, "AAPL", "test", ts_offset_days=2)
        repo = BarRepository(db_session, DataMode.DEVELOPMENT)
        bars = repo.get_bars("AAPL", "1d")  # no splits arg — should not raise
        split_labels = {b.split_label for b in bars}
        assert "test" not in split_labels
        assert split_labels == {"train", "validation"}


class TestFinalEvaluationMode:
    def test_can_read_test_split(self, db_session):
        """FINAL_EVALUATION mode can access test bars."""
        _make_bar(db_session, "GOOGL", "test", ts_offset_days=0)
        repo = BarRepository(db_session, DataMode.FINAL_EVALUATION)
        bars = repo.get_bars("GOOGL", "1d", splits={"test"})
        assert len(bars) == 1

    def test_cannot_read_train_in_final_eval(self, db_session):
        """FINAL_EVALUATION mode cannot read train bars (exclusive mode)."""
        _make_bar(db_session, "META", "train", ts_offset_days=0)
        repo = BarRepository(db_session, DataMode.FINAL_EVALUATION)
        with pytest.raises(SplitAccessError):
            repo.get_bars("META", "1d", splits={"train"})


class TestLiveMode:
    def test_can_read_all_splits(self, db_session):
        """LIVE mode can read any split (paper trading uses latest available data)."""
        _make_bar(db_session, "SPY", "train", ts_offset_days=0)
        _make_bar(db_session, "SPY", "validation", ts_offset_days=1)
        _make_bar(db_session, "SPY", "test", ts_offset_days=2)
        repo = BarRepository(db_session, DataMode.LIVE)
        bars = repo.get_bars("SPY", "1d", splits={"train", "validation", "test"})
        assert len(bars) == 3
