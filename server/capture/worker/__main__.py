"""python -m capture.worker — the extraction worker process (spec §3). Needs the OCR extra: uv sync --extra ocr."""

import logging
import os
import signal
import socket
import threading

from capture.config import Settings
from capture.db.base import make_sessionmaker
from capture.extraction.paddle import PaddleOcrEngine
from capture.extraction.vlm import client_from_settings
from capture.worker.loop import run_worker
from capture.worker.process import Engines


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    settings = Settings()
    engines = Engines(ocr=PaddleOcrEngine(settings), vlm=client_from_settings(settings))
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    run_worker(make_sessionmaker(settings.database_url), settings, engines, stop, f"{socket.gethostname()}-{os.getpid()}")


if __name__ == "__main__":
    main()
