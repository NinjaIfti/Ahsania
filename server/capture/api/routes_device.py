import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from capture.api.deps import get_db, require_roles
from capture.api.schemas import FingerprintIn, FingerprintOut
from capture.app_settings import load_app_settings
from capture.db.models import Role, User

router = APIRouter(prefix="/device", tags=["device"])
audit = logging.getLogger("capture.audit")


@router.get("/fingerprint", response_model=FingerprintOut)
def get_fingerprint(
    _: User = Depends(require_roles(Role.UPLOADER, Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
) -> FingerprintOut:
    return FingerprintOut(expected=load_app_settings(db).expected_key_fingerprint)


@router.post("/fingerprint", response_model=FingerprintOut)
def register_fingerprint(
    body: FingerprintIn,
    user: User = Depends(require_roles(Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
) -> FingerprintOut:
    row = load_app_settings(db, for_update=True)
    if row.expected_key_fingerprint is None:
        row.expected_key_fingerprint = body.fingerprint
        db.commit()
        audit.warning("hospital key fingerprint %s registered by user %s", body.fingerprint, user.id)
        return FingerprintOut(expected=body.fingerprint, status="set")
    if row.expected_key_fingerprint == body.fingerprint:
        return FingerprintOut(expected=body.fingerprint, status="match")
    raise HTTPException(status_code=409, detail="This key doesn't match the hospital key already registered")
