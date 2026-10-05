import json
import threading
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from capture.clock import utcnow
from capture.db.models import Job, Record, RecordFile
from capture.extraction.stub import stub_completion
from capture.jobqueue import cancel_jobs, claim_next
from capture.worker.loop import housekeeping, run_worker
from capture.worker.process import Engines, process_job
from constants import PHOTO, STUDY_CODE
from fakes import REPORT_LINES, FakeOcr, run_once, stub_vlm

READS_CLEANLY = Engines(FakeOcr(*REPORT_LINES), stub_vlm())
SHOWS_A_MOBILE = Engines(FakeOcr("CT CHEST REPORT", "Mobile: 01712345678"), stub_vlm())


@pytest.fixture
def worker_settings(ai_settings):
    return ai_settings.model_copy(update={"worker_poll_s": 0.05})


def stored(db, record_id: str) -> Record:
    with db() as s:
        return s.get(Record, uuid.UUID(record_id))


def test_a_report_is_read_into_a_draft_with_colours_and_sources(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    assert body["status"] == "processing"
    assert run_once(db, worker_settings, READS_CLEANLY) == "done"
    record = ai_uploader.get(f"/api/records/{body['id']}").json()
    assert (record["status"], record["extraction_status"]) == ("draft", "done")
    assert record["values"]["modality"] == "CT"
    assert record["values"]["lesions"] == [{"lobe": "RUL", "long_axis_cm": 2.3, "short_axis_cm": 1.8, "description": "spiculated mass"}]
    assert record["document_date"] == "2026-09-01"
    assert record["row_version"] == body["row_version"] + 1
    fields = record["extraction"]["fields"]
    assert fields["modality"]["colour"] == "green"
    assert fields["lesions[0].short_axis_cm"]["colour"] == "amber"  # the stub is unsure of it
    assert fields["contrast"]["colour"] == "grey"
    assert fields["impression"]["sources"] == [{"page": 1, "box": [10, 120, 500, 150]}]
    with db() as s:
        assert s.scalar(select(Job.status)) == "done"


def test_a_readable_identifier_quarantines_the_record(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    assert run_once(db, worker_settings, SHOWS_A_MOBILE) == "quarantined"
    record = ai_uploader.get(f"/api/records/{body['id']}").json()
    assert record["status"] == "quarantined"
    assert record["values"] == {}
    assert record["events"][-1]["action"] == "quarantine"
    assert record["events"][-1]["actor_name"] == "System"
    assert record["events"][-1]["comment"] == "Possible patient details found: mobile number (page 1)"
    quarantine = stored(db, body["id"]).quarantine
    assert quarantine["hits"] == [{"page": 1, "kind": "mobile", "box": [10, 40, 500, 70]}]
    assert quarantine["summary"] == "Possible patient details found: mobile number (page 1)"
    assert quarantine["files_expired"] is False


def test_a_released_record_skips_the_safety_net(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    with db.begin() as s:
        s.scalar(select(Job)).skip_safety_net = True
    assert run_once(db, worker_settings, Engines(FakeOcr("Mobile: 01712345678", *REPORT_LINES), stub_vlm())) == "done"
    assert stored(db, body["id"]).status == "draft"


def test_an_unreachable_model_keeps_the_record_waiting(db, worker_settings, ai_uploader, upload):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    body = upload(ai_uploader, pages=(PHOTO,)).json()
    now = utcnow()
    assert run_once(db, worker_settings, Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(refuse))), now=now) == "retry"
    with db() as s:
        job = s.scalar(select(Job))
    assert (job.status, job.attempts) == ("queued", 0)
    assert job.run_after > now
    assert stored(db, body["id"]).status == "processing"


def test_three_failed_attempts_send_the_record_to_manual_entry(db, worker_settings, ai_uploader, upload):
    broken = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(lambda request: httpx.Response(500))))
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    now = utcnow()
    outcomes = []
    for _ in range(3):
        outcomes.append(run_once(db, worker_settings, broken, now=now))
        now += timedelta(minutes=5)
    assert outcomes == ["retry", "retry", "failed"]
    record = stored(db, body["id"])
    assert (record.status, record.extraction_status) == ("draft", "failed")
    with db() as s:
        job = s.scalar(select(Job))
    assert (job.status, job.last_error) == ("failed", "VlmError: model server answered 500")


