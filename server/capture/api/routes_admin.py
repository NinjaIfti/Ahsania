import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from capture.api.deps import get_db, require_roles
from capture.api.schemas import SettingsIn, SettingsOut
from capture.app_settings import load_app_settings
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
