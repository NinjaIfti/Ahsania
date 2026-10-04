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
