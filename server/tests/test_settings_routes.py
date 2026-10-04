import pytest

PHASE3 = {"pathology_molecular_report", "lab_report", "treatment_sheet", "clinical_summary", "outcome_followup"}


def test_templates_need_login(client):
    assert client.get("/api/templates").status_code == 401


def test_templates_list_marks_phase3_locked(templates, make_user, login_as, enable_phase3):
    c = login_as(make_user())
    body = c.get("/api/templates").json()
    assert len(body) == 9
    assert {t["key"] for t in body if t["locked"]} == PHASE3
    radiology = next(t for t in body if t["key"] == "radiology_report")
    assert radiology["definition"]["fields"][0]["key"] == "modality"
    enable_phase3()
    assert not any(t["locked"] for t in c.get("/api/templates").json())


def test_admin_toggles_phase3(make_user, login_as):
    admin = login_as(make_user("admin"))
    r = admin.put("/api/admin/settings", json={"phase3_enabled": True})
    assert r.status_code == 200
    assert r.json()["phase3_enabled"] is True
    assert admin.get("/api/admin/settings").json()["phase3_enabled"] is True


@pytest.mark.parametrize("role", ["uploader", "hospital_doctor", "nsu_reviewer"])
def test_settings_are_admin_only(role, make_user, login_as):
    c = login_as(make_user(role))
    assert c.put("/api/admin/settings", json={"phase3_enabled": True}).status_code == 403


def test_first_doctor_registers_hospital_key_then_others_must_match(make_user, login_as):
    doctor = login_as(make_user("hospital_doctor"))
    first = doctor.post("/api/device/fingerprint", json={"fingerprint": "K-B9FF"})
    assert first.json() == {"expected": "K-B9FF", "status": "set"}
    assert doctor.post("/api/device/fingerprint", json={"fingerprint": "K-B9FF"}).json()["status"] == "match"
    other = doctor.post("/api/device/fingerprint", json={"fingerprint": "K-786D"})
    assert other.status_code == 409
    uploader = login_as(make_user("uploader"))
    assert uploader.get("/api/device/fingerprint").json()["expected"] == "K-B9FF"


def test_only_doctors_register_keys(make_user, login_as):
    c = login_as(make_user("uploader"))
    assert c.post("/api/device/fingerprint", json={"fingerprint": "K-B9FF"}).status_code == 403


def test_nsu_cannot_read_the_fingerprint(make_user, login_as):
    assert login_as(make_user("nsu_reviewer")).get("/api/device/fingerprint").status_code == 403


def test_fingerprint_format_is_checked(make_user, login_as):
    c = login_as(make_user("hospital_doctor"))
    assert c.post("/api/device/fingerprint", json={"fingerprint": "K-ZZZZ"}).status_code == 422


def test_admin_can_clear_the_key_fingerprint(hospital_key, make_user, login_as):
    admin = login_as(make_user("admin"))
    assert admin.get("/api/admin/settings").json()["expected_key_fingerprint"] == hospital_key
    assert admin.delete("/api/admin/settings/fingerprint").json()["expected_key_fingerprint"] is None
