from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from capture.auth.sessions import user_for_token
from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import User

SESSION_COOKIE = "capture_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = user_for_token(db, token, utcnow()) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Not allowed for your role")
        return user

    return dependency
