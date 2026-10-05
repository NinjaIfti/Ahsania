import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from capture.api.convert import record_summary
from capture.api.deps import current_user, get_db, get_settings, require_roles
from capture.api.schemas import CreateMeta, ReadIdOut, RecordDetail, RecordSummary, TransitionIn, ValuesIn
from capture.clock import today
from capture.config import Settings
from capture.db.models import ExtractionStatus, Record, ReviewEvent, Role, Template, User
from capture.extraction.read_id import OcrUnavailable
from capture.formschema.diff import diff_values
from capture.formschema.store import template_def
from capture.formschema.validate import document_date_of, validate_values
from capture.jobqueue import cancel_jobs
from capture.jpeg import check_jpeg
from capture.records.service import CONFLICT_MESSAGE, UploadRejected, create_record, detail_for, last_events
from capture.workflow.rules import Action, TransitionError, can_edit, next_status

router = APIRouter(tags=["records"])


def _meta_error(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
    return "Invalid upload details: " + "; ".join(parts)


@router.post("/records", status_code=201, response_model=RecordDetail)
def create(
    response: Response,
    meta: str = Form(...),
    pages: list[UploadFile] = File(...),
    user: User = Depends(require_roles(Role.DOCTOR)),
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
        record, created = create_record(
            db,
            settings,
            user,
            reg_no=parsed.reg_no,
            template_key=parsed.template_key,
            client_upload_id=parsed.client_upload_id,
            fill_by_hand=parsed.fill_by_hand,
            pages=data,
        )
    except UploadRejected as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message) from None
    db.commit()
    if not created:
        response.status_code = 200
    return detail_for(db, record)



@router.post("/read-id", response_model=ReadIdOut)
def read_id(
    request: Request,
    page: UploadFile = File(...),
    user: User = Depends(require_roles(Role.DOCTOR)),
    settings: Settings = Depends(get_settings),
) -> ReadIdOut:
    """Find the patient ID on one photographed page; nothing is stored."""
    data = page.file.read(settings.max_page_bytes + 1)
    if len(data) > settings.max_page_bytes:
        raise HTTPException(status_code=413, detail="Page is too large")
    try:
        check_jpeg(data)
    except ValueError:
        raise HTTPException(status_code=415, detail="Pages must be JPEG images") from None
    try:
        return ReadIdOut(reg_no=request.app.state.id_reader.read(data))
    except OcrUnavailable:
        raise HTTPException(status_code=503, detail="This server cannot read photos; type the patient ID") from None

def _load(db: Session, record_id: uuid.UUID, *, for_update: bool = False) -> Record:
    record = db.get(Record, record_id, with_for_update=True if for_update else None)
    if record is None:
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("/records", response_model=list[RecordSummary])
def list_records(
    status: str | None = None,
    reg_no: str | None = None,
    template: str | None = None,
    mine: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RecordSummary]:
    stmt = select(Record).join(Record.template)
    if status:
        stmt = stmt.where(Record.status == status)
    if reg_no:
        stmt = stmt.where(Record.reg_no == reg_no)
    if template:
        stmt = stmt.where(Template.key == template)
    if mine:
        stmt = stmt.where(Record.created_by == user.id)
    records = list(db.scalars(stmt.order_by(Record.updated_at.desc()).limit(500)))
    latest = last_events(db, [r.id for r in records])
    return [record_summary(r, latest.get(r.id)) for r in records]


@router.get("/records/{record_id}", response_model=RecordDetail)
def get_record(record_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> RecordDetail:
    return detail_for(db, _load(db, record_id))


@router.patch("/records/{record_id}/values", response_model=RecordDetail)
def update_values(
    record_id: uuid.UUID,
    body: ValuesIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecordDetail:
    record = _load(db, record_id, for_update=True)
    if not can_edit(user.role, record.status):
        raise HTTPException(status_code=403, detail="You cannot edit this record now")
    if body.row_version != record.row_version:
        raise HTTPException(status_code=409, detail=CONFLICT_MESSAGE)
    changes = diff_values(record.field_values, body.values)
    record.field_values = body.values
    record.document_date = document_date_of(template_def(record.template), body.values)
    record.row_version += 1
    if changes:
        db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="edit", field_changes=changes))
    db.commit()
    return detail_for(db, record)


@router.post("/records/{record_id}/transition", response_model=RecordDetail)
def transition(
    record_id: uuid.UUID,
    body: TransitionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecordDetail:
    record = _load(db, record_id, for_update=True)
    if body.row_version != record.row_version:
        raise HTTPException(status_code=409, detail=CONFLICT_MESSAGE)
    errors = validate_values(template_def(record.template), record.field_values, today())
    try:
        new_status = next_status(
            action=body.action,
            role=user.role,
            status=record.status,
            comment=body.comment,
            has_errors=bool(errors),
        )
    except TransitionError as e:
        raise HTTPException(status_code=e.http_status, detail=e.message) from None
    record.status = new_status
    record.row_version += 1
    if body.action == Action.FILL_BY_HAND:
        cancel_jobs(db, record.id)
        record.extraction_status = ExtractionStatus.SKIPPED
    comment = (body.comment or "").strip() or None
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action=body.action, comment=comment, field_flags=body.field_flags))
    db.commit()
    return detail_for(db, record)

