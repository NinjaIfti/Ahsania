# M1 — Server Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI + PostgreSQL server that stores de-identified uploads, form templates and the two-approval review workflow, so the M2 web app can do capture → doctor approval → NSU approval with no AI.

**Architecture:** One Python package `capture` in `server/`. The API process (`uvicorn capture.api.app:create_app --factory`) is the only writer of records. Business rules sit in small modules with no I/O (`formschema/`, `workflow/rules.py`), and routes stay thin. Tests run against real PostgreSQL 16 provided by the `pgserver` pip package, so no Docker is needed on Windows.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, pydantic-settings, SQLAlchemy 2 (sync) + psycopg 3, Alembic, argon2-cffi, PyYAML, Typer, pytest, httpx TestClient, pgserver.

**Spec:** `docs/superpowers/specs/2026-10-04-data-capture-design.md` (this plan covers milestone M1 of §13; M2 is `docs/superpowers/plans/2026-10-04-m2-web-capture.md`).

## Global Constraints

- Python `>=3.12,<3.13`; PostgreSQL 16 (pgserver bundles 16.2 for tests and local dev).
- The package is named `capture` (the spec's `server.api:app` is replaced by `capture.api.app:create_app --factory`). Entry points: API = `capture.api.app:create_app`, CLI = `capture` (Typer), dev server = `python -m capture.devserver`.
- Roles, exactly: `uploader`, `hospital_doctor`, `nsu_reviewer`, `admin`. Institutions: `AMCGH` (hospital roles), `NSU` (NSU roles).
- Record statuses, exactly: `processing`, `quarantined`, `draft`, `pending_doctor`, `pending_nsu`, `approved`. Extraction statuses: `pending`, `done`, `failed`, `not_applicable`.
- Study code regex: `^AMH-[0-9A-HJKMNP-TV-Z]{10}$`. Key fingerprint regex: `^K-[0-9A-F]{4}$`.
- User-facing messages copied from the spec, verbatim: `This device's key doesn't match — ask your hospital admin.` · `Someone else changed this record — reload` · `Locked until Phase 3`.
- Session cookie `capture_session`: HttpOnly, SameSite=Strict, Secure (only `CAPTURE_COOKIE_SECURE=false` for local http), 12-hour expiry; the server stores only the SHA-256 of the token. After 5 failed logins the account locks for 15 minutes. Passwords use argon2id.
- `review_events` is append-only, **enforced in the database by a trigger**. This is stronger than the spec's "no UPDATE/DELETE grant", because it also binds the table owner.
- "Today" for date validation is the Asia/Dhaka calendar date.
- Files are served only through `GET /api/files/{id}` after a role + status check. Stored paths are relative to `CAPTURE_STORAGE_DIR`.
- Until M3, `CAPTURE_EXTRACTION_ENABLED=false` (the default): new records start as `draft` with `extraction_status=not_applicable`. When it is true they start `processing`/`pending` and a `jobs` row is queued.
- No patient-identifying columns anywhere (no names, reg. numbers, dates of birth).
- Every commit ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Login email typed with capitals or surrounding spaces** (`"  Dr.Rahman@AMCGH.test "`) should still sign in. Pinned in Task 5.
2. **A page that is not a JPEG** (a PNG, or an iPhone HEIC sent by some other client) should get 415 with a clear message and leave no record or file behind. Pinned in Task 8.
3. **A malformed study code** (lowercase, wrong length, the excluded letter `U`, a leading space) should get 422 and never become a patient row. Pinned in Task 8.
4. **A draft saved with wrongly typed values** (`"2.3"` as a string in a number field) should be saved so work isn't lost, show the error, and block submit with 422. Pinned in Task 9.
5. **A repeat-group item deleted while editing** (removing the second lesion) should appear in the audit trail as old value → `null`, not vanish silently. Pinned in Tasks 3 and 9.

## File Map

```
.gitignore                              repo-wide ignores (Task 1)
templates/*.yaml                        9 form templates (Task 4)
server/
  .python-version  pyproject.toml  alembic.ini  README.md
  migrations/env.py  migrations/script.py.mako  migrations/versions/0001_initial.py
  capture/
    config.py          Settings (CAPTURE_* env)                         Task 1
    clock.py           utcnow(), today() in Asia/Dhaka                  Task 5
    storage.py         save_page(), resolve_in_storage()                Task 8
    app_settings.py    load_app_settings()                              Task 7
    cli.py             `capture templates load`, `capture users …`      Task 10
    devserver.py       embedded-Postgres dev server + demo users        Task 10
    db/base.py         Base, make_sessionmaker()                        Task 1
    db/models.py       ORM models, Role/Status enums                    Task 2
    db/migrate.py      upgrade(database_url)                            Task 2
    formschema/model.py     TemplateDef (pydantic)                      Task 3
    formschema/validate.py  validate_values(), document_date_of()       Task 3
    formschema/diff.py      diff_values()                               Task 3
    formschema/store.py     load_templates(), active_templates(), …     Task 4
    auth/passwords.py  auth/sessions.py  auth/login.py                  Task 5
    workflow/rules.py  can_view(), can_edit(), next_status()            Task 6
    records/service.py create_record(), detail_for(), last_events()     Tasks 8–9
    api/app.py  api/deps.py  api/schemas.py  api/convert.py             Tasks 5–9
    api/routes_auth.py  routes_templates.py  routes_device.py
    api/routes_admin.py  routes_records.py  routes_files.py
  tests/
    constants.py  conftest.py  test_*.py
```

---

### Task 1: Server project, settings and a test PostgreSQL

**Files:**
- Create: `.gitignore`, `server/.python-version`, `server/pyproject.toml`, `server/capture/__init__.py`, `server/capture/config.py`, `server/capture/db/__init__.py`, `server/capture/db/base.py`
- Test: `server/tests/conftest.py`, `server/tests/test_foundation.py`

**Interfaces:**
- Produces: `capture.config.Settings` (fields `database_url: str`, `storage_dir: Path`, `session_hours: int = 12`, `cookie_secure: bool = True`, `extraction_enabled: bool = False`, `max_pages: int = 20`, `max_page_bytes: int = 15 MiB`); `capture.db.base.Base`; `capture.db.base.make_sessionmaker(database_url: str) -> sessionmaker[Session]` (`expire_on_commit=False`); pytest fixtures `pg_server`, `database_url` (session-scoped, SQLAlchemy URL string `postgresql+psycopg://…/capture_test`).

- [ ] **Step 1: Write the failing tests**

`server/tests/conftest.py`:

```python
import pgserver
import pytest
from sqlalchemy.engine import make_url


@pytest.fixture(scope="session")
def pg_server(tmp_path_factory):
    """A throwaway PostgreSQL 16 for the whole test session (stopped at exit)."""
    yield pgserver.get_server(tmp_path_factory.mktemp("pg"), cleanup_mode="stop")


@pytest.fixture(scope="session")
def database_url(pg_server) -> str:
    pg_server.psql("CREATE DATABASE capture_test;")
    url = make_url(pg_server.get_uri()).set(drivername="postgresql+psycopg", database="capture_test")
    return url.render_as_string(hide_password=False)
```

`server/tests/test_foundation.py`:

```python
from pathlib import Path

from sqlalchemy import text

from capture.config import Settings
from capture.db.base import make_sessionmaker


def test_settings_read_capture_env_vars(monkeypatch):
    monkeypatch.setenv("CAPTURE_STORAGE_DIR", "/data/files")
    monkeypatch.setenv("CAPTURE_EXTRACTION_ENABLED", "true")
    settings = Settings()
    assert settings.storage_dir == Path("/data/files")
    assert settings.extraction_enabled is True
    assert settings.session_hours == 12
    assert settings.cookie_secure is True
    assert settings.max_pages == 20
    assert settings.max_page_bytes == 15 * 1024 * 1024


def test_sessionmaker_talks_to_test_postgres(database_url):
    sessions = make_sessionmaker(database_url)
    with sessions() as s:
        assert s.scalar(text("select 1")) == 1
        assert s.scalar(text("show server_version")).startswith("16")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest -q`
Expected: FAIL. `uv` reports there is no `pyproject.toml` (or `ModuleNotFoundError: capture`).

- [ ] **Step 3: Create the project files**

`.gitignore` (repo root):

```gitignore
__pycache__/
*.pyc
.pytest_cache/
server/.venv/
server/.devdata/
server/storage/
server/.env
web/node_modules/
web/dist/
web/public/tesseract/
web/test-results/
web/playwright-report/
```

`server/.python-version`:

```
3.12
```

`server/pyproject.toml`:

```toml
[project]
name = "capture"
version = "0.1.0"
description = "AMCGH × NSU lung cancer study — photo-to-form data capture server"
requires-python = ">=3.12,<3.13"
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.30",
  "sqlalchemy>=2.0.30",
  "psycopg[binary]>=3.2",
  "alembic>=1.13",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "argon2-cffi>=23.1",
  "python-multipart>=0.0.9",
  "pyyaml>=6.0",
  "typer>=0.12",
  "tzdata>=2024.1",
]

[project.scripts]
capture = "capture.cli:app"

[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27", "pgserver>=0.1.4"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["capture"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`server/capture/__init__.py` and `server/capture/db/__init__.py`: empty files.

`server/capture/config.py`:

```python
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration from CAPTURE_* environment variables (or server/.env)."""

    model_config = SettingsConfigDict(env_prefix="CAPTURE_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://capture@localhost:5432/capture"
    storage_dir: Path = Path("storage")
    session_hours: int = 12
    cookie_secure: bool = True
    extraction_enabled: bool = False
    max_pages: int = 20
    max_page_bytes: int = 15 * 1024 * 1024
```

`server/capture/db/base.py`:

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_sessionmaker(database_url: str) -> sessionmaker[Session]:
    engine = create_engine(database_url, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
```

- [ ] **Step 4: Install and run the tests**

Run: `cd server && uv sync && uv run pytest -q`
Expected: `2 passed`. The first run downloads Python 3.12 and the pgserver wheel.

- [ ] **Step 5: Commit**

```bash
git add .gitignore server/.python-version server/pyproject.toml server/uv.lock server/capture server/tests
git commit -m "feat(server): project skeleton, settings and test PostgreSQL" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Database schema, migration and append-only audit log

**Files:**
- Create: `server/capture/db/models.py`, `server/capture/db/migrate.py`, `server/alembic.ini`, `server/migrations/env.py`, `server/migrations/script.py.mako`, `server/migrations/versions/0001_initial.py`, `server/tests/constants.py`
- Replace: `server/tests/conftest.py` (full version used by all later tasks)
- Test: `server/tests/test_schema.py`

**Interfaces:**
- Consumes: `Base`, `make_sessionmaker` (Task 1).
- Produces:
  - `capture.db.models`: `Role`, `Status`, `ExtractionStatus` (StrEnums), `HOSPITAL_ROLES`, `NSU_ROLES` (frozensets), models `User`, `UserSession`, `AppSettings`, `Patient`, `Template`, `Record` (JSON column attribute `field_values`; relationships `template`, `creator`, `files`), `RecordFile`, `Job`, `ReviewEvent` (relationship `actor`).
  - `capture.db.migrate.upgrade(database_url: str) -> None`.
  - Fixtures: `migrated_url`, `session_factory`, `db` (a clean sessionmaker), `settings`, `app`, `client`, `make_user(role, *, email=None, password="correct-horse-1", active=True) -> dict(id,email,password,role)`, `login_as(user, on_app=None) -> TestClient`, `templates`, `hospital_key`, `enable_phase3()`, `upload(client, *, template_key, study_code, fingerprint, pages) -> Response`. Fixtures that need later modules import them lazily inside the fixture body.
  - `tests/constants.py`: `REPO_DIR`, `TEMPLATES_DIR`, `FINGERPRINT = "K-B9FF"`, `STUDY_CODE = "AMH-N0ZDG4KM8V"`, `JPEG`.

- [ ] **Step 1: Write the failing tests**

`server/tests/constants.py`:

```python
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
TEMPLATES_DIR = REPO_DIR / "templates"
FINGERPRINT = "K-B9FF"
STUDY_CODE = "AMH-N0ZDG4KM8V"
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64 + b"\xff\xd9"
```

`server/tests/conftest.py` (replace the whole file):

```python
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
    def _upload(client, *, template_key="radiology_report", study_code=STUDY_CODE, fingerprint=FINGERPRINT, pages=(JPEG,)):
        meta = {"study_code": study_code, "template_key": template_key, "key_fingerprint": fingerprint}
        files = [("pages", (f"page-{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(pages)]
        return client.post("/api/records", data={"meta": json.dumps(meta)}, files=files)

    return _upload
```

`server/tests/test_schema.py`:

```python
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from capture.db import models
from capture.db.base import Base


def test_migration_matches_models(migrated_url):
    engine = create_engine(migrated_url)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    engine.dispose()
    assert diff == []


def test_settings_singleton_row_exists(db):
    with db() as s:
        row = s.get(models.AppSettings, 1)
    assert row is not None
    assert row.phase3_enabled is False
    assert row.expected_key_fingerprint is None


def _one_event(db) -> int:
    with db.begin() as s:
        user = models.User(name="U", email="u@example.test", password_hash="x", role="uploader", institution="AMCGH")
        template = models.Template(key="t", version=1, phase=1, kind="document", title="T", definition={})
        s.add_all([user, template, models.Patient(study_code="AMH-N0ZDG4KM8V")])
        s.flush()
        record = models.Record(
            study_code="AMH-N0ZDG4KM8V",
            template_id=template.id,
            status=models.Status.DRAFT,
            extraction_status=models.ExtractionStatus.NOT_APPLICABLE,
            created_by=user.id,
        )
        s.add(record)
        s.flush()
        event = models.ReviewEvent(record_id=record.id, actor_id=user.id, action="upload")
        s.add(event)
        s.flush()
        return event.id


def test_review_events_cannot_be_updated(db):
    event_id = _one_event(db)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin() as s:
            s.execute(text("UPDATE review_events SET comment = 'changed' WHERE id = :id"), {"id": event_id})


def test_review_events_cannot_be_deleted(db):
    event_id = _one_event(db)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin() as s:
            s.execute(text("DELETE FROM review_events WHERE id = :id"), {"id": event_id})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.db.models'`.

- [ ] **Step 3: Write the models**

`server/capture/db/models.py`:

```python
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from capture.db.base import Base


class Role(enum.StrEnum):
    UPLOADER = "uploader"
    HOSPITAL_DOCTOR = "hospital_doctor"
    NSU_REVIEWER = "nsu_reviewer"
    ADMIN = "admin"


class Status(enum.StrEnum):
    PROCESSING = "processing"
    QUARANTINED = "quarantined"
    DRAFT = "draft"
    PENDING_DOCTOR = "pending_doctor"
    PENDING_NSU = "pending_nsu"
    APPROVED = "approved"


class ExtractionStatus(enum.StrEnum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"


HOSPITAL_ROLES = frozenset({Role.UPLOADER, Role.HOSPITAL_DOCTOR})
NSU_ROLES = frozenset({Role.NSU_REVIEWER, Role.ADMIN})


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(32))
    institution: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # SHA-256 hex of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class AppSettings(Base):
    __tablename__ = "settings"
    __table_args__ = (CheckConstraint("id = 1", name="settings_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    expected_key_fingerprint: Mapped[str | None] = mapped_column(String(16))
    phase3_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class Patient(Base):
    __tablename__ = "patients"

    study_code: Mapped[str] = mapped_column(String(16), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Template(Base):
    __tablename__ = "templates"
    __table_args__ = (UniqueConstraint("key", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer)
    phase: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    definition: Mapped[dict] = mapped_column(JSONB)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Record(Base):
    __tablename__ = "records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    study_code: Mapped[str] = mapped_column(ForeignKey("patients.study_code"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id"))
    status: Mapped[str] = mapped_column(String(32), index=True)
    extraction_status: Mapped[str] = mapped_column(String(32))
    field_values: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    extraction: Mapped[dict | None] = mapped_column(JSONB)
    document_date: Mapped[date | None] = mapped_column(Date)
    quarantine: Mapped[dict | None] = mapped_column(JSONB)
    row_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    template: Mapped[Template] = relationship(lazy="selectin")
    creator: Mapped[User] = relationship(lazy="selectin")
    files: Mapped[list["RecordFile"]] = relationship(order_by="RecordFile.page_no")


class RecordFile(Base):
    __tablename__ = "record_files"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(BigInteger)
    page_no: Mapped[int | None] = mapped_column(Integer)
    dicom_meta: Mapped[dict | None] = mapped_column(JSONB)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", server_default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = _created_at()


class ReviewEvent(Base):
    __tablename__ = "review_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    actor_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(16))
    comment: Mapped[str | None] = mapped_column(Text)
    field_changes: Mapped[list | None] = mapped_column(JSONB)
    field_flags: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()

    actor: Mapped[User] = relationship(lazy="selectin")
```

- [ ] **Step 4: Write the Alembic setup and the initial migration**

`server/alembic.ini`:

```ini
[alembic]
script_location = %(here)s/migrations
```

`server/migrations/env.py`:

```python
from alembic import context
from sqlalchemy import create_engine, pool

from capture.config import Settings
from capture.db import models  # noqa: F401  (registers tables on Base.metadata)
from capture.db.base import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or Settings().database_url

engine = create_engine(url, poolclass=pool.NullPool)
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
```

`server/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`server/migrations/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("institution", sa.String(16), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("failed_logins", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
    )
    op.create_table(
        "sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("expected_key_fingerprint", sa.String(16), nullable=True),
        sa.Column("phase3_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.CheckConstraint("id = 1", name="settings_singleton"),
    )
    op.execute("INSERT INTO settings (id, phase3_enabled) VALUES (1, false)")
    op.create_table(
        "patients",
        sa.Column("study_code", sa.String(16), primary_key=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("definition", postgresql.JSONB(), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("key", "version"),
    )
    op.create_table(
        "records",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("study_code", sa.String(16), sa.ForeignKey("patients.study_code"), nullable=False),
        sa.Column("template_id", sa.Integer(), sa.ForeignKey("templates.id"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("extraction_status", sa.String(32), nullable=False),
        sa.Column("field_values", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("extraction", postgresql.JSONB(), nullable=True),
        sa.Column("document_date", sa.Date(), nullable=True),
        sa.Column("quarantine", postgresql.JSONB(), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_records_study_code", "records", ["study_code"])
    op.create_index("ix_records_status", "records", ["status"])
    op.create_table(
        "record_files",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=True),
        sa.Column("dicom_meta", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_record_files_record_id", "record_files", ["record_id"])
    op.create_index("ix_record_files_sha256", "record_files", ["sha256"])
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(64), nullable=True),
        _created_at(),
    )
    op.create_index("ix_jobs_record_id", "jobs", ["record_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])
    op.create_table(
        "review_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("record_id", UUID, sa.ForeignKey("records.id"), nullable=False),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("field_changes", postgresql.JSONB(), nullable=True),
        sa.Column("field_flags", postgresql.JSONB(), nullable=True),
        _created_at(),
    )
    op.create_index("ix_review_events_record_id", "review_events", ["record_id"])
    op.execute(
        """
        CREATE FUNCTION review_events_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'review_events is append-only';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER review_events_no_update_delete
        BEFORE UPDATE OR DELETE ON review_events
        FOR EACH ROW EXECUTE FUNCTION review_events_append_only();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS review_events_no_update_delete ON review_events")
    op.execute("DROP FUNCTION IF EXISTS review_events_append_only()")
    for table in ("review_events", "jobs", "record_files", "records", "templates", "patients", "settings", "sessions", "users"):
        op.drop_table(table)
```

`server/capture/db/migrate.py`:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config

SERVER_DIR = Path(__file__).resolve().parents[2]


def upgrade(database_url: str) -> None:
    """Apply all Alembic migrations to the given database."""
    config = Config(str(SERVER_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_DIR / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: `6 passed`. If `test_migration_matches_models` lists differences, fix whichever side is wrong so the model and migration agree. Do not weaken the test.

- [ ] **Step 6: Commit**

```bash
git add server/capture/db server/alembic.ini server/migrations server/tests
git commit -m "feat(server): schema, initial migration and append-only audit log" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Form templates — schema, validation and change diff

**Files:**
- Create: `server/capture/formschema/__init__.py` (empty), `server/capture/formschema/model.py`, `server/capture/formschema/validate.py`, `server/capture/formschema/diff.py`
- Test: `server/tests/test_formschema.py`

**Interfaces:**
- Produces:
  - `TemplateDef` (pydantic): `key`, `version`, `phase: 1|2|3`, `kind: "document"|"film_photo"|"dicom"`, `title`, `fields: list[AnyField]`, and the property `document_date_key -> str`.
  - Field classes `TextField`, `NumberField(unit,min,max)`, `DateField(document_date)`, `EnumField(options: list[Option])`, `BooleanField`, `GroupField(repeat, fields)`. All have `key`, `label`, `hint`, `required`, `source`.
  - `validate_values(tpl, values, today: date) -> list[{"path","message"}]`
  - `parse_date(v) -> date | None`
  - `document_date_of(tpl, values) -> date | None`
  - `diff_values(old, new) -> list[{"path","old","new"}]`, sorted by path.
  - Path format, used by the server and the web app: `lesions[0].long_axis_cm`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_formschema.py`:

```python
import copy
from datetime import date

import pytest
from pydantic import ValidationError

from capture.formschema.diff import diff_values
from capture.formschema.model import EnumField, TemplateDef
from capture.formschema.validate import document_date_of, validate_values

TODAY = date(2026, 10, 4)
RAW = {
    "key": "radiology_report",
    "version": 1,
    "phase": 1,
    "kind": "document",
    "title": "Radiology report",
    "fields": [
        {"key": "modality", "type": "enum", "required": True, "options": ["CT", "MRI"]},
        {"key": "study_date", "type": "date", "required": True, "document_date": True},
        {"key": "contrast", "type": "boolean"},
        {
            "key": "lesions",
            "type": "group",
            "repeat": True,
            "fields": [
                {"key": "lobe", "type": "enum", "options": [{"value": "RUL", "synonyms": ["right upper lobe"]}, {"value": "LUL"}]},
                {"key": "long_axis_cm", "type": "number", "unit": "cm", "min": 0.1, "max": 20},
            ],
        },
        {"key": "impression", "type": "text"},
    ],
}
TPL = TemplateDef.model_validate(RAW)
GOOD = {
    "modality": "CT",
    "study_date": "2026-09-01",
    "contrast": False,
    "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}],
    "impression": "mass",
}


def test_plain_string_options_become_option_objects():
    modality = TPL.fields[0]
    assert isinstance(modality, EnumField)
    assert [o.value for o in modality.options] == ["CT", "MRI"]
    assert modality.options[0].synonyms == []


def test_document_date_key():
    assert TPL.document_date_key == "study_date"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["fields"][1].pop("document_date"), "exactly one top-level date field"),
        (lambda r: r["fields"].append({"key": "followup", "type": "date", "document_date": True}), "exactly one top-level date field"),
        (lambda r: r["fields"].append({"key": "modality", "type": "text"}), "duplicate field key 'modality'"),
        (lambda r: r.update(colour="blue"), "Extra inputs are not permitted"),
        (lambda r: r["fields"].append({"key": "Bad Key", "type": "text"}), "String should match pattern"),
    ],
)
def test_invalid_templates_are_rejected(change, message):
    raw = copy.deepcopy(RAW)
    change(raw)
    with pytest.raises(ValidationError, match=message):
        TemplateDef.model_validate(raw)


