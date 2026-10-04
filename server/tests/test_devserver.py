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
