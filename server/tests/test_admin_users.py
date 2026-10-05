from datetime import timedelta

from fastapi.testclient import TestClient

from capture.clock import utcnow
from capture.db.models import User

NEW_DOCTOR = {"name": "Dr. Rahman", "username": " Dr.Rahman ", "password": "long-enough-1", "role": "doctor"}


def test_doctors_cannot_manage_accounts(make_user, login_as):
    doctor = login_as(make_user("doctor"))
    assert doctor.get("/api/admin/users").status_code == 403
    assert doctor.post("/api/admin/users", json=NEW_DOCTOR).status_code == 403
    assert doctor.patch("/api/admin/users/1", json={"active": False}).status_code == 403


def test_admin_lists_accounts_by_name(make_user, login_as):
    admin_user = make_user("admin", username="boss")
    make_user("doctor", username="dr.a")
    body = login_as(admin_user).get("/api/admin/users").json()
    assert [(u["username"], u["role"], u["active"]) for u in body] == [("boss", "admin", True), ("dr.a", "doctor", True)]
    assert set(body[0]) == {"id", "name", "username", "role", "active"}


def test_admin_creates_a_doctor_who_can_sign_in(app, make_user, login_as):
    admin = login_as(make_user("admin"))
    r = admin.post("/api/admin/users", json=NEW_DOCTOR)
    assert r.status_code == 201, r.text
    assert r.json()["username"] == "dr.rahman"
    assert r.json()["name"] == "Dr. Rahman"
    signed_in = TestClient(app).post("/api/auth/login", json={"username": "dr.rahman", "password": "long-enough-1"})
    assert signed_in.status_code == 200


def test_a_taken_id_in_any_case_is_refused(make_user, login_as):
    make_user("doctor", username="dr.rahman")
    r = login_as(make_user("admin")).post("/api/admin/users", json=dict(NEW_DOCTOR, username="DR.RAHMAN"))
    assert r.status_code == 409
    assert r.json()["detail"] == "That ID is already taken"


def test_bad_account_details_are_422(make_user, login_as):
    admin = login_as(make_user("admin"))
    for bad in [{"username": "a b"}, {"username": "x"}, {"password": "123456789"}, {"role": "uploader"}, {"name": " "}]:
        assert admin.post("/api/admin/users", json=dict(NEW_DOCTOR, **bad)).status_code == 422, bad


def test_deactivating_an_account_ends_its_sessions(make_user, login_as):
    admin = login_as(make_user("admin"))
    doctor_user = make_user("doctor")
    doctor = login_as(doctor_user)
    r = admin.patch(f"/api/admin/users/{doctor_user['id']}", json={"active": False})
    assert r.status_code == 200
    assert r.json()["active"] is False
    assert doctor.get("/api/me").status_code == 401
    assert admin.patch(f"/api/admin/users/{doctor_user['id']}", json={"active": True}).json()["active"] is True


def test_an_admin_cannot_deactivate_their_own_account(make_user, login_as):
    admin_user = make_user("admin")
    r = login_as(admin_user).patch(f"/api/admin/users/{admin_user['id']}", json={"active": False})
    assert r.status_code == 422
    assert r.json()["detail"] == "You cannot deactivate your own account"


def test_a_new_password_replaces_the_old_one_and_unlocks(db, app, make_user, login_as):
    admin = login_as(make_user("admin"))
    doctor_user = make_user("doctor")
    with db.begin() as s:
        user = s.get(User, doctor_user["id"])
        user.failed_logins, user.locked_until = 3, utcnow() + timedelta(minutes=10)
    assert admin.patch(f"/api/admin/users/{doctor_user['id']}", json={"password": "brand-new-pass"}).status_code == 200
    with db() as s:
        user = s.get(User, doctor_user["id"])
        assert (user.failed_logins, user.locked_until) == (0, None)
    c = TestClient(app)
    old = c.post("/api/auth/login", json={"username": doctor_user["username"], "password": doctor_user["password"]})
    assert old.status_code == 401
    new = c.post("/api/auth/login", json={"username": doctor_user["username"], "password": "brand-new-pass"})
    assert new.status_code == 200


def test_a_short_new_password_is_422(make_user, login_as):
    admin = login_as(make_user("admin"))
    doctor_user = make_user("doctor")
    assert admin.patch(f"/api/admin/users/{doctor_user['id']}", json={"password": "short"}).status_code == 422


def test_unknown_account_is_404(make_user, login_as):
    assert login_as(make_user("admin")).patch("/api/admin/users/99999", json={"active": False}).status_code == 404
