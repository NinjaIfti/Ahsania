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
    DATA_DIR.mkdir(parents=True, exist_ok=True)
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
