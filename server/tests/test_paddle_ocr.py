"""Real PaddleOCR on the e2e report photo. Run with: uv run --extra ocr pytest -m paddle (downloads models once)."""

import pytest

from capture.config import Settings
from capture.extraction.phi import phi_hits
from constants import REPO_DIR

pytestmark = pytest.mark.paddle
REPORT = REPO_DIR / "web" / "e2e" / "fixtures" / "report.jpg"


def test_paddleocr_reads_the_report_and_the_safety_net_catches_its_identifiers():
    pytest.importorskip("paddleocr")
    from capture.extraction.paddle import PaddleOcrEngine

    lines = PaddleOcrEngine(Settings()).read(1, REPORT.read_bytes())
    texts = " | ".join(line.text for line in lines)
    assert "01712345678" in texts
    assert "spiculated mass" in texts
    assert all(line.page == 1 and line.box[0] < line.box[2] and line.box[1] < line.box[3] for line in lines)
    assert {hit.kind for hit in phi_hits(lines)} >= {"mobile", "label"}
