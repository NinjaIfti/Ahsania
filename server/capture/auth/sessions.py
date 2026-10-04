import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from capture.db.models import User, UserSession


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: int, now: datetime, hours: int) -> str:
    """Store a new session and return the raw token for the cookie (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    db.add(UserSession(id=_digest(token), user_id=user_id, expires_at=now + timedelta(hours=hours)))
    return token


def user_for_token(db: Session, token: str, now: datetime) -> User | None:
    row = db.get(UserSession, _digest(token))
    if row is None or row.revoked or row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.active else None


def revoke_token(db: Session, token: str) -> None:
    row = db.get(UserSession, _digest(token))
    if row is not None:
        row.revoked = True


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id).values(revoked=True))
