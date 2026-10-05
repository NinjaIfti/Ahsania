from pathlib import Path

import typer
from sqlalchemy import func, select

from capture.api.schemas import normalize_username
from capture.auth.passwords import hash_password
from capture.auth.sessions import revoke_all_for_user
from capture.config import Settings
from capture.db.base import make_sessionmaker
from capture.db.models import Role, User
from capture.evaluation import report, run_eval
from capture.extraction.stub import stub_transport
from capture.extraction.vlm import client_from_settings
from capture.formschema.store import TemplateConflict, load_templates

REPO_TEMPLATES = Path(__file__).resolve().parents[2] / "templates"
REPO_GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden"

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
    username: str,
    name: str,
    role: Role,
    password: str = typer.Option(..., prompt=True, hide_input=True, confirmation_prompt=True),
) -> None:
    """Create a login (the first admin; admins create the rest in the web app)."""
    if len(password) < 10:
        _fail("password must be at least 10 characters")
    try:
        username = normalize_username(username)
    except ValueError as e:
        _fail(str(e))
    with _sessions().begin() as s:
        if s.scalar(select(User).where(func.lower(User.username) == username)) is not None:
            _fail(f"a user with ID {username} already exists")
        s.add(User(name=name, username=username, password_hash=hash_password(password), role=role))
    typer.echo(f"created {role} {username}")


@users_cli.command("deactivate")
def users_deactivate(username: str) -> None:
    """Block a login and end all of its sessions."""
    username = username.strip().lower()
    with _sessions().begin() as s:
        user = s.scalar(select(User).where(func.lower(User.username) == username))
        if user is None:
            _fail(f"no user with ID {username}")
        user.active = False
        revoke_all_for_user(s, user.id)
    typer.echo(f"deactivated {username} and ended their sessions")


@app.command("eval")
def eval_command(
    golden: Path = typer.Option(REPO_GOLDEN, help="Folder of <template>/<case>/ golden documents"),
    stub: bool = typer.Option(False, help="Use the built-in stub model: checks the harness, not a real model"),
) -> None:
    """Measure the model's per-field accuracy on the synthetic golden set (spec §11.3)."""
    client = client_from_settings(Settings(), stub_transport() if stub else None)
    results = run_eval(golden, REPO_TEMPLATES, client)
    if not results:
        _fail(f"no golden documents found in {golden}")
    typer.echo(report(results))
