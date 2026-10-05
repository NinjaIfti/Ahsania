import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from capture.api.convert import record_detail
from capture.api.schemas import RecordDetail
from capture.app_settings import load_app_settings
from capture.clock import today
from capture.config import Settings
from capture.db.models import NSU_ROLES, ExtractionStatus, Patient, Record, RecordFile, ReviewEvent, Status, User
from capture.formschema.store import get_active, template_def
from capture.formschema.validate import validate_values
from capture.jobqueue import queue_extraction, queued_at
from capture.jpeg import HAS_METADATA, check_jpeg
from capture.storage import save_page
from capture.workflow.rules import can_view

METADATA_MESSAGE = "Pages must not contain photo metadata (EXIF/XMP) — re-capture the photo in the app"
CONFLICT_MESSAGE = "Someone else changed this record — reload"


class UploadRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _check_device_key(db: Session, key_fingerprint: str) -> None:
    expected = load_app_settings(db).expected_key_fingerprint
    if expected is None:
        raise UploadRejected(409, "The hospital key has not been set up yet — ask a hospital doctor to set up a device")
    if key_fingerprint != expected:
        raise UploadRejected(409, "This device's key doesn't match — ask your hospital admin.")


def _check_pages(settings: Settings, pages: list[bytes]) -> None:
    if not 1 <= len(pages) <= settings.max_pages:
        raise UploadRejected(422, f"Upload between 1 and {settings.max_pages} pages")
    for data in pages:
        if len(data) > settings.max_page_bytes:
            raise UploadRejected(413, f"Each page must be at most {settings.max_page_bytes // (1024 * 1024)} MB")
        try:
            check_jpeg(data)
        except ValueError as e:
            if str(e) == HAS_METADATA:
                raise UploadRejected(422, METADATA_MESSAGE) from None
            raise UploadRejected(415, "Pages must be JPEG images") from None


def create_record(
    db: Session,
    settings: Settings,
    user: User,
    *,
    study_code: str,
    template_key: str,
    key_fingerprint: str,
    client_upload_id: uuid.UUID,
    pages: list[bytes],
) -> tuple[Record, bool]:
    """Validate an upload, store its pages and create the record. Nothing is written on rejection.

    Returns (record, created). A replay of an earlier upload by the same user returns that record unchanged.
    """
    _check_device_key(db, key_fingerprint)
    template = get_active(db, template_key)
    if template is None:
        raise UploadRejected(404, "Unknown form type")
    existing = db.scalar(select(Record).where(Record.client_upload_id == client_upload_id))
    if existing is not None:
        if existing.created_by == user.id:
            return existing, False
        raise UploadRejected(409, "This upload ID is already in use")
    if template.kind == "dicom":
        raise UploadRejected(422, "Use the DICOM upload for this form")
    if template.phase == 3 and not load_app_settings(db).phase3_enabled:
        raise UploadRejected(403, "Locked until Phase 3")
    _check_pages(settings, pages)

    db.execute(pg_insert(Patient).values(study_code=study_code).on_conflict_do_nothing())
    record = Record(
        id=uuid.uuid4(),
        study_code=study_code,
        template_id=template.id,
        status=Status.DRAFT,
        extraction_status=ExtractionStatus.NOT_APPLICABLE,
        field_values={},
        created_by=user.id,
        client_upload_id=client_upload_id,
    )
    db.add(record)
    db.flush()
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, study_code, record.id, page_no, data)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
    queue_extraction(db, settings, record)
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="upload"))
    db.flush()
    return record, True


def replace_pages(
    db: Session,
    settings: Settings,
    user: User,
    record: Record,
    *,
    row_version: int,
    key_fingerprint: str,
    pages: list[bytes],
) -> list[str]:
    """New redacted photos for a held-back record (spec §8.1): the old files go and the AI reads the new ones.

    Returns the old files' stored paths, to delete once the change is committed. Nothing is written on rejection.
    """
    if record.status != Status.QUARANTINED:
        raise UploadRejected(409, "Only records held back for patient details can get new photos")
    if row_version != record.row_version:
        raise UploadRejected(409, CONFLICT_MESSAGE)
    _check_device_key(db, key_fingerprint)
    _check_pages(settings, pages)
    old = list(record.files)
    for page in old:
        db.delete(page)
    suffix = "-" + uuid.uuid4().hex[:8]
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, record.study_code, record.id, page_no, data, suffix=suffix)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
    record.quarantine = None
    record.row_version += 1
    queue_extraction(db, settings, record)
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="reupload"))
    db.flush()
    db.expire(record, ["files"])
    return [page.path for page in old]


def load_events(db: Session, record_id: uuid.UUID) -> list[ReviewEvent]:
    stmt = select(ReviewEvent).where(ReviewEvent.record_id == record_id).order_by(ReviewEvent.id)
    return list(db.scalars(stmt))


def duplicates_of(db: Session, record: Record, viewer_role: str) -> list[uuid.UUID]:
    """Other records of the same patient sharing a page photo, limited to what the viewer may see."""
    hashes = select(RecordFile.sha256).where(RecordFile.record_id == record.id)
    stmt = (
        select(Record.id, Record.status, Record.created_at)
        .join(RecordFile, RecordFile.record_id == Record.id)
        .where(Record.study_code == record.study_code, Record.id != record.id, RecordFile.sha256.in_(hashes))
        .distinct()
    )
    rows = [row for row in db.execute(stmt) if can_view(viewer_role, row.status)]
    return [row.id for row in sorted(rows, key=lambda row: row.created_at)]


def detail_for(db: Session, record: Record, viewer_role: str) -> RecordDetail:
    errors = validate_values(template_def(record.template), record.field_values, today())
    phase3_enabled = load_app_settings(db).phase3_enabled
    since = queued_at(db, record.id) if record.status == Status.PROCESSING else None
    return record_detail(
        record,
        load_events(db, record.id),
        errors,
        phase3_enabled,
        duplicates_of(db, record, viewer_role),
        viewer_role in NSU_ROLES,
        since,
    )


def last_events(db: Session, record_ids: list[uuid.UUID]) -> dict[uuid.UUID, ReviewEvent]:
    """The newest review event of each record (one query)."""
    if not record_ids:
        return {}
    stmt = (
        select(ReviewEvent)
        .where(ReviewEvent.record_id.in_(record_ids))
        .order_by(ReviewEvent.record_id, ReviewEvent.id.desc())
        .ext(distinct_on(ReviewEvent.record_id))
    )
    return {event.record_id: event for event in db.scalars(stmt)}
