"""NYSE market calendar helpers (US Eastern timezone)."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

ET = ZoneInfo("America/New_York")
_nyse = mcal.get_calendar("NYSE")


def _now_et() -> datetime:
    return datetime.now(tz=ET)


def is_market_open(dt: datetime | None = None) -> bool:
    """Return True if the NYSE session is currently open (9:30–16:00 ET, excl. holidays)."""
    if dt is None:
        dt = _now_et()
    dt_et = dt.astimezone(ET)
    today = dt_et.date()
    schedule = _nyse.schedule(start_date=str(today), end_date=str(today))
    if schedule.empty:
        return False
    market_open = schedule.iloc[0]["market_open"].to_pydatetime().astimezone(ET)
    market_close = schedule.iloc[0]["market_close"].to_pydatetime().astimezone(ET)
    return market_open <= dt_et <= market_close


def market_hours(dt: datetime | None = None) -> tuple[datetime, datetime] | None:
    """Return (open, close) for the given date in ET, or None if closed that day."""
    if dt is None:
        dt = _now_et()
    dt_et = dt.astimezone(ET)
    today = dt_et.date()
    schedule = _nyse.schedule(start_date=str(today), end_date=str(today))
    if schedule.empty:
        return None
    market_open = schedule.iloc[0]["market_open"].to_pydatetime().astimezone(ET)
    market_close = schedule.iloc[0]["market_close"].to_pydatetime().astimezone(ET)
    return market_open, market_close


def is_trading_day(d: date) -> bool:
    """Return True if d is an NYSE trading day."""
    schedule = _nyse.schedule(start_date=str(d), end_date=str(d))
    return not schedule.empty


def next_trading_day(d: date) -> date:
    """Return the next NYSE trading day after d."""
    candidate = d + timedelta(days=1)
    for _ in range(10):
        if is_trading_day(candidate):
            return candidate
        candidate += timedelta(days=1)
    raise RuntimeError(f"Could not find next trading day after {d}")
