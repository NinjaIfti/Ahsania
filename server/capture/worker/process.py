"""One extraction job, start to finish (spec §5.2). Never logs or stores page text or field values."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from capture.clock import today, utcnow
from capture.config import Settings
from capture.db.models import ExtractionStatus, JobStatus, Record, Status
from capture.extraction.assemble import build_extraction, conform
from capture.extraction.ocr import OcrEngine, OcrLine
from capture.extraction.spans import field_confidences
from capture.extraction.vlm import VlmClient, VlmError, VlmUnavailable
from capture.formschema.model import TemplateDef
from capture.formschema.store import template_def
from capture.formschema.validate import document_date_of, validate_values
from capture.jobqueue import ClaimedJob, lock_claimed, retry_later
from capture.storage import resolve_in_storage

log = logging.getLogger("capture.worker")


@dataclass
class Engines:
    ocr: OcrEngine
    vlm: VlmClient


def _load(sessions: sessionmaker, settings: Settings, claimed: ClaimedJob) -> tuple[TemplateDef, list[bytes]] | None:
    """The template and page images, or None when the record no longer waits for the AI."""
    with sessions() as db:
        record = db.get(Record, claimed.record_id)
        if record is None or record.status != Status.PROCESSING:
            return None
        pages = [resolve_in_storage(settings.storage_dir, f.path).read_bytes() for f in record.files if f.kind == "page"]
        return template_def(record.template), pages


def _drop(sessions: sessionmaker, claimed: ClaimedJob) -> str:
    """The record stopped waiting for the AI (filled by hand, or another worker finished it): let the job go."""
    with sessions.begin() as db:
        _, job = lock_claimed(db, claimed)
        if job is not None:
            job.status = JobStatus.CANCELLED
    return "dropped"


def _finish(sessions: sessionmaker, claimed: ClaimedJob, apply: Callable[[Record], str]) -> str:
    """Write a result if this claim still holds the job and the record still waits for the AI; otherwise drop it."""
    with sessions.begin() as db:
        record, job = lock_claimed(db, claimed)
        if job is None:
            return "dropped"
        if record is None or record.status != Status.PROCESSING:
            job.status = JobStatus.CANCELLED
            return "dropped"
        job.status = JobStatus.DONE
        outcome = apply(record)
        record.row_version += 1
        return outcome


def _no_constants(name: str) -> None:
    """json.loads accepts NaN and Infinity, which are not JSON and which PostgreSQL refuses to store."""
    raise ValueError(f"{name} is not JSON")


def _result(tpl: TemplateDef, values: dict, extraction: dict) -> Callable[[Record], str]:
    def apply(record: Record) -> str:
        record.field_values = values
        record.extraction = extraction
        record.document_date = document_date_of(tpl, values)
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.DONE
        return "done"

    return apply


def process_job(
    sessions: sessionmaker,
    settings: Settings,
    engines: Engines,
    claimed: ClaimedJob,
    now: Callable[[], datetime] = utcnow,
) -> str:
    """Run one claimed job. Returns done, dropped, retry or failed."""
    try:
        loaded = _load(sessions, settings, claimed)
        if loaded is None:
            return _drop(sessions, claimed)
        tpl, pages = loaded
        lines: list[OcrLine] = []
        for page_no, image in enumerate(pages, start=1):
            lines.extend(engines.ocr.read(page_no, image))
        answer = engines.vlm.extract(tpl, pages)
        try:
            raw = json.loads(answer.text, parse_constant=_no_constants)
        except ValueError:
            raise VlmError("the model's answer was not JSON") from None
        values = conform(tpl, raw)
        errors = validate_values(tpl, values, today())
        confidences = field_confidences(answer.text, answer.tokens)
        extraction = build_extraction(tpl, values, confidences, lines, errors, settings.confidence_threshold, answer.model)
        return _finish(sessions, claimed, _result(tpl, values, extraction))
    except VlmUnavailable as e:
        with sessions.begin() as db:
            return retry_later(db, claimed, str(e), now(), use_attempt=False)
    except Exception as e:
        # Only our own VlmError messages are kept: others can quote page text or field values (e.g. database errors).
        error = f"VlmError: {e}" if isinstance(e, VlmError) else type(e).__name__
        log.error("job %s (record %s) failed: %s", claimed.id, claimed.record_id, error)
        with sessions.begin() as db:
            return retry_later(db, claimed, error[:300], now(), use_attempt=True)