def test_valid_values_have_no_errors():
    assert validate_values(TPL, GOOD, TODAY) == []


def test_empty_optional_values_are_fine():
    values = {"modality": "CT", "study_date": "2026-09-01", "lesions": [], "impression": ""}
    assert validate_values(TPL, values, TODAY) == []


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"study_date": "2026-09-01"}, {"path": "modality", "message": "required"}),
        (dict(GOOD, modality="PET"), {"path": "modality", "message": "must be one of: CT, MRI"}),
        (dict(GOOD, study_date="01/09/2026"), {"path": "study_date", "message": "must be a date (YYYY-MM-DD)"}),
        (dict(GOOD, study_date="2026-10-05"), {"path": "study_date", "message": "cannot be in the future"}),
        (dict(GOOD, contrast="yes"), {"path": "contrast", "message": "must be yes or no"}),
        (dict(GOOD, impression=5), {"path": "impression", "message": "must be text"}),
        (dict(GOOD, lesions=[{"long_axis_cm": "2.3"}]), {"path": "lesions[0].long_axis_cm", "message": "must be a number"}),
        (dict(GOOD, lesions=[{"long_axis_cm": True}]), {"path": "lesions[0].long_axis_cm", "message": "must be a number"}),
        (dict(GOOD, lesions=[{}, {"long_axis_cm": 25}]), {"path": "lesions[1].long_axis_cm", "message": "must be at most 20"}),
        (dict(GOOD, lesions=[{"long_axis_cm": 0.05}]), {"path": "lesions[0].long_axis_cm", "message": "must be at least 0.1"}),
        (dict(GOOD, lesions={"lobe": "RUL"}), {"path": "lesions", "message": "must be a list"}),
        (dict(GOOD, lesions=[{"lobe": "RUL", "size": 1}]), {"path": "lesions[0].size", "message": "unknown field"}),
        (dict(GOOD, weight=70), {"path": "weight", "message": "unknown field"}),
    ],
)
def test_value_errors(values, expected):
    assert expected in validate_values(TPL, values, TODAY)


def test_document_date_of():
    assert document_date_of(TPL, GOOD) == date(2026, 9, 1)
    assert document_date_of(TPL, {"study_date": "garbage"}) is None
    assert document_date_of(TPL, None) is None


