import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from capture.clock import utcnow
from capture.db.models import Job
from capture.jobqueue import claim_next
from capture.worker.loop import housekeeping
from capture.worker.process import Engines
from constants import FINGERPRINT, PHOTO, STUDY_CODE
from fakes import REPORT_LINES, FakeOcr, run_once, stub_vlm

SHOWS_A_MOBILE = Engines(FakeOcr("Mobile: 01712345678", *REPORT_LINES), stub_vlm())
READS_CLEANLY = Engines(FakeOcr(*REPORT_LINES), stub_vlm())
WITH_EXIF = PHOTO[:2] + b"\xff\xe1\x00\x08Exif\x00\x00" + PHOTO[2:]


@pytest.fixture
def staff(ai_app, templates, hospital_key, make_user, login_as):
    roles = {"uploader": "uploader", "doctor": "hospital_doctor", "reviewer": "nsu_reviewer"}
    return SimpleNamespace(**{name: login_as(make_user(role), on_app=ai_app) for name, role in roles.items()})


def fresh(client, record_id: str) -> dict:
    return client.get(f"/api/records/{record_id}").json()


def held_back(db, ai_settings, staff, upload) -> dict:
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    assert run_once(db, ai_settings, SHOWS_A_MOBILE) == "quarantined"
    return fresh(staff.uploader, body["id"])


def act(client, record, action, comment=None):
    body = {"action": action, "comment": comment, "row_version": record["row_version"]}
    return client.post(f"/api/records/{record['id']}/transition", json=body)


