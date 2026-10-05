"""Cross-check (spec §5.2 step 4): find each extracted value in the OCR lines and keep where it was found."""

import re
from datetime import date
from typing import Any

from dateutil import parser as date_parser
from rapidfuzz import fuzz

from capture.extraction.ocr import OcrLine
from capture.formschema.model import BooleanField, DateField, EnumField, NumberField, TextField

TEXT_MATCH_MIN = 85  # rapidfuzz.partial_ratio, spec §5.2
_NUMBER = re.compile(r"(?<![\d.,·])\d+(?:[.,·]\d+)?")
_DATE_TOKENS = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
    re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b"),
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+[A-Za-z]{3,9},?\s+\d{4}\b"),
    re.compile(r"\b[A-Za-z]{3,9}\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b"),
]


def _source(lines: list[OcrLine]) -> dict[str, Any]:
    boxes = [line.box for line in lines]
    return {
        "page": lines[0].page,
        "box": [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)],
    }


def _numbers_in(line: str, unit: str | None) -> set[float]:
    found: set[float] = set()
    lowered = line.lower()
    for match in _NUMBER.finditer(line):
        n = float(match.group().replace(",", ".").replace("·", "."))
        found.add(n)
        if unit == "cm" and re.search(r"\bmm\b", lowered):
            found.add(n / 10)
        if unit == "mm" and re.search(r"\bcm\b", lowered):
            found.add(n * 10)
    return found


def _dates_in(line: str) -> set[date]:
    found: set[date] = set()
    for pattern in _DATE_TOKENS:
        for match in pattern.finditer(line):
            token = match.group()
            try:
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", token):
                    found.add(date.fromisoformat(token))  # dateutil would read 2026-09-01 day-first as 9 January
                else:
                    found.add(date_parser.parse(token, dayfirst=True).date())
            except (ValueError, OverflowError):
                continue
    return found


def _contains_term(line: str, term: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", line, re.IGNORECASE) is not None


def _single_line_match(field: Any, value: Any, line: OcrLine) -> bool:
    if isinstance(field, NumberField):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return any(abs(n - value) < 1e-6 for n in _numbers_in(line.text, field.unit))
    if isinstance(field, DateField):
        try:
            wanted = date.fromisoformat(value) if isinstance(value, str) else None
        except ValueError:
            return False
        return wanted is not None and wanted in _dates_in(line.text)
    if isinstance(field, EnumField):
        option = next((o for o in field.options if o.value == value), None)
        if option is None:
            return False
        return any(_contains_term(line.text, term) for term in [option.value, *option.synonyms])
    return False


def _text_match(value: str, lines: list[OcrLine]) -> list[OcrLine] | None:
    """The best run of 1–3 consecutive lines on one page that contains the text (long values wrap over lines)."""
    wanted = " ".join(value.split()).lower()
    if len(wanted) < 3:
        return None
    for size in (1, 2, 3):
        best: tuple[float, list[OcrLine]] | None = None
        for i in range(len(lines) - size + 1):
            run = lines[i : i + size]
            if any(line.page != run[0].page for line in run):
                continue
            joined = " ".join(" ".join(line.text.split()) for line in run).lower()
            if len(joined) < len(wanted):
                continue  # partial_ratio scores a short line inside a long value as 100; the lines must cover the value
            score = fuzz.partial_ratio(wanted, joined)
            if score >= TEXT_MATCH_MIN and (best is None or score > best[0]):
                best = (score, run)
        if best is not None:
            return best[1]
    return None


def checkable(field: Any) -> bool:
    """Booleans have no text of their own to find on the page; their colour rests on confidence alone."""
    return not isinstance(field, BooleanField)


def find_sources(field: Any, value: Any, lines: list[OcrLine]) -> list[dict[str, Any]]:
    """[{"page": 1, "box": [x0, y0, x1, y1]}] for every place the value was found; empty when it was not found."""
    if value is None or not checkable(field):
        return []
    if isinstance(field, TextField):
        if not isinstance(value, str):
            return []
        run = _text_match(value, lines)
        return [_source(run)] if run else []
    return [_source([line]) for line in lines if _single_line_match(field, value, line)]