def test_diff_reports_changed_added_and_removed_leaves():
    old = {"modality": "CT", "lesions": [{"lobe": "RUL"}, {"lobe": "LUL"}]}
    new = {"modality": "MRI", "lesions": [{"lobe": "RUL"}], "impression": "mass"}
    assert diff_values(old, new) == [
        {"path": "impression", "old": None, "new": "mass"},
        {"path": "lesions[1].lobe", "old": "LUL", "new": None},
        {"path": "modality", "old": "CT", "new": "MRI"},
    ]


def test_diff_of_identical_values_is_empty():
    assert diff_values(GOOD, copy.deepcopy(GOOD)) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_formschema.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.formschema'`.

- [ ] **Step 3: Implement the template model**

`server/capture/formschema/__init__.py`: empty file.

`server/capture/formschema/model.py`:

```python
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

KEY_PATTERN = r"^[a-z][a-z0-9_]*$"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Option(_Strict):
    value: str
    synonyms: list[str] = []


class _FieldBase(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    label: str | None = None
    hint: str | None = None
    required: bool = False
    source: Literal["dicom"] | None = None


class TextField(_FieldBase):
    type: Literal["text"]


class NumberField(_FieldBase):
    type: Literal["number"]
    unit: str | None = None
    min: float | None = None
    max: float | None = None


class DateField(_FieldBase):
    type: Literal["date"]
    document_date: bool = False


class EnumField(_FieldBase):
    type: Literal["enum"]
    options: list[Option] = Field(min_length=1)

    @field_validator("options", mode="before")
    @classmethod
    def _plain_strings_to_options(cls, value):
        return [o if isinstance(o, dict) else {"value": str(o)} for o in value]


class BooleanField(_FieldBase):
    type: Literal["boolean"]


class GroupField(_FieldBase):
    type: Literal["group"]
    repeat: bool = False
    fields: list["AnyField"] = Field(min_length=1)


AnyField = Annotated[
    Union[TextField, NumberField, DateField, EnumField, BooleanField, GroupField],
    Field(discriminator="type"),
]
GroupField.model_rebuild()


def _check_unique_keys(fields: list, where: str) -> None:
    seen: set[str] = set()
    for f in fields:
        if f.key in seen:
            raise ValueError(f"duplicate field key '{f.key}' in {where}")
        seen.add(f.key)
        if isinstance(f, GroupField):
            _check_unique_keys(f.fields, f.key)


class TemplateDef(_Strict):
    key: str = Field(pattern=KEY_PATTERN)
    version: int = Field(ge=1)
    phase: Literal[1, 2, 3]
    kind: Literal["document", "film_photo", "dicom"]
    title: str
    fields: list[AnyField] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_structure(self) -> "TemplateDef":
        _check_unique_keys(self.fields, "template")
        dates = [f for f in self.fields if isinstance(f, DateField) and f.document_date]
        if len(dates) != 1:
            raise ValueError("template needs exactly one top-level date field with document_date: true")
        return self

    @property
    def document_date_key(self) -> str:
        return next(f.key for f in self.fields if isinstance(f, DateField) and f.document_date)
```

- [ ] **Step 4: Implement validation and diff**

`server/capture/formschema/validate.py`:

```python
from datetime import date
from typing import Any

from capture.formschema.model import (
    BooleanField,
    DateField,
    EnumField,
    GroupField,
    NumberField,
    TemplateDef,
    TextField,
)


def validate_values(tpl: TemplateDef, values: Any, today: date) -> list[dict[str, str]]:
    """Every problem in `values`, as {"path": "lesions[0].long_axis_cm", "message": "..."}."""
    errors: list[dict[str, str]] = []
    _check_object(tpl.fields, values, "", errors, today)
    return errors


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def document_date_of(tpl: TemplateDef, values: Any) -> date | None:
    if not isinstance(values, dict):
        return None
    return parse_date(values.get(tpl.document_date_key))


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _check_object(fields: list, values: Any, prefix: str, errors: list, today: date) -> None:
    if not isinstance(values, dict):
        errors.append({"path": prefix or "$", "message": "must be an object"})
        return
    known = {f.key for f in fields}
    for key in values:
        if key not in known:
            errors.append({"path": _join(prefix, key), "message": "unknown field"})
    for f in fields:
        path = _join(prefix, f.key)
        value = values.get(f.key)
        if _is_empty(value):
            if f.required:
                errors.append({"path": path, "message": "required"})
            continue
        _check_value(f, value, path, errors, today)


def _check_value(f: Any, value: Any, path: str, errors: list, today: date) -> None:
    def error(message: str) -> None:
        errors.append({"path": path, "message": message})

    if isinstance(f, TextField):
        if not isinstance(value, str):
            error("must be text")
    elif isinstance(f, NumberField):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            error("must be a number")
            return
        if f.min is not None and value < f.min:
            error(f"must be at least {f.min:g}")
        if f.max is not None and value > f.max:
            error(f"must be at most {f.max:g}")
    elif isinstance(f, DateField):
        parsed = parse_date(value)
        if parsed is None:
            error("must be a date (YYYY-MM-DD)")
        elif parsed > today:
            error("cannot be in the future")
    elif isinstance(f, EnumField):
        allowed = [o.value for o in f.options]
        if value not in allowed:
            error("must be one of: " + ", ".join(allowed))
    elif isinstance(f, BooleanField):
        if not isinstance(value, bool):
            error("must be yes or no")
    elif isinstance(f, GroupField):
        if f.repeat:
            if not isinstance(value, list):
                error("must be a list")
                return
            for i, item in enumerate(value):
                _check_object(f.fields, item, f"{path}[{i}]", errors, today)
        else:
            _check_object(f.fields, value, path, errors, today)
```

`server/capture/formschema/diff.py`:

```python
from typing import Any


def flatten(value: Any, prefix: str = "") -> dict[str, Any]:
    """{"lesions": [{"lobe": "RUL"}]} -> {"lesions[0].lobe": "RUL"}"""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(flatten(item, f"{prefix}.{key}" if prefix else key))
        return out
    if isinstance(value, list):
        out = {}
        for i, item in enumerate(value):
            out.update(flatten(item, f"{prefix}[{i}]"))
        return out
    return {prefix: value}


def diff_values(old: Any, new: Any) -> list[dict[str, Any]]:
    """Leaf-level changes between two value trees; removed leaves have new=None."""
    before, after = flatten(old or {}), flatten(new or {})
    return [
        {"path": path, "old": before.get(path), "new": after.get(path)}
        for path in sorted(set(before) | set(after))
        if before.get(path) != after.get(path)
    ]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_formschema.py -q`
Expected: all pass (26 tests).

- [ ] **Step 6: Commit**

```bash
git add server/capture/formschema server/tests/test_formschema.py
git commit -m "feat(server): form template schema, value validation and audit diff" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Template store and the nine study templates

**Files:**
- Create: `server/capture/formschema/store.py`, and in `templates/`: `radiology_report.yaml`, `xray_film_photo.yaml`, `ct_mri_film_photo.yaml`, `dicom_series.yaml`, `pathology_molecular_report.yaml`, `lab_report.yaml`, `treatment_sheet.yaml`, `clinical_summary.yaml`, `outcome_followup.yaml`
- Test: `server/tests/test_store.py`

**Interfaces:**
- Consumes: `TemplateDef` (Task 3); `Template` model (Task 2).
- Produces:
  - `load_templates(session, directory: Path) -> list[str]`, which returns lines like `"radiology_report v1: created"` or `"… unchanged"` and raises `TemplateConflict` when a definition changes without a version bump.
  - `active_templates(session) -> list[Template]` (highest version per key, ordered by phase then key).
  - `get_active(session, key) -> Template | None`.
  - `template_def(t: Template) -> TemplateDef`.
  - `TemplateConflict`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_store.py`:

```python
import pytest
from sqlalchemy import func, select

from capture.db.models import Template
from capture.formschema.store import TemplateConflict, active_templates, get_active, load_templates
from constants import TEMPLATES_DIR

MINIMAL = """\
key: demo_form
version: {version}
phase: 1
kind: document
title: Demo form
fields:
  - {{key: seen_on, type: date, document_date: true}}
  - {{key: note, type: text, label: "{label}"}}
"""


def write(directory, version=1, label="Note"):
    (directory / "demo_form.yaml").write_text(MINIMAL.format(version=version, label=label), encoding="utf-8")


def test_load_creates_then_reports_unchanged(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        assert load_templates(s, tmp_path) == ["demo_form v1: created"]
    with db.begin() as s:
        assert load_templates(s, tmp_path) == ["demo_form v1: unchanged"]


def test_changing_a_template_without_bumping_version_fails(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        load_templates(s, tmp_path)
    write(tmp_path, label="Comment")
    with pytest.raises(TemplateConflict, match="without bumping"):
        with db.begin() as s:
            load_templates(s, tmp_path)


def test_new_version_becomes_active_and_old_is_kept(db, tmp_path):
    write(tmp_path)
    with db.begin() as s:
        load_templates(s, tmp_path)
    write(tmp_path, version=2, label="Comment")
    with db.begin() as s:
        load_templates(s, tmp_path)
        assert get_active(s, "demo_form").version == 2
        assert [t.version for t in active_templates(s)] == [2]
        assert s.scalar(select(func.count()).select_from(Template)) == 2


def test_repository_templates_are_valid(db):
    with db.begin() as s:
        load_templates(s, TEMPLATES_DIR)
        found = {(t.key, t.phase, t.kind) for t in active_templates(s)}
    assert found == {
        ("radiology_report", 1, "document"),
        ("xray_film_photo", 1, "film_photo"),
        ("ct_mri_film_photo", 1, "film_photo"),
        ("dicom_series", 1, "dicom"),
        ("pathology_molecular_report", 3, "document"),
        ("lab_report", 3, "document"),
        ("treatment_sheet", 3, "document"),
        ("clinical_summary", 3, "document"),
        ("outcome_followup", 3, "document"),
    }
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_store.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.formschema.store'`.

- [ ] **Step 3: Implement the store**

`server/capture/formschema/store.py`:

```python
import json
from pathlib import Path

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capture.db.models import Template
from capture.formschema.model import TemplateDef


class TemplateConflict(Exception):
    pass


def _canonical(definition: dict) -> str:
    return json.dumps(definition, sort_keys=True, separators=(",", ":"))


def load_templates(session: Session, directory: Path) -> list[str]:
    """Insert every *.yaml template not yet in the database; refuse silent edits."""
    report: list[str] = []
    for path in sorted(Path(directory).glob("*.yaml")):
        tpl = TemplateDef.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        definition = tpl.model_dump(mode="json", exclude_none=True)
        existing = session.scalar(select(Template).where(Template.key == tpl.key, Template.version == tpl.version))
        if existing is None:
            session.add(
                Template(
                    key=tpl.key,
                    version=tpl.version,
                    phase=tpl.phase,
                    kind=tpl.kind,
                    title=tpl.title,
                    definition=definition,
                )
            )
            report.append(f"{tpl.key} v{tpl.version}: created")
        elif _canonical(existing.definition) != _canonical(definition):
            raise TemplateConflict(f"{path.name}: {tpl.key} v{tpl.version} was changed without bumping 'version'")
        else:
            report.append(f"{tpl.key} v{tpl.version}: unchanged")
    session.flush()
    return report


def active_templates(session: Session) -> list[Template]:
    latest = select(Template.key, func.max(Template.version).label("version")).group_by(Template.key).subquery()
    stmt = (
        select(Template)
        .join(latest, (Template.key == latest.c.key) & (Template.version == latest.c.version))
        .order_by(Template.phase, Template.key)
    )
    return list(session.scalars(stmt))


def get_active(session: Session, key: str) -> Template | None:
    return session.scalar(select(Template).where(Template.key == key).order_by(Template.version.desc()).limit(1))


def template_def(template: Template) -> TemplateDef:
    return TemplateDef.model_validate(template.definition)
```

- [ ] **Step 4: Write the nine templates**

These are the draft field lists from spec §6.2. Clinicians review them before the pilot (spec §12, item 1).

`templates/radiology_report.yaml`:

```yaml
key: radiology_report
version: 1
phase: 1
kind: document
title: Radiology report (CT / MRI / X-ray / PET-CT)
fields:
  - {key: modality, label: Modality, type: enum, required: true, options: [CT, MRI, X-ray, PET-CT]}
  - {key: study_date, label: Study date, type: date, required: true, document_date: true}
  - {key: contrast, label: Contrast given, type: boolean}
  - key: lesions
    label: Lesion
    type: group
    repeat: true
    fields:
      - key: lobe
        label: Lobe
        type: enum
        options:
          - {value: RUL, synonyms: [right upper lobe, rt upper lobe]}
          - {value: RML, synonyms: [right middle lobe, rt middle lobe]}
          - {value: RLL, synonyms: [right lower lobe, rt lower lobe]}
          - {value: LUL, synonyms: [left upper lobe, lt upper lobe]}
          - {value: LLL, synonyms: [left lower lobe, lt lower lobe]}
          - {value: other}
      - {key: long_axis_cm, label: Long axis, type: number, unit: cm, min: 0.1, max: 20}
      - {key: short_axis_cm, label: Short axis, type: number, unit: cm, min: 0.1, max: 20}
      - {key: description, label: Description, type: text, hint: "e.g. spiculated, cavitating, ground-glass"}
  - {key: lymph_nodes, label: Lymph nodes, type: text}
  - {key: metastasis_sites, label: Metastasis sites, type: text}
  - {key: pleural_effusion, label: Pleural effusion, type: enum, options: [none, left, right, bilateral]}
  - {key: reported_change, label: Change vs previous study, type: enum, options: [new, increased, decreased, stable, not stated]}
  - {key: impression, label: Impression, type: text}
```

