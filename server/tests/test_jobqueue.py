import uuid
from datetime import timedelta

from sqlalchemy import select

from capture.clock import utcnow
from capture.db.models import Job, Record, ReviewEvent
from capture.jobqueue import MAX_ATTEMPTS, cancel_jobs, claim_next, fail_abandoned, lock_claimed, queued_at, retry_later


def job_of(db, record_id: str) -> Job:
    with db() as s:
        return s.scalar(select(Job).where(Job.record_id == uuid.UUID(record_id)))


def record_of(db, record_id: str) -> Record:
    with db() as s:
        return s.get(Record, uuid.UUID(record_id))


def claim(db, worker="w1", now=None):
    with db.begin() as s:
        return claim_next(s, worker, now or utcnow())


def test_an_upload_queues_one_job(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    job = job_of(db, body["id"])
    assert (job.status, job.attempts) == ("queued", 0)
    with db() as s:
        assert queued_at(s, uuid.UUID(body["id"])) == job.created_at


def test_claim_takes_the_oldest_due_job_and_marks_it_running(db, ai_doctor, upload):
    first = upload(ai_doctor).json()
    upload(ai_doctor)
    claimed = claim(db)
    assert str(claimed.record_id) == first["id"]
    assert claimed.attempts == 1
    assert claimed.token.startswith("w1:")
    job = job_of(db, first["id"])
    assert (job.status, job.locked_by) == ("running", claimed.token)
    assert claim(db) is not None  # the second upload's job
    assert claim(db) is None  # nothing left


def test_a_job_locked_by_another_worker_is_skipped(db, ai_doctor, upload):
    first = upload(ai_doctor).json()
    second = upload(ai_doctor).json()
    with db.begin() as holding:
        held = claim_next(holding, "w1", utcnow())  # this transaction stays open, so the row stays locked
        with db.begin() as other:
            taken = claim_next(other, "w2", utcnow())
    assert str(held.record_id) == first["id"]
    assert str(taken.record_id) == second["id"]


def test_a_job_whose_worker_went_silent_is_reclaimed_after_ten_minutes(db, ai_doctor, upload):
    upload(ai_doctor)
    start = utcnow()
    first = claim(db, "a", start)
    assert claim(db, "b", start + timedelta(minutes=9)) is None
    second = claim(db, "b", start + timedelta(minutes=11))
    assert (second.id, second.attempts) == (first.id, 2)
    assert second.token != first.token
    with db.begin() as s:
        assert lock_claimed(s, first)[1] is None  # the first worker no longer holds the job
        assert lock_claimed(s, second)[1] is not None


def test_a_failed_attempt_waits_before_the_next_one(db, ai_doctor, upload):
    upload(ai_doctor)
    now = utcnow()
    claimed = claim(db, now=now)
    with db.begin() as s:
        assert retry_later(s, claimed, "VlmError: boom", now, use_attempt=True) == "retry"
    assert claim(db, now=now + timedelta(seconds=10)) is None
    assert claim(db, now=now + timedelta(seconds=31)).attempts == 2


def test_an_unreachable_model_does_not_use_up_an_attempt(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    now = utcnow()
    claimed = claim(db, now=now)
    with db.begin() as s:
        assert retry_later(s, claimed, "model server unreachable", now, use_attempt=False) == "retry"
    job = job_of(db, body["id"])
    assert (job.status, job.attempts, job.last_error) == ("queued", 0, "model server unreachable")
    assert record_of(db, body["id"]).status == "processing"


def test_the_last_failed_attempt_sends_the_record_to_manual_entry(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    now = utcnow()
    outcomes = []
    for _ in range(MAX_ATTEMPTS):
        claimed = claim(db, now=now)
        with db.begin() as s:
            outcomes.append(retry_later(s, claimed, "VlmError: boom", now, use_attempt=True))
        now += timedelta(minutes=5)
    assert outcomes == ["retry", "retry", "failed"]
    job = job_of(db, body["id"])
    assert (job.status, job.last_error) == ("failed", "VlmError: boom")
    record = record_of(db, body["id"])
    assert (record.status, record.extraction_status, record.row_version) == ("draft", "failed", 2)
    assert claim(db, now=now) is None


def test_housekeeping_gives_up_on_a_job_abandoned_on_its_last_attempt(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    with db.begin() as s:
        job = s.scalar(select(Job))
        job.status, job.attempts, job.locked_at = "running", MAX_ATTEMPTS, utcnow() - timedelta(minutes=11)
    with db.begin() as s:
        assert fail_abandoned(s, utcnow()) == 1
    assert (record_of(db, body["id"]).status, job_of(db, body["id"]).status) == ("draft", "failed")
    assert claim(db) is None


def test_cancelled_jobs_are_never_claimed(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    with db.begin() as s:
        cancel_jobs(s, uuid.UUID(body["id"]))
    assert job_of(db, body["id"]).status == "cancelled"
    assert claim(db) is None


def test_events_without_an_actor_show_as_system(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    with db.begin() as s:
        s.add(ReviewEvent(record_id=uuid.UUID(body["id"]), actor_id=None, action="upload", comment="test"))
    record = ai_doctor.get(f"/api/records/{body['id']}").json()
    assert record["events"][-1]["actor_name"] == "System"
    assert record["last_event"]["actor_name"] == "System"
