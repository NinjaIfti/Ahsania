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


def test_settings_are_admin_only(make_user, login_as):
    c = login_as(make_user("doctor"))
    assert c.put("/api/admin/settings", json={"phase3_enabled": True}).status_code == 403


def test_the_device_key_endpoints_are_gone(make_user, login_as):
    c = login_as(make_user("doctor"))
    assert c.get("/api/device/fingerprint").status_code == 404