`templates/xray_film_photo.yaml`:

```yaml
key: xray_film_photo
version: 1
phase: 1
kind: film_photo
title: Chest X-ray (photo of film or screen)
fields:
  - {key: study_date, label: X-ray date, type: date, required: true, document_date: true}
  - {key: view, label: View, type: enum, required: true, options: [PA, AP, lateral, other]}
  - {key: side_marker, label: Side marker, type: enum, options: [L, R, none visible]}
  - {key: capture_source, label: Photographed from, type: enum, required: true, options: [lightbox film, monitor screen, printout]}
```

`templates/ct_mri_film_photo.yaml`:

```yaml
key: ct_mri_film_photo
version: 1
phase: 1
kind: film_photo
title: CT / MRI film (photo)
fields:
  - {key: modality, label: Modality, type: enum, required: true, options: [CT, MRI]}
  - {key: study_date, label: Study date, type: date, required: true, document_date: true}
  - {key: window, label: Window, type: enum, options: [lung, mediastinal, other, unknown]}
  - {key: slice_label, label: Slice / image label, type: text}
  - {key: capture_source, label: Photographed from, type: enum, required: true, options: [lightbox film, monitor screen, printout]}
```

`templates/dicom_series.yaml`:

```yaml
key: dicom_series
version: 1
phase: 1
kind: dicom
title: DICOM series (CT / MRI / X-ray files)
fields:
  - {key: modality, label: Modality, type: text, source: dicom}
  - {key: study_date, label: Study date, type: date, required: true, document_date: true, source: dicom}
  - {key: body_part, label: Body part, type: text, source: dicom}
  - {key: series_description, label: Series description, type: text, source: dicom}
  - {key: pixel_spacing, label: Pixel spacing, type: text, source: dicom}
  - {key: slice_thickness, label: Slice thickness, type: number, unit: mm, source: dicom}
  - {key: image_count, label: Number of images, type: number, source: dicom}
  - {key: rows, label: Rows, type: number, source: dicom}
  - {key: columns, label: Columns, type: number, source: dicom}
```

`templates/pathology_molecular_report.yaml`:

```yaml
key: pathology_molecular_report
version: 1
phase: 3
kind: document
title: Pathology / molecular report
fields:
  - {key: report_date, label: Report date, type: date, required: true, document_date: true}
  - {key: specimen, label: Specimen, type: enum, options: [biopsy, resection, cytology, other]}
  - {key: histological_subtype, label: Histological subtype, type: enum, options: [adenocarcinoma, squamous cell carcinoma, small cell carcinoma, large cell carcinoma, NSCLC-NOS, other]}
  - {key: grade, label: Grade, type: enum, options: [G1, G2, G3, G4, not stated]}
  - {key: egfr, label: EGFR, type: enum, options: [mutated, wild-type, not tested]}
  - {key: egfr_variant, label: EGFR variant, type: text}
  - {key: alk, label: ALK, type: enum, options: [rearranged, not rearranged, not tested]}
  - {key: ros1, label: ROS1, type: enum, options: [rearranged, not rearranged, not tested]}
  - {key: kras, label: KRAS, type: enum, options: [mutated, wild-type, not tested]}
  - {key: kras_variant, label: KRAS variant, type: text, hint: "e.g. G12C"}
  - {key: pdl1_tps_percent, label: PD-L1 TPS, type: number, unit: "%", min: 0, max: 100}
  - {key: pdl1_assay, label: PD-L1 assay, type: text}
```

`templates/lab_report.yaml`:

```yaml
key: lab_report
version: 1
phase: 3
kind: document
title: Laboratory report
fields:
  - {key: report_date, label: Report date, type: date, required: true, document_date: true}
  - key: results
    label: Result
    type: group
    repeat: true
    fields:
      - {key: analyte, label: Test, type: enum, required: true, options: [CEA, LDH, Albumin, Hemoglobin, WBC, Platelets, Neutrophils, Lymphocytes, Other]}
      - {key: other_name, label: Other test name, type: text}
      - {key: value, label: Value, type: number, required: true}
      - {key: unit_as_printed, label: Unit (as printed), type: text}
      - {key: reference_range, label: Reference range, type: text}
```

`templates/treatment_sheet.yaml`:

```yaml
key: treatment_sheet
version: 1
phase: 3
kind: document
title: Treatment sheet
fields:
  - {key: sheet_date, label: Sheet date, type: date, required: true, document_date: true}
  - key: treatments
    label: Treatment
    type: group
    repeat: true
    fields:
      - {key: modality, label: Type, type: enum, required: true, options: [chemotherapy, immunotherapy, targeted therapy, radiotherapy, surgery]}
      - {key: regimen_drugs, label: Regimen / drugs, type: text}
      - {key: cycle_number, label: Cycle, type: number, min: 1, max: 100}
      - {key: dose, label: Dose, type: text}
      - {key: dose_modified, label: Dose modified, type: boolean}
      - {key: dose_modification_reason, label: Reason for dose change, type: text}
      - {key: start_date, label: Start date, type: date}
  - {key: response, label: Response, type: enum, options: [CR, PR, SD, PD, not assessed]}
  - key: adverse_events
    label: Adverse event
    type: group
    repeat: true
    fields:
      - {key: event, label: Event, type: text, required: true}
      - {key: ctcae_grade, label: CTCAE grade, type: enum, options: ["1", "2", "3", "4", "5"]}
```

`templates/clinical_summary.yaml`:

```yaml
key: clinical_summary
version: 1
phase: 3
kind: document
title: Clinical summary
fields:
  - {key: summary_date, label: Summary date, type: date, required: true, document_date: true}
  - {key: age_years, label: Age, type: number, unit: years, min: 0, max: 120}
  - {key: sex, label: Sex, type: enum, options: [male, female]}
  - {key: smoking_status, label: Smoking, type: enum, options: [never, former, current, unknown]}
  - {key: pack_years, label: Pack-years, type: number, min: 0, max: 300}
  - {key: ecog, label: ECOG, type: enum, options: ["0", "1", "2", "3", "4"]}
  - {key: comorbidities, label: Comorbidities, type: text}
  - {key: presenting_symptoms, label: Presenting symptoms, type: text}
```

`templates/outcome_followup.yaml`:

```yaml
key: outcome_followup
version: 1
phase: 3
kind: document
title: Outcome follow-up
fields:
  - {key: followup_date, label: Follow-up date, type: date, required: true, document_date: true}
  - {key: vital_status, label: Vital status, type: enum, required: true, options: [alive, dead, lost to follow-up]}
  - {key: progression, label: Progression, type: boolean}
  - {key: progression_date, label: Progression date, type: date}
  - {key: recurrence, label: Recurrence, type: boolean}
  - {key: recurrence_date, label: Recurrence date, type: date}
  - {key: date_of_death, label: Date of death, type: date}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_store.py -q`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add server/capture/formschema/store.py server/tests/test_store.py templates
git commit -m "feat(server): template loader and the nine study form templates" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Logins, sessions and the API app

**Files:**
- Create: `server/capture/clock.py`, `server/capture/auth/__init__.py` (empty), `server/capture/auth/passwords.py`, `server/capture/auth/sessions.py`, `server/capture/auth/login.py`, `server/capture/api/__init__.py` (empty), `server/capture/api/deps.py`, `server/capture/api/schemas.py`, `server/capture/api/routes_auth.py`, `server/capture/api/app.py`
- Test: `server/tests/test_auth.py`

**Interfaces:**
- Consumes: `User`, `UserSession` (Task 2); `Settings`, `make_sessionmaker` (Task 1).
- Produces:
  - `capture.clock.utcnow() -> datetime` (aware UTC) and `capture.clock.today() -> date` (Asia/Dhaka).
  - `hash_password(p) -> str`, `verify_password(hash, p) -> bool`.
  - `create_session(db, user_id, now, hours) -> token`, `user_for_token(db, token, now) -> User | None`, `revoke_token(db, token)`, `revoke_all_for_user(db, user_id)`.
  - `authenticate(db, email, password, now) -> User | None`, which raises `AccountLocked`.
  - Deps: `SESSION_COOKIE = "capture_session"`, `get_db`, `get_settings`, `current_user`, `require_roles(*roles)`.
  - `create_app(settings=None, session_factory=None) -> FastAPI` with the module-level tuple `ROUTERS`. Every router is mounted under `/api`; `GET /api/health` returns `{"ok": true}`.
  - `schemas.UserOut`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_auth.py`:

```python
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from capture.clock import utcnow
from capture.db.models import User, UserSession


def login(client, email, password):
    return client.post("/api/auth/login", json={"email": email, "password": password})


def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_login_sets_strict_httponly_cookie_and_me_works(client, make_user):
    user = make_user("hospital_doctor")
    r = login(client, user["email"], user["password"])
    assert r.status_code == 200
    assert r.json()["role"] == "hospital_doctor"
    assert r.json()["institution"] == "AMCGH"
    cookie = r.headers["set-cookie"].lower()
    assert "capture_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert client.get("/api/me").json()["email"] == user["email"]


def test_login_ignores_email_case_and_spaces(client, make_user):
    user = make_user(email="dr.rahman@amcgh.test")
    assert login(client, "  Dr.Rahman@AMCGH.test ", user["password"]).status_code == 200


def test_wrong_password_and_unknown_email_get_the_same_answer(client, make_user):
    user = make_user()
    a = login(client, user["email"], "nope")
    b = login(client, "ghost@example.test", "nope")
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json() == {"detail": "Invalid email or password"}


def test_five_failures_lock_the_account(client, make_user):
    user = make_user()
    for _ in range(5):
        assert login(client, user["email"], "wrong").status_code == 401
    r = login(client, user["email"], user["password"])
    assert r.status_code == 429
    assert "locked" in r.json()["detail"]


def test_success_resets_failure_count(client, make_user, db):
    user = make_user()
    for _ in range(4):
        login(client, user["email"], "wrong")
    assert login(client, user["email"], user["password"]).status_code == 200
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_auth.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.clock'`.

- [ ] **Step 3: Implement clock, passwords, sessions and login**

`server/capture/clock.py`:

```python
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

DHAKA = ZoneInfo("Asia/Dhaka")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def today() -> date:
    """The current calendar date at the hospital."""
    return datetime.now(DHAKA).date()
```

`server/capture/auth/__init__.py`: empty file.

`server/capture/auth/passwords.py`:

```python
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

_hasher = PasswordHasher()  # argon2id with library defaults


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False
```

`server/capture/auth/sessions.py`:

```python
import hashlib
import secrets
from datetime import datetime, timedelta

from sqlalchemy import update
from sqlalchemy.orm import Session

from capture.db.models import User, UserSession


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user_id: int, now: datetime, hours: int) -> str:
    """Store a new session and return the raw token for the cookie (only its hash is stored)."""
    token = secrets.token_urlsafe(32)
    db.add(UserSession(id=_digest(token), user_id=user_id, expires_at=now + timedelta(hours=hours)))
    return token


def user_for_token(db: Session, token: str, now: datetime) -> User | None:
    row = db.get(UserSession, _digest(token))
    if row is None or row.revoked or row.expires_at <= now:
        return None
    user = db.get(User, row.user_id)
    return user if user is not None and user.active else None


def revoke_token(db: Session, token: str) -> None:
    row = db.get(UserSession, _digest(token))
    if row is not None:
        row.revoked = True


def revoke_all_for_user(db: Session, user_id: int) -> None:
    db.execute(update(UserSession).where(UserSession.user_id == user_id).values(revoked=True))
```

`server/capture/auth/login.py`:

```python
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from capture.auth.passwords import hash_password, verify_password
from capture.db.models import User

LOCK_AFTER_FAILURES = 5
LOCK_MINUTES = 15
_dummy_hash: str | None = None


class AccountLocked(Exception):
    def __init__(self, until: datetime) -> None:
        super().__init__(f"locked until {until.isoformat()}")
        self.until = until


def _spend_time_like_a_real_check(password: str) -> None:
    """Hash anyway for unknown emails so response time does not reveal which emails exist."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    verify_password(_dummy_hash, password)


def authenticate(db: Session, email: str, password: str, now: datetime) -> User | None:
    user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if user is None or not user.active:
        _spend_time_like_a_real_check(password)
        return None
    if user.locked_until is not None and user.locked_until > now:
        raise AccountLocked(user.locked_until)
    if not verify_password(user.password_hash, password):
        user.failed_logins += 1
        if user.failed_logins >= LOCK_AFTER_FAILURES:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_logins = 0
        return None
    user.failed_logins = 0
    user.locked_until = None
    return user
```

