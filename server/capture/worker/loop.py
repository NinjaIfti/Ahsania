"""The worker loop (spec §5.1) and its housekeeping: abandoned jobs, and the 14-day quarantine expiry (spec §8.1)."""

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import Record, Status
from capture.jobqueue import claim_next, fail_abandoned
from capture.storage import remove_stored
from capture.worker.process import Engines, process_job

log = logging.getLogger("capture.worker")
QUARANTINE_KEEP = timedelta(days=14)
HOUSEKEEPING_EVERY_S = 300


def expire_quarantined_files(db: Session, now: datetime) -> list[str]:
    """Drop the photos of records quarantined for 14 days. Returns their stored paths, to delete after commit."""
    removed: list[str] = []
    records = db.scalars(select(Record).where(Record.status == Status.QUARANTINED).with_for_update(skip_locked=True))
    for record in records:
        quarantine = record.quarantine or {}
        held_since = quarantine.get("at")
        if quarantine.get("files_expired") or held_since is None or datetime.fromisoformat(held_since) > now - QUARANTINE_KEEP:
            continue
        for page in list(record.files):
            removed.append(page.path)
            db.delete(page)
        record.quarantine = {**quarantine, "files_expired": True}
        record.row_version += 1
    return removed


def housekeeping(sessions: sessionmaker, settings: Settings, now: datetime) -> None:
    with sessions.begin() as db:
        fail_abandoned(db, now)
        removed = expire_quarantined_files(db, now)
    remove_stored(settings.storage_dir, removed)


def run_worker(sessions: sessionmaker, settings: Settings, engines: Engines, stop: threading.Event, name: str) -> None:
    """Claim and run jobs until `stop` is set. Errors are logged and never end the loop."""
    log.info("worker %s started", name)
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_housekeeping:
                housekeeping(sessions, settings, utcnow())
                next_housekeeping = time.monotonic() + HOUSEKEEPING_EVERY_S
            with sessions.begin() as db:
                claimed = claim_next(db, name, utcnow())
            if claimed is None:
                stop.wait(settings.worker_poll_s)
                continue
            outcome = process_job(sessions, settings, engines, claimed)
            log.info("job %s (record %s): %s", claimed.id, claimed.record_id, outcome)
        except Exception:
            log.exception("worker loop error")
            stop.wait(settings.worker_poll_s)
    log.info("worker %s stopped", name)