def reupload(client, record, *, pages=(PHOTO,), fingerprint=FINGERPRINT, row_version=None):
    meta = {"row_version": record["row_version"] if row_version is None else row_version, "key_fingerprint": fingerprint}
    files = [("pages", (f"page-{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(pages)]
    return client.post(f"/api/records/{record['id']}/reupload", data={"meta": json.dumps(meta)}, files=files)


def test_hospital_staff_see_why_a_record_was_held_back_and_nsu_sees_nothing(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    assert record["status"] == "quarantined"
    assert record["quarantine"]["summary"] == "Possible patient details found: mobile number (page 1)"
    assert record["quarantine"]["hits"] == [{"page": 1, "kind": "mobile", "box": [10, 0, 500, 30]}]
    assert staff.reviewer.get(f"/api/records/{record['id']}").status_code == 404


def test_a_doctor_releases_a_false_alarm_and_the_ai_reads_it_without_the_safety_net(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    r = act(staff.doctor, record, "release", "That number is the hospital's own helpline")
    assert r.status_code == 200, r.text
    released = r.json()
    assert (released["status"], released["quarantine"]) == ("processing", None)
    assert released["events"][-1]["action"] == "release"
    with db() as s:
        assert s.scalars(select(Job.skip_safety_net).order_by(Job.id)).all() == [False, True]
    assert run_once(db, ai_settings, SHOWS_A_MOBILE) == "done"
    assert fresh(staff.doctor, record["id"])["status"] == "draft"


@pytest.mark.parametrize(("who", "comment", "status"), [("uploader", "false alarm", 403), ("doctor", None, 422), ("doctor", "  ", 422)])
def test_release_needs_a_hospital_doctor_and_a_reason(db, ai_settings, staff, upload, who, comment, status):
    record = held_back(db, ai_settings, staff, upload)
    assert act(getattr(staff, who), record, "release", comment).status_code == status


def test_photos_deleted_after_14_days_cannot_be_released(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    housekeeping(db, ai_settings, utcnow() + timedelta(days=15))
    record = fresh(staff.doctor, record["id"])
    assert record["quarantine"]["files_expired"] is True
    assert record["files"] == []
    r = act(staff.doctor, record, "release", "false alarm")
    assert r.status_code == 409
    assert r.json()["detail"] == "The photos were deleted after 14 days — upload them again"
    assert reupload(staff.uploader, record).status_code == 200


def test_new_photos_replace_the_held_back_ones(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    old_page = ai_settings.storage_dir / "records" / STUDY_CODE / record["id"] / "page-1.jpg"
    assert old_page.exists()
    r = reupload(staff.uploader, record, pages=(PHOTO, PHOTO))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["quarantine"]) == ("processing", None)
    assert [f["page_no"] for f in body["files"]] == [1, 2]
    assert body["events"][-1]["action"] == "reupload"
    assert not old_page.exists()
    assert staff.uploader.get(f"/api/files/{body['files'][0]['id']}").content == PHOTO
    assert run_once(db, ai_settings, READS_CLEANLY) == "done"
    assert fresh(staff.uploader, record["id"])["status"] == "draft"


def test_new_photos_are_checked_like_any_upload(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    wrong_key = reupload(staff.uploader, record, fingerprint="K-0000")
    assert (wrong_key.status_code, wrong_key.json()["detail"]) == (409, "This device's key doesn't match — ask your hospital admin.")
    stale = reupload(staff.uploader, record, row_version=record["row_version"] - 1)
    assert (stale.status_code, stale.json()["detail"]) == (409, "Someone else changed this record — reload")
    assert reupload(staff.uploader, record, pages=(WITH_EXIF,)).status_code == 422
    assert reupload(staff.reviewer, record).status_code == 403
    after = fresh(staff.uploader, record["id"])
    assert (after["status"], len(after["files"])) == ("quarantined", 1)


def test_only_held_back_records_take_new_photos(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    r = reupload(staff.uploader, fresh(staff.uploader, body["id"]))
    assert (r.status_code, r.json()["detail"]) == (409, "Only records held back for patient details can get new photos")


def test_fill_by_hand_is_offered_after_two_minutes_and_stops_the_ai(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    assert body["extraction_queued_at"] is not None
    early = act(staff.uploader, body, "fill_by_hand")
    assert (early.status_code, early.json()["detail"]) == (409, "The AI is still reading this record — try again in a minute")
    with db.begin() as s:
        s.scalar(select(Job)).created_at = utcnow() - timedelta(minutes=3)
    r = act(staff.uploader, body, "fill_by_hand")
    assert r.status_code == 200, r.text
    filled = r.json()
    assert (filled["status"], filled["extraction_status"], filled["extraction_queued_at"]) == ("draft", "skipped", None)
    assert filled["events"][-1]["action"] == "fill_by_hand"
    with db.begin() as s:
        assert s.scalar(select(Job.status)) == "cancelled"
        assert claim_next(s, "w", utcnow()) is None


def test_nsu_sees_where_values_were_found_but_never_the_ai_values(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    record = fresh(staff.uploader, body["id"])
    values = {**record["values"], "impression": "Retyped by the uploader"}
    r = staff.uploader.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})
    record = r.json()
    hospital_view = record["extraction"]["fields"]
    assert hospital_view["impression"]["edited"] is True
    assert hospital_view["impression"]["value"] == "Suspicious for primary lung malignancy."
    assert (hospital_view["modality"]["edited"], hospital_view["contrast"]["edited"]) == (False, False)
    record = act(staff.uploader, record, "submit").json()
    act(staff.doctor, record, "approve")
    nsu_view = fresh(staff.reviewer, record["id"])["extraction"]["fields"]
    assert "value" not in nsu_view["impression"]
    assert nsu_view["impression"]["edited"] is True
    assert nsu_view["modality"]["colour"] == "green"
    assert nsu_view["modality"]["sources"] == hospital_view["modality"]["sources"]


def test_record_lists_count_the_ai_fields_still_to_check(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    [listed] = staff.uploader.get("/api/records", params={"status": "draft"}).json()
    assert (listed["ai_amber"], listed["ai_red"]) == (1, 0)  # the stub is unsure of the short axis
    record = fresh(staff.uploader, body["id"])
    lesion = {**record["values"]["lesions"][0], "short_axis_cm": 1.9}
    values = {**record["values"], "lesions": [lesion]}
    staff.uploader.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})
    [listed] = staff.uploader.get("/api/records", params={"status": "draft"}).json()
    assert (listed["ai_amber"], listed["ai_red"]) == (0, 0)
