import pytest
from sqlalchemy import func, select

from capture.api.app import create_app
from capture.db.models import Job, Record
from constants import JPEG, STUDY_CODE

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


def count(db, model) -> int:
    with db() as s:
        return s.scalar(select(func.count()).select_from(model))


@pytest.fixture
def uploader(templates, hospital_key, make_user, login_as):
    return login_as(make_user("uploader"))


def test_uploader_creates_a_draft_record(db, settings, uploader, upload):
    r = upload(uploader)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["extraction_status"] == "not_applicable"
    assert body["study_code"] == STUDY_CODE
    assert body["template_key"] == "radiology_report"
    assert body["values"] == {}
    assert body["duplicate_of"] == []
    assert body["row_version"] == 1
    assert [e["action"] for e in body["events"]] == ["upload"]
    assert [f["page_no"] for f in body["files"]] == [1]
    stored = settings.storage_dir / "records" / STUDY_CODE / body["id"] / "page-1.jpg"
    assert stored.read_bytes() == JPEG
    assert count(db, Job) == 0


def test_extraction_enabled_queues_a_job(db, settings, templates, hospital_key, make_user, login_as, upload):
    app = create_app(settings.model_copy(update={"extraction_enabled": True}), session_factory=db)
    client = login_as(make_user("uploader"), on_app=app)
    body = upload(client).json()
    assert body["status"] == "processing"
    assert body["extraction_status"] == "pending"
    with db() as s:
        job = s.scalar(select(Job))
    assert str(job.record_id) == body["id"]
    assert job.status == "queued"


def test_nsu_reviewer_cannot_upload(templates, hospital_key, make_user, login_as, upload):
    assert upload(login_as(make_user("nsu_reviewer"))).status_code == 403


def test_upload_refused_before_hospital_key_is_set(templates, make_user, login_as, upload):
    r = upload(login_as(make_user("uploader")))
    assert r.status_code == 409
    assert "not been set up" in r.json()["detail"]


def test_wrong_device_key_is_refused(db, uploader, upload):
    r = upload(uploader, fingerprint="K-0000")
    assert r.status_code == 409
    assert r.json()["detail"] == "This device's key doesn't match — ask your hospital admin."
    assert count(db, Record) == 0


def test_phase3_forms_locked_until_enabled(uploader, upload, enable_phase3):
    r = upload(uploader, template_key="pathology_molecular_report")
    assert r.status_code == 403
    assert r.json()["detail"] == "Locked until Phase 3"
    enable_phase3()
    assert upload(uploader, template_key="pathology_molecular_report").status_code == 201


def test_dicom_form_needs_the_dicom_upload(uploader, upload):
    assert upload(uploader, template_key="dicom_series").status_code == 422


def test_unknown_form_is_404(uploader, upload):
    assert upload(uploader, template_key="no_such_form").status_code == 404


def test_non_jpeg_page_is_rejected_and_nothing_is_stored(db, settings, uploader, upload):
    r = upload(uploader, pages=(PNG,))
    assert r.status_code == 415
    assert r.json()["detail"] == "Pages must be JPEG images"
    assert count(db, Record) == 0
    assert not (settings.storage_dir / "records").exists()


@pytest.mark.parametrize("code", ["amh-n0zdg4km8v", "AMH-N0ZDG4KM8", "AMH-N0ZDG4KM8U", " AMH-N0ZDG4KM8V"])
def test_malformed_study_code_is_rejected(code, db, uploader, upload):
    r = upload(uploader, study_code=code)
    assert r.status_code == 422
    assert "study_code" in r.json()["detail"]
    assert count(db, Record) == 0


def test_too_many_pages(uploader, upload):
    assert upload(uploader, pages=(JPEG,) * 21).status_code == 422


def test_duplicate_photo_is_flagged_for_the_same_patient_only(uploader, upload):
    first = upload(uploader).json()
    second = upload(uploader).json()
    assert second["duplicate_of"] == [first["id"]]
    other_patient = upload(uploader, study_code="AMH-MHNZ0NHAA4").json()
    assert other_patient["duplicate_of"] == []


def test_page_file_access(uploader, upload, make_user, login_as, client):
    file_id = upload(uploader).json()["files"][0]["id"]
    r = uploader.get(f"/api/files/{file_id}")
    assert r.status_code == 200
    assert r.content == JPEG
    assert r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, no-store"
    reviewer = login_as(make_user("nsu_reviewer"))
    assert reviewer.get(f"/api/files/{file_id}").status_code == 404
    assert client.get(f"/api/files/{file_id}").status_code == 401
