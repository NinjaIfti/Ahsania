from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from capture.api.deps import get_db, get_settings, require_roles
from capture.api.schemas import CreateMeta, RecordDetail
from capture.config import Settings
from capture.db.models import Role, User
from capture.records.service import UploadRejected, create_record, detail_for

router = APIRouter(tags=["records"])


def _meta_error(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
    return "Invalid upload details: " + "; ".join(parts)


@router.post("/records", status_code=201, response_model=RecordDetail)
def create(
    meta: str = Form(...),
    pages: list[UploadFile] = File(...),
    user: User = Depends(require_roles(Role.UPLOADER, Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecordDetail:
    try:
        parsed = CreateMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_meta_error(e)) from None
    if len(pages) > settings.max_pages:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {settings.max_pages} pages")
    data = [page.file.read(settings.max_page_bytes + 1) for page in pages]
    try:
        record, duplicates = create_record(
            db,
            settings,
            user,
            study_code=parsed.study_code,
            template_key=parsed.template_key,
            key_fingerprint=parsed.key_fingerprint,
            pages=data,
        )
    except UploadRejected as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message) from None
    db.commit()
    return detail_for(db, record, duplicate_of=duplicates)
