"""The extraction job queue (spec §5.1). The API adds jobs; the worker claims and finishes them.

Jobs are claimed with FOR UPDATE SKIP LOCKED, reclaimed after 10 minutes of silence, and given 3 attempts.
Lock order everywhere: the record first, then its jobs (the API's transitions lock the record first too).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from capture.config import Settings
from capture.db.models import ExtractionStatus, Job, JobStatus, Record, Status

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=10)
RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    record_id: uuid.UUID
    token: str  # identifies this claim; a reclaimed job gets a new token
    attempts: int


def queue_extraction(db: Session, settings: Settings, record: Record) -> None:
    """Hand a record to the AI worker, or straight to manual entry when extraction is switched off."""
    if not settings.extraction_enabled:
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.NOT_APPLICABLE
        return
    record.status = Status.PROCESSING
    record.extraction_status = ExtractionStatus.PENDING
    db.add(Job(kind="extract", record_id=record.id))


def queued_at(db: Session, record_id: uuid.UUID) -> datetime | None:
    """When the record's newest job was queued."""
    return db.scalar(select(func.max(Job.created_at)).where(Job.record_id == record_id))


def cancel_jobs(db: Session, record_id: uuid.UUID) -> None:
    db.execute(
        update(Job)
        .where(Job.record_id == record_id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        .values(status=JobStatus.CANCELLED)
    )


def claim_next(db: Session, worker: str, now: datetime) -> ClaimedJob | None:
    """Take the next due job, or one whose worker has been silent for 10 minutes, and mark it running."""
    job = db.scalar(
        select(Job)
        .where(
            Job.kind == "extract",
            or_(
                (Job.status == JobStatus.QUEUED) & (Job.run_after <= now),
                (Job.status == JobStatus.RUNNING) & (Job.locked_at < now - STALE_AFTER) & (Job.attempts < MAX_ATTEMPTS),
            ),
        )
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.locked_at = now
    job.locked_by = f"{worker[:40]}:{uuid.uuid4().hex[:12]}"
    job.attempts += 1
    db.flush()
    return ClaimedJob(job.id, job.record_id, job.locked_by, job.attempts)


def lock_claimed(db: Session, claimed: ClaimedJob) -> tuple[Record | None, Job | None]:
    """Lock the record, then the job. The job is None when this claim no longer holds it (cancelled or reclaimed)."""
    record = db.get(Record, claimed.record_id, with_for_update=True)
    job = db.get(Job, claimed.id, with_for_update=True)
    if job is None or job.status != JobStatus.RUNNING or job.locked_by != claimed.token:
        return record, None
    return record, job


def give_up(record: Record | None, job: Job, error: str) -> None:
    """The AI is a shortcut, never a blocker (spec §5.1): after the last attempt the record goes to manual entry."""
    job.status = JobStatus.FAILED
    job.last_error = error
    if record is not None and record.status == Status.PROCESSING:
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.FAILED
        record.row_version += 1


def retry_later(db: Session, claimed: ClaimedJob, error: str, now: datetime, *, use_attempt: bool) -> str:
    """Put the job back in the queue, or give up after the last attempt. Returns 'retry', 'failed' or 'dropped'."""
    record, job = lock_claimed(db, claimed)
    if job is None:
        return "dropped"
    if not use_attempt:
        job.attempts -= 1
    elif job.attempts >= MAX_ATTEMPTS:
        give_up(record, job, error)
        return "failed"
    job.status = JobStatus.QUEUED
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    job.run_after = now + RETRY_DELAY * max(job.attempts, 1)
    return "retry"


def fail_abandoned(db: Session, now: datetime) -> int:
    """Give up on jobs whose worker went silent during their last attempt. Returns how many."""
    stale = (Job.status == JobStatus.RUNNING) & (Job.locked_at < now - STALE_AFTER) & (Job.attempts >= MAX_ATTEMPTS)
    count = 0
    for job_id, record_id in db.execute(select(Job.id, Job.record_id).where(stale)).all():
        record = db.get(Record, record_id, with_for_update=True)
        job = db.get(Job, job_id, with_for_update=True)
        if job.status == JobStatus.RUNNING and job.locked_at < now - STALE_AFTER and job.attempts >= MAX_ATTEMPTS:
            give_up(record, job, "the worker stopped while reading this record")
            count += 1
    return count
