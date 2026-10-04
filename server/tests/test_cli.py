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
