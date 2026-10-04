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
