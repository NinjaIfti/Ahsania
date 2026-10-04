from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capture.auth.passwords import hash_password, verify_password
from capture.db.models import User

LOCK_AFTER_FAILURES = 5
LOCK_MINUTES = 15
_dummy_hash: str | None = None


class AccountLocked(Exception):
    def __init__(self, until: datetime) -> None:
        super().__init__(f"locked until {until.isoformat()}")
        self.until = until


def _spend_time_like_a_real_check(password: str) -> None:
    """Hash anyway for unknown emails so response time does not reveal which emails exist."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(_dummy_hash, password)


def authenticate(db: Session, email: str, password: str, now: datetime) -> User | None:
    user = db.scalar(
        select(User).where(func.lower(User.email) == email.strip().lower()).with_for_update()
    )
    if user is None or not user.active:
        _spend_time_like_a_real_check(password)
        return None
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLocked(user.locked_until)
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= LOCK_AFTER_FAILURES:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        return None
    user.failed_logins = 0
    user.locked_until = None
    return user
