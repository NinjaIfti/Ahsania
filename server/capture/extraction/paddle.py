"""PaddleOCR on the CPU as the worker's OCR engine (spec §3). Needs the OCR extra: uv sync --extra ocr.

Only the worker imports this module; the API process never loads a model.
"""

import io

from PIL import Image

from capture.config import Settings
from capture.extraction.ocr import OcrLine


class PaddleOcrEngine:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._ocr = None  # created on first use, in the thread that runs the jobs

    def _engine(self):
        if self._ocr is None:
            from paddleocr import PaddleOCR

            self._ocr = PaddleOCR(
                text_detection_model_name=self._settings.ocr_det_model,
                text_recognition_model_name=self._settings.ocr_rec_model,
                use_doc_orientation_classify=False,  # pages are already upright (rotated in the capture wizard)
                use_doc_unwarping=False,
                use_textline_orientation=False,
                enable_mkldnn=self._settings.ocr_enable_mkldnn,
            )
        return self._ocr

    def read(self, page: int, image: bytes) -> list[OcrLine]:
        import numpy as np

        with Image.open(io.BytesIO(image)) as picture:
            rgb = np.asarray(picture.convert("RGB"))
        result = self._engine().predict(np.ascontiguousarray(rgb[:, :, ::-1]))[0]  # PaddleOCR expects OpenCV's BGR order
        return [
            OcrLine(page, text, tuple(int(v) for v in box))
            for text, box in zip(result["rec_texts"], result["rec_boxes"])
            if text.strip()
        ]
