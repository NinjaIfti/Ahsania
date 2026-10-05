"""The worker loop (spec §5.1) and its housekeeping: jobs whose worker went silent."""

import logging
import threading
import time
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from capture.clock import utcnow
from capture.config import Settings
from capture.jobqueue import claim_next, fail_abandoned
from capture.worker.process import Engines, process_job

log = logging.getLogger("capture.worker")
HOUSEKEEPING_EVERY_S = 300


def housekeeping(sessions: sessionmaker, now: datetime) -> None:
    with sessions.begin() as db:
        fail_abandoned(db, now)


def run_worker(sessions: sessionmaker, settings: Settings, engines: Engines, stop: threading.Event, name: str) -> None:
    """Claim and run jobs until `stop` is set. Errors are logged and never end the loop."""
    log.info("worker %s started", name)
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_housekeeping:
                housekeeping(sessions, utcnow())
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