- [ ] **Step 4: Implement the API dependencies, schemas, routes and app**

`server/capture/api/__init__.py`: empty file.

`server/capture/api/deps.py`:

```python
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from capture.auth.sessions import user_for_token
from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import User

SESSION_COOKIE = "capture_session"


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.sessionmaker() as session:
        yield session


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    user = user_for_token(db, token, utcnow()) if token else None
    if user is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return user


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="Not allowed for your role")
        return user

    return dependency
```

`server/capture/api/schemas.py`:

```python
import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    role: str
    institution: str
```

`server/capture/api/routes_auth.py`:

```python
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from capture.api.deps import SESSION_COOKIE, current_user, get_db, get_settings
from capture.api.schemas import LoginIn, UserOut
from capture.auth.login import AccountLocked, authenticate
from capture.auth.sessions import create_session, revoke_token
from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import User

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=UserOut)
def login(
    body: LoginIn,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> UserOut:
    now = utcnow()
    try:
        user = authenticate(db, body.email, body.password, now)
    except AccountLocked:
        db.commit()
        raise HTTPException(status_code=429, detail="Account locked for 15 minutes after 5 failed attempts") from None
    if user is None:
        db.commit()  # keep the failed-login counter
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_session(db, user.id, now, settings.session_hours)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_hours * 3600,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return UserOut.model_validate(user)


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        revoke_token(db, token)
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user)
```

`server/capture/api/app.py`:

```python
from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from capture.api import routes_auth
from capture.config import Settings
from capture.db.base import make_sessionmaker

ROUTERS = (routes_auth.router,)


def create_app(settings: Settings | None = None, session_factory: sessionmaker | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="AMCGH Data Capture", docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.sessionmaker = session_factory or make_sessionmaker(settings.database_url)

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    for router in ROUTERS:
        app.include_router(router, prefix="/api")
    return app
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all tests pass (12 new auth tests plus the earlier ones).

- [ ] **Step 6: Commit**

```bash
git add server/capture/clock.py server/capture/auth server/capture/api server/tests/test_auth.py
git commit -m "feat(server): argon2 logins, hashed server-side sessions, lockout" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Workflow rules (who may see, edit and move a record)

**Files:**
- Create: `server/capture/workflow/__init__.py` (empty), `server/capture/workflow/rules.py`
- Test: `server/tests/test_rules.py`

**Interfaces:**
- Consumes: `Role`, `Status`, `HOSPITAL_ROLES` (Task 2).
- Produces:
  - `Action` (StrEnum: `submit`, `approve`, `return`, `reopen`).
  - `TransitionError(message, http_status=409)` with `.message` and `.http_status`.
  - `can_view(role, status) -> bool`.
  - `can_edit(role, status) -> bool`.
  - `next_status(*, action, role, status, actor_id, creator_id, comment, has_errors) -> Status`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_rules.py`:

```python
import pytest

from capture.db.models import Role, Status
from capture.workflow.rules import Action, TransitionError, can_edit, can_view, next_status


@pytest.mark.parametrize("role", [Role.UPLOADER, Role.HOSPITAL_DOCTOR])
@pytest.mark.parametrize("status", list(Status))
def test_hospital_roles_see_every_status(role, status):
    assert can_view(role, status)


@pytest.mark.parametrize("role", [Role.NSU_REVIEWER, Role.ADMIN])
@pytest.mark.parametrize("status", list(Status))
def test_nsu_roles_only_see_records_past_the_doctor(role, status):
    assert can_view(role, status) == (status in (Status.PENDING_NSU, Status.APPROVED))


@pytest.mark.parametrize(
    ("role", "status", "expected"),
    [
        (Role.UPLOADER, Status.DRAFT, True),
        (Role.UPLOADER, Status.PENDING_DOCTOR, False),
        (Role.HOSPITAL_DOCTOR, Status.DRAFT, True),
        (Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, True),
        (Role.HOSPITAL_DOCTOR, Status.PENDING_NSU, False),
        (Role.NSU_REVIEWER, Status.PENDING_NSU, False),
        (Role.ADMIN, Status.APPROVED, False),
    ],
)
def test_can_edit(role, status, expected):
    assert can_edit(role, status) is expected


def move(action, role, status, *, actor=1, creator=2, comment=None, errors=False):
    return next_status(
        action=action, role=role, status=status, actor_id=actor, creator_id=creator, comment=comment, has_errors=errors
    )


def rejected(*args, **kwargs) -> TransitionError:
    with pytest.raises(TransitionError) as info:
        move(*args, **kwargs)
    return info.value


def test_submit_draft():
    assert move(Action.SUBMIT, Role.UPLOADER, Status.DRAFT) == Status.PENDING_DOCTOR


def test_submit_with_errors_is_422():
    e = rejected(Action.SUBMIT, Role.UPLOADER, Status.DRAFT, errors=True)
    assert e.http_status == 422
    assert e.message == "Fix the highlighted fields before submitting"


def test_nsu_cannot_submit():
    assert rejected(Action.SUBMIT, Role.NSU_REVIEWER, Status.DRAFT).http_status == 403


def test_submit_only_from_draft():
    assert rejected(Action.SUBMIT, Role.UPLOADER, Status.PENDING_DOCTOR).http_status == 409


def test_doctor_approves():
    assert move(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR) == Status.PENDING_NSU


def test_four_eyes_rule():
    e = rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, actor=7, creator=7)
    assert e.http_status == 403
    assert "another doctor" in e.message


def test_uploader_cannot_approve():
    assert rejected(Action.APPROVE, Role.UPLOADER, Status.PENDING_DOCTOR).http_status == 403


def test_doctor_cannot_approve_with_errors():
    assert rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, errors=True).http_status == 422


def test_nsu_approves():
    assert move(Action.APPROVE, Role.NSU_REVIEWER, Status.PENDING_NSU) == Status.APPROVED


@pytest.mark.parametrize("role", [Role.ADMIN, Role.HOSPITAL_DOCTOR])
def test_only_nsu_reviewer_approves_nsu_stage(role):
    assert rejected(Action.APPROVE, role, Status.PENDING_NSU).http_status == 403


def test_approve_draft_is_409():
    assert rejected(Action.APPROVE, Role.HOSPITAL_DOCTOR, Status.DRAFT).http_status == 409


@pytest.mark.parametrize("comment", [None, "", "   "])
def test_return_needs_comment(comment):
    assert rejected(Action.RETURN, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, comment=comment).http_status == 422


def test_doctor_returns():
    assert move(Action.RETURN, Role.HOSPITAL_DOCTOR, Status.PENDING_DOCTOR, comment="date wrong") == Status.DRAFT


def test_nsu_returns():
    assert move(Action.RETURN, Role.NSU_REVIEWER, Status.PENDING_NSU, comment="unclear") == Status.DRAFT


def test_uploader_cannot_return():
    assert rejected(Action.RETURN, Role.UPLOADER, Status.PENDING_DOCTOR, comment="x").http_status == 403


def test_admin_reopens():
    assert move(Action.REOPEN, Role.ADMIN, Status.APPROVED, comment="wrong lobe") == Status.DRAFT


def test_reopen_needs_admin():
    assert rejected(Action.REOPEN, Role.NSU_REVIEWER, Status.APPROVED, comment="x").http_status == 403


def test_reopen_needs_reason():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.APPROVED).http_status == 422


def test_reopen_only_approved():
    assert rejected(Action.REOPEN, Role.ADMIN, Status.PENDING_NSU, comment="x").http_status == 409
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.workflow'`.

- [ ] **Step 3: Implement the rules**

`server/capture/workflow/__init__.py`: empty file.

`server/capture/workflow/rules.py`:

```python
import enum

from capture.db.models import HOSPITAL_ROLES, Role, Status


class Action(enum.StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    RETURN = "return"
    REOPEN = "reopen"


class TransitionError(Exception):
    def __init__(self, message: str, http_status: int = 409) -> None:
        super().__init__(message)
        self.message = message
        self.http_status = http_status


NSU_VISIBLE = frozenset({Status.PENDING_NSU, Status.APPROVED})


def can_view(role: str, status: str) -> bool:
    """Hospital staff see everything; NSU only sees records a hospital doctor has approved."""
    return role in HOSPITAL_ROLES or status in NSU_VISIBLE


def can_edit(role: str, status: str) -> bool:
    if role == Role.UPLOADER:
        return status == Status.DRAFT
    if role == Role.HOSPITAL_DOCTOR:
        return status in (Status.DRAFT, Status.PENDING_DOCTOR)
    return False


def next_status(
    *,
    action: str,
    role: str,
    status: str,
    actor_id: int,
    creator_id: int,
    comment: str | None,
    has_errors: bool,
) -> Status:
    has_comment = bool(comment and comment.strip())
    if action == Action.SUBMIT:
        if role not in HOSPITAL_ROLES:
            raise TransitionError("Only hospital staff can submit records", 403)
        if status != Status.DRAFT:
            raise TransitionError("Only drafts can be submitted")
        if has_errors:
            raise TransitionError("Fix the highlighted fields before submitting", 422)
        return Status.PENDING_DOCTOR
    if action == Action.APPROVE:
        if status == Status.PENDING_DOCTOR:
            if role != Role.HOSPITAL_DOCTOR:
                raise TransitionError("Only a hospital doctor can approve at this stage", 403)
            if actor_id == creator_id:
                raise TransitionError("You uploaded this record, so another doctor must approve it", 403)
            if has_errors:
                raise TransitionError("Fix the highlighted fields before approving", 422)
            return Status.PENDING_NSU
        if status == Status.PENDING_NSU:
            if role != Role.NSU_REVIEWER:
                raise TransitionError("Only an NSU reviewer can approve at this stage", 403)
            return Status.APPROVED
        raise TransitionError("This record is not waiting for approval")
    if action == Action.RETURN:
        if not has_comment:
            raise TransitionError("A comment is required when returning a record", 422)
        doctor_stage = status == Status.PENDING_DOCTOR and role == Role.HOSPITAL_DOCTOR
        nsu_stage = status == Status.PENDING_NSU and role == Role.NSU_REVIEWER
        if doctor_stage or nsu_stage:
            return Status.DRAFT
        raise TransitionError("You cannot return this record at this stage", 403)
    if action == Action.REOPEN:
        if role != Role.ADMIN:
            raise TransitionError("Only an admin can reopen records", 403)
        if status != Status.APPROVED:
            raise TransitionError("Only approved records can be reopened")
        if not has_comment:
            raise TransitionError("A reason is required to reopen a record", 422)
        return Status.DRAFT
    raise TransitionError(f"Unknown action: {action}", 422)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_rules.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add server/capture/workflow server/tests/test_rules.py
git commit -m "feat(server): record visibility, editing and approval rules" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Templates list, device key registration and admin settings

**Files:**
- Create: `server/capture/app_settings.py`, `server/capture/api/convert.py`, `server/capture/api/routes_templates.py`, `server/capture/api/routes_device.py`, `server/capture/api/routes_admin.py`
- Modify: `server/capture/api/schemas.py` (append), `server/capture/api/app.py` (router list)
- Test: `server/tests/test_settings_routes.py`

**Interfaces:**
- Consumes: `active_templates` (Task 4); `current_user`, `require_roles`, `get_db` (Task 5); `AppSettings`, `Role` (Task 2).
- Produces:
  - `load_app_settings(db, *, for_update=False) -> AppSettings`.
  - `convert.template_out(t: Template, phase3_enabled: bool) -> TemplateOut`.
  - Schemas `TemplateOut`, `FingerprintIn`, `FingerprintOut`, `SettingsIn`, `SettingsOut`.
  - Endpoints:
    - `GET /api/templates` → `[TemplateOut]`, where `locked = phase == 3 and not phase3_enabled`.
    - `GET /api/device/fingerprint` → `{"expected": str|null, "status": null}` (hospital roles).
    - `POST /api/device/fingerprint {fingerprint}` → `{"expected", "status": "set"|"match"}` or 409 (hospital_doctor only).
    - `GET`/`PUT /api/admin/settings` and `DELETE /api/admin/settings/fingerprint` (admin only).

- [ ] **Step 1: Write the failing tests**

`server/tests/test_settings_routes.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_settings_routes.py -q`
Expected: FAIL. `/api/templates` returns 404 instead of 401, and the other tests fail the same way.

- [ ] **Step 3: Add the schemas, settings helper and converters**

Append to `server/capture/api/schemas.py`:

```python


class TemplateOut(BaseModel):
    key: str
    version: int
    phase: int
    kind: str
    title: str
    definition: dict[str, Any]
    locked: bool


class FingerprintIn(BaseModel):
    fingerprint: str = Field(pattern=r"^K-[0-9A-F]{4}$")


class FingerprintOut(BaseModel):
    expected: str | None
    status: Literal["set", "match"] | None = None