def test_an_answer_that_is_not_json_uses_up_an_attempt(db, worker_settings, ai_uploader, upload):
    garbled = {"choices": [{"finish_reason": "stop", "message": {"content": "I think it is a CT scan"}}]}
    engines = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(lambda request: httpx.Response(200, json=garbled))))
    upload(ai_uploader, pages=(PHOTO,))
    assert run_once(db, worker_settings, engines) == "retry"
    with db() as s:
        assert s.scalar(select(Job.attempts)) == 1


def test_a_record_taken_by_hand_while_the_model_was_reading_keeps_the_users_draft(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()

    def fill_by_hand_meanwhile(request: httpx.Request) -> httpx.Response:
        with db.begin() as s:
            record = s.get(Record, uuid.UUID(body["id"]), with_for_update=True)
            record.status, record.extraction_status = "draft", "skipped"
            cancel_jobs(s, record.id)
        return httpx.Response(200, json=stub_completion(json.loads(request.content)))

    engines = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(fill_by_hand_meanwhile)))
    assert run_once(db, worker_settings, engines) == "dropped"
    record = stored(db, body["id"])
    assert (record.status, record.extraction_status, record.field_values) == ("draft", "skipped", {})
    with db() as s:
        assert s.scalar(select(Job.status)) == "cancelled"


def test_a_worker_that_lost_its_job_to_another_drops_its_late_result(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    start = utcnow()
    with db.begin() as s:
        first = claim_next(s, "slow-worker", start)
    with db.begin() as s:
        second = claim_next(s, "other-worker", start + timedelta(minutes=11))
    assert process_job(db, worker_settings, READS_CLEANLY, second) == "done"
    assert process_job(db, worker_settings, SHOWS_A_MOBILE, first) == "dropped"
    assert stored(db, body["id"]).status == "draft"


def test_photos_held_back_for_14_days_are_deleted(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    run_once(db, worker_settings, SHOWS_A_MOBILE)
    page = worker_settings.storage_dir / "records" / STUDY_CODE / body["id"] / "page-1.jpg"
    housekeeping(db, worker_settings, utcnow() + timedelta(days=13))
    assert page.exists()
    housekeeping(db, worker_settings, utcnow() + timedelta(days=15))
    assert not page.exists()
    record = stored(db, body["id"])
    assert (record.status, record.quarantine["files_expired"]) == ("quarantined", True)
    with db() as s:
        assert s.scalar(select(func.count()).select_from(RecordFile)) == 0


def test_the_worker_loop_reads_waiting_records_until_stopped(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    stop = threading.Event()
    thread = threading.Thread(target=run_worker, args=(db, worker_settings, READS_CLEANLY, stop, "loop-test"))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while stored(db, body["id"]).status != "draft" and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert stored(db, body["id"]).status == "draft"
    assert not thread.is_alive()


def test_an_answer_with_nan_is_rejected_as_not_json(db, worker_settings, ai_uploader, upload):
    nan = {"choices": [{"finish_reason": "stop", "message": {"content": '{"modality": "CT", "contrast": NaN}'}}]}
    engines = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(lambda request: httpx.Response(200, json=nan))))
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    assert run_once(db, worker_settings, engines) == "retry"
    with db() as s:
        job = s.scalar(select(Job))
    assert (job.attempts, job.last_error) == (1, "VlmError: the model's answer was not JSON")
    assert stored(db, body["id"]).field_values == {}


class _OcrThatFailsQuotingThePage:
    def read(self, page, image):
        raise RuntimeError("could not read line 'Patient Name: Rahim Uddin'")


def test_an_unexpected_error_keeps_only_its_type_out_of_logs_and_the_job(db, worker_settings, ai_uploader, upload, caplog):
    upload(ai_uploader, pages=(PHOTO,))
    with caplog.at_level("DEBUG", logger="capture.worker"):
        assert run_once(db, worker_settings, Engines(_OcrThatFailsQuotingThePage(), stub_vlm())) == "retry"
    with db() as s:
        assert s.scalar(select(Job.last_error)) == "RuntimeError"
    assert "RuntimeError" in caplog.text
    assert "Rahim" not in caplog.text
