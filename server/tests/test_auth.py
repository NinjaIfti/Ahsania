from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from capture.clock import utcnow
from capture.db.models import User, UserSession


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_login_sets_strict_httponly_cookie_and_me_works(client, make_user):
    user = make_user("doctor")
    r = login(client, user["username"], user["password"])
    assert r.status_code == 200
    assert r.json() == {"id": user["id"], "name": "Test doctor", "username": user["username"], "role": "doctor"}
    cookie = r.headers["set-cookie"].lower()
    assert "capture_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/api/me").json()["username"] == user["username"]


def test_login_ignores_id_case_and_spaces(client, make_user):
    user = make_user(username="dr.test")
    assert login(client, " Dr.Test ", user["password"]).status_code == 200


def test_wrong_password_and_unknown_id_get_the_same_answer(client, make_user):
    user = make_user()
    a = login(client, user["username"], "nope")
    b = login(client, "ghost", "nope")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Invalid ID or password"}


def test_five_failures_lock_the_account(client, make_user):
    user = make_user()
    for _ in range(5):
        assert login(client, user["username"], "wrong").status_code == 401
    r = login(client, user["username"], user["password"])
    assert r.status_code == 429
    assert "locked" in r.json()["detail"]


def test_success_resets_failure_count(client, make_user, db):
    user = make_user()
    for _ in range(4):
        login(client, user["username"], "wrong")
    assert login(client, user["username"], user["password"]).status_code == 200
    with db() as s:
        assert s.get(User, user["id"]).failed_logins == 0


def test_logout_revokes_the_session_on_the_server(app, login_as, make_user):
    c = login_as(make_user())
    token = c.cookies.get("capture_session")
    assert c.post("/api/auth/logout").status_code == 204
    replay = TestClient(app).get("/api/me", headers={"Cookie": f"capture_session={token}"})
    assert replay.status_code == 401


def test_me_requires_login(client):
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.json()["detail"] == "Not logged in"


def test_expired_session_is_rejected(login_as, make_user, db):
    c = login_as(make_user())
    with db.begin() as s:
        s.execute(update(UserSession).values(expires_at=utcnow() - timedelta(minutes=1)))
    assert c.get("/api/me").status_code == 401


def test_deactivated_user_is_logged_out(login_as, make_user, db):
    user = make_user()
    c = login_as(user)
    with db.begin() as s:
        s.get(User, user["id"]).active = False
    assert c.get("/api/me").status_code == 401


def test_passwords_are_stored_with_argon2id(make_user, db):
    user = make_user()
    with db() as s:
        assert s.get(User, user["id"]).password_hash.startswith("$argon2id$")


def test_session_token_is_not_stored_in_plain_text(login_as, make_user, db):
    c = login_as(make_user())
    token = c.cookies.get("capture_session")
    with db() as s:
        ids = list(s.scalars(select(UserSession.id)))
    assert token not in ids
    assert len(ids) == 1 and len(ids[0]) == 64


def test_parallel_failures_still_lock_the_account(app, make_user):
    user = make_user()

    def attempt(_):
        return login(TestClient(app), user["username"], "wrong").status_code

    with ThreadPoolExecutor(10) as pool:
        list(pool.map(attempt, range(10)))
    assert login(TestClient(app), user["username"], user["password"]).status_code == 429


def test_secure_cookie_flag_is_set_when_configured(settings, db, make_user):
    from capture.api.app import create_app

    secure = create_app(settings.model_copy(update={"cookie_secure": True}), session_factory=db)
    user = make_user("doctor")
    r = login(TestClient(secure), user["username"], user["password"])
    assert r.status_code == 200
    assert "secure" in r.headers["set-cookie"].lower().split("; ")