class SettingsIn(BaseModel):
    phase3_enabled: bool


class SettingsOut(BaseModel):
    phase3_enabled: bool
    expected_key_fingerprint: str | None
```

`server/capture/app_settings.py`:

```python
from sqlalchemy.orm import Session

from capture.db.models import AppSettings


def load_app_settings(db: Session, *, for_update: bool = False) -> AppSettings:
    """The single settings row (id=1) created by the initial migration."""
    return db.get(AppSettings, 1, with_for_update=True if for_update else None)
```

`server/capture/api/convert.py`:

```python
from capture.api.schemas import TemplateOut
from capture.db.models import Template


def template_out(template: Template, phase3_enabled: bool) -> TemplateOut:
    return TemplateOut(
        key=template.key,
        version=template.version,
        phase=template.phase,
        kind=template.kind,
        title=template.title,
        definition=template.definition,
        locked=template.phase == 3 and not phase3_enabled,
    )
```

- [ ] **Step 4: Add the routes**

`server/capture/api/routes_templates.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from capture.api.convert import template_out
from capture.api.deps import current_user, get_db
from capture.api.schemas import TemplateOut
from capture.app_settings import load_app_settings
from capture.db.models import User
from capture.formschema.store import active_templates

router = APIRouter(tags=["templates"])


@router.get("/templates", response_model=list[TemplateOut])
def list_templates(_: User = Depends(current_user), db: Session = Depends(get_db)) -> list[TemplateOut]:
    phase3_enabled = load_app_settings(db).phase3_enabled
    return [template_out(t, phase3_enabled) for t in active_templates(db)]
```

`server/capture/api/routes_device.py`:

```python
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from capture.api.deps import get_db, require_roles
from capture.api.schemas import FingerprintIn, FingerprintOut
from capture.app_settings import load_app_settings
from capture.db.models import Role, User

router = APIRouter(prefix="/device", tags=["device"])
audit = logging.getLogger("capture.audit")


