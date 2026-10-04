import copy
from types import SimpleNamespace

import pytest

VALID = {"modality": "CT", "study_date": "2026-09-01", "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}]}


@pytest.fixture
def team(templates, hospital_key, make_user, login_as):
    roles = {
        "uploader": "uploader",
        "doctor": "hospital_doctor",
        "doctor2": "hospital_doctor",
        "reviewer": "nsu_reviewer",
        "admin": "admin",
    }
    users = {name: make_user(role) for name, role in roles.items()}
    return SimpleNamespace(users=users, **{name: login_as(user) for name, user in users.items()})


def save(client, record, values):
    return client.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})


def new_record(team, upload, values=VALID, by=None) -> dict:
    client = by or team.uploader
    record = upload(client).json()
    r = save(client, record, values)
    assert r.status_code == 200, r.text
    return r.json()


def act(client, record, action, comment=None):
    body = {"action": action, "comment": comment, "row_version": record["row_version"]}
    return client.post(f"/api/records/{record['id']}/transition", json=body)


def fresh(client, record_id) -> dict:
    return client.get(f"/api/records/{record_id}").json()


def test_full_double_approval_path(team, upload):
    record = new_record(team, upload)
    assert record["errors"] == []
    assert record["document_date"] == "2026-09-01"
    assert act(team.uploader, fresh(team.uploader, record["id"]), "submit").json()["status"] == "pending_doctor"
    assert act(team.doctor, fresh(team.doctor, record["id"]), "approve").json()["status"] == "pending_nsu"
    final = act(team.reviewer, fresh(team.reviewer, record["id"]), "approve").json()
    assert final["status"] == "approved"
    assert [e["action"] for e in final["events"]] == ["upload", "edit", "submit", "approve", "approve"]


def test_nsu_sees_a_record_only_after_doctor_approval(team, upload):
    record = new_record(team, upload)
    assert team.reviewer.get(f"/api/records/{record['id']}").status_code == 404
    assert team.reviewer.get("/api/records").json() == []
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    listed = team.reviewer.get("/api/records", params={"status": "pending_nsu"}).json()
    assert [r["id"] for r in listed] == [record["id"]]


def test_list_filter_mine(team, upload):
    mine = upload(team.uploader).json()
    upload(team.doctor)
    ids = [r["id"] for r in team.uploader.get("/api/records", params={"mine": "true"}).json()]
    assert ids == [mine["id"]]


def test_edit_sets_document_date_and_logs_the_diff(team, upload):
    record = new_record(team, upload)
    edit = record["events"][-1]
    assert edit["action"] == "edit"
    assert {"path": "lesions[0].lobe", "old": None, "new": "RUL"} in edit["field_changes"]
    assert record["row_version"] == 2


def test_removing_a_lesion_is_recorded_in_the_audit_trail(team, upload):
    two = dict(VALID, lesions=[{"lobe": "RUL", "long_axis_cm": 2.3}, {"lobe": "LUL", "long_axis_cm": 1.1}])
    record = new_record(team, upload, values=two)
    changes = save(team.uploader, record, VALID).json()["events"][-1]["field_changes"]
    assert {"path": "lesions[1].lobe", "old": "LUL", "new": None} in changes
    assert {"path": "lesions[1].long_axis_cm", "old": 1.1, "new": None} in changes


def test_wrongly_typed_values_are_saved_but_block_submit(team, upload):
    bad = copy.deepcopy(VALID)
    bad["lesions"][0]["long_axis_cm"] = "2.3"
    record = new_record(team, upload, values=bad)
    assert record["values"] == bad
    assert {"path": "lesions[0].long_axis_cm", "message": "must be a number"} in record["errors"]
    r = act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    assert r.status_code == 422
    assert r.json()["detail"] == "Fix the highlighted fields before submitting"


def test_stale_row_version_conflicts(team, upload):
    record = new_record(team, upload)
    r = team.doctor.patch(f"/api/records/{record['id']}/values", json={"row_version": 1, "values": VALID})
    assert r.status_code == 409
    assert r.json()["detail"] == "Someone else changed this record — reload"


def test_uploader_cannot_edit_after_submit(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    assert save(team.uploader, fresh(team.uploader, record["id"]), VALID).status_code == 403


def test_doctor_can_correct_while_reviewing(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    r = save(team.doctor, fresh(team.doctor, record["id"]), dict(VALID, modality="MRI"))
    assert r.status_code == 200
    assert r.json()["values"]["modality"] == "MRI"


def test_nsu_cannot_edit(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    assert save(team.reviewer, fresh(team.reviewer, record["id"]), VALID).status_code == 403


def test_four_eyes_rule(team, upload):
    record = new_record(team, upload, by=team.doctor)
    act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    r = act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    assert r.status_code == 403
    assert "another doctor" in r.json()["detail"]
    assert act(team.doctor2, fresh(team.doctor2, record["id"]), "approve").status_code == 200


def test_nsu_return_goes_back_through_the_doctor(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    assert act(team.reviewer, fresh(team.reviewer, record["id"]), "return").status_code == 422
    returned = act(team.reviewer, fresh(team.reviewer, record["id"]), "return", "Lesion size unreadable — check page 1")
    assert returned.json()["status"] == "draft"
    listed = team.uploader.get("/api/records", params={"status": "draft", "mine": "true"}).json()
    assert listed[0]["last_event"]["action"] == "return"
    assert listed[0]["last_event"]["comment"] == "Lesion size unreadable — check page 1"
    assert act(team.uploader, fresh(team.uploader, record["id"]), "submit").json()["status"] == "pending_doctor"


def test_admin_reopens_an_approved_record(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    act(team.reviewer, fresh(team.reviewer, record["id"]), "approve")
    r = act(team.admin, fresh(team.admin, record["id"]), "reopen", "Wrong lobe recorded")
    assert r.json()["status"] == "draft"


def test_approving_a_changed_record_conflicts(team, upload):
    record = new_record(team, upload, by=team.doctor)
    act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    seen = fresh(team.doctor2, record["id"])
    assert save(team.doctor, fresh(team.doctor, record["id"]), dict(VALID, modality="MRI")).status_code == 200
    r = act(team.doctor2, seen, "approve")
    assert r.status_code == 409
    assert r.json()["detail"] == "Someone else changed this record — reload"
    assert act(team.doctor2, fresh(team.doctor2, record["id"]), "approve").status_code == 200


def test_unknown_record_is_404(team):
    assert team.uploader.get("/api/records/00000000-0000-0000-0000-000000000000").status_code == 404


def test_nsu_sees_edit_paths_but_no_draft_values(team, upload):
    record = new_record(team, upload)
    act(team.uploader, fresh(team.uploader, record["id"]), "submit")
    act(team.doctor, fresh(team.doctor, record["id"]), "approve")
    act(team.reviewer, fresh(team.reviewer, record["id"]), "approve")

    nsu_edits = [e for e in fresh(team.reviewer, record["id"])["events"] if e["action"] == "edit"]
    assert nsu_edits and nsu_edits[0]["field_changes"]
    for event in nsu_edits:
        assert all(set(change) == {"path"} for change in event["field_changes"])

    hospital_edits = [e for e in fresh(team.doctor, record["id"])["events"] if e["action"] == "edit"]
    assert {"path": "lesions[0].lobe", "old": None, "new": "RUL"} in hospital_edits[0]["field_changes"]
