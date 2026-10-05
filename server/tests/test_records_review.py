import copy
from types import SimpleNamespace

import pytest

VALID = {"modality": "CT", "study_date": "2026-09-01", "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}]}


@pytest.fixture
def team(templates, make_user, login_as):
    roles = {"doctor": "doctor", "doctor2": "doctor", "admin": "admin"}
    users = {name: make_user(role) for name, role in roles.items()}
    return SimpleNamespace(users=users, **{name: login_as(user) for name, user in users.items()})


def save(client, record, values):
    return client.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})


def new_record(team, upload, values=VALID, by=None) -> dict:
    client = by or team.doctor
    record = upload(client).json()
    r = save(client, record, values)
    assert r.status_code == 200, r.text
    return r.json()


def act(client, record, action, comment=None):
    body = {"action": action, "comment": comment, "row_version": record["row_version"]}
    return client.post(f"/api/records/{record['id']}/transition", json=body)


def fresh(client, record_id) -> dict:
    return client.get(f"/api/records/{record_id}").json()


def test_doctor_then_admin_approval_path(team, upload):
    record = new_record(team, upload)
    assert record["errors"] == []
    assert record["document_date"] == "2026-09-01"
    assert act(team.doctor, fresh(team.doctor, record["id"]), "submit").json()["status"] == "pending_admin"
    final = act(team.admin, fresh(team.admin, record["id"]), "approve").json()
    assert final["status"] == "approved"
    assert [e["action"] for e in final["events"]] == ["upload", "edit", "submit", "approve"]


def test_admin_sees_drafts_and_every_value(team, upload):
    record = new_record(team, upload)
    assert team.admin.get(f"/api/records/{record['id']}").status_code == 200
    assert [r["id"] for r in team.admin.get("/api/records").json()] == [record["id"]]
    edits = [e for e in fresh(team.admin, record["id"])["events"] if e["action"] == "edit"]
    assert {"path": "lesions[0].lobe", "old": None, "new": "RUL"} in edits[0]["field_changes"]


def test_list_filters_mine_and_patient(team, upload):
    mine = upload(team.doctor).json()
    upload(team.doctor2, reg_no="RC999")
    ids = [r["id"] for r in team.doctor.get("/api/records", params={"mine": "true"}).json()]
    assert ids == [mine["id"]]
    ids = [r["id"] for r in team.doctor2.get("/api/records", params={"reg_no": mine["reg_no"]}).json()]
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
    changes = save(team.doctor, record, VALID).json()["events"][-1]["field_changes"]
    assert {"path": "lesions[1].lobe", "old": "LUL", "new": None} in changes
    assert {"path": "lesions[1].long_axis_cm", "old": 1.1, "new": None} in changes


def test_wrongly_typed_values_are_saved_but_block_approval(team, upload):
    bad = copy.deepcopy(VALID)
    bad["lesions"][0]["long_axis_cm"] = "2.3"
    record = new_record(team, upload, values=bad)
    assert record["values"] == bad
    assert {"path": "lesions[0].long_axis_cm", "message": "must be a number"} in record["errors"]
    r = act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    assert r.status_code == 422
    assert r.json()["detail"] == "Fix the highlighted fields before approving"


def test_stale_row_version_conflicts(team, upload):
    record = new_record(team, upload)
    r = team.doctor2.patch(f"/api/records/{record['id']}/values", json={"row_version": 1, "values": VALID})
    assert r.status_code == 409
    assert r.json()["detail"] == "Someone else changed this record — reload"


def test_another_doctor_can_edit_a_draft(team, upload):
    record = new_record(team, upload)
    r = save(team.doctor2, fresh(team.doctor2, record["id"]), dict(VALID, modality="MRI"))
    assert r.status_code == 200
    assert r.json()["values"]["modality"] == "MRI"


def test_nobody_edits_after_the_doctor_approves(team, upload):
    record = new_record(team, upload)
    act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    assert save(team.doctor, fresh(team.doctor, record["id"]), VALID).status_code == 403
    assert save(team.admin, fresh(team.admin, record["id"]), VALID).status_code == 403


def test_admin_sends_back_and_the_doctor_approves_again(team, upload):
    record = new_record(team, upload)
    act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    assert act(team.admin, fresh(team.admin, record["id"]), "return").status_code == 422
    returned = act(team.admin, fresh(team.admin, record["id"]), "return", "Lesion size unreadable — check page 1")
    assert returned.json()["status"] == "draft"
    listed = team.doctor.get("/api/records", params={"status": "draft", "mine": "true"}).json()
    assert listed[0]["last_event"]["action"] == "return"
    assert listed[0]["last_event"]["comment"] == "Lesion size unreadable — check page 1"
    assert act(team.doctor, fresh(team.doctor, record["id"]), "submit").json()["status"] == "pending_admin"


def test_admin_reopens_an_approved_record(team, upload):
    record = new_record(team, upload)
    act(team.doctor, fresh(team.doctor, record["id"]), "submit")
    act(team.admin, fresh(team.admin, record["id"]), "approve")
    r = act(team.admin, fresh(team.admin, record["id"]), "reopen", "Wrong lobe recorded")
    assert r.json()["status"] == "draft"


def test_approving_a_changed_record_conflicts(team, upload):
    record = new_record(team, upload)
    seen = fresh(team.doctor2, record["id"])
    assert save(team.doctor, fresh(team.doctor, record["id"]), dict(VALID, modality="MRI")).status_code == 200
    r = act(team.doctor2, seen, "submit")
    assert r.status_code == 409
    assert r.json()["detail"] == "Someone else changed this record — reload"
    assert act(team.doctor2, fresh(team.doctor2, record["id"]), "submit").status_code == 200


def test_released_is_not_an_action_any_more(team, upload):
    record = new_record(team, upload)
    assert act(team.doctor, record, "release", "x").status_code == 422


def test_unknown_record_is_404(team):
    assert team.doctor.get("/api/records/00000000-0000-0000-0000-000000000000").status_code == 404
