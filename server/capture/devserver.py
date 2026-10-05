"""Run the API locally on an embedded PostgreSQL with demo users (development and e2e tests only)."""

import argparse
import importlib.util
import logging
import shutil
import threading
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
    ("doctor", "Demo Doctor", "doctor"),
    ("doctor2", "Demo Doctor Two", "doctor"),
    ("admin", "Demo Admin", "admin"),
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
        for username, name, role in DEMO_USERS:
            if s.scalar(select(User).where(User.username == username)) is None:
                s.add(User(name=name, username=username, password_hash=hash_password(DEMO_PASSWORD), role=role))
    sessions.kw["bind"].dispose()
    return Settings(database_url=url, storage_dir=storage, cookie_secure=False)


def start_worker(settings: Settings, mode: str) -> threading.Event:
    """Run the extraction worker in a background thread with real PaddleOCR, and either the stub model ("stub")
    or the model server at CAPTURE_VLM_URL ("vlm"). Returns the event that stops it."""
    if importlib.util.find_spec("paddleocr") is None:
        raise SystemExit(
            "The worker needs the OCR extra: run the dev server with `uv run --extra ocr python -m capture.devserver ...`"
        )
    from capture.extraction.paddle import PaddleOcrEngine
    from capture.extraction.stub import stub_transport
    from capture.extraction.vlm import client_from_settings
    from capture.worker.loop import run_worker
    from capture.worker.process import Engines

    engines = Engines(ocr=PaddleOcrEngine(settings), vlm=client_from_settings(settings, stub_transport() if mode == "stub" else None))
    stop = threading.Event()
    sessions = make_sessionmaker(settings.database_url)
    threading.Thread(target=run_worker, args=(sessions, settings, engines, stop, "devserver"), name="worker", daemon=True).start()
    return stop


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe the dev database and stored files first")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--worker",
        choices=["off", "stub", "vlm"],
        default="off",
        help="off: no AI, uploads go straight to manual entry; stub: PaddleOCR + a fixed-answer model; "
        "vlm: PaddleOCR + the model server at CAPTURE_VLM_URL",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = prepare(args.reset)
    if args.worker != "off":
        settings = settings.model_copy(update={"extraction_enabled": True})
        start_worker(settings, args.worker)
    print(f"Demo users (password {DEMO_PASSWORD!r}): " + ", ".join(u[0] for u in DEMO_USERS))
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
