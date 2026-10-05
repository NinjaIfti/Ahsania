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


def test_two_panel_columns(migrated_url):
    engine = create_engine(migrated_url)
    with engine.connect() as conn:
        columns = {
            (t, c)
            for t, c in conn.execute(text("SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"))
        }
    engine.dispose()
    assert ("users", "username") in columns and ("users", "email") not in columns
    assert ("records", "reg_no") in columns and ("patients", "reg_no") in columns
    assert ("records", "quarantine") not in columns
    assert ("settings", "expected_key_fingerprint") not in columns
    assert ("jobs", "skip_safety_net") not in columns


def test_settings_singleton_row_exists(db):
    with db() as s:
        row = s.get(models.AppSettings, 1)
    assert row is not None
    assert row.phase3_enabled is False


def _one_event(db) -> int:
    with db.begin() as s:
        user = models.User(name="U", username="u", password_hash="x", role="doctor")
        template = models.Template(key="t", version=1, phase=1, kind="document", title="T", definition={})
        s.add_all([user, template, models.Patient(reg_no="RC00123")])
        s.flush()
        record = models.Record(
            reg_no="RC00123",
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


def test_review_events_cannot_be_truncated(db):
    _one_event(db)
    with pytest.raises(DBAPIError, match="append-only"):
        with db.begin() as s:
            s.execute(text("TRUNCATE review_events"))
