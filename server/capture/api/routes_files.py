import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from capture.api.deps import current_user, get_db, get_settings
from capture.config import Settings
from capture.db.models import Record, RecordFile, User
from capture.storage import resolve_in_storage

router = APIRouter(tags=["files"])


@router.get("/files/{file_id}")
def get_file(
    file_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    stored = db.get(RecordFile, file_id)
    record = db.get(Record, stored.record_id) if stored is not None else None
    if stored is None or record is None:
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "image/jpeg" if stored.kind == "page" else "application/dicom"
    return FileResponse(
        resolve_in_storage(settings.storage_dir, stored.path),
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