@router.get("/fingerprint", response_model=FingerprintOut)
def get_fingerprint(
    _: User = Depends(require_roles(Role.UPLOADER, Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
) -> FingerprintOut:
    return FingerprintOut(expected=load_app_settings(db).expected_key_fingerprint)


@router.post("/fingerprint", response_model=FingerprintOut)
def register_fingerprint(
    body: FingerprintIn,
    user: User = Depends(require_roles(Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
) -> FingerprintOut:
    row = load_app_settings(db, for_update=True)
    if row.expected_key_fingerprint is None:
        row.expected_key_fingerprint = body.fingerprint
        db.commit()
        audit.warning("hospital key fingerprint %s registered by user %s", body.fingerprint, user.id)
        return FingerprintOut(expected=body.fingerprint, status="set")
    if row.expected_key_fingerprint == body.fingerprint:
        return FingerprintOut(expected=body.fingerprint, status="match")
    raise HTTPException(status_code=409, detail="This key doesn't match the hospital key already registered")
```

`server/capture/api/routes_admin.py`:

```python
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from capture.api.deps import get_db, require_roles
from capture.api.schemas import SettingsIn, SettingsOut
from capture.app_settings import load_app_settings
from capture.db.models import AppSettings, Role, User

router = APIRouter(prefix="/admin", tags=["admin"])
audit = logging.getLogger("capture.audit")
admin_only = require_roles(Role.ADMIN)


def _out(row: AppSettings) -> SettingsOut:
    return SettingsOut(phase3_enabled=row.phase3_enabled, expected_key_fingerprint=row.expected_key_fingerprint)


@router.get("/settings", response_model=SettingsOut)
def read_settings(_: User = Depends(admin_only), db: Session = Depends(get_db)) -> SettingsOut:
    return _out(load_app_settings(db))


@router.put("/settings", response_model=SettingsOut)
def update_settings(body: SettingsIn, user: User = Depends(admin_only), db: Session = Depends(get_db)) -> SettingsOut:
    row = load_app_settings(db, for_update=True)
    row.phase3_enabled = body.phase3_enabled
    db.commit()
    audit.warning("phase3_enabled set to %s by user %s", body.phase3_enabled, user.id)
    return _out(row)


@router.delete("/settings/fingerprint", response_model=SettingsOut)
def clear_fingerprint(user: User = Depends(admin_only), db: Session = Depends(get_db)) -> SettingsOut:
    row = load_app_settings(db, for_update=True)
    old = row.expected_key_fingerprint
    row.expected_key_fingerprint = None
    db.commit()
    audit.warning("hospital key fingerprint %s cleared by user %s", old, user.id)
    return _out(row)
```

In `server/capture/api/app.py`, replace

```python
from capture.api import routes_auth
```

with

```python
from capture.api import routes_admin, routes_auth, routes_device, routes_templates
```

and replace

```python
ROUTERS = (routes_auth.router,)
```

with

```python
ROUTERS = (routes_auth.router, routes_templates.router, routes_device.router, routes_admin.router)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server/capture/app_settings.py server/capture/api server/tests/test_settings_routes.py
git commit -m "feat(server): templates list, device key fingerprint, admin settings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Uploading a record, storing pages and serving files

**Files:**
- Create: `server/capture/storage.py`, `server/capture/records/__init__.py` (empty), `server/capture/records/service.py`, `server/capture/api/routes_records.py`, `server/capture/api/routes_files.py`
- Modify: `server/capture/api/schemas.py` (append), `server/capture/api/convert.py` (append), `server/capture/api/app.py` (router list)
- Test: `server/tests/test_storage.py`, `server/tests/test_records_create.py`

**Interfaces:**
- Consumes: `load_app_settings` (Task 7), `get_active`, `template_def` (Task 4), `validate_values` (Task 3), `can_view` (Task 6), `today` (Task 5).
- Produces:
  - `save_page(storage_dir, study_code, record_id, page_no, data) -> (relative_path, sha256_hex)` and `resolve_in_storage(storage_dir, relative) -> Path` (raises `ValueError` when the path escapes storage).
  - `UploadRejected(status, message)`.
  - `create_record(db, settings, user, *, study_code, template_key, key_fingerprint, pages: list[bytes]) -> (Record, duplicate_of: list[UUID])`.
  - `load_events(db, record_id) -> list[ReviewEvent]`.
  - `detail_for(db, record, duplicate_of=()) -> RecordDetail`.
  - Schemas `CreateMeta` (with `STUDY_CODE_PATTERN`), `FileOut`, `LastEventOut`, `EventOut`, `RecordSummary`, `RecordDetail`.
  - `convert.record_summary(record, last_event) -> RecordSummary` and `convert.record_detail(record, events, errors, phase3_enabled, duplicate_of=()) -> RecordDetail`.
  - Endpoints:
    - `POST /api/records`: multipart with field `meta` (JSON string) and 1–20 files named `pages`. Returns 201 with `RecordDetail`.
    - `GET /api/files/{file_id}`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_storage.py`:

```python
import hashlib
import uuid

import pytest

from capture.storage import resolve_in_storage, save_page


def test_save_page_writes_file_and_returns_hash(tmp_path):
    record_id = uuid.uuid4()
    relative, digest = save_page(tmp_path, "AMH-N0ZDG4KM8V", record_id, 2, b"abc")
    assert relative == f"records/AMH-N0ZDG4KM8V/{record_id}/page-2.jpg"
    assert (tmp_path / relative).read_bytes() == b"abc"
    assert digest == hashlib.sha256(b"abc").hexdigest()


def test_resolve_rejects_paths_outside_storage(tmp_path):
    with pytest.raises(ValueError):
        resolve_in_storage(tmp_path, "../secret.txt")
```

`server/tests/test_records_create.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_storage.py tests/test_records_create.py -q`
Expected: FAIL. `capture.storage` does not exist, and the upload tests get 404 from `/api/records`.

- [ ] **Step 3: Implement storage**

`server/capture/storage.py`:

```python
import hashlib
import uuid
from pathlib import Path


def resolve_in_storage(storage_dir: Path, relative: str) -> Path:
    root = Path(storage_dir).resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes storage: {relative}")
    return target


def save_page(storage_dir: Path, study_code: str, record_id: uuid.UUID, page_no: int, data: bytes) -> tuple[str, str]:
    relative = f"records/{study_code}/{record_id}/page-{page_no}.jpg"
    target = resolve_in_storage(storage_dir, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, hashlib.sha256(data).hexdigest()
```

- [ ] **Step 4: Add the record schemas and converters**

Append to `server/capture/api/schemas.py`:

```python


STUDY_CODE_PATTERN = r"^AMH-[0-9A-HJKMNP-TV-Z]{10}$"


class CreateMeta(BaseModel):
    study_code: str = Field(pattern=STUDY_CODE_PATTERN)
    template_key: str
    key_fingerprint: str


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: str
    page_no: int | None
    size: int


class LastEventOut(BaseModel):
    action: str
    comment: str | None
    actor_name: str
    created_at: datetime


class EventOut(LastEventOut):
    id: int
    field_changes: list[dict[str, Any]] | None
    field_flags: dict[str, str] | None


class RecordSummary(BaseModel):
    id: uuid.UUID
    study_code: str
    template_key: str
    template_title: str
    template_version: int
    status: str
    extraction_status: str
    document_date: date | None
    created_by_id: int
    created_by_name: str
    created_at: datetime
    updated_at: datetime
    last_event: LastEventOut | None


class RecordDetail(RecordSummary):
    values: dict[str, Any]
    extraction: dict[str, Any] | None
    row_version: int
    files: list[FileOut]
    events: list[EventOut]
    template: TemplateOut
    errors: list[dict[str, str]]
    duplicate_of: list[uuid.UUID] = []
```

Append to `server/capture/api/convert.py`. Put the import lines next to the existing imports at the top of the file and the functions at the end:

```python
from collections.abc import Iterable
import uuid

from capture.api.schemas import EventOut, FileOut, LastEventOut, RecordDetail, RecordSummary
from capture.db.models import Record, ReviewEvent


def _last_event(event: ReviewEvent | None) -> LastEventOut | None:
    if event is None:
        return None
    return LastEventOut(action=event.action, comment=event.comment, actor_name=event.actor.name, created_at=event.created_at)


def record_summary(record: Record, last_event: ReviewEvent | None) -> RecordSummary:
    return RecordSummary(
        id=record.id,
        study_code=record.study_code,
        template_key=record.template.key,
        template_title=record.template.title,
        template_version=record.template.version,
        status=record.status,
        extraction_status=record.extraction_status,
        document_date=record.document_date,
        created_by_id=record.created_by,
        created_by_name=record.creator.name,
        created_at=record.created_at,
        updated_at=record.updated_at,
        last_event=_last_event(last_event),
    )


def record_detail(
    record: Record,
    events: list[ReviewEvent],
    errors: list[dict[str, str]],
    phase3_enabled: bool,
    duplicate_of: Iterable[uuid.UUID] = (),
) -> RecordDetail:
    summary = record_summary(record, events[-1] if events else None)
    return RecordDetail(
        **summary.model_dump(),
        values=record.field_values,
        extraction=record.extraction,
        row_version=record.row_version,
        files=[FileOut.model_validate(f) for f in record.files],
        events=[
            EventOut(
                id=e.id,
                action=e.action,
                comment=e.comment,
                actor_name=e.actor.name,
                created_at=e.created_at,
                field_changes=e.field_changes,
                field_flags=e.field_flags,
            )
            for e in events
        ],
        template=template_out(record.template, phase3_enabled),
        errors=errors,
        duplicate_of=list(duplicate_of),
    )
```

- [ ] **Step 5: Implement the record service**

`server/capture/records/__init__.py`: empty file.

`server/capture/records/service.py`:

```python
import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from capture.api.convert import record_detail
from capture.api.schemas import RecordDetail
from capture.app_settings import load_app_settings
from capture.clock import today
from capture.config import Settings
from capture.db.models import ExtractionStatus, Job, Patient, Record, RecordFile, ReviewEvent, Status, User
from capture.formschema.store import get_active, template_def
from capture.formschema.validate import validate_values
from capture.storage import save_page

JPEG_MAGIC = b"\xff\xd8\xff"


class UploadRejected(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def create_record(
    db: Session,
    settings: Settings,
    user: User,
    *,
    study_code: str,
    template_key: str,
    key_fingerprint: str,
    pages: list[bytes],
) -> tuple[Record, list[uuid.UUID]]:
    """Validate an upload, store its pages and create the record. Nothing is written on rejection."""
    app_settings = load_app_settings(db)
    if app_settings.expected_key_fingerprint is None:
        raise UploadRejected(409, "The hospital key has not been set up yet — ask a hospital doctor to set up a device")
    if key_fingerprint != app_settings.expected_key_fingerprint:
        raise UploadRejected(409, "This device's key doesn't match — ask your hospital admin.")
    template = get_active(db, template_key)
    if template is None:
        raise UploadRejected(404, "Unknown form type")
    if template.kind == "dicom":
        raise UploadRejected(422, "Use the DICOM upload for this form")
    if template.phase == 3 and not app_settings.phase3_enabled:
        raise UploadRejected(403, "Locked until Phase 3")
    if not 1 <= len(pages) <= settings.max_pages:
        raise UploadRejected(422, f"Upload between 1 and {settings.max_pages} pages")
    for data in pages:
        if len(data) > settings.max_page_bytes:
            raise UploadRejected(413, f"Each page must be at most {settings.max_page_bytes // (1024 * 1024)} MB")
        if not data.startswith(JPEG_MAGIC):
            raise UploadRejected(415, "Pages must be JPEG images")

    db.execute(pg_insert(Patient).values(study_code=study_code).on_conflict_do_nothing())
    extracting = settings.extraction_enabled
    record = Record(
        id=uuid.uuid4(),
        study_code=study_code,
        template_id=template.id,
        status=Status.PROCESSING if extracting else Status.DRAFT,
        extraction_status=ExtractionStatus.PENDING if extracting else ExtractionStatus.NOT_APPLICABLE,
        field_values={},
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    hashes: list[str] = []
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, study_code, record.id, page_no, data)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
        hashes.append(digest)
    duplicates = list(
        db.scalars(
            select(RecordFile.record_id)
            .join(Record, Record.id == RecordFile.record_id)
            .where(Record.study_code == study_code, RecordFile.sha256.in_(hashes), RecordFile.record_id != record.id)
            .distinct()
        )
    )
    if extracting:
        db.add(Job(kind="extract", record_id=record.id))
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="upload"))
    db.flush()
    return record, duplicates


def load_events(db: Session, record_id: uuid.UUID) -> list[ReviewEvent]:
    stmt = select(ReviewEvent).where(ReviewEvent.record_id == record_id).order_by(ReviewEvent.created_at, ReviewEvent.id)
    return list(db.scalars(stmt))


def detail_for(db: Session, record: Record, duplicate_of: Iterable[uuid.UUID] = ()) -> RecordDetail:
    errors = validate_values(template_def(record.template), record.field_values, today())
    phase3_enabled = load_app_settings(db).phase3_enabled
    return record_detail(record, load_events(db, record.id), errors, phase3_enabled, duplicate_of)
```

- [ ] **Step 6: Add the routes**

`server/capture/api/routes_records.py`:

```python
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from capture.api.deps import get_db, get_settings, require_roles
from capture.api.schemas import CreateMeta, RecordDetail
from capture.config import Settings
from capture.db.models import Role, User
from capture.records.service import UploadRejected, create_record, detail_for

router = APIRouter(tags=["records"])


def _meta_error(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
    return "Invalid upload details: " + "; ".join(parts)


@router.post("/records", status_code=201, response_model=RecordDetail)
def create(
    meta: str = Form(...),
    pages: list[UploadFile] = File(...),
    user: User = Depends(require_roles(Role.UPLOADER, Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecordDetail:
    try:
        parsed = CreateMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_meta_error(e)) from None
    if len(pages) > settings.max_pages:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {settings.max_pages} pages")
    data = [page.file.read(settings.max_page_bytes + 1) for page in pages]
    try:
        record, duplicates = create_record(
            db,
            settings,
            user,
            study_code=parsed.study_code,
            template_key=parsed.template_key,
            key_fingerprint=parsed.key_fingerprint,
            pages=data,
        )
    except UploadRejected as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message) from None
    db.commit()
    return detail_for(db, record, duplicate_of=duplicates)
```

`server/capture/api/routes_files.py`:

```python
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from capture.api.deps import current_user, get_db, get_settings
from capture.config import Settings
from capture.db.models import Record, RecordFile, User
from capture.storage import resolve_in_storage
from capture.workflow.rules import can_view

router = APIRouter(tags=["files"])


@router.get("/files/{file_id}")
def get_file(
    file_id: uuid.UUID,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> FileResponse:
    stored = db.get(RecordFile, file_id)
    record = db.get(Record, stored.record_id) if stored is not None else None
    if stored is None or record is None or not can_view(user.role, record.status):
        raise HTTPException(status_code=404, detail="File not found")
    media_type = "image/jpeg" if stored.kind == "page" else "application/dicom"
    return FileResponse(
        resolve_in_storage(settings.storage_dir, stored.path),
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
```

In `server/capture/api/app.py`, replace

```python
from capture.api import routes_admin, routes_auth, routes_device, routes_templates
```

with

```python
from capture.api import routes_admin, routes_auth, routes_device, routes_files, routes_records, routes_templates
```

and replace

```python
ROUTERS = (routes_auth.router, routes_templates.router, routes_device.router, routes_admin.router)
```

with

```python
ROUTERS = (
    routes_auth.router,
    routes_templates.router,
    routes_device.router,
    routes_admin.router,
    routes_records.router,
    routes_files.router,
)
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add server/capture server/tests/test_storage.py server/tests/test_records_create.py
git commit -m "feat(server): upload records with JPEG pages, duplicate check, guarded file access" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Listing, editing and approving records

**Files:**
- Modify: `server/capture/api/schemas.py` (append), `server/capture/records/service.py` (append), `server/capture/api/routes_records.py` (append)
- Test: `server/tests/test_records_review.py`

**Interfaces:**
- Consumes: `next_status`, `can_view`, `can_edit`, `Action`, `TransitionError` (Task 6); `diff_values`, `document_date_of`, `validate_values` (Task 3); `detail_for`, `record_summary` (Task 8).
- Produces:
  - Schemas `ValuesIn {row_version: int, values: dict}` and `TransitionIn {action: Action, comment: str|None, field_flags: dict[str,str]|None}`.
  - `last_events(db, ids) -> dict[UUID, ReviewEvent]`.
  - Endpoints:
    - `GET /api/records?status=&study_code=&template=&mine=` → `[RecordSummary]`, newest first, at most 500. NSU roles only ever see `pending_nsu`/`approved`.
    - `GET /api/records/{id}` → `RecordDetail` (404 if the caller may not view it).
    - `PATCH /api/records/{id}/values` → `RecordDetail` (403 if not editable; 409 `Someone else changed this record — reload` on a stale `row_version`). Invalid values are saved and reported in `errors`.
    - `POST /api/records/{id}/transition` → `RecordDetail`, with errors from `TransitionError`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_records_review.py`:

```python
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


def act(client, record_id, action, comment=None):
    return client.post(f"/api/records/{record_id}/transition", json={"action": action, "comment": comment})


def fresh(client, record_id) -> dict:
    return client.get(f"/api/records/{record_id}").json()


def test_full_double_approval_path(team, upload):
    record = new_record(team, upload)
    assert record["errors"] == []
    assert record["document_date"] == "2026-09-01"
    assert act(team.uploader, record["id"], "submit").json()["status"] == "pending_doctor"
    assert act(team.doctor, record["id"], "approve").json()["status"] == "pending_nsu"
    final = act(team.reviewer, record["id"], "approve").json()
    assert final["status"] == "approved"
    assert [e["action"] for e in final["events"]] == ["upload", "edit", "submit", "approve", "approve"]


def test_nsu_sees_a_record_only_after_doctor_approval(team, upload):
    record = new_record(team, upload)
    assert team.reviewer.get(f"/api/records/{record['id']}").status_code == 404
    assert team.reviewer.get("/api/records").json() == []
    act(team.uploader, record["id"], "submit")
    act(team.doctor, record["id"], "approve")
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
    r = act(team.uploader, record["id"], "submit")
    assert r.status_code == 422
    assert r.json()["detail"] == "Fix the highlighted fields before submitting"


def test_stale_row_version_conflicts(team, upload):
    record = new_record(team, upload)
    r = team.doctor.patch(f"/api/records/{record['id']}/values", json={"row_version": 1, "values": VALID})
    assert r.status_code == 409
    assert r.json()["detail"] == "Someone else changed this record — reload"


def test_uploader_cannot_edit_after_submit(team, upload):
    record = new_record(team, upload)
    act(team.uploader, record["id"], "submit")
    assert save(team.uploader, fresh(team.uploader, record["id"]), VALID).status_code == 403


def test_doctor_can_correct_while_reviewing(team, upload):
    record = new_record(team, upload)
    act(team.uploader, record["id"], "submit")
    r = save(team.doctor, fresh(team.doctor, record["id"]), dict(VALID, modality="MRI"))
    assert r.status_code == 200
    assert r.json()["values"]["modality"] == "MRI"


def test_nsu_cannot_edit(team, upload):
    record = new_record(team, upload)
    act(team.uploader, record["id"], "submit")
    act(team.doctor, record["id"], "approve")
    assert save(team.reviewer, fresh(team.reviewer, record["id"]), VALID).status_code == 403


def test_four_eyes_rule(team, upload):
    record = new_record(team, upload, by=team.doctor)
    act(team.doctor, record["id"], "submit")
    r = act(team.doctor, record["id"], "approve")
    assert r.status_code == 403
    assert "another doctor" in r.json()["detail"]
    assert act(team.doctor2, record["id"], "approve").status_code == 200


def test_nsu_return_goes_back_through_the_doctor(team, upload):
    record = new_record(team, upload)
    act(team.uploader, record["id"], "submit")
    act(team.doctor, record["id"], "approve")
    assert act(team.reviewer, record["id"], "return").status_code == 422
    returned = act(team.reviewer, record["id"], "return", "Lesion size unreadable — check page 1")
    assert returned.json()["status"] == "draft"
    listed = team.uploader.get("/api/records", params={"status": "draft", "mine": "true"}).json()
    assert listed[0]["last_event"]["action"] == "return"
    assert listed[0]["last_event"]["comment"] == "Lesion size unreadable — check page 1"
    assert act(team.uploader, record["id"], "submit").json()["status"] == "pending_doctor"


def test_admin_reopens_an_approved_record(team, upload):
    record = new_record(team, upload)
    act(team.uploader, record["id"], "submit")
    act(team.doctor, record["id"], "approve")
    act(team.reviewer, record["id"], "approve")
    r = act(team.admin, record["id"], "reopen", "Wrong lobe recorded")
    assert r.json()["status"] == "draft"


def test_unknown_record_is_404(team):
    assert team.uploader.get("/api/records/00000000-0000-0000-0000-000000000000").status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_records_review.py -q`
Expected: FAIL. `PATCH /api/records/{id}/values` returns 404 or 405 because the route does not exist yet.

- [ ] **Step 3: Add the schemas and `last_events`**

In `server/capture/api/schemas.py`, add this line to the imports at the top:

```python
from capture.workflow.rules import Action
```

and append:

```python


class ValuesIn(BaseModel):
    row_version: int
    values: dict[str, Any]


class TransitionIn(BaseModel):
    action: Action
    comment: str | None = None
    field_flags: dict[str, str] | None = None
```

Append to `server/capture/records/service.py`:

```python


def last_events(db: Session, record_ids: list[uuid.UUID]) -> dict[uuid.UUID, ReviewEvent]:
    """The newest review event of each record (one query)."""
    if not record_ids:
        return {}
    stmt = (
        select(ReviewEvent)
        .where(ReviewEvent.record_id.in_(record_ids))
        .order_by(ReviewEvent.record_id, ReviewEvent.created_at.desc(), ReviewEvent.id.desc())
        .distinct(ReviewEvent.record_id)
    )
    return {event.record_id: event for event in db.scalars(stmt)}
```

- [ ] **Step 4: Add the routes**

Append to `server/capture/api/routes_records.py`. Put these imports with the others at the top of the file:

```python
import uuid

from sqlalchemy import select

from capture.api.convert import record_summary
from capture.api.deps import current_user
from capture.api.schemas import RecordSummary, TransitionIn, ValuesIn
from capture.clock import today
from capture.db.models import NSU_ROLES, Record, ReviewEvent, Status, Template
from capture.formschema.diff import diff_values
from capture.formschema.store import template_def
from capture.formschema.validate import document_date_of, validate_values
from capture.records.service import last_events
from capture.workflow.rules import TransitionError, can_edit, can_view, next_status
```

and these functions at the end:

```python
def _load_visible(db: Session, user: User, record_id: uuid.UUID, *, for_update: bool = False) -> Record:
    record = db.get(Record, record_id, with_for_update=True if for_update else None)
    if record is None or not can_view(user.role, record.status):
        raise HTTPException(status_code=404, detail="Record not found")
    return record


@router.get("/records", response_model=list[RecordSummary])
def list_records(
    status: str | None = None,
    study_code: str | None = None,
    template: str | None = None,
    mine: bool = False,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> list[RecordSummary]:
    stmt = select(Record).join(Record.template)
    if user.role in NSU_ROLES:
        stmt = stmt.where(Record.status.in_([Status.PENDING_NSU, Status.APPROVED]))
    if status:
        stmt = stmt.where(Record.status == status)
    if study_code:
        stmt = stmt.where(Record.study_code == study_code)
    if template:
        stmt = stmt.where(Template.key == template)
    if mine:
        stmt = stmt.where(Record.created_by == user.id)
    records = list(db.scalars(stmt.order_by(Record.updated_at.desc()).limit(500)))
    latest = last_events(db, [r.id for r in records])
    return [record_summary(r, latest.get(r.id)) for r in records]


@router.get("/records/{record_id}", response_model=RecordDetail)
def get_record(record_id: uuid.UUID, user: User = Depends(current_user), db: Session = Depends(get_db)) -> RecordDetail:
    return detail_for(db, _load_visible(db, user, record_id))


@router.patch("/records/{record_id}/values", response_model=RecordDetail)
def update_values(
    record_id: uuid.UUID,
    body: ValuesIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecordDetail:
    record = _load_visible(db, user, record_id, for_update=True)
    if not can_edit(user.role, record.status):
        raise HTTPException(status_code=403, detail="You cannot edit this record now")
    if body.row_version != record.row_version:
        raise HTTPException(status_code=409, detail="Someone else changed this record — reload")
    changes = diff_values(record.field_values, body.values)
    record.field_values = body.values
    record.document_date = document_date_of(template_def(record.template), body.values)
    record.row_version += 1
    if changes:
        db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="edit", field_changes=changes))
    db.commit()
    return detail_for(db, record)


@router.post("/records/{record_id}/transition", response_model=RecordDetail)
def transition(
    record_id: uuid.UUID,
    body: TransitionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
) -> RecordDetail:
    record = _load_visible(db, user, record_id, for_update=True)
    errors = validate_values(template_def(record.template), record.field_values, today())
    try:
        new_status = next_status(
            action=body.action,
            role=user.role,
            status=record.status,
            actor_id=user.id,
            creator_id=record.created_by,
            comment=body.comment,
            has_errors=bool(errors),
        )
    except TransitionError as e:
        raise HTTPException(status_code=e.http_status, detail=e.message) from None
    record.status = new_status
    record.row_version += 1
    comment = (body.comment or "").strip() or None
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action=body.action, comment=comment, field_flags=body.field_flags))
    db.commit()
    return detail_for(db, record)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add server/capture server/tests/test_records_review.py
git commit -m "feat(server): list, edit with audit diff, and two-step approval of records" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Admin CLI, local dev server and README

**Files:**
- Create: `server/capture/cli.py`, `server/capture/devserver.py`, `server/README.md`
- Test: `server/tests/test_cli.py`, `server/tests/test_devserver.py`

**Interfaces:**
- Consumes: `load_templates` (Task 4), `hash_password`, `revoke_all_for_user` (Task 5), `upgrade` (Task 2), `create_app` (Task 5).
- Produces:
  - CLI `capture`:
    - `capture templates load [DIR]`, where DIR defaults to repo `templates/`.
    - `capture users create EMAIL NAME ROLE` (prompts for the password twice; at least 10 characters).
    - `capture users deactivate EMAIL`.
  - `python -m capture.devserver [--reset] [--port 8000]`: starts an embedded PostgreSQL in `server/.devdata/`, applies migrations, loads templates, seeds demo users (password `demo-pass-123`) and serves the API at `http://127.0.0.1:PORT`.
  - `devserver.prepare(reset: bool) -> Settings`, `DEMO_USERS`, `DEMO_PASSWORD`, `DATA_DIR`.
  - M2's Playwright tests start the server with `--reset`.

- [ ] **Step 1: Write the failing tests**

`server/tests/test_cli.py`:

```python
import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from capture.cli import app as cli
from capture.db.models import User

runner = CliRunner()


@pytest.fixture(autouse=True)
def point_cli_at_test_db(db, migrated_url, monkeypatch):
    monkeypatch.setenv("CAPTURE_DATABASE_URL", migrated_url)


def test_templates_load(db):
    first = runner.invoke(cli, ["templates", "load"])
    assert first.exit_code == 0, first.output
    assert "radiology_report v1: created" in first.output
    second = runner.invoke(cli, ["templates", "load"])
    assert "radiology_report v1: unchanged" in second.output


def test_create_user_lowercases_email_and_sets_institution(db):
    r = runner.invoke(
        cli,
        ["users", "create", "New.Doctor@AMCGH.test", "New Doctor", "hospital_doctor"],
        input="long-password-1\nlong-password-1\n",
    )
    assert r.exit_code == 0, r.output
    with db() as s:
        user = s.scalar(select(User).where(User.email == "new.doctor@amcgh.test"))
    assert user.role == "hospital_doctor"
    assert user.institution == "AMCGH"


def test_create_user_rejects_short_password(db):
    r = runner.invoke(cli, ["users", "create", "a@nsu.test", "A", "nsu_reviewer"], input="short\nshort\n")
    assert r.exit_code == 1
    assert "at least 10 characters" in r.output


def test_create_user_rejects_duplicate_email(db, make_user):
    make_user(email="taken@nsu.test")
    r = runner.invoke(cli, ["users", "create", "Taken@NSU.test", "T", "admin"], input="long-password-1\nlong-password-1\n")
    assert r.exit_code == 1
    assert "already exists" in r.output


def test_deactivate_user_ends_their_sessions(db, make_user, login_as):
    user = make_user()
    session = login_as(user)
    r = runner.invoke(cli, ["users", "deactivate", user["email"]])
    assert r.exit_code == 0, r.output
    assert session.get("/api/me").status_code == 401
```

`server/tests/test_devserver.py`:

```python
from sqlalchemy import func, select

from capture import devserver
from capture.db.base import make_sessionmaker
from capture.db.models import Template, User


def test_prepare_creates_database_templates_and_demo_users(tmp_path, monkeypatch):
    monkeypatch.setattr(devserver, "DATA_DIR", tmp_path / "devdata")
    settings = devserver.prepare(reset=True)
    sessions = make_sessionmaker(settings.database_url)
    with sessions() as s:
        emails = set(s.scalars(select(User.email)))
        assert {u[0] for u in devserver.DEMO_USERS} <= emails
        assert s.scalar(select(func.count()).select_from(Template)) == 9
    sessions.kw["bind"].dispose()
    assert settings.cookie_secure is False
    devserver.prepare(reset=True)  # a second reset must also work
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_cli.py tests/test_devserver.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'capture.cli'`.

- [ ] **Step 3: Implement the CLI**

`server/capture/cli.py`:

```python
from pathlib import Path

import typer
from sqlalchemy import func, select

from capture.auth.passwords import hash_password
from capture.auth.sessions import revoke_all_for_user
from capture.config import Settings
from capture.db.base import make_sessionmaker
from capture.db.models import NSU_ROLES, Role, User
from capture.formschema.store import TemplateConflict, load_templates

REPO_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"

app = typer.Typer(no_args_is_help=True, help="AMCGH data capture administration")
templates_cli = typer.Typer(no_args_is_help=True, help="Form templates")
users_cli = typer.Typer(no_args_is_help=True, help="User accounts")
app.add_typer(templates_cli, name="templates")
app.add_typer(users_cli, name="users")


def _sessions():
    return make_sessionmaker(Settings().database_url)


def _fail(message: str) -> None:
    typer.echo(f"ERROR: {message}", err=True)
    raise typer.Exit(1)


@templates_cli.command("load")
def templates_load(directory: Path = typer.Argument(REPO_TEMPLATES, help="Folder of *.yaml templates")) -> None:
    """Add new templates or new template versions to the database."""
    try:
        with _sessions().begin() as s:
            for line in load_templates(s, directory):
                typer.echo(line)
    except TemplateConflict as e:
        _fail(str(e))


@users_cli.command("create")
def users_create(
    email: str,
    name: str,
    role: Role,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a login. The institution follows from the role."""
    if len(password) < 10:
        _fail("password must be at least 10 characters")
    email = email.strip().lower()
    institution = "NSU" if role in NSU_ROLES else "AMCGH"
    with _sessions().begin() as s:
        if s.scalar(select(User).where(func.lower(User.email) == email)) is not None:
            _fail(f"a user with email {email} already exists")
        s.add(User(name=name, email=email, password_hash=hash_password(password), role=role, institution=institution))
    typer.echo(f"created {role} {email}")


@users_cli.command("deactivate")
def users_deactivate(email: str) -> None:
    """Block a login and end all of its sessions."""
    email = email.strip().lower()
    with _sessions().begin() as s:
        user = s.scalar(select(User).where(func.lower(User.email) == email))
        if user is None:
            _fail(f"no user with email {email}")
        user.active = False
        revoke_all_for_user(s, user.id)
    typer.echo(f"deactivated {email} and ended their sessions")
```

- [ ] **Step 4: Implement the dev server**

`server/capture/devserver.py`:

```python
"""Run the API locally on an embedded PostgreSQL with demo users (development and e2e tests only)."""

import argparse
import shutil
from pathlib import Path

import pgserver
import uvicorn
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url

from capture.api.app import create_app
from capture.auth.passwords import hash_password
from capture.config import Settings
from capture.db.base import make_sessionmaker
from capture.db.migrate import upgrade
from capture.db.models import User
from capture.formschema.store import load_templates

SERVER_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = SERVER_DIR / ".devdata"
TEMPLATES_DIR = SERVER_DIR.parent / "templates"
DEMO_PASSWORD = "demo-pass-123"
DEMO_USERS = [
    ("uploader@amcgh.test", "Demo Uploader", "uploader", "AMCGH"),
    ("doctor@amcgh.test", "Demo Doctor", "hospital_doctor", "AMCGH"),
    ("doctor2@amcgh.test", "Demo Doctor Two", "hospital_doctor", "AMCGH"),
    ("reviewer@nsu.test", "Demo Reviewer", "nsu_reviewer", "NSU"),
    ("admin@nsu.test", "Demo Admin", "admin", "NSU"),
]


def prepare(reset: bool) -> Settings:
    server = pgserver.get_server(DATA_DIR / "pg", cleanup_mode="stop")
    admin_url = make_url(server.get_uri()).set(drivername="postgresql+psycopg")
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        if reset:
            conn.execute(text("DROP DATABASE IF EXISTS capture WITH (FORCE)"))
        if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = 'capture'")):
            conn.execute(text("CREATE DATABASE capture"))
    engine.dispose()

    storage = DATA_DIR / "storage"
    if reset and storage.exists():
        shutil.rmtree(storage)
    url = admin_url.set(database="capture").render_as_string(hide_password=False)
    upgrade(url)
    sessions = make_sessionmaker(url)
    with sessions.begin() as s:
        load_templates(s, TEMPLATES_DIR)
        for email, name, role, institution in DEMO_USERS:
            if s.scalar(select(User).where(User.email == email)) is None:
                s.add(User(name=name, email=email, password_hash=hash_password(DEMO_PASSWORD), role=role, institution=institution))
    sessions.kw["bind"].dispose()
    return Settings(database_url=url, storage_dir=storage, cookie_secure=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe the dev database and stored files first")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    settings = prepare(args.reset)
    print(f"Demo users (password {DEMO_PASSWORD!r}): " + ", ".join(u[0] for u in DEMO_USERS))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
```

`server/README.md`:

````markdown
# Capture server

FastAPI + PostgreSQL API for the AMCGH × NSU lung cancer data capture app.
Design: `../docs/superpowers/specs/2026-10-04-data-capture-design.md`.

## Develop

```bash
uv sync                                        # Python 3.12 + dependencies
uv run pytest                                  # tests (start their own PostgreSQL)
uv run python -m capture.devserver --reset     # API on http://127.0.0.1:8000, demo users
```

Demo users (password `demo-pass-123`): `uploader@amcgh.test`, `doctor@amcgh.test`,
`doctor2@amcgh.test`, `reviewer@nsu.test`, `admin@nsu.test`.

## Operate

Configuration comes from `CAPTURE_*` environment variables (see `capture/config.py`):
`CAPTURE_DATABASE_URL`, `CAPTURE_STORAGE_DIR`, `CAPTURE_COOKIE_SECURE` (keep `true` behind HTTPS),
`CAPTURE_EXTRACTION_ENABLED` (stays `false` until the M3 worker exists).

```bash
uv run alembic upgrade head                    # migrate
uv run capture templates load                  # add new templates / versions from ../templates
uv run capture users create EMAIL "Full Name" hospital_doctor
uv run capture users deactivate EMAIL
uv run uvicorn capture.api.app:create_app --factory --host 127.0.0.1 --port 8000
```
````

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Smoke-test the dev server by hand**

Run: `cd server && uv run python -m capture.devserver --reset`
In a second terminal, run: `curl -s http://127.0.0.1:8000/api/health`
Expected: `{"ok":true}`. Stop the server with Ctrl+C.

- [ ] **Step 7: Commit**

```bash
git add server/capture/cli.py server/capture/devserver.py server/README.md server/tests/test_cli.py server/tests/test_devserver.py
git commit -m "feat(server): admin CLI, embedded-Postgres dev server, README" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Done when

- `cd server && uv run pytest -q` passes with no skips.
- `uv run python -m capture.devserver --reset` serves `/api/health`, and `/api/docs` lists `auth`, `templates`, `device`, `admin`, `records` and `files` endpoints.
- Every Review Focus item has a passing test: Task 5 (email case), Task 8 (non-JPEG, malformed study code), Tasks 3 and 9 (removed lesion in diff, wrongly typed values).
