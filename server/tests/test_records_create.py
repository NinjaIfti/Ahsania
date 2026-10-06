import json

import pytest
from sqlalchemy import func, select

from capture.db.models import Job, Patient, Record
from constants import JPEG, REG_NO

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def count(db, model) -> int:
    with db() as s:
        return s.scalar(select(func.count()).select_from(model))


@pytest.fixture
def doctor(templates, make_user, login_as):
    return login_as(make_user("doctor"))


def test_doctor_creates_a_draft_record(db, settings, doctor, upload):
    r = upload(doctor)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["extraction_status"] == "not_applicable"
    assert body["reg_no"] == REG_NO
    assert body["template_key"] == "radiology_report"
    assert body["values"] == {}
    assert body["duplicate_of"] == []
    assert body["row_version"] == 1
    assert [e["action"] for e in body["events"]] == ["upload"]
    assert [f["page_no"] for f in body["files"]] == [1]
    stored = settings.storage_dir / "records" / body["id"] / "page-1.jpg"
    assert stored.read_bytes() == JPEG
    assert count(db, Job) == 0


def test_extraction_enabled_queues_a_job(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    assert body["status"] == "processing"
    assert body["extraction_status"] == "pending"
    with db() as s:
        job = s.scalar(select(Job))
    assert str(job.record_id) == body["id"]
    assert job.status == "queued"


def test_fill_by_hand_opens_a_draft_and_skips_the_ai(db, ai_doctor, upload):
    body = upload(ai_doctor, fill_by_hand=True).json()
    assert body["status"] == "draft"
    assert body["extraction_status"] == "skipped"
    assert count(db, Job) == 0


def test_replayed_fill_by_hand_upload_queues_nothing(db, ai_doctor, upload):
    upload_id = "6f1c2f0e-8f55-4c36-9a53-0b6d2b0f7a11"
    first = upload(ai_doctor, fill_by_hand=True, client_upload_id=upload_id)
    replay = upload(ai_doctor, fill_by_hand=True, client_upload_id=upload_id)
    assert (first.status_code, replay.status_code) == (201, 200)
    assert replay.json()["id"] == first.json()["id"]
    assert count(db, Job) == 0


def test_admin_cannot_upload(templates, make_user, login_as, upload):
    assert upload(login_as(make_user("admin"))).status_code == 403


def test_patient_id_is_normalised_to_one_patient(db, doctor, upload):
    first = upload(doctor, reg_no=" rc 123 ").json()
    second = upload(doctor, reg_no="RC123").json()
    assert first["reg_no"] == second["reg_no"] == "RC123"
    assert count(db, Patient) == 1


@pytest.mark.parametrize("reg_no", ["", "   ", "12345", "RCX1", "RC-123", "RC/../1", "RC" + "1" * 31])
def test_patient_id_must_be_rc_and_numbers(reg_no, db, settings, doctor, upload):
    r = upload(doctor, reg_no=reg_no)
    assert r.status_code == 422
    assert "Patient ID must be RC followed by numbers" in r.json()["detail"]
    assert count(db, Record) == 0
    assert not (settings.storage_dir / "records").exists()


def test_phase3_forms_locked_until_enabled(doctor, upload, enable_phase3):
    r = upload(doctor, template_key="pathology_molecular_report")
    assert r.status_code == 403
    assert r.json()["detail"] == "Locked until Phase 3"
    enable_phase3()
    assert upload(doctor, template_key="pathology_molecular_report").status_code == 201


def test_dicom_form_needs_the_dicom_upload(doctor, upload):
    assert upload(doctor, template_key="dicom_series").status_code == 422


def test_unknown_form_is_404(doctor, upload):
    assert upload(doctor, template_key="no_such_form").status_code == 404


def test_non_jpeg_page_is_rejected_and_nothing_is_stored(db, settings, doctor, upload):
    r = upload(doctor, pages=(PNG,))
    assert r.status_code == 415
    assert r.json()["detail"] == "Pages must be JPEG images"
    assert count(db, Record) == 0
    assert not (settings.storage_dir / "records").exists()


def test_too_many_pages(doctor, upload):
    assert upload(doctor, pages=(JPEG,) * 21).status_code == 422


def test_duplicate_photo_is_flagged_for_the_same_patient_only(doctor, upload):
    first = upload(doctor).json()
    second = upload(doctor).json()
    assert second["duplicate_of"] == [first["id"]]
    other_patient = upload(doctor, reg_no="RC999").json()
    assert other_patient["duplicate_of"] == []


def test_page_file_access(doctor, upload, make_user, login_as, client):
    file_id = upload(doctor).json()["files"][0]["id"]
    r = doctor.get(f"/api/files/{file_id}")
    assert r.status_code == 200
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, no-store"
    assert login_as(make_user("admin")).get(f"/api/files/{file_id}").status_code == 200
    assert client.get(f"/api/files/{file_id}").status_code == 401


def test_duplicates_are_shown_on_every_detail_and_symmetric(doctor, upload):
    first = upload(doctor).json()
    second = upload(doctor).json()
    assert doctor.get(f"/api/records/{second['id']}").json()["duplicate_of"] == [first["id"]]
    assert doctor.get(f"/api/records/{first['id']}").json()["duplicate_of"] == [second["id"]]


def test_replayed_upload_returns_the_same_record(db, settings, doctor, upload):
    upload_id = "6f1c2f0e-8f55-4c36-9a53-0b6d2b0f7a11"
    first = upload(doctor, client_upload_id=upload_id)
    replay = upload(doctor, client_upload_id=upload_id)
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert count(db, Record) == 1
    assert len(list((settings.storage_dir / "records").rglob("*.jpg"))) == 1


def test_upload_id_used_by_another_doctor_conflicts(db, doctor, upload, make_user, login_as):
    upload_id = "6f1c2f0e-8f55-4c36-9a53-0b6d2b0f7a11"
    assert upload(doctor, client_upload_id=upload_id).status_code == 201
    other = login_as(make_user("doctor"))
    r = upload(other, client_upload_id=upload_id)
    assert r.status_code == 409
    assert r.json()["detail"] == "This upload ID is already in use"
    assert count(db, Record) == 1


def test_missing_upload_id_is_rejected(doctor):
    meta = {"reg_no": REG_NO, "template_key": "radiology_report"}
    r = doctor.post("/api/records", data={"meta": json.dumps(meta)}, files=[("pages", ("p.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 422
    assert "client_upload_id" in r.json()["detail"]


def test_deleting_a_record_the_ai_is_reading_cancels_its_job(db, ai_doctor, upload):
    body = upload(ai_doctor).json()
    assert body["status"] == "processing"
    assert ai_doctor.delete(f"/api/records/{body['id']}").status_code == 204
    with db() as s:
        assert s.scalar(select(Job)).status == "cancelled"
        assert s.get(Record, body["id"]).status == "deleted"
