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
