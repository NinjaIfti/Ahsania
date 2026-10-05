import json
import uuid

import pgserver
import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url

from constants import FINGERPRINT, JPEG, STUDY_CODE, TEMPLATES_DIR

TABLES = "review_events, jobs, record_files, records, patients, templates, sessions, users"


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory):
    """A throwaway PostgreSQL 16 for the whole test session (stopped at exit)."""
    yield pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")


@pytest.fixture(scope="session")
def database_url(pg_server) -> str:
    pg_server.psql("CREATE DATABASE capture_test;")
    url = make_url(pg_server.get_uri()).set(drivername="postgresql+psycopg", database="capture_test")
    return url.render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def migrated_url(database_url) -> str:
    from capture.db.migrate import upgrade

    upgrade(database_url)
    return database_url


@pytest.fixture(scope="session")
def session_factory(migrated_url):
    from capture.db.base import make_sessionmaker

    return make_sessionmaker(migrated_url)


@pytest.fixture
def db(session_factory):
    """The session factory, on an emptied database."""
    with session_factory.begin() as s:
        # Superuser-only: skip the append-only triggers for test cleanup.
        s.execute(text("SET LOCAL session_replication_role = replica"))
        s.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        s.execute(text("UPDATE settings SET expected_key_fingerprint = NULL, phase3_enabled = false"))
    return session_factory


@pytest.fixture
def settings(migrated_url, tmp_path):
    from capture.config import Settings

    return Settings(database_url=migrated_url, storage_dir=tmp_path / "storage", cookie_secure=False)


@pytest.fixture
def app(settings, db):
    from capture.api.app import create_app

    return create_app(settings, session_factory=db)


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture
def make_user(db):
    from capture.auth.passwords import hash_password
    from capture.db.models import User

    def _make(role="uploader", *, email=None, password="correct-horse-1", active=True) -> dict:
        institution = "NSU" if role in ("nsu_reviewer", "admin") else "AMCGH"
        email = email or f"{role}-{uuid.uuid4().hex[:8]}@example.test"
        with db.begin() as s:
            user = User(
                name=f"Test {role}",
                email=email,
                password_hash=hash_password(password),
                role=role,
                institution=institution,
                active=active,
            )
            s.add(user)
            s.flush()
            return {"id": user.id, "email": email, "password": password, "role": role}

    return _make


@pytest.fixture
def login_as(app):
    from fastapi.testclient import TestClient

    def _login(user: dict, on_app=None):
        c = TestClient(on_app or app)
        r = c.post("/api/auth/login", json={"email": user["email"], "password": user["password"]})
        assert r.status_code == 200, r.text
        return c

    return _login


@pytest.fixture
def templates(db):
    from capture.formschema.store import load_templates

    with db.begin() as s:
        load_templates(s, TEMPLATES_DIR)


@pytest.fixture
def hospital_key(db):
    from capture.db.models import AppSettings

    with db.begin() as s:
        s.get(AppSettings, 1).expected_key_fingerprint = FINGERPRINT
    return FINGERPRINT


@pytest.fixture
def enable_phase3(db):
    def _enable():
        from capture.db.models import AppSettings

        with db.begin() as s:
            s.get(AppSettings, 1).phase3_enabled = True

    return _enable


@pytest.fixture
def upload():
    def _upload(
        client,
        *,
        template_key="radiology_report",
        study_code=STUDY_CODE,
        fingerprint=FINGERPRINT,
        pages=(JPEG,),
        client_upload_id=None,
    ):
        meta = {
            "study_code": study_code,
            "template_key": template_key,
            "key_fingerprint": fingerprint,
            "client_upload_id": client_upload_id or str(uuid.uuid4()),
        }
        files = [("pages", (f"page-{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(pages)]
        return client.post("/api/records", data={"meta": json.dumps(meta)}, files=files)

    return _upload


@pytest.fixture
def ai_settings(settings):
    """Settings with the AI worker switched on, so uploads start in `processing` with a queued job."""
    return settings.model_copy(update={"extraction_enabled": True})


@pytest.fixture
def ai_app(ai_settings, db):
    from capture.api.app import create_app

    return create_app(ai_settings, session_factory=db)


@pytest.fixture
def ai_uploader(ai_app, templates, hospital_key, make_user, login_as):
    return login_as(make_user("uploader"), on_app=ai_app)
