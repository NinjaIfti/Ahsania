import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from capture.api.convert import record_detail
from capture.api.schemas import RecordDetail
from capture.app_settings import load_app_settings
from capture.clock import today
from capture.config import Settings
from capture.db.models import ExtractionStatus, Job, Patient, Record, RecordFile, ReviewEvent, Status, User
from capture.formschema.store import get_active, template_def
from capture.formschema.validate import validate_values
from capture.storage import save_page

JPEG_MAGIC = b"\xff\xd8\xff"


class UploadRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def create_record(
    db: Session,
    settings: Settings,
    user: User,
    *,
    study_code: str,
    template_key: str,
    key_fingerprint: str,
    pages: list[bytes],
) -> tuple[Record, list[uuid.UUID]]:
    """Validate an upload, store its pages and create the record. Nothing is written on rejection."""
    app_settings = load_app_settings(db)
    if app_settings.expected_key_fingerprint is None:
        raise UploadRejected(409, "The hospital key has not been set up yet — ask a hospital doctor to set up a device")
    if key_fingerprint != app_settings.expected_key_fingerprint:
        raise UploadRejected(409, "This device's key doesn't match — ask your hospital admin.")
    template = get_active(db, template_key)
    if template is None:
        raise UploadRejected(404, "Unknown form type")
    if template.kind == "dicom":
        raise UploadRejected(422, "Use the DICOM upload for this form")
    if template.phase == 3 and not app_settings.phase3_enabled:
        raise UploadRejected(403, "Locked until Phase 3")
    if not 1 <= len(pages) <= settings.max_pages:
        raise UploadRejected(422, f"Upload between 1 and {settings.max_pages} pages")
    for data in pages:
        if len(data) > settings.max_page_bytes:
            raise UploadRejected(413, f"Each page must be at most {settings.max_page_bytes // (1024 * 1024)} MB")
        if not data.startswith(JPEG_MAGIC):
            raise UploadRejected(415, "Pages must be JPEG images")

    db.execute(pg_insert(Patient).values(study_code=study_code).on_conflict_do_nothing())
    extracting = settings.extraction_enabled
    record = Record(
        id=uuid.uuid4(),
        study_code=study_code,
        template_id=template.id,
        status=Status.PROCESSING if extracting else Status.DRAFT,
        extraction_status=ExtractionStatus.PENDING if extracting else ExtractionStatus.NOT_APPLICABLE,
        field_values={},
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    hashes: list[str] = []
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, study_code, record.id, page_no, data)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
        hashes.append(digest)
    duplicates = list(
        db.scalars(
            select(RecordFile.record_id)
            .join(Record, Record.id == RecordFile.record_id)
            .where(Record.study_code == study_code, RecordFile.sha256.in_(hashes), RecordFile.record_id != record.id)
            .distinct()
        )
    )
    if extracting:
        db.add(Job(kind="extract", record_id=record.id))
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="upload"))
    db.flush()
    return record, duplicates


def load_events(db: Session, record_id: uuid.UUID) -> list[ReviewEvent]:
    stmt = select(ReviewEvent).where(ReviewEvent.record_id == record_id).order_by(ReviewEvent.created_at, ReviewEvent.id)
    return list(db.scalars(stmt))


def detail_for(db: Session, record: Record, duplicate_of: Iterable[uuid.UUID] = ()) -> RecordDetail:
    errors = validate_values(template_def(record.template), record.field_values, today())
    phase3_enabled = load_app_settings(db).phase3_enabled
    return record_detail(record, load_events(db, record.id), errors, phase3_enabled, duplicate_of)
