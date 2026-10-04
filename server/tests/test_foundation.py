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
