"""PHI safety net (spec §5.2 step 1): identifiers the OCR can still read on a page that should be redacted.

On-device redaction is the primary control; this is the backstop, and any hit quarantines the record.
The detection rules match web/src/redaction/labels.ts. Both are tested against server/tests/fixtures/phi_cases.json.
"""

import re
from dataclasses import dataclass

from capture.extraction.ocr import OcrLine

REDACTION_LABELS = [
    "Name", "Patient", "Pt", "Mobile", "Mob", "Phone", "Cell", "Contact", "Address", "Addr",
    "Father", "Husband", "Guardian", "S/O", "D/O", "W/O", "Reg", "Registration", "ID", "MRN", "UHID", "NID",
]
# Labels that introduce an identifier wherever they stand in a line. The rest (Patient, Pt, Cell, Contact, ...)
# also occur in clinical prose, so mid-line they only count when followed by a colon.
MIDLINE_LABELS = [
    "Name", "Father", "Husband", "Guardian", "Mobile", "Phone", "Address",
    "Registration", "MRN", "UHID", "NID", "S/O", "D/O", "W/O",
]


def _alternation(labels: list[str], *, any_case: bool = False) -> str:
    variants = {
        v
        for label in labels
        for v in ((label, label.upper(), label.lower(), label.capitalize()) if any_case else (label,))
    }
    return "|".join(re.escape(v) for v in sorted(variants, key=len, reverse=True))


_ALL = _alternation(REDACTION_LABELS)
# 1. a label at the start of the line ("Patient Name: ...", "Mobile 017...")
_AT_START = re.compile(rf"^[^A-Za-z0-9]*(?:{_ALL})(?![A-Za-z])", re.IGNORECASE)
# 2. a label anywhere, followed by a colon or '#', optionally via 's / No / Number / Name ("Reg No:", "Father's Name:")
_WITH_COLON = re.compile(rf"(?<![A-Za-z])(?:{_ALL})(?:'s)?\.?\s*(?:(?:No|Number|Name)\.?\s*)?[:#]", re.IGNORECASE)
# 3. an unambiguous label mid-line, followed by a capitalised word or a digit ("... Name Rahim Uddin")
_MIDLINE = re.compile(rf"(?<![A-Za-z])(?:{_alternation(MIDLINE_LABELS, any_case=True)})\s+(?=[A-Z0-9])")

_BENGALI_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
_DIGIT_SEPARATORS = re.compile(r"(?<=\d)[\s\-.()]{1,3}(?=\d)")
_MOBILE = re.compile(r"(?<!\d)(?:\+?88)?01[3-9]\d{8}(?!\d)")
_NID = re.compile(r"(?<![\d.,])(?:\d{17}|\d{13}|\d{10})(?!\d|[.,]\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

KIND_TEXT = {
    "mobile": "mobile number",
    "nid": "ID number",
    "email": "email address",
    "label": "name or ID label with text after it",
}


def label_ends(text: str) -> list[int]:
    """Where each label found in the line ends (empty when the line has no label)."""
    ends = [m.end() for rule in (_AT_START, _WITH_COLON, _MIDLINE) for m in rule.finditer(text)]
    return sorted(set(ends))


def has_mobile(text: str) -> bool:
    return bool(_MOBILE.search(_DIGIT_SEPARATORS.sub("", text.translate(_BENGALI_DIGITS))))


def has_nid(text: str) -> bool:
    return bool(_NID.search(text.translate(_BENGALI_DIGITS)))


def has_email(text: str) -> bool:
    return bool(_EMAIL.search(text))


def has_labelled_text(text: str) -> bool:
    """A label followed by at least 3 letters: redacted values are black, so readable text after a label was left uncovered."""
    return any(sum(c.isalpha() for c in text[end:]) >= 3 for end in label_ends(text))


@dataclass(frozen=True)
class PhiHit:
    page: int
    kind: str  # one of KIND_TEXT
    box: tuple[int, int, int, int]


def phi_hits(lines: list[OcrLine]) -> list[PhiHit]:
    hits: list[PhiHit] = []
    checks = (("mobile", has_mobile), ("nid", has_nid), ("email", has_email), ("label", has_labelled_text))
    for line in lines:
        hits.extend(PhiHit(line.page, kind, line.box) for kind, check in checks if check(line.text))
    return hits


def describe(hits: list[PhiHit]) -> str:
    """'Possible patient details found: mobile number (page 1); ...' names the kinds and pages, never the text."""
    pages: dict[str, set[int]] = {}
    for hit in hits:
        pages.setdefault(hit.kind, set()).add(hit.page)
    parts = [f"{KIND_TEXT[kind]} (page {', '.join(str(p) for p in sorted(found))})" for kind, found in pages.items()]
    return "Possible patient details found: " + "; ".join(parts)
