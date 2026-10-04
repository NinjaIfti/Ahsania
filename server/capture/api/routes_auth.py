from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from capture.api.deps import SESSION_COOKIE, current_user, get_db, get_settings
from capture.api.schemas import LoginIn, UserOut
from capture.auth.login import AccountLocked, authenticate
from capture.auth.sessions import create_session, revoke_token
from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import User

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(
    body: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    now = utcnow()
    try:
        user = authenticate(db, body.email, body.password, now)
    except AccountLocked:
        db.commit()
        raise HTTPException(status_code=429, detail="Account locked for 15 minutes after 5 failed attempts") from None
    if user is None:
        db.commit()  # keep the failed-login counter
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(db, user.id, now, settings.session_hours)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_token(db, token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
