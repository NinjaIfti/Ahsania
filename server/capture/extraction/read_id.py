"""Reads the patient ID (RC + digits) off a photographed page, so doctors don't type it.

Runs PaddleOCR inside the API process, on one dedicated thread (PaddleOCR is not thread-safe).
"""

import re
from concurrent.futures import ThreadPoolExecutor

from capture.config import Settings
from capture.extraction.ocr import OcrEngine, OcrLine

# "RC12345", "RC 12345", "RC-12345", "Reg No: rc:12345"; the digits must stand alone ("RC123abc" is not an ID).
REG_NO = re.compile(r"\bR\s?C\s*[-:.]?\s*([0-9]{1,30})(?![0-9A-Za-z])", re.IGNORECASE)


class OcrUnavailable(Exception):
    """The server was installed without the OCR extra."""


def find_reg_no(lines: list[OcrLine]) -> str | None:
    """The first RC number on the page, normalized like capture.api.schemas.normalize_reg_no."""
    for line in lines:
        match = REG_NO.search(line.text)
        if match:
            return "RC" + match.group(1)
    return None


class IdReader:
    def __init__(self, settings: Settings, engine: OcrEngine | None = None) -> None:
        self._settings = settings
        self._engine = engine  # created on first use when not given
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="read-id")

    def _read(self, image: bytes) -> str | None:
        try:
            if self._engine is None:
                from capture.extraction.paddle import PaddleOcrEngine

                self._engine = PaddleOcrEngine(self._settings)
            return find_reg_no(self._engine.read(1, image))
        except ImportError:  # PIL, numpy or paddleocr missing
            raise OcrUnavailable from None

    def read(self, image: bytes) -> str | None:
        return self._thread.submit(self._read, image).result()
