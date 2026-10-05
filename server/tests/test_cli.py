import pytest
from sqlalchemy import select
from typer.testing import CliRunner

from capture.cli import app as cli
from capture.db.models import User

runner = CliRunner()
PASSWORDS = "long-password-1\nlong-password-1\n"


@pytest.fixture(autouse=True)
def point_cli_at_test_db(db, migrated_url, monkeypatch):
    monkeypatch.setenv("CAPTURE_DATABASE_URL", migrated_url)


def test_templates_load(db):
    first = runner.invoke(cli, ["templates", "load"])
    assert first.exit_code == 0, first.output
    assert "radiology_report v1: created" in first.output
    second = runner.invoke(cli, ["templates", "load"])
    assert "radiology_report v1: unchanged" in second.output


def test_templates_load_from_an_empty_folder_fails(db, tmp_path):
    r = runner.invoke(cli, ["templates", "load", str(tmp_path)])
    assert r.exit_code == 1
    assert "no *.yaml templates found" in r.output


def test_create_user_lowercases_the_id(db):
    r = runner.invoke(cli, ["users", "create", "First.Admin", "First Admin", "admin"], input=PASSWORDS)
    assert r.exit_code == 0, r.output
    with db() as s:
        user = s.scalar(select(User).where(User.username == "first.admin"))
    assert user.role == "admin"


def test_create_user_rejects_a_bad_id(db):
    r = runner.invoke(cli, ["users", "create", "a b", "A", "doctor"], input=PASSWORDS)
    assert r.exit_code == 1
    assert "ID must be" in r.output


def test_create_user_rejects_short_password(db):
    r = runner.invoke(cli, ["users", "create", "dr.a", "A", "doctor"], input="short\nshort\n")
    assert r.exit_code == 1
    assert "at least 10 characters" in r.output


def test_create_user_rejects_duplicate_id(db, make_user):
    make_user(username="taken")
    r = runner.invoke(cli, ["users", "create", "Taken", "T", "admin"], input=PASSWORDS)
    assert r.exit_code == 1
    assert "already exists" in r.output


def test_deactivate_user_ends_their_sessions(db, make_user, login_as):
    user = make_user()
    session = login_as(user)
    r = runner.invoke(cli, ["users", "deactivate", user["username"]])
    assert r.exit_code == 0, r.output
    assert session.get("/api/me").status_code == 401
