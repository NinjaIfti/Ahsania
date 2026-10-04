from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo("Asia/Dhaka")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    """The current calendar date at the hospital."""
    return datetime.now(DHAKA).date()
