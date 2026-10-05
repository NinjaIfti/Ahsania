import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capture.api.deps import get_db, require_roles
from capture.api.schemas import AccountIn, AccountOut, AccountPatch, SettingsIn, SettingsOut
from capture.app_settings import load_app_settings
from capture.auth.passwords import hash_password
from capture.auth.sessions import revoke_all_for_user
from capture.db.models import AppSettings, Role, User

router = APIRouter(prefix="/admin", tags=["admin"])
audit = logging.getLogger("capture.audit")
admin_only = require_roles(Role.ADMIN)


def _out(row: AppSettings) -> SettingsOut:
    return SettingsOut(phase3_enabled=row.phase3_enabled)


@router.get("/settings", response_model=SettingsOut)
def read_settings(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> SettingsOut:
    return _out(load_app_settings(db))


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsIn, user: User = Depends(admin_only), db: Session = Depends(get_db)) -> SettingsOut:
    row = load_app_settings(db, for_update=True)
    row.phase3_enabled = body.phase3_enabled
    db.commit()
    audit.warning("phase3_enabled set to %s by user %s", body.phase3_enabled, user.id)
    return _out(row)


@router.get("/users", response_model=list[AccountOut])
def list_users(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> list[User]:
    return list(db.scalars(select(User).order_by(User.name, User.id)))


@router.post("/users", status_code=201, response_model=AccountOut)
def create_user(body: AccountIn, user: User = Depends(admin_only), db: Session = Depends(get_db)) -> User:
    if db.scalar(select(User).where(func.lower(User.username) == body.username)) is not None:
        raise HTTPException(status_code=409, detail="That ID is already taken")
    account = User(name=body.name, username=body.username, password_hash=hash_password(body.password), role=body.role)
    db.add(account)
    db.commit()
    audit.warning("account %s (%s) created by user %s", account.username, account.role, user.id)
    return account


@router.patch("/users/{user_id}", response_model=AccountOut)
def update_user(user_id: int, body: AccountPatch, user: User = Depends(admin_only), db: Session = Depends(get_db)) -> User:
    account = db.get(User, user_id, with_for_update=True)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if body.active is False and account.id == user.id:
        raise HTTPException(status_code=422, detail="You cannot deactivate your own account")
    if body.active is not None:
        account.active = body.active
        if not body.active:
            revoke_all_for_user(db, account.id)
    if body.password is not None:
        account.password_hash = hash_password(body.password)
        account.failed_logins = 0
        account.locked_until = None
    db.commit()
    audit.warning("account %s updated by user %s (active=%s, password changed=%s)", account.username, user.id, account.active, body.password is not None)
    return account
