"""Test doubles for the extraction worker: OCR that returns fixed lines, and the stub model server."""

import httpx

from capture.clock import utcnow
from capture.extraction.ocr import OcrLine
from capture.extraction.stub import stub_transport
from capture.extraction.vlm import VlmClient
from capture.jobqueue import claim_next
from capture.worker.process import process_job

# What PaddleOCR reads on web/e2e/fixtures/report.jpg once the identifier lines are blacked out.
REPORT_LINES = (
    "CT CHEST REPORT",
    "Date: 01/09/2026",
    "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.",
    "Impression: Suspicious for primary lung malignancy.",
)


class FakeOcr:
    """Every page reads as the given lines; line i sits at y = 40 * i."""

    def __init__(self, *lines: str) -> None:
        self.lines = lines

    def read(self, page: int, image: bytes) -> list[OcrLine]:
        return [OcrLine(page, text, (10, 40 * i, 500, 40 * i + 30)) for i, text in enumerate(self.lines)]


def stub_vlm(transport: httpx.BaseTransport | None = None) -> VlmClient:
    return VlmClient("http://vlm.test/v1", "test-model", timeout=5, max_image_side=1600, transport=transport or stub_transport())


def run_once(db, settings, engines, now=None) -> str:
    """Claim the next job and process it, as one turn of the worker loop. A job must be waiting."""
    moment = now or utcnow()
    with db.begin() as s:
        claimed = claim_next(s, "test-worker", moment)
    assert claimed is not None, "no job was waiting"
    return process_job(db, settings, engines, claimed, now=lambda: moment)
