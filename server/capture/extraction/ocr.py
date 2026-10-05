"""OCR results shared by the PHI safety net, the cross-check and the OCR engines."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class OcrLine:
    page: int  # 1-based
    text: str
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in the stored page's pixels


class OcrEngine(Protocol):
    def read(self, page: int, image: bytes) -> list[OcrLine]:
        """Every text line on one JPEG page, in reading order."""
        ...
