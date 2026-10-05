# M3 — AI Extraction Worker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After an upload, a worker reads the pages, holds back any page where a patient identifier is still readable, and otherwise pre-fills the form with the AI's values. Each value is coloured by confidence and OCR match, and tapping a field shows where it was found. Hospital staff can release a false alarm, upload new photos, or stop waiting and fill the form by hand.

**Architecture:** One Python package with two entry points. The API process only adds rows to the `jobs` table (`capture/jobqueue.py`). The worker process (`python -m capture.worker`) claims jobs with `FOR UPDATE SKIP LOCKED` and runs each one:
1. PaddleOCR reads every page.
2. The PHI safety net (`extraction/phi.py`) can quarantine the record.
3. The vision-language model is called through vLLM's OpenAI-compatible API (`extraction/vlm.py`).
4. Each value's tokens give a per-field confidence (`extraction/spans.py`).
5. Each value is looked up in the OCR lines (`extraction/crosscheck.py`).
6. Every field gets a colour (`extraction/assemble.py`).

The pure modules are unit-tested. The worker, queue and API are tested against the embedded PostgreSQL, using fake OCR and a stub model server. The web app shows the colours, source boxes, quarantine, release, re-upload and "Fill by hand now". The dev server can run the worker in-process with real PaddleOCR and the stub model, and the Playwright story uses that mode.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 (`pgserver` in tests), httpx, Pillow, rapidfuzz, python-dateutil, PaddleOCR 3.7 + PaddlePaddle 3.3 (optional `ocr` extra, CPU), vLLM (OpenAI-compatible, not run locally). Web: React 19, TanStack Query 5, Tailwind 4, Vitest, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-04-data-capture-design.md`, milestone M3 of §13. Read §5 (extraction pipeline), §7 (data model), §8 (review workflow) and §11 (errors, testing).

**Depends on:** M1 and M2, merged on local `main` at `0ef5e9d`:
- `docs/superpowers/plans/2026-10-04-m1-server-core.md`
- `docs/superpowers/plans/2026-10-04-m2-web-capture.md`

**Pre-flight (2026-10-05):** this plan's code and tests, taken verbatim, were applied task by task to a scratch copy of `0ef5e9d`. Results:
- 514 server tests passed;
- the `paddle` test passed with the OCR extra;
- 150 web unit tests passed, and `tsc` was clean;
- the 10-test Playwright story passed, using real PaddleOCR and the stub model.

A failure during execution therefore points at the environment or a deviation, not at the plan's own code.

## Global Constraints

- **No third-party AI service.** The model is reached only at `CAPTURE_VLM_URL` (self-hosted vLLM). OCR runs locally (PaddleOCR on CPU).
- **The API never loads a model.** `capture.api` must not import `capture.extraction`, `paddleocr` or `capture.worker`. The API and the worker communicate only through the `jobs` table and shared storage.
- **Never log or store page text or field values outside `records`.** Logs, `jobs.last_error`, quarantine data and review-event comments name kinds, pages, boxes, ids and error types only. The quarantine summary reads like `Possible patient details found: mobile number (page 1)`.
- **Spec numbers, verbatim:**
  - 3 attempts per job;
  - a job locked for more than 10 minutes is reclaimable;
  - `CONFIDENCE_THRESHOLD` defaults to 0.85 (setting `confidence_threshold`);
  - text matches need `rapidfuzz.partial_ratio ≥ 85`;
  - OCR dates are read day-first;
  - the browser polls every 3 s while `processing`;
  - "Fill by hand now" is offered after 2 minutes;
  - quarantined files are deleted after 14 days.
- **Colour rule (spec §5.2 step 6):** 🔴 red fails validation; 🟡 amber has confidence < threshold **or** no OCR match; 🟢 green is matched and confident; ⚪ grey is empty.
- **The same PHI rules on both sides.** `server/capture/extraction/phi.py` and `web/src/redaction/labels.ts` implement the same label, mobile, NID and email rules. Both are tested against `server/tests/fixtures/phi_cases.json`.
- **Value paths** match the server everywhere: `lesions[0].long_axis_cm`.
- **Lock order:** take the record row lock before any job row lock, in the API and the worker alike.
- **UI copy from the spec, verbatim:** `Fill by hand now` · `Someone else changed this record — reload`.
- **Tests never need a GPU or PaddleOCR.** The one PaddleOCR test is marked `paddle`, is excluded by default, and runs with `uv run --extra ocr pytest -m paddle`.
- Every commit ends with the trailer line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Spec deviations

The controller writes these into the spec before Task 1, as was done for M2.

1. **Quarantined pages stay where they were stored.** Spec §7 lists `storage/quarantine/<record_id>/`. Files are already served only after a role and status check, so NSU cannot see a quarantined record's files. Moving them would open a crash window between the database and the disk.
2. **Environment names carry the existing prefix:** `CAPTURE_VLM_URL` and `CAPTURE_VLM_MODEL`, not `VLM_URL` and `VLM_MODEL`.
3. **New review-event actions:** `quarantine` (written by the worker, with no actor, shown as "System"), `release`, `reupload` and `fill_by_hand`. `review_events.actor_id` becomes nullable.
4. **"Fill by hand now"** is a transition: `processing → draft`. It sets `extraction_status = skipped`, cancels the job, and is refused for the first 2 minutes.
5. **Unavailable model server:** connection refused, connect timeout, 502, 503 or 504 does not use up one of the 3 attempts. The record stays `processing` (§11.2) until the model is back or someone chooses "Fill by hand now". Other failures use up an attempt, with a 30 s × attempt delay.
6. **Booleans are not cross-checked.** They have no text of their own on the page, so their colour rests on confidence alone. A value with no logprobs counts as not confident, so it is amber.
7. **NSU never sees the AI's own values.** NSU sees the colours and source boxes, plus an `edited` flag per field. AI values that the hospital changed or deleted may have held identifiers.
8. **The golden set in M3 is 20 typed synthetic documents.** Handwritten cases come later, from photos of handwritten made-up sheets (see `eval/README.md`).
9. **The default model** is `Qwen/Qwen3-VL-8B-Instruct`. Use an AWQ 4-bit variant on GPUs under 24 GB; the GPU size is still open item §12.2.

## Review Focus

1. **The model returns extra keys, wrong types or out-of-range numbers** (`"long_axis_cm": 25`, `"2.3 cm"`, an unknown field). Expected: the values keep the template's shape, the bad value is shown red, and the user can fix it and submit. An unknown key must never block submission. Pinned in Task 4 (`conform` and the colour tests).
2. **Someone acts on a record while the worker is reading it.** For example, the user chooses "Fill by hand now", or a worker comes back after its job was reclaimed. Expected: the late result is dropped and the user's draft stays as it is. Pinned in Task 7.
3. **The same value written differently on the page:** `01/09/2026`, `1 Sep 2026`, `2026-09-01`, `2·3`, `2,3`, `23 mm` for a cm field, `right upper lobe` for `RUL`, a sentence wrapped over two lines. Expected: each is found and the field is green. Pinned in Task 4.
4. **Clinical prose that looks like a label** (`small cell carcinoma`, `in contact with the pleura`, `Regular margins`) must not quarantine. Real identifiers in odd formats must quarantine: `017-1234-5678`, `(017) 1234.5678`, Bengali digits, 10-, 13- or 17-digit IDs, `Name Rahim` mid-line. Pinned in Task 1, and in Task 2 for the web.
5. **NSU never sees AI values the hospital removed.** If the AI copied text that the uploader then deleted, an NSU reviewer must not be able to read it from `extraction`. Pinned in Task 8.

## File Map

```
server/
  pyproject.toml                           + httpx, pillow, rapidfuzz, python-dateutil; [ocr] extra; paddle marker   Tasks 4, 5, 9
  capture/config.py                        + model, threshold, worker and OCR settings                                Tasks 5, 7, 9
  capture/extraction/__init__.py           (empty)                                                                   Task 1
  capture/extraction/ocr.py                OcrLine, OcrEngine                                                        Task 1
  capture/extraction/phi.py                PHI safety net                                                            Task 1
  capture/extraction/schema.py             JSON schema + prompt from a template                                      Task 3
  capture/extraction/spans.py              value spans in the model's JSON + per-field confidence                    Task 3
  capture/extraction/crosscheck.py         find each value in the OCR lines                                          Task 4
  capture/extraction/assemble.py           conform the answer to the template; colours                               Task 4
  capture/extraction/vlm.py                vLLM client                                                               Task 5
  capture/extraction/stub.py               stub model server (dev server, e2e, tests)                                Task 5
  capture/extraction/paddle.py             PaddleOCR engine (worker only)                                            Task 9
  capture/db/models.py                     JobStatus, Job.run_after / skip_safety_net, nullable event actor, SKIPPED Task 6
  migrations/versions/0003_worker.py                                                                                 Task 6
  capture/jobqueue.py                      queue: add, claim, lock, retry, give up, cancel                           Task 6
  capture/worker/__init__.py, process.py   one job: OCR → safety net → model → result                                Task 7
  capture/worker/loop.py                   worker loop + housekeeping (abandoned jobs, 14-day expiry)                Task 7
  capture/worker/__main__.py               python -m capture.worker                                                  Task 9
  capture/storage.py                       remove_stored; save_page suffix                                           Tasks 7, 8
  capture/records/service.py               queue via jobqueue; replace_pages; detail extras                          Tasks 6, 8
  capture/workflow/rules.py                release, fill_by_hand                                                     Task 8
  capture/api/routes_records.py            transition side effects; POST /records/{id}/reupload                      Task 8
  capture/api/schemas.py, convert.py       quarantine, extraction view, queued-at, "System" actor                    Tasks 6, 8
  capture/devserver.py                     --worker off|stub|vlm                                                     Task 9
  capture/evaluation.py, cli.py            capture eval                                                              Task 10
  README.md                                worker, OCR extra, eval                                                   Tasks 9, 10
  tests/fixtures/phi_cases.json            shared with the web app                                                   Task 1
  tests/fakes.py                           FakeOcr, stub_vlm, run_once                                               Task 7
  tests/test_phi.py  test_extraction_schema.py  test_crosscheck.py  test_vlm.py  test_jobqueue.py
  tests/test_worker.py  test_quarantine_api.py  test_paddle_ocr.py  test_evaluation.py
eval/make_golden.py, README.md, golden/<template>/case-NN/{page-1.jpg, expected.json}                                Task 10
web/
  src/redaction/labels.ts, labels.test.ts                                                                            Task 2
  src/api/types.ts                                                                                                   Task 11
  src/records/aiMarkers.ts (+test), FormRenderer.tsx (+test), PageViewer.tsx, RecordPage.tsx, permissions.ts (+test) Tasks 11, 12
  src/ui/useNow.ts                                                                                                   Task 11
  src/home/HomePage.tsx                                                                                              Tasks 11, 12
  src/capture/RedactStep.tsx (+test), CapturePage.tsx, ReuploadPage.tsx; src/App.tsx                                 Task 12
  playwright.config.ts, e2e/flow.spec.ts                                                                             Tasks 11, 12
```

Commands:
- Server tests: `cd server && uv run pytest -q` (313 tests at the start of M3).
- Web, from `web/`: `npm test` (111 tests), `npm run typecheck`, `npm run e2e`.

---
### Task 1: PHI safety net and the shared detection cases

**Files:**
- Create: `server/capture/extraction/__init__.py` (empty), `server/capture/extraction/ocr.py`, `server/capture/extraction/phi.py`, `server/tests/fixtures/phi_cases.json`
- Test: `server/tests/test_phi.py`

**Interfaces:**
- Produces:
  - `ocr.py`: `OcrLine(page: int, text: str, box: tuple[int, int, int, int])` (frozen dataclass; 1-based page; box = x0, y0, x1, y1 in the stored page's pixels); `OcrEngine` Protocol with `read(page: int, image: bytes) -> list[OcrLine]`.
  - `phi.py`: `REDACTION_LABELS`, `MIDLINE_LABELS`, `KIND_TEXT`, `label_ends(text) -> list[int]`, `has_mobile(text) -> bool`, `has_nid(text) -> bool`, `has_email(text) -> bool`, `has_labelled_text(text) -> bool`, `PhiHit(page, kind, box)` (frozen dataclass), `phi_hits(lines: list[OcrLine]) -> list[PhiHit]`, `describe(hits) -> str`.
  - `phi_cases.json`: a list of `{"text", "label", "mobile", "nid", "email", "hit"}`. Task 2's web test reads the same file.

- [ ] **Step 1: Write the shared cases and the failing test**

`server/tests/fixtures/phi_cases.json` (UTF-8; the Bengali line is intentional):

```json
[
  {"text": "Patient Name: Test Person", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "Mobile: 01712345678", "label": true, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "Mobile:01712345678", "label": true, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "Reg No: AMH-00123", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "Reg No:", "label": true, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Name:", "label": true, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Cell: 017-1234-5678", "label": true, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "Contact (017) 1234.5678", "label": true, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "Tel +880 1712-345678", "label": false, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "মোবাইল ০১৭১২৩৪৫৬৭৮", "label": false, "mobile": true, "nid": false, "email": false, "hit": true},
  {"text": "NID 1234567890", "label": true, "mobile": false, "nid": true, "email": false, "hit": true},
  {"text": "Smart card 19901234567890123", "label": false, "mobile": false, "nid": true, "email": false, "hit": true},
  {"text": "Email rahim.uddin@example.com", "label": false, "mobile": false, "nid": false, "email": true, "hit": true},
  {"text": "Age 54 Sex M Name Rahim Uddin", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "Father's Name: Abdul Karim", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "MRN 445566", "label": true, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Patient is a 60 year old smoker", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Histology: small cell carcinoma", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "The mass is in contact with the pleura.", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Date: 01-09-2026 10:30", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "WBC 8000 Platelets 250000", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Impression: Suspicious for primary lung malignancy.", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "IDENTIFIED nodules are stable", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Regular margins, no calcification", "label": false, "mobile": false, "nid": false, "email": false, "hit": false},
  {"text": "Mobile number 01212345678", "label": true, "mobile": false, "nid": false, "email": false, "hit": true},
  {"text": "CEA 3.2 ng/mL (ref 0-5)", "label": false, "mobile": false, "nid": false, "email": false, "hit": false}
]
```

`"Patient is a 60 year old smoker"` is a deliberate false alarm. The spec's rule flags a label followed by 3 or more letters. Prose that starts with "Patient" at the beginning of an OCR line is quarantined, and a doctor releases it. That is the accepted cost of the backstop.

`server/tests/test_phi.py`:

```python
import json
from pathlib import Path

import pytest

from capture.extraction import phi
from capture.extraction.ocr import OcrLine

CASES = json.loads((Path(__file__).parent / "fixtures" / "phi_cases.json").read_text(encoding="utf-8"))
IDS = [case["text"] for case in CASES]


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_detection_matches_the_shared_cases(case):
    text = case["text"]
    found = {
        "label": bool(phi.label_ends(text)),
        "mobile": phi.has_mobile(text),
        "nid": phi.has_nid(text),
        "email": phi.has_email(text),
    }
    assert found == {key: case[key] for key in ("label", "mobile", "nid", "email")}


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_the_safety_net_flags_exactly_the_shared_hits(case):
    assert bool(phi.phi_hits([OcrLine(1, case["text"], (0, 0, 10, 10))])) is case["hit"]


def test_hits_carry_page_kind_and_box_and_skip_clean_lines():
    hits = phi.phi_hits(
        [
            OcrLine(2, "Mobile: 01712345678", (5, 6, 70, 18)),
            OcrLine(2, "Findings: 2.3 cm mass", (5, 30, 90, 42)),
        ]
    )
    assert hits == [phi.PhiHit(2, "mobile", (5, 6, 70, 18))]


def test_a_line_can_have_several_kinds_of_hit():
    kinds = [hit.kind for hit in phi.phi_hits([OcrLine(1, "Name: Rahim 01712345678", (0, 0, 1, 1))])]
    assert kinds == ["mobile", "label"]


def test_the_summary_names_kinds_and_pages_but_never_the_text():
    box = (0, 0, 1, 1)
    hits = [phi.PhiHit(1, "mobile", box), phi.PhiHit(3, "mobile", box), phi.PhiHit(2, "label", box)]
    assert phi.describe(hits) == (
        "Possible patient details found: mobile number (page 1, 3); name or ID label with text after it (page 2)"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd server && uv run pytest tests/test_phi.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.extraction'`.

- [ ] **Step 3: Write the implementation**

`server/capture/extraction/__init__.py`: an empty file.

`server/capture/extraction/ocr.py`:

```python
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
```

`server/capture/extraction/phi.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_phi.py -q`
Expected: 57 passed (27 cases × 2, plus 3 more tests).

Run: `cd server && uv run pytest -q`
Expected: all pass (313 + 57).

- [ ] **Step 5: Commit**

```bash
git add server/capture/extraction server/tests/fixtures/phi_cases.json server/tests/test_phi.py
git commit -m "feat(worker): PHI safety net with detection cases shared with the web app

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Web redaction hints follow the same rules

On-device boxes now cover what the server net would flag:
- mobile numbers with `.` or `()` separators, and in Bengali digits;
- 10-, 13- and 17-digit ID numbers;
- email addresses;
- unambiguous labels in the middle of a line.

This closes the M2 deferral "label/mobile gaps → M3".

**Files:**
- Modify: `web/src/redaction/labels.ts` (whole file below)
- Test: `web/src/redaction/labels.test.ts`

**Interfaces:**
- Consumes: `server/tests/fixtures/phi_cases.json` (Task 1).
- Produces: `labels.ts` exports `REDACTION_LABELS`, `MIDLINE_LABELS`, `hasLabel`, `hasMobile`, `hasNid`, `hasEmail`, `lineNeedsRedaction(text)` and `suggestBoxes(lines, pad?)`. The last two keep their M2 signatures; `RedactStep` is unchanged.

- [ ] **Step 1: Add the failing shared-case test**

Append to `web/src/redaction/labels.test.ts`. Keep the existing tests: the import line changes, and a new `describe` block is added at the end.

```ts
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { hasEmail, hasLabel, hasMobile, hasNid, lineNeedsRedaction, suggestBoxes } from "./labels";
```

(replace the file's first two import lines with the three above), then at the end of the file:

```ts
interface SharedCase {
  text: string;
  label: boolean;
  mobile: boolean;
  nid: boolean;
  email: boolean;
}

// The same cases the server's PHI safety net is tested against (server/tests/test_phi.py).
const CASES: SharedCase[] = JSON.parse(
  readFileSync(new URL("../../../server/tests/fixtures/phi_cases.json", import.meta.url), "utf8"),
);

describe("matches the server's PHI safety net", () => {
  it.each(CASES)("$text", (c) => {
    expect({ label: hasLabel(c.text), mobile: hasMobile(c.text), nid: hasNid(c.text), email: hasEmail(c.text) }).toEqual({
      label: c.label,
      mobile: c.mobile,
      nid: c.nid,
      email: c.email,
    });
    expect(lineNeedsRedaction(c.text)).toBe(c.label || c.mobile || c.nid || c.email);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd web && npx vitest run src/redaction/labels.test.ts`
Expected: FAIL. `hasLabel` is not exported (TypeError: hasLabel is not a function), and the new mobile and NID cases fail.

- [ ] **Step 3: Replace `web/src/redaction/labels.ts`**

```ts
import type { Rect } from "../imaging/geometry";

/** Line labels that introduce patient identifiers (spec §4.3). */
export const REDACTION_LABELS = [
  "Name", "Patient", "Pt", "Mobile", "Mob", "Phone", "Cell", "Contact", "Address", "Addr",
  "Father", "Husband", "Guardian", "S/O", "D/O", "W/O", "Reg", "Registration", "ID", "MRN", "UHID", "NID",
];
/** Labels that introduce an identifier anywhere in a line. The others also occur in clinical prose. */
export const MIDLINE_LABELS = [
  "Name", "Father", "Husband", "Guardian", "Mobile", "Phone", "Address",
  "Registration", "MRN", "UHID", "NID", "S/O", "D/O", "W/O",
];

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const capitalize = (s: string) => s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();

function alternation(labels: string[], anyCase = false): string {
  const variants = new Set(labels.flatMap((l) => (anyCase ? [l, l.toUpperCase(), l.toLowerCase(), capitalize(l)] : [l])));
  return [...variants].sort((a, b) => b.length - a.length).map(escape).join("|");
}

// The same three rules as server/capture/extraction/phi.py; both are tested against server/tests/fixtures/phi_cases.json.
const ALL = alternation(REDACTION_LABELS);
const AT_START = new RegExp(`^[^A-Za-z0-9]*(?:${ALL})(?![A-Za-z])`, "i");
const WITH_COLON = new RegExp(`(?<![A-Za-z])(?:${ALL})(?:'s)?\\.?\\s*(?:(?:No|Number|Name)\\.?\\s*)?[:#]`, "i");
const MIDLINE = new RegExp(`(?<![A-Za-z])(?:${alternation(MIDLINE_LABELS, true)})\\s+(?=[A-Z0-9])`);

const BENGALI_ZERO = 0x09e6;
const toAsciiDigits = (s: string) => s.replace(/[০-৯]/g, (d) => String(d.charCodeAt(0) - BENGALI_ZERO));
const DIGIT_SEPARATORS = /(?<=\d)[\s\-.()]{1,3}(?=\d)/g;
const BD_MOBILE = /(?<!\d)(?:\+?88)?01[3-9]\d{8}(?!\d)/;
const NID = /(?<![\d.,])(?:\d{17}|\d{13}|\d{10})(?!\d|[.,]\d)/;
const EMAIL = /[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}/;

export const hasLabel = (text: string): boolean => AT_START.test(text) || WITH_COLON.test(text) || MIDLINE.test(text);
export const hasMobile = (text: string): boolean => BD_MOBILE.test(toAsciiDigits(text).replace(DIGIT_SEPARATORS, ""));
export const hasNid = (text: string): boolean => NID.test(toAsciiDigits(text));
export const hasEmail = (text: string): boolean => EMAIL.test(text);

export interface OcrLine {
  text: string;
  bbox: { x0: number; y0: number; x1: number; y1: number };
}

export function lineNeedsRedaction(text: string): boolean {
  return hasLabel(text) || hasMobile(text) || hasNid(text) || hasEmail(text);
}

export function suggestBoxes(lines: OcrLine[], pad = 6): Rect[] {
  return lines
    .filter((line) => lineNeedsRedaction(line.text))
    .map(({ bbox }) => {
      const x = Math.max(0, bbox.x0 - pad);
      const y = Math.max(0, bbox.y0 - pad);
      return { x, y, w: bbox.x1 + pad - x, h: bbox.y1 + pad - y };
    });
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/redaction/labels.test.ts`
Expected: PASS. The existing 19 cases still pass ("Region of interest…", "Identification of a new nodule" and the rest), plus 27 shared cases.

Run: `cd web && npm test && npm run typecheck`
Expected: all pass (138: 111 + 27 shared cases), and no type errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/redaction/labels.ts web/src/redaction/labels.test.ts
git commit -m "feat(web): redaction hints follow the server's PHI rules (separators, Bengali digits, IDs, email)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: What the model is asked, and how sure it was of each value

**Files:**
- Create: `server/capture/extraction/schema.py`, `server/capture/extraction/spans.py`
- Test: `server/tests/test_extraction_schema.py`

**Interfaces:**
- Consumes: `capture.formschema.model` (`TemplateDef`, the field classes; every field has `.key`, `.label`, `.hint` and `.source`).
- Produces:
  - `schema.py`:
    - `SYSTEM_PROMPT: str`;
    - `json_schema_for(tpl: TemplateDef) -> dict` (every non-DICOM field is required and nullable; `additionalProperties: false`);
    - `prompt_for(tpl: TemplateDef) -> str`.
  - `spans.py`:
    - `Token(text_bytes: bytes, logprob: float)` (frozen dataclass);
    - `leaf_spans(text: str) -> dict[str, tuple[int, int]]` (character spans keyed by value path; raises `ValueError` on malformed JSON);
    - `field_confidences(text: str, tokens: list[Token] | None) -> dict[str, float]` (empty when there are no logprobs or they do not line up).

- [ ] **Step 1: Write the failing tests**

`server/tests/test_extraction_schema.py`:

```python
import math

import pytest
import yaml

from capture.extraction.schema import json_schema_for, prompt_for
from capture.extraction.spans import Token, field_confidences, leaf_spans
from capture.formschema.model import TemplateDef
from constants import TEMPLATES_DIR


def template(key: str) -> TemplateDef:
    return TemplateDef.model_validate(yaml.safe_load((TEMPLATES_DIR / f"{key}.yaml").read_text(encoding="utf-8")))


RADIOLOGY = template("radiology_report")


def test_every_field_is_required_and_nullable_and_nothing_else_is_allowed():
    schema = json_schema_for(RADIOLOGY)
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == [f.key for f in RADIOLOGY.fields]
    assert schema["properties"]["modality"] == {
        "anyOf": [{"type": "string", "enum": ["CT", "MRI", "X-ray", "PET-CT"]}, {"type": "null"}]
    }
    assert schema["properties"]["study_date"] == {
        "anyOf": [{"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"}, {"type": "null"}]
    }
    assert schema["properties"]["contrast"] == {"anyOf": [{"type": "boolean"}, {"type": "null"}]}


def test_repeat_groups_are_lists_of_closed_objects():
    lesions = json_schema_for(RADIOLOGY)["properties"]["lesions"]["anyOf"][0]
    assert lesions["type"] == "array"
    assert lesions["items"]["required"] == ["lobe", "long_axis_cm", "short_axis_cm", "description"]
    assert lesions["items"]["additionalProperties"] is False


def test_numbers_have_no_range_so_out_of_range_values_reach_the_reviewer():
    lesion = json_schema_for(RADIOLOGY)["properties"]["lesions"]["anyOf"][0]["items"]
    assert lesion["properties"]["long_axis_cm"] == {"anyOf": [{"type": "number"}, {"type": "null"}]}


def test_fields_read_from_dicom_headers_are_left_out():
    schema = json_schema_for(template("dicom_series"))
    assert schema["properties"] == {}
    assert schema["required"] == []


def test_the_prompt_lists_fields_options_synonyms_units_and_the_rules():
    prompt = prompt_for(RADIOLOGY)
    assert "RUL (also written: right upper lobe, rt upper lobe)" in prompt
    assert "- long_axis_cm: Long axis; number in cm (convert if the document uses another unit)" in prompt
    assert "  - lobe: Lobe;" in prompt  # group members are indented under their group
    assert "day first (DD/MM/YYYY)" in prompt
    assert "Do not infer" in prompt


def test_film_prompts_read_only_the_text_on_the_film():
    assert "Read only the text printed or burned into the image" in prompt_for(template("xray_film_photo"))


def test_leaf_spans_point_at_each_scalar_value():
    text = '{"a": "x", "b": [ {"c": 1.5}, {"c": null} ], "d": {"e": true}}'
    spans = leaf_spans(text)
    assert set(spans) == {"a", "b[0].c", "b[1].c", "d.e"}
    assert text[slice(*spans["a"])] == '"x"'
    assert text[slice(*spans["b[0].c"])] == "1.5"
    assert text[slice(*spans["b[1].c"])] == "null"
    assert text[slice(*spans["d.e"])] == "true"


@pytest.mark.parametrize("bad", ['{"a": 1', '{"a": 1} trailing', '{"a" 1}', "[1, 2"])
def test_leaf_spans_reject_malformed_json(bad):
    with pytest.raises(ValueError):
        leaf_spans(bad)


def test_confidence_is_the_geometric_mean_of_the_value_tokens():
    text = '{"a": 12}'
    tokens = [Token(b'{"a": ', math.log(0.9)), Token(b"1", math.log(0.8)), Token(b"2", math.log(0.5)), Token(b"}", 0.0)]
    assert field_confidences(text, tokens)["a"] == pytest.approx(math.sqrt(0.8 * 0.5))


def test_tokens_split_inside_a_character_still_line_up_by_bytes():
    text = '{"a": "রহিম"}'
    raw = text.encode("utf-8")
    tokens = [Token(raw[:7], 0.0), Token(raw[7:9], math.log(0.5)), Token(raw[9:], 0.0)]
    assert field_confidences(text, tokens)["a"] == pytest.approx(0.5 ** (1 / 3))


def test_no_logprobs_or_mismatched_tokens_give_no_confidence():
    assert field_confidences('{"a": 1}', None) == {}
    assert field_confidences('{"a": 1}', [Token(b'{"a": 2}', 0.0)]) == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_extraction_schema.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.extraction.schema'`.

- [ ] **Step 3: Write `server/capture/extraction/schema.py`**

```python
"""What the vision-language model is asked (spec §5.2 step 2): a JSON schema and a prompt generated from the template."""

from typing import Any

from capture.formschema.model import BooleanField, DateField, EnumField, GroupField, NumberField, TemplateDef, TextField

SYSTEM_PROMPT = (
    "You copy information from photos of hospital documents into a JSON form. "
    "Copy only what is written. Return null for anything that is not present. Do not infer, guess or calculate."
)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(fields: list) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {f.key: _field_schema(f) for f in fields if f.source is None},
        "required": [f.key for f in fields if f.source is None],
        "additionalProperties": False,
    }


def _field_schema(f: Any) -> dict[str, Any]:
    if isinstance(f, TextField):
        return _nullable({"type": "string"})
    if isinstance(f, NumberField):
        # No minimum/maximum: an out-of-range value must reach the reviewer (shown red), not be bent into range.
        return _nullable({"type": "number"})
    if isinstance(f, DateField):
        return _nullable({"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"})
    if isinstance(f, EnumField):
        return _nullable({"type": "string", "enum": [o.value for o in f.options]})
    if isinstance(f, BooleanField):
        return _nullable({"type": "boolean"})
    if isinstance(f, GroupField):
        item = _object(f.fields)
        return _nullable({"type": "array", "items": item} if f.repeat else item)
    raise TypeError(f"unsupported field {f!r}")


def json_schema_for(tpl: TemplateDef) -> dict[str, Any]:
    """Every field is present in the output; absent information is null. Fields filled from DICOM headers are left out."""
    return _object(tpl.fields)


def _describe(f: Any, indent: str) -> list[str]:
    label = f.label or f.key.replace("_", " ")
    if isinstance(f, GroupField):
        kind = "a list of items, one per" if f.repeat else "a group:"
        lines = [f"{indent}- {f.key}: {kind} {label.lower()}"]
        for sub in f.fields:
            if sub.source is None:
                lines.extend(_describe(sub, indent + "  "))
        return lines
    detail = {
        TextField: "text, copied as written",
        NumberField: "number",
        DateField: "date as YYYY-MM-DD",
        BooleanField: "true or false",
    }.get(type(f), "")
    if isinstance(f, NumberField) and f.unit:
        detail = f"number in {f.unit} (convert if the document uses another unit)"
    if isinstance(f, EnumField):
        options = [f"{o.value} (also written: {', '.join(o.synonyms)})" if o.synonyms else o.value for o in f.options]
        detail = "one of: " + "; ".join(options)
    hint = f" — {f.hint}" if f.hint else ""
    return [f"{indent}- {f.key}: {label}; {detail}{hint}"]


def prompt_for(tpl: TemplateDef) -> str:
    if tpl.kind == "film_photo":
        intro = (
            f"The images are photos of a medical imaging film or screen ({tpl.title}). "
            "Read only the text printed or burned into the image, such as dates, view and side markers."
        )
    else:
        intro = f"The images are the pages of one document: {tpl.title}."
    lines = [
        intro,
        "Dates in these documents are written day first (DD/MM/YYYY). Write every date as YYYY-MM-DD.",
        "Fill these fields:",
    ]
    for f in tpl.fields:
        if f.source is None:
            lines.extend(_describe(f, ""))
    lines.append("Return null for any field that is not in the document. Do not infer.")
    return "\n".join(lines)
```

- [ ] **Step 4: Write `server/capture/extraction/spans.py`**

```python
"""Per-field confidence (spec §5.2 step 3): map each value in the model's JSON output to its tokens.

confidence = geometric mean of the probabilities of the tokens that overlap the value's text.
Tokens are matched by bytes, because a tokenizer can split one character over several tokens.
"""

import json
import math
from dataclasses import dataclass

_WHITESPACE = " \t\r\n"
_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class Token:
    text_bytes: bytes
    logprob: float


def leaf_spans(text: str) -> dict[str, tuple[int, int]]:
    """Character span of every scalar value in a JSON document, keyed by value path ("lesions[0].lobe").

    Raises ValueError when the text is not one well-formed JSON value.
    """
    spans: dict[str, tuple[int, int]] = {}

    def skip(i: int) -> int:
        while i < len(text) and text[i] in _WHITESPACE:
            i += 1
        return i

    def expect(i: int, char: str) -> int:
        if i >= len(text) or text[i] != char:
            raise ValueError(f"expected {char!r} at {i}")
        return i + 1

    def value(i: int, path: str) -> int:
        i = skip(i)
        if i >= len(text):
            raise ValueError("unexpected end")
        if text[i] == "{":
            i = skip(i + 1)
            if i < len(text) and text[i] == "}":
                return i + 1
            while True:
                key, i = _DECODER.raw_decode(text, skip(i))
                if not isinstance(key, str):
                    raise ValueError("object keys must be strings")
                i = skip(value(expect(skip(i), ":"), f"{path}.{key}" if path else key))
                if i < len(text) and text[i] == ",":
                    i += 1
                    continue
                return expect(i, "}")
        if text[i] == "[":
            i = skip(i + 1)
            if i < len(text) and text[i] == "]":
                return i + 1
            index = 0
            while True:
                i = skip(value(i, f"{path}[{index}]"))
                index += 1
                if i < len(text) and text[i] == ",":
                    i += 1
                    continue
                return expect(i, "]")
        _, end = _DECODER.raw_decode(text, i)
        spans[path] = (i, end)
        return end

    if skip(value(0, "")) != len(text):
        raise ValueError("trailing text after the JSON value")
    return spans


def field_confidences(text: str, tokens: list[Token] | None) -> dict[str, float]:
    """Confidence per value path. Empty when there are no token logprobs or they do not line up with the text."""
    if not tokens or b"".join(t.text_bytes for t in tokens) != text.encode("utf-8"):
        return {}
    try:
        spans = leaf_spans(text)
    except ValueError:
        return {}
    starts: list[int] = []
    offset = 0
    for token in tokens:
        starts.append(offset)
        offset += len(token.text_bytes)
    result: dict[str, float] = {}
    for path, (start, end) in spans.items():
        lo, hi = len(text[:start].encode("utf-8")), len(text[:end].encode("utf-8"))
        logprobs = [t.logprob for t, s in zip(tokens, starts) if s < hi and s + len(t.text_bytes) > lo]
        if logprobs:
            result[path] = math.exp(sum(logprobs) / len(logprobs))
    return result
```

`json.JSONDecoder.raw_decode` raises `json.JSONDecodeError`, which is a `ValueError`. So the malformed-input test is covered without extra handling.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_extraction_schema.py -q`
Expected: 14 passed.

- [ ] **Step 6: Commit**

```bash
git add server/capture/extraction/schema.py server/capture/extraction/spans.py server/tests/test_extraction_schema.py
git commit -m "feat(worker): JSON schema and prompt from a template; per-field confidence from token logprobs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Cross-check against the OCR, and field colours

**Files:**
- Modify: `server/pyproject.toml` (add `rapidfuzz` and `python-dateutil`)
- Create: `server/capture/extraction/crosscheck.py`, `server/capture/extraction/assemble.py`
- Test: `server/tests/test_crosscheck.py`

**Interfaces:**
- Consumes: `OcrLine` (Task 1); `capture.formschema.model`; `capture.formschema.validate.validate_values` (existing; returns `[{"path", "message"}]`).
- Produces:
  - `crosscheck.py`:
    - `TEXT_MATCH_MIN = 85`;
    - `checkable(field) -> bool` (False for booleans);
    - `find_sources(field, value, lines) -> list[dict]`, returning `[{"page": int, "box": [x0, y0, x1, y1]}]`.
  - `assemble.py`:
    - `GREEN, AMBER, RED, GREY`;
    - `conform(tpl, raw) -> dict` (the template's own fields only, in its shape, empty answers dropped);
    - `build_extraction(tpl, values, confidences, lines, errors, threshold, model) -> dict` (`{"model": str, "fields": {path: {"value", "confidence", "colour", "sources"}}}`).

- [ ] **Step 1: Add the dependencies**

```bash
cd server && uv add "rapidfuzz>=3.9" "python-dateutil>=2.9"
```

Expected: `pyproject.toml` lists both under `dependencies`, and `uv.lock` is updated.

- [ ] **Step 2: Write the failing tests**

`server/tests/test_crosscheck.py`:

```python
from datetime import date

import pytest
import yaml

from capture.extraction.assemble import AMBER, GREEN, GREY, RED, build_extraction, conform
from capture.extraction.crosscheck import checkable, find_sources
from capture.extraction.ocr import OcrLine
from capture.formschema.model import TemplateDef
from capture.formschema.validate import validate_values
from constants import TEMPLATES_DIR

RADIOLOGY = TemplateDef.model_validate(
    yaml.safe_load((TEMPLATES_DIR / "radiology_report.yaml").read_text(encoding="utf-8"))
)
LINES = [
    OcrLine(1, "CT CHEST REPORT", (60, 567, 441, 606)),
    OcrLine(1, "Date: 01/09/2026", (60, 666, 408, 708)),
    OcrLine(1, "Findings: 2.3 x 1.8 cm spiculated mass in right upper lobe.", (58, 765, 1199, 813)),
    OcrLine(2, "Impression: Suspicious for primary", (55, 100, 700, 140)),
    OcrLine(2, "lung malignancy.", (55, 150, 400, 190)),
]
FINDINGS_BOX = {"page": 1, "box": [58, 765, 1199, 813]}


def field(path: str):
    """The template field at a dotted path without indexes, e.g. 'lesions.long_axis_cm'."""
    fields = RADIOLOGY.fields
    *groups, key = path.split(".")
    for group in groups:
        fields = next(f for f in fields if f.key == group).fields
    return next(f for f in fields if f.key == key)


def one_line(text: str) -> list[OcrLine]:
    return [OcrLine(1, text, (0, 0, 10, 10))]


@pytest.mark.parametrize("text", ["2.3 x 1.8 cm", "2,3 cm", "2·3 cm", "2.30 cm", "23 x 18 mm"])
def test_numbers_match_after_formatting_and_unit_conversion(text):
    assert find_sources(field("lesions.long_axis_cm"), 2.3, one_line(text)) == [{"page": 1, "box": [0, 0, 10, 10]}]


def test_a_different_number_is_not_a_match():
    assert find_sources(field("lesions.long_axis_cm"), 2.4, one_line("2.3 x 1.8 cm")) == []


@pytest.mark.parametrize("text", ["Date: 01/09/2026", "Date: 01.09.26", "Seen on 1 Sep 2026", "on 2026-09-01", "01-09-2026 10:30"])
def test_dates_are_read_day_first(text):
    assert find_sources(field("study_date"), "2026-09-01", one_line(text)) != []


def test_a_month_first_reading_is_not_a_match():
    assert find_sources(field("study_date"), "2026-01-09", one_line("Date: 01/09/2026")) == []


def test_enum_values_match_by_value_or_synonym_as_whole_words():
    assert find_sources(field("lesions.lobe"), "RUL", LINES) == [FINDINGS_BOX]
    assert find_sources(field("modality"), "CT", LINES) == [{"page": 1, "box": [60, 567, 441, 606]}]
    assert find_sources(field("lesions.lobe"), "LLL", LINES) == []
    assert find_sources(field("modality"), "CT", one_line("ARTEFACT reduction")) == []


def test_text_matches_despite_ocr_typos():
    assert find_sources(field("lesions.description"), "spiculated mass", one_line("2.3 cm spicu1ated mass seen")) != []


def test_text_wrapped_over_two_lines_matches_both_lines():
    found = find_sources(field("impression"), "Suspicious for primary lung malignancy.", LINES)
    assert found == [{"page": 2, "box": [55, 100, 700, 190]}]


def test_a_short_line_inside_a_long_value_is_not_a_match():
    value = "spiculated mass with pleural tags in the right upper lobe"
    assert find_sources(field("lesions.description"), value, one_line("spiculated mass")) == []


def test_booleans_are_not_cross_checked():
    assert checkable(field("contrast")) is False
    assert find_sources(field("contrast"), True, LINES) == []


def test_conform_keeps_only_template_fields_in_the_template_shape():
    raw = {
        "modality": "CT",
        "unknown": 1,
        "lesions": [{"lobe": "RUL", "junk": 2}, "not an object", {}],
        "contrast": None,
        "impression": "   ",
        "lymph_nodes": {"wrong": "shape"},
    }
    assert conform(RADIOLOGY, raw) == {"modality": "CT", "lesions": [{"lobe": "RUL"}]}


def test_conform_keeps_wrong_types_for_the_reviewer_to_fix():
    assert conform(RADIOLOGY, {"lesions": [{"long_axis_cm": "2.3 cm"}]}) == {"lesions": [{"long_axis_cm": "2.3 cm"}]}
    assert conform(RADIOLOGY, ["not", "an", "object"]) == {}


def colours(values, confidences, lines=LINES):
    errors = validate_values(RADIOLOGY, values, date(2026, 10, 5))
    result = build_extraction(RADIOLOGY, values, confidences, lines, errors, 0.85, "test-model")
    assert result["model"] == "test-model"
    return result["fields"]


def test_colours_follow_the_spec_table():
    values = {
        "modality": "CT",
        "study_date": "2026-09-01",
        "lesions": [{"lobe": "RUL", "long_axis_cm": 25, "short_axis_cm": 1.8, "description": "spiculated mass"}],
        "impression": "Not written anywhere on the page",
    }
    sure = {path: 0.99 for path in ("modality", "lesions[0].lobe", "lesions[0].long_axis_cm", "lesions[0].short_axis_cm", "lesions[0].description", "impression")}
    fields = colours(values, {**sure, "study_date": 0.6})
    assert fields["modality"]["colour"] == GREEN  # found and confident
    assert fields["study_date"]["colour"] == AMBER  # found, but confidence 0.6 < 0.85
    assert fields["impression"]["colour"] == AMBER  # confident, but not on the page
    assert fields["lesions[0].long_axis_cm"]["colour"] == RED  # 25 is above the template's max of 20
    assert fields["contrast"]["colour"] == GREY  # empty
    assert fields["lesions[0].short_axis_cm"] == {"value": 1.8, "confidence": 0.99, "colour": GREEN, "sources": [FINDINGS_BOX]}


def test_a_value_without_a_confidence_is_amber():
    assert colours({"modality": "CT", "study_date": "2026-09-01"}, {})["modality"]["colour"] == AMBER


def test_a_required_field_left_empty_is_red():
    fields = colours({}, {})
    assert fields["modality"]["colour"] == RED
    assert fields["study_date"]["colour"] == RED


def test_a_confident_boolean_is_green_without_an_ocr_match():
    fields = colours({"modality": "CT", "study_date": "2026-09-01", "contrast": True}, {"contrast": 0.95})
    assert fields["contrast"]["colour"] == GREEN
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_crosscheck.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.extraction.assemble'`.

- [ ] **Step 4: Write `server/capture/extraction/crosscheck.py`**

```python
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
```

- [ ] **Step 5: Write `server/capture/extraction/assemble.py`**

```python
"""Turn the model's answer into form values and per-field results (spec §5.2 steps 5–7)."""

from typing import Any

from capture.extraction.crosscheck import checkable, find_sources
from capture.extraction.ocr import OcrLine
from capture.formschema.model import GroupField, TemplateDef

GREEN, AMBER, RED, GREY = "green", "amber", "red", "grey"


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or (isinstance(value, str) and not value.strip())


def _conform_object(fields: list, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for f in fields:
        if f.source is not None or f.key not in raw:
            continue
        value = raw[f.key]
        if isinstance(f, GroupField):
            if f.repeat:
                items = [_conform_object(f.fields, item) for item in value] if isinstance(value, list) else []
                value = [item for item in items if item]
            else:
                value = _conform_object(f.fields, value)
            if not value:
                continue
        elif isinstance(value, (dict, list)) or _is_empty(value):
            continue
        out[f.key] = value
    return out


def conform(tpl: TemplateDef, raw: Any) -> dict[str, Any]:
    """Keep only the template's own fields, in the template's shape, and drop empty answers.

    Scalars keep the model's type even when wrong ("2.3 cm" for a number): validation shows them red and the
    form lets the user correct them. Unknown keys would block submission, because the form cannot show them.
    """
    return _conform_object(tpl.fields, raw)


def _leaves(fields: list, values: dict[str, Any], prefix: str):
    for f in fields:
        if f.source is not None:
            continue
        path = f"{prefix}.{f.key}" if prefix else f.key
        value = values.get(f.key)
        if isinstance(f, GroupField):
            if f.repeat:
                for i, item in enumerate(value if isinstance(value, list) else []):
                    yield from _leaves(f.fields, item if isinstance(item, dict) else {}, f"{path}[{i}]")
            else:
                yield from _leaves(f.fields, value if isinstance(value, dict) else {}, path)
        else:
            yield path, f, value


def build_extraction(
    tpl: TemplateDef,
    values: dict[str, Any],
    confidences: dict[str, float],
    lines: list[OcrLine],
    errors: list[dict[str, str]],
    threshold: float,
    model: str,
) -> dict[str, Any]:
    """{"model": ..., "fields": {path: {"value", "confidence", "colour", "sources"}}} for every leaf field (spec §5.2 step 6)."""
    error_paths = {e["path"] for e in errors}
    fields: dict[str, Any] = {}
    for path, f, value in _leaves(tpl.fields, values, ""):
        confidence = confidences.get(path)
        sources = [] if _is_empty(value) else find_sources(f, value, lines)
        if path in error_paths:
            colour = RED
        elif _is_empty(value):
            colour = GREY
        elif confidence is None or confidence < threshold or (checkable(f) and not sources):
            colour = AMBER
        else:
            colour = GREEN
        fields[path] = {
            "value": value,
            "confidence": round(confidence, 4) if confidence is not None else None,
            "colour": colour,
            "sources": sources,
        }
    return {"model": model, "fields": fields}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_crosscheck.py -q`
Expected: 23 passed.

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server/pyproject.toml server/uv.lock server/capture/extraction/crosscheck.py server/capture/extraction/assemble.py server/tests/test_crosscheck.py
git commit -m "feat(worker): cross-check extracted values against OCR lines and colour each field

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The model client and the stub model server

**Files:**
- Modify: `server/pyproject.toml` (add `httpx` and `pillow` as runtime dependencies), `server/capture/config.py`
- Create: `server/capture/extraction/vlm.py`, `server/capture/extraction/stub.py`
- Test: `server/tests/test_vlm.py`

**Interfaces:**
- Consumes: `json_schema_for`, `prompt_for`, `SYSTEM_PROMPT` (Task 3); `Token`, `leaf_spans` (Task 3).
- Produces:
  - `config.Settings`: `vlm_url: str = "http://127.0.0.1:8001/v1"`, `vlm_model: str = "Qwen/Qwen3-VL-8B-Instruct"`, `vlm_timeout_s: float = 120`, `vlm_max_image_side: int = 1600`, `confidence_threshold: float = 0.85`.
  - `vlm.py`:
    - `VlmUnavailable` (no attempt used) and `VlmError` (attempt used);
    - `VlmAnswer(text: str, tokens: list[Token] | None, model: str)`;
    - `image_for_model(data: bytes, max_side: int) -> bytes`;
    - `VlmClient(url, model, *, timeout, max_image_side, transport=None)` with `.model`, `.request_body(tpl, pages) -> dict`, `.extract(tpl, pages: list[bytes]) -> VlmAnswer` and `.close()`;
    - `client_from_settings(settings, transport=None) -> VlmClient`.
  - `stub.py`: `STUB_MODEL`, `STUB_VALUES`, `UNSURE_PATHS`, `stub_completion(body: dict) -> dict`, `stub_transport() -> httpx.MockTransport`. The stub fills the radiology report from `web/e2e/fixtures/report.jpg` and is unsure of `lesions[0].short_axis_cm`. Any other template gets all nulls.

- [ ] **Step 1: Add the dependencies and settings**

```bash
cd server && uv add "httpx>=0.27" "pillow>=10.1"
```

`httpx` is already in the `dev` group. Keep it there as well; `uv add` moves the runtime requirement into `dependencies`.

In `server/capture/config.py`, add these fields at the end of `Settings`:

```python
    vlm_url: str = "http://127.0.0.1:8001/v1"  # vLLM's OpenAI-compatible API (self-hosted; spec §3)
    vlm_model: str = "Qwen/Qwen3-VL-8B-Instruct"  # an AWQ 4-bit variant on GPUs under 24 GB
    vlm_timeout_s: float = 120
    vlm_max_image_side: int = 1600  # pages are shrunk to this long side before they go to the model
    confidence_threshold: float = 0.85  # spec §5.2: below this a field is amber
```

- [ ] **Step 2: Write the failing tests**

`server/tests/test_vlm.py`:

```python
import io
import json

import httpx
import pytest
import yaml
from PIL import Image

from capture.extraction.spans import field_confidences
from capture.extraction.stub import STUB_VALUES, stub_completion, stub_transport
from capture.extraction.vlm import VlmClient, VlmError, VlmUnavailable, client_from_settings, image_for_model
from capture.formschema.model import TemplateDef
from constants import TEMPLATES_DIR

RADIOLOGY = TemplateDef.model_validate(
    yaml.safe_load((TEMPLATES_DIR / "radiology_report.yaml").read_text(encoding="utf-8"))
)


def jpeg(width: int, height: int) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def client(handler) -> VlmClient:
    return VlmClient("http://vlm.test/v1", "qwen-test", timeout=5, max_image_side=1600, transport=httpx.MockTransport(handler))


def test_the_request_carries_the_prompt_every_page_the_schema_and_logprobs():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=stub_completion(seen["body"]))

    client(handler).extract(RADIOLOGY, [jpeg(800, 600), jpeg(800, 600)])
    body = seen["body"]
    assert seen["url"] == "http://vlm.test/v1/chat/completions"
    assert (body["model"], body["temperature"], body["logprobs"]) == ("qwen-test", 0, True)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "radiology_report"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][0]["role"] == "system"
    content = body["messages"][1]["content"]
    assert content[0]["type"] == "text"
    assert "Return null for any field" in content[0]["text"]
    assert [part["type"] for part in content[1:]] == ["image_url", "image_url"]
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_the_stub_answer_comes_back_with_token_logprobs():
    stub = VlmClient("http://vlm.test/v1", "qwen-test", timeout=5, max_image_side=1600, transport=stub_transport())
    answer = stub.extract(RADIOLOGY, [jpeg(10, 10)])
    assert answer.model == "qwen-test"
    values = json.loads(answer.text)
    assert {k: v for k, v in values.items() if v is not None} == STUB_VALUES["radiology_report"]
    confidences = field_confidences(answer.text, answer.tokens)
    assert confidences["modality"] == pytest.approx(0.99)
    assert confidences["lesions[0].short_axis_cm"] < 0.85


def test_the_stub_answers_other_templates_with_nulls():
    body = {"response_format": {"json_schema": {"name": "lab_report", "schema": {"properties": {"report_date": {}, "results": {}}}}}}
    text = stub_completion(body)["choices"][0]["message"]["content"]
    assert json.loads(text) == {"report_date": None, "results": None}


def test_large_pages_are_shrunk_for_the_model_and_small_ones_sent_as_they_are():
    with Image.open(io.BytesIO(image_for_model(jpeg(3000, 2000), 1600))) as shrunk:
        assert shrunk.size == (1600, 1067)
    small = jpeg(800, 600)
    assert image_for_model(small, 1600) is small


@pytest.mark.parametrize("error", [httpx.ConnectError("refused"), httpx.ConnectTimeout("no answer")])
def test_an_unreachable_server_is_unavailable(error):
    def handler(request):
        raise error

    with pytest.raises(VlmUnavailable):
        client(handler).extract(RADIOLOGY, [jpeg(10, 10)])


@pytest.mark.parametrize("status", [502, 503, 504])
def test_a_busy_or_restarting_server_is_unavailable(status):
    with pytest.raises(VlmUnavailable):
        client(lambda request: httpx.Response(status)).extract(RADIOLOGY, [jpeg(10, 10)])


def test_a_slow_answer_uses_up_an_attempt():
    def handler(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(VlmError, match="took too long"):
        client(handler).extract(RADIOLOGY, [jpeg(10, 10)])


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{"modality": '}}]}),
    ],
)
def test_unusable_answers_are_errors(response):
    with pytest.raises(VlmError):
        client(lambda request: response).extract(RADIOLOGY, [jpeg(10, 10)])


def test_settings_choose_the_model_server(settings):
    configured = settings.model_copy(update={"vlm_url": "http://gpu.nsu:9000/v1", "vlm_model": "Qwen/Qwen3-VL-8B-Instruct-AWQ"})
    assert client_from_settings(configured).model == "Qwen/Qwen3-VL-8B-Instruct-AWQ"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_vlm.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.extraction.stub'`.

- [ ] **Step 4: Write `server/capture/extraction/vlm.py`**

```python
"""Client for the self-hosted vision-language model (vLLM's OpenAI-compatible API, spec §3)."""

import base64
import io
from dataclasses import dataclass

import httpx
from PIL import Image

from capture.config import Settings
from capture.extraction.schema import SYSTEM_PROMPT, json_schema_for, prompt_for
from capture.extraction.spans import Token
from capture.formschema.model import TemplateDef


class VlmUnavailable(Exception):
    """The model server cannot be reached or is overloaded. The job waits; it does not use up an attempt."""


class VlmError(Exception):
    """The model server answered, but not with a usable result. The job uses up an attempt."""


@dataclass(frozen=True)
class VlmAnswer:
    text: str
    tokens: list[Token] | None
    model: str


def image_for_model(data: bytes, max_side: int) -> bytes:
    """The page as JPEG with its long side at most max_side pixels (fewer image tokens, same text)."""
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= max_side:
            return data
        picture = image.convert("RGB")
    picture.thumbnail((max_side, max_side))
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _tokens(logprobs: dict | None) -> list[Token] | None:
    content = (logprobs or {}).get("content")
    if not content:
        return None
    return [
        Token(bytes(entry["bytes"]) if entry.get("bytes") is not None else entry["token"].encode("utf-8"), float(entry["logprob"]))
        for entry in content
    ]


class VlmClient:
    def __init__(
        self,
        url: str,
        model: str,
        *,
        timeout: float,
        max_image_side: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.max_image_side = max_image_side
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transport)

    def request_body(self, tpl: TemplateDef, pages: list[bytes]) -> dict:
        images = [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image_for_model(page, self.max_image_side)).decode("ascii")},
            }
            for page in pages
        ]
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [{"type": "text", "text": prompt_for(tpl)}, *images]},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": tpl.key, "schema": json_schema_for(tpl), "strict": True},
            },
            "temperature": 0,
            "logprobs": True,
            "max_tokens": 4096,
        }

    def extract(self, tpl: TemplateDef, pages: list[bytes]) -> VlmAnswer:
        try:
            response = self._http.post("/chat/completions", json=self.request_body(tpl, pages))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            raise VlmUnavailable(f"model server unreachable ({type(e).__name__})") from None
        except httpx.TimeoutException:
            raise VlmError("the model server took too long to answer") from None
        if response.status_code in (502, 503, 504):
            raise VlmUnavailable(f"model server busy or down ({response.status_code})")
        if response.status_code != 200:
            raise VlmError(f"model server answered {response.status_code}")
        try:
            choice = response.json()["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise VlmError("the model server's answer was not understood") from None
        if choice.get("finish_reason") == "length" or not isinstance(text, str):
            raise VlmError("the model's answer was cut off")
        return VlmAnswer(text=text, tokens=_tokens(choice.get("logprobs")), model=self.model)

    def close(self) -> None:
        self._http.close()


def client_from_settings(settings: Settings, transport: httpx.BaseTransport | None = None) -> VlmClient:
    return VlmClient(
        settings.vlm_url,
        settings.vlm_model,
        timeout=settings.vlm_timeout_s,
        max_image_side=settings.vlm_max_image_side,
        transport=transport,
    )
```

- [ ] **Step 5: Write `server/capture/extraction/stub.py`**

```python
"""A stand-in model server for the dev server and tests: fixed answers in vLLM's response format."""

import json
import math
from typing import Any

import httpx

from capture.extraction.spans import leaf_spans

STUB_MODEL = "stub-extractor"
# What web/e2e/fixtures/report.jpg (a made-up patient) says.
STUB_VALUES: dict[str, dict[str, Any]] = {
    "radiology_report": {
        "modality": "CT",
        "study_date": "2026-09-01",
        "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3, "short_axis_cm": 1.8, "description": "spiculated mass"}],
        "impression": "Suspicious for primary lung malignancy.",
    },
}
# The stub is unsure of this value, so the dev app and the e2e test show one amber field.
UNSURE_PATHS = {"lesions[0].short_axis_cm"}
SURE, UNSURE = math.log(0.99), math.log(0.5)


def stub_completion(body: dict[str, Any]) -> dict[str, Any]:
    spec = body["response_format"]["json_schema"]
    values = {key: None for key in spec["schema"].get("properties", {})}
    values.update(STUB_VALUES.get(spec["name"], {}))
    text = json.dumps(values)
    unsure = [span for path, span in leaf_spans(text).items() if path in UNSURE_PATHS]
    tokens = []
    for start in range(0, len(text), 3):
        end = min(start + 3, len(text))
        logprob = UNSURE if any(start < hi and end > lo for lo, hi in unsure) else SURE
        tokens.append({"token": text[start:end], "logprob": logprob, "bytes": list(text[start:end].encode("utf-8"))})
    return {
        "model": STUB_MODEL,
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
                "logprobs": {"content": tokens},
            }
        ],
    }


def stub_transport() -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(200, json=stub_completion(json.loads(request.content))))
```

`json.dumps` escapes non-ASCII by default, so the stub's text is ASCII and slicing it 3 characters at a time slices bytes too.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_vlm.py -q`
Expected: 15 passed.

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server/pyproject.toml server/uv.lock server/capture/config.py server/capture/extraction/vlm.py server/capture/extraction/stub.py server/tests/test_vlm.py
git commit -m "feat(worker): vLLM client with JSON-schema output and logprobs, plus a stub model server

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 6: The job queue

**Files:**
- Modify: `server/capture/db/models.py`, `server/capture/api/convert.py`, `server/capture/records/service.py`, `server/tests/conftest.py`
- Create: `server/migrations/versions/0003_worker.py`, `server/capture/jobqueue.py`
- Test: `server/tests/test_jobqueue.py`

**Interfaces:**
- Consumes: `Settings.extraction_enabled` (existing). `create_record` keeps its signature and behaviour.
- Produces:
  - `models.py`:
    - `JobStatus` (`queued`, `running`, `done`, `failed`, `cancelled`);
    - `ExtractionStatus.SKIPPED = "skipped"`;
    - `Job.run_after: datetime` and `Job.skip_safety_net: bool`;
    - `ReviewEvent.actor_id: int | None`.
  - `jobqueue.py`:
    - constants `MAX_ATTEMPTS = 3`, `STALE_AFTER = timedelta(minutes=10)`, `RETRY_DELAY = timedelta(seconds=30)`;
    - `ClaimedJob(id, record_id, token, attempts, skip_safety_net)`;
    - `queue_extraction(db, settings, record, *, skip_safety_net=False) -> None`;
    - `queued_at(db, record_id) -> datetime | None`;
    - `cancel_jobs(db, record_id) -> None`;
    - `claim_next(db, worker: str, now) -> ClaimedJob | None`;
    - `lock_claimed(db, claimed) -> tuple[Record | None, Job | None]`;
    - `give_up(record, job, error) -> None`;
    - `retry_later(db, claimed, error, now, *, use_attempt: bool) -> str` (returns `"retry"`, `"failed"` or `"dropped"`);
    - `fail_abandoned(db, now) -> int`.
  - `conftest.py`:
    - fixtures `ai_settings` (extraction switched on);
    - `ai_app`;
    - `ai_uploader`, a logged-in uploader on `ai_app` with templates and the hospital key set up.
  - Event output: an event with no actor shows `actor_name == "System"`.

- [ ] **Step 1: Write the failing tests**

Append to `server/tests/conftest.py`:

```python
@pytest.fixture
def ai_settings(settings):
    """Settings with the AI worker switched on, so uploads start in `processing` with a queued job."""
    return settings.model_copy(update={"extraction_enabled": True})


@pytest.fixture
def ai_app(ai_settings, db):
    from capture.api.app import create_app

    return create_app(ai_settings, session_factory=db)


@pytest.fixture
def ai_uploader(ai_app, templates, hospital_key, make_user, login_as):
    return login_as(make_user("uploader"), on_app=ai_app)
```

`server/tests/test_jobqueue.py`:

```python
import uuid
from datetime import timedelta

from sqlalchemy import select

from capture.clock import utcnow
from capture.db.models import Job, Record, ReviewEvent
from capture.jobqueue import MAX_ATTEMPTS, cancel_jobs, claim_next, fail_abandoned, lock_claimed, queued_at, retry_later


def job_of(db, record_id: str) -> Job:
    with db() as s:
        return s.scalar(select(Job).where(Job.record_id == uuid.UUID(record_id)))


def record_of(db, record_id: str) -> Record:
    with db() as s:
        return s.get(Record, uuid.UUID(record_id))


def claim(db, worker="w1", now=None):
    with db.begin() as s:
        return claim_next(s, worker, now or utcnow())


def test_an_upload_queues_one_job(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    job = job_of(db, body["id"])
    assert (job.status, job.attempts, job.skip_safety_net) == ("queued", 0, False)
    with db() as s:
        assert queued_at(s, uuid.UUID(body["id"])) == job.created_at


def test_claim_takes_the_oldest_due_job_and_marks_it_running(db, ai_uploader, upload):
    first = upload(ai_uploader).json()
    upload(ai_uploader)
    claimed = claim(db)
    assert str(claimed.record_id) == first["id"]
    assert claimed.attempts == 1
    assert claimed.token.startswith("w1:")
    job = job_of(db, first["id"])
    assert (job.status, job.locked_by) == ("running", claimed.token)
    assert claim(db) is not None  # the second upload's job
    assert claim(db) is None  # nothing left


def test_a_job_locked_by_another_worker_is_skipped(db, ai_uploader, upload):
    first = upload(ai_uploader).json()
    second = upload(ai_uploader).json()
    with db.begin() as holding:
        held = claim_next(holding, "w1", utcnow())  # this transaction stays open, so the row stays locked
        with db.begin() as other:
            taken = claim_next(other, "w2", utcnow())
    assert str(held.record_id) == first["id"]
    assert str(taken.record_id) == second["id"]


def test_a_job_whose_worker_went_silent_is_reclaimed_after_ten_minutes(db, ai_uploader, upload):
    upload(ai_uploader)
    start = utcnow()
    first = claim(db, "a", start)
    assert claim(db, "b", start + timedelta(minutes=9)) is None
    second = claim(db, "b", start + timedelta(minutes=11))
    assert (second.id, second.attempts) == (first.id, 2)
    assert second.token != first.token
    with db.begin() as s:
        assert lock_claimed(s, first)[1] is None  # the first worker no longer holds the job
        assert lock_claimed(s, second)[1] is not None


def test_a_failed_attempt_waits_before_the_next_one(db, ai_uploader, upload):
    upload(ai_uploader)
    now = utcnow()
    claimed = claim(db, now=now)
    with db.begin() as s:
        assert retry_later(s, claimed, "VlmError: boom", now, use_attempt=True) == "retry"
    assert claim(db, now=now + timedelta(seconds=10)) is None
    assert claim(db, now=now + timedelta(seconds=31)).attempts == 2


def test_an_unreachable_model_does_not_use_up_an_attempt(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    now = utcnow()
    claimed = claim(db, now=now)
    with db.begin() as s:
        assert retry_later(s, claimed, "model server unreachable", now, use_attempt=False) == "retry"
    job = job_of(db, body["id"])
    assert (job.status, job.attempts, job.last_error) == ("queued", 0, "model server unreachable")
    assert record_of(db, body["id"]).status == "processing"


def test_the_last_failed_attempt_sends_the_record_to_manual_entry(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    now = utcnow()
    outcomes = []
    for _ in range(MAX_ATTEMPTS):
        claimed = claim(db, now=now)
        with db.begin() as s:
            outcomes.append(retry_later(s, claimed, "VlmError: boom", now, use_attempt=True))
        now += timedelta(minutes=5)
    assert outcomes == ["retry", "retry", "failed"]
    job = job_of(db, body["id"])
    assert (job.status, job.last_error) == ("failed", "VlmError: boom")
    record = record_of(db, body["id"])
    assert (record.status, record.extraction_status, record.row_version) == ("draft", "failed", 2)
    assert claim(db, now=now) is None


def test_housekeeping_gives_up_on_a_job_abandoned_on_its_last_attempt(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    with db.begin() as s:
        job = s.scalar(select(Job))
        job.status, job.attempts, job.locked_at = "running", MAX_ATTEMPTS, utcnow() - timedelta(minutes=11)
    with db.begin() as s:
        assert fail_abandoned(s, utcnow()) == 1
    assert (record_of(db, body["id"]).status, job_of(db, body["id"]).status) == ("draft", "failed")
    assert claim(db) is None


def test_cancelled_jobs_are_never_claimed(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    with db.begin() as s:
        cancel_jobs(s, uuid.UUID(body["id"]))
    assert job_of(db, body["id"]).status == "cancelled"
    assert claim(db) is None


def test_events_without_an_actor_show_as_system(db, ai_uploader, upload):
    body = upload(ai_uploader).json()
    with db.begin() as s:
        s.add(ReviewEvent(record_id=uuid.UUID(body["id"]), actor_id=None, action="quarantine", comment="test"))
    record = ai_uploader.get(f"/api/records/{body['id']}").json()
    assert record["events"][-1]["actor_name"] == "System"
    assert record["last_event"]["actor_name"] == "System"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_jobqueue.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.jobqueue'`.

- [ ] **Step 3: Update the models**

In `server/capture/db/models.py`:

1. Add `Index` to the `from sqlalchemy import (...)` list.
2. Add `SKIPPED = "skipped"` to `ExtractionStatus`. "Fill by hand now" uses it.
3. After `ExtractionStatus`, add:

```python
class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

4. Replace the `Job` class with:

```python
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_queue", "status", "run_after"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("records.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default=JobStatus.QUEUED, server_default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(String(64))
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    skip_safety_net: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = _created_at()
```

5. In `ReviewEvent`, make the actor optional. Events written by the worker have none:

```python
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
```

```python
    actor: Mapped[User | None] = relationship(lazy="selectin")
```

- [ ] **Step 4: Write the migration `server/migrations/versions/0003_worker.py`**

```python
"""extraction worker: job retry time and safety-net flag; worker-written review events have no actor

Revision ID: 0003
"""
import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("run_after", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.add_column("jobs", sa.Column("skip_safety_net", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_index("ix_jobs_queue", "jobs", ["status", "run_after"])
    op.alter_column("review_events", "actor_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("review_events", "actor_id", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_jobs_queue", table_name="jobs")
    op.drop_column("jobs", "skip_safety_net")
    op.drop_column("jobs", "run_after")
```

`tests/test_schema.py::test_migration_matches_models` compares the migrated database with the models. It must stay green.

- [ ] **Step 5: Write `server/capture/jobqueue.py`**

```python
"""The extraction job queue (spec §5.1). The API adds jobs; the worker claims and finishes them.

Jobs are claimed with FOR UPDATE SKIP LOCKED, reclaimed after 10 minutes of silence, and given 3 attempts.
Lock order everywhere: the record first, then its jobs (the API's transitions lock the record first too).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from capture.config import Settings
from capture.db.models import ExtractionStatus, Job, JobStatus, Record, Status

MAX_ATTEMPTS = 3
STALE_AFTER = timedelta(minutes=10)
RETRY_DELAY = timedelta(seconds=30)


@dataclass(frozen=True)
class ClaimedJob:
    id: int
    record_id: uuid.UUID
    token: str  # identifies this claim; a reclaimed job gets a new token
    attempts: int
    skip_safety_net: bool


def queue_extraction(db: Session, settings: Settings, record: Record, *, skip_safety_net: bool = False) -> None:
    """Hand a record to the AI worker, or straight to manual entry when extraction is switched off."""
    if not settings.extraction_enabled:
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.NOT_APPLICABLE
        return
    record.status = Status.PROCESSING
    record.extraction_status = ExtractionStatus.PENDING
    db.add(Job(kind="extract", record_id=record.id, skip_safety_net=skip_safety_net))


def queued_at(db: Session, record_id: uuid.UUID) -> datetime | None:
    """When the record's newest job was queued."""
    return db.scalar(select(func.max(Job.created_at)).where(Job.record_id == record_id))


def cancel_jobs(db: Session, record_id: uuid.UUID) -> None:
    db.execute(
        update(Job)
        .where(Job.record_id == record_id, Job.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
        .values(status=JobStatus.CANCELLED)
    )


def claim_next(db: Session, worker: str, now: datetime) -> ClaimedJob | None:
    """Take the next due job, or one whose worker has been silent for 10 minutes, and mark it running."""
    job = db.scalar(
        select(Job)
        .where(
            Job.kind == "extract",
            or_(
                (Job.status == JobStatus.QUEUED) & (Job.run_after <= now),
                (Job.status == JobStatus.RUNNING) & (Job.locked_at < now - STALE_AFTER) & (Job.attempts < MAX_ATTEMPTS),
            ),
        )
        .order_by(Job.run_after, Job.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.locked_at = now
    job.locked_by = f"{worker[:40]}:{uuid.uuid4().hex[:12]}"
    job.attempts += 1
    db.flush()
    return ClaimedJob(job.id, job.record_id, job.locked_by, job.attempts, job.skip_safety_net)


def lock_claimed(db: Session, claimed: ClaimedJob) -> tuple[Record | None, Job | None]:
    """Lock the record, then the job. The job is None when this claim no longer holds it (cancelled or reclaimed)."""
    record = db.get(Record, claimed.record_id, with_for_update=True)
    job = db.get(Job, claimed.id, with_for_update=True)
    if job is None or job.status != JobStatus.RUNNING or job.locked_by != claimed.token:
        return record, None
    return record, job


def give_up(record: Record | None, job: Job, error: str) -> None:
    """The AI is a shortcut, never a blocker (spec §5.1): after the last attempt the record goes to manual entry."""
    job.status = JobStatus.FAILED
    job.last_error = error
    if record is not None and record.status == Status.PROCESSING:
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.FAILED
        record.row_version += 1


def retry_later(db: Session, claimed: ClaimedJob, error: str, now: datetime, *, use_attempt: bool) -> str:
    """Put the job back in the queue, or give up after the last attempt. Returns 'retry', 'failed' or 'dropped'."""
    record, job = lock_claimed(db, claimed)
    if job is None:
        return "dropped"
    if not use_attempt:
        job.attempts -= 1
    elif job.attempts >= MAX_ATTEMPTS:
        give_up(record, job, error)
        return "failed"
    job.status = JobStatus.QUEUED
    job.last_error = error
    job.locked_at = None
    job.locked_by = None
    job.run_after = now + RETRY_DELAY * max(job.attempts, 1)
    return "retry"


def fail_abandoned(db: Session, now: datetime) -> int:
    """Give up on jobs whose worker went silent during their last attempt. Returns how many."""
    stale = (Job.status == JobStatus.RUNNING) & (Job.locked_at < now - STALE_AFTER) & (Job.attempts >= MAX_ATTEMPTS)
    count = 0
    for job_id, record_id in db.execute(select(Job.id, Job.record_id).where(stale)).all():
        record = db.get(Record, record_id, with_for_update=True)
        job = db.get(Job, job_id, with_for_update=True)
        if job.status == JobStatus.RUNNING and job.locked_at < now - STALE_AFTER and job.attempts >= MAX_ATTEMPTS:
            give_up(record, job, "the worker stopped while reading this record")
            count += 1
    return count
```

- [ ] **Step 6: Queue uploads through `queue_extraction`, and show actor-less events as "System"**

In `server/capture/records/service.py`:
- add `from capture.jobqueue import queue_extraction`;
- drop `Job` from the `capture.db.models` import;
- replace the block from `db.execute(pg_insert(Patient)...` to the end of `create_record` with:

```python
    db.execute(pg_insert(Patient).values(study_code=study_code).on_conflict_do_nothing())
    record = Record(
        id=uuid.uuid4(),
        study_code=study_code,
        template_id=template.id,
        status=Status.DRAFT,
        extraction_status=ExtractionStatus.NOT_APPLICABLE,
        field_values={},
        created_by=user.id,
        client_upload_id=client_upload_id,
    )
    db.add(record)
    db.flush()
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, study_code, record.id, page_no, data)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
    queue_extraction(db, settings, record)
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="upload"))
    db.flush()
    return record, True
```

In `server/capture/api/convert.py`, add:

```python
SYSTEM_ACTOR = "System"


def _actor_name(event: ReviewEvent) -> str:
    """Events the worker writes (quarantine) have no actor."""
    return event.actor.name if event.actor is not None else SYSTEM_ACTOR
```

Then use `_actor_name(event)` in `_last_event`, and `_actor_name(e)` in `record_detail`'s `EventOut(...)`, in place of `event.actor.name` and `e.actor.name`.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_jobqueue.py tests/test_schema.py tests/test_records_create.py -q`
Expected: all pass. That includes the existing `test_extraction_enabled_queues_a_job` and `test_uploader_creates_a_draft_record`.

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add server/capture/db/models.py server/migrations/versions/0003_worker.py server/capture/jobqueue.py server/capture/records/service.py server/capture/api/convert.py server/tests/conftest.py server/tests/test_jobqueue.py
git commit -m "feat(worker): extraction job queue with skip-locked claims, reclaim, retries and give-up

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The worker reads a record, start to finish

**Files:**
- Modify: `server/capture/config.py` (add `worker_poll_s`), `server/capture/storage.py` (add `remove_stored`), `server/tests/constants.py` (add `PHOTO`)
- Create: `server/capture/worker/__init__.py` (empty), `server/capture/worker/process.py`, `server/capture/worker/loop.py`, `server/tests/fakes.py`
- Test: `server/tests/test_worker.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 4, 5 and 6.
  - `phi_hits` and `describe`;
  - `conform` and `build_extraction`;
  - `field_confidences`;
  - `VlmClient`, `VlmError` and `VlmUnavailable`;
  - `ClaimedJob`, `lock_claimed`, `retry_later`, `claim_next` and `fail_abandoned`;
  - `template_def(record.template)` and `document_date_of`, `validate_values` (existing).
- Produces:
  - `Settings.worker_poll_s: float = 2.0`;
  - `storage.remove_stored(storage_dir, relatives: list[str]) -> None`;
  - `worker/process.py`:
    - `Engines(ocr: OcrEngine, vlm: VlmClient)`;
    - `process_job(sessions, settings, engines, claimed, now=utcnow) -> str`, returning `"done"`, `"quarantined"`, `"dropped"`, `"retry"` or `"failed"`.
  - `worker/loop.py`:
    - `QUARANTINE_KEEP = timedelta(days=14)`;
    - `expire_quarantined_files(db, now) -> list[str]`;
    - `housekeeping(sessions, settings, now) -> None`;
    - `run_worker(sessions, settings, engines, stop: threading.Event, name: str) -> None`.
  - On quarantine, `record.quarantine` = `{"at": iso, "summary": str, "hits": [{"page", "kind", "box"}], "files_expired": false}`.
  - `tests/fakes.py`: `REPORT_LINES`, `FakeOcr(*lines)`, `stub_vlm(transport=None) -> VlmClient`, `run_once(db, settings, engines, now=None) -> str`.
  - `tests/constants.py`: `PHOTO`, a decodable JPEG with no metadata.

- [ ] **Step 1: Add the setting, `remove_stored`, `PHOTO` and the test doubles**

At the end of `Settings` in `server/capture/config.py`:

```python
    worker_poll_s: float = 2.0  # how long an idle worker waits before looking for jobs again
```

At the end of `server/capture/storage.py`:

```python
def remove_stored(storage_dir: Path, relatives: list[str]) -> None:
    """Delete stored files once the database no longer points at them; a file that is already gone is fine."""
    for relative in relatives:
        resolve_in_storage(storage_dir, relative).unlink(missing_ok=True)
```

At the end of `server/tests/constants.py` (add `import io` at the top):

```python
def _photo() -> bytes:
    """A real, decodable JPEG with no metadata: for tests that send pages to the model."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


PHOTO = _photo()
```

`server/tests/fakes.py`:

```python
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
```

- [ ] **Step 2: Write the failing tests**

`server/tests/test_worker.py`:

```python
import json
import threading
import time
import uuid
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from capture.clock import utcnow
from capture.db.models import Job, Record, RecordFile
from capture.extraction.stub import stub_completion
from capture.jobqueue import cancel_jobs, claim_next
from capture.worker.loop import housekeeping, run_worker
from capture.worker.process import Engines, process_job
from constants import PHOTO, STUDY_CODE
from fakes import REPORT_LINES, FakeOcr, run_once, stub_vlm

READS_CLEANLY = Engines(FakeOcr(*REPORT_LINES), stub_vlm())
SHOWS_A_MOBILE = Engines(FakeOcr("CT CHEST REPORT", "Mobile: 01712345678"), stub_vlm())


@pytest.fixture
def worker_settings(ai_settings):
    return ai_settings.model_copy(update={"worker_poll_s": 0.05})


def stored(db, record_id: str) -> Record:
    with db() as s:
        return s.get(Record, uuid.UUID(record_id))


def test_a_report_is_read_into_a_draft_with_colours_and_sources(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    assert body["status"] == "processing"
    assert run_once(db, worker_settings, READS_CLEANLY) == "done"
    record = ai_uploader.get(f"/api/records/{body['id']}").json()
    assert (record["status"], record["extraction_status"]) == ("draft", "done")
    assert record["values"]["modality"] == "CT"
    assert record["values"]["lesions"] == [{"lobe": "RUL", "long_axis_cm": 2.3, "short_axis_cm": 1.8, "description": "spiculated mass"}]
    assert record["document_date"] == "2026-09-01"
    assert record["row_version"] == body["row_version"] + 1
    fields = record["extraction"]["fields"]
    assert fields["modality"]["colour"] == "green"
    assert fields["lesions[0].short_axis_cm"]["colour"] == "amber"  # the stub is unsure of it
    assert fields["contrast"]["colour"] == "grey"
    assert fields["impression"]["sources"] == [{"page": 1, "box": [10, 120, 500, 150]}]
    with db() as s:
        assert s.scalar(select(Job.status)) == "done"


def test_a_readable_identifier_quarantines_the_record(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    assert run_once(db, worker_settings, SHOWS_A_MOBILE) == "quarantined"
    record = ai_uploader.get(f"/api/records/{body['id']}").json()
    assert record["status"] == "quarantined"
    assert record["values"] == {}
    assert record["events"][-1]["action"] == "quarantine"
    assert record["events"][-1]["actor_name"] == "System"
    assert record["events"][-1]["comment"] == "Possible patient details found: mobile number (page 1)"
    quarantine = stored(db, body["id"]).quarantine
    assert quarantine["hits"] == [{"page": 1, "kind": "mobile", "box": [10, 40, 500, 70]}]
    assert quarantine["summary"] == "Possible patient details found: mobile number (page 1)"
    assert quarantine["files_expired"] is False


def test_a_released_record_skips_the_safety_net(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    with db.begin() as s:
        s.scalar(select(Job)).skip_safety_net = True
    assert run_once(db, worker_settings, Engines(FakeOcr("Mobile: 01712345678", *REPORT_LINES), stub_vlm())) == "done"
    assert stored(db, body["id"]).status == "draft"


def test_an_unreachable_model_keeps_the_record_waiting(db, worker_settings, ai_uploader, upload):
    def refuse(request):
        raise httpx.ConnectError("connection refused")

    body = upload(ai_uploader, pages=(PHOTO,)).json()
    now = utcnow()
    assert run_once(db, worker_settings, Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(refuse))), now=now) == "retry"
    with db() as s:
        job = s.scalar(select(Job))
    assert (job.status, job.attempts) == ("queued", 0)
    assert job.run_after > now
    assert stored(db, body["id"]).status == "processing"


def test_three_failed_attempts_send_the_record_to_manual_entry(db, worker_settings, ai_uploader, upload):
    broken = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(lambda request: httpx.Response(500))))
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    now = utcnow()
    outcomes = []
    for _ in range(3):
        outcomes.append(run_once(db, worker_settings, broken, now=now))
        now += timedelta(minutes=5)
    assert outcomes == ["retry", "retry", "failed"]
    record = stored(db, body["id"])
    assert (record.status, record.extraction_status) == ("draft", "failed")
    with db() as s:
        job = s.scalar(select(Job))
    assert (job.status, job.last_error) == ("failed", "VlmError: model server answered 500")


def test_an_answer_that_is_not_json_uses_up_an_attempt(db, worker_settings, ai_uploader, upload):
    garbled = {"choices": [{"finish_reason": "stop", "message": {"content": "I think it is a CT scan"}}]}
    engines = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(lambda request: httpx.Response(200, json=garbled))))
    upload(ai_uploader, pages=(PHOTO,))
    assert run_once(db, worker_settings, engines) == "retry"
    with db() as s:
        assert s.scalar(select(Job.attempts)) == 1


def test_a_record_taken_by_hand_while_the_model_was_reading_keeps_the_users_draft(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()

    def fill_by_hand_meanwhile(request: httpx.Request) -> httpx.Response:
        with db.begin() as s:
            record = s.get(Record, uuid.UUID(body["id"]), with_for_update=True)
            record.status, record.extraction_status = "draft", "skipped"
            cancel_jobs(s, record.id)
        return httpx.Response(200, json=stub_completion(json.loads(request.content)))

    engines = Engines(FakeOcr(*REPORT_LINES), stub_vlm(httpx.MockTransport(fill_by_hand_meanwhile)))
    assert run_once(db, worker_settings, engines) == "dropped"
    record = stored(db, body["id"])
    assert (record.status, record.extraction_status, record.field_values) == ("draft", "skipped", {})
    with db() as s:
        assert s.scalar(select(Job.status)) == "cancelled"


def test_a_worker_that_lost_its_job_to_another_drops_its_late_result(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    start = utcnow()
    with db.begin() as s:
        first = claim_next(s, "slow-worker", start)
    with db.begin() as s:
        second = claim_next(s, "other-worker", start + timedelta(minutes=11))
    assert process_job(db, worker_settings, READS_CLEANLY, second) == "done"
    assert process_job(db, worker_settings, SHOWS_A_MOBILE, first) == "dropped"
    assert stored(db, body["id"]).status == "draft"


def test_photos_held_back_for_14_days_are_deleted(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    run_once(db, worker_settings, SHOWS_A_MOBILE)
    page = worker_settings.storage_dir / "records" / STUDY_CODE / body["id"] / "page-1.jpg"
    housekeeping(db, worker_settings, utcnow() + timedelta(days=13))
    assert page.exists()
    housekeeping(db, worker_settings, utcnow() + timedelta(days=15))
    assert not page.exists()
    record = stored(db, body["id"])
    assert (record.status, record.quarantine["files_expired"]) == ("quarantined", True)
    with db() as s:
        assert s.scalar(select(func.count()).select_from(RecordFile)) == 0


def test_the_worker_loop_reads_waiting_records_until_stopped(db, worker_settings, ai_uploader, upload):
    body = upload(ai_uploader, pages=(PHOTO,)).json()
    stop = threading.Event()
    thread = threading.Thread(target=run_worker, args=(db, worker_settings, READS_CLEANLY, stop, "loop-test"))
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while stored(db, body["id"]).status != "draft" and time.monotonic() < deadline:
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(timeout=5)
    assert stored(db, body["id"]).status == "draft"
    assert not thread.is_alive()
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_worker.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.worker'`.

- [ ] **Step 4: Write `server/capture/worker/process.py`**

```python
"""One extraction job, start to finish (spec §5.2). Never logs or stores page text or field values."""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import sessionmaker

from capture.clock import today, utcnow
from capture.config import Settings
from capture.db.models import ExtractionStatus, JobStatus, Record, ReviewEvent, Status
from capture.extraction.assemble import build_extraction, conform
from capture.extraction.ocr import OcrEngine, OcrLine
from capture.extraction.phi import PhiHit, describe, phi_hits
from capture.extraction.spans import field_confidences
from capture.extraction.vlm import VlmClient, VlmError, VlmUnavailable
from capture.formschema.model import TemplateDef
from capture.formschema.store import template_def
from capture.formschema.validate import document_date_of, validate_values
from capture.jobqueue import ClaimedJob, lock_claimed, retry_later
from capture.storage import resolve_in_storage

log = logging.getLogger("capture.worker")


@dataclass
class Engines:
    ocr: OcrEngine
    vlm: VlmClient


def _load(sessions: sessionmaker, settings: Settings, claimed: ClaimedJob) -> tuple[TemplateDef, list[bytes]] | None:
    """The template and page images, or None when the record no longer waits for the AI."""
    with sessions() as db:
        record = db.get(Record, claimed.record_id)
        if record is None or record.status != Status.PROCESSING:
            return None
        pages = [resolve_in_storage(settings.storage_dir, f.path).read_bytes() for f in record.files if f.kind == "page"]
        return template_def(record.template), pages


def _drop(sessions: sessionmaker, claimed: ClaimedJob) -> str:
    """The record stopped waiting for the AI (filled by hand, or another worker finished it): let the job go."""
    with sessions.begin() as db:
        _, job = lock_claimed(db, claimed)
        if job is not None:
            job.status = JobStatus.CANCELLED
    return "dropped"


def _finish(sessions: sessionmaker, claimed: ClaimedJob, apply: Callable[[Record], str]) -> str:
    """Write a result if this claim still holds the job and the record still waits for the AI; otherwise drop it."""
    with sessions.begin() as db:
        record, job = lock_claimed(db, claimed)
        if job is None:
            return "dropped"
        if record is None or record.status != Status.PROCESSING:
            job.status = JobStatus.CANCELLED
            return "dropped"
        job.status = JobStatus.DONE
        outcome = apply(record)
        record.row_version += 1
        if outcome == "quarantined":
            db.add(ReviewEvent(record_id=record.id, actor_id=None, action="quarantine", comment=record.quarantine["summary"]))
        return outcome


def _quarantine(hits: list[PhiHit], now: datetime) -> Callable[[Record], str]:
    def apply(record: Record) -> str:
        record.status = Status.QUARANTINED
        record.quarantine = {
            "at": now.isoformat(),
            "summary": describe(hits),
            "hits": [{"page": h.page, "kind": h.kind, "box": list(h.box)} for h in hits],
            "files_expired": False,
        }
        return "quarantined"

    return apply


def _result(tpl: TemplateDef, values: dict, extraction: dict) -> Callable[[Record], str]:
    def apply(record: Record) -> str:
        record.field_values = values
        record.extraction = extraction
        record.document_date = document_date_of(tpl, values)
        record.status = Status.DRAFT
        record.extraction_status = ExtractionStatus.DONE
        return "done"

    return apply


def process_job(
    sessions: sessionmaker,
    settings: Settings,
    engines: Engines,
    claimed: ClaimedJob,
    now: Callable[[], datetime] = utcnow,
) -> str:
    """Run one claimed job. Returns done, quarantined, dropped, retry or failed."""
    try:
        loaded = _load(sessions, settings, claimed)
        if loaded is None:
            return _drop(sessions, claimed)
        tpl, pages = loaded
        lines: list[OcrLine] = []
        for page_no, image in enumerate(pages, start=1):
            lines.extend(engines.ocr.read(page_no, image))
        if not claimed.skip_safety_net:
            hits = phi_hits(lines)
            if hits:
                return _finish(sessions, claimed, _quarantine(hits, now()))
        answer = engines.vlm.extract(tpl, pages)
        try:
            raw = json.loads(answer.text)
        except ValueError:
            raise VlmError("the model's answer was not JSON") from None
        values = conform(tpl, raw)
        errors = validate_values(tpl, values, today())
        confidences = field_confidences(answer.text, answer.tokens)
        extraction = build_extraction(tpl, values, confidences, lines, errors, settings.confidence_threshold, answer.model)
        return _finish(sessions, claimed, _result(tpl, values, extraction))
    except VlmUnavailable as e:
        with sessions.begin() as db:
            return retry_later(db, claimed, str(e), now(), use_attempt=False)
    except Exception as e:
        log.exception("job %s (record %s) failed", claimed.id, claimed.record_id)
        with sessions.begin() as db:
            return retry_later(db, claimed, f"{type(e).__name__}: {e}"[:300], now(), use_attempt=True)
```

- [ ] **Step 5: Write `server/capture/worker/loop.py`**

```python
"""The worker loop (spec §5.1) and its housekeeping: abandoned jobs, and the 14-day quarantine expiry (spec §8.1)."""

import logging
import threading
import time
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from capture.clock import utcnow
from capture.config import Settings
from capture.db.models import Record, Status
from capture.jobqueue import claim_next, fail_abandoned
from capture.storage import remove_stored
from capture.worker.process import Engines, process_job

log = logging.getLogger("capture.worker")
QUARANTINE_KEEP = timedelta(days=14)
HOUSEKEEPING_EVERY_S = 300


def expire_quarantined_files(db: Session, now: datetime) -> list[str]:
    """Drop the photos of records quarantined for 14 days. Returns their stored paths, to delete after commit."""
    removed: list[str] = []
    records = db.scalars(select(Record).where(Record.status == Status.QUARANTINED).with_for_update(skip_locked=True))
    for record in records:
        quarantine = record.quarantine or {}
        held_since = quarantine.get("at")
        if quarantine.get("files_expired") or held_since is None or datetime.fromisoformat(held_since) > now - QUARANTINE_KEEP:
            continue
        for page in list(record.files):
            removed.append(page.path)
            db.delete(page)
        record.quarantine = {**quarantine, "files_expired": True}
        record.row_version += 1
    return removed


def housekeeping(sessions: sessionmaker, settings: Settings, now: datetime) -> None:
    with sessions.begin() as db:
        fail_abandoned(db, now)
        removed = expire_quarantined_files(db, now)
    remove_stored(settings.storage_dir, removed)


def run_worker(sessions: sessionmaker, settings: Settings, engines: Engines, stop: threading.Event, name: str) -> None:
    """Claim and run jobs until `stop` is set. Errors are logged and never end the loop."""
    log.info("worker %s started", name)
    next_housekeeping = 0.0
    while not stop.is_set():
        try:
            if time.monotonic() >= next_housekeeping:
                housekeeping(sessions, settings, utcnow())
                next_housekeeping = time.monotonic() + HOUSEKEEPING_EVERY_S
            with sessions.begin() as db:
                claimed = claim_next(db, name, utcnow())
            if claimed is None:
                stop.wait(settings.worker_poll_s)
                continue
            outcome = process_job(sessions, settings, engines, claimed)
            log.info("job %s (record %s): %s", claimed.id, claimed.record_id, outcome)
        except Exception:
            log.exception("worker loop error")
            stop.wait(settings.worker_poll_s)
    log.info("worker %s stopped", name)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_worker.py -q`
Expected: 10 passed.

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add server/capture/config.py server/capture/storage.py server/capture/worker server/tests/constants.py server/tests/fakes.py server/tests/test_worker.py
git commit -m "feat(worker): process a job end to end (safety net, model, colours) and run the worker loop

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 8: Release, re-upload, "Fill by hand now", and what the API shows

**Files:**
- Modify: `server/capture/workflow/rules.py`, `server/capture/storage.py`, `server/capture/records/service.py`, `server/capture/api/schemas.py`, `server/capture/api/convert.py`, `server/capture/api/routes_records.py`, `server/tests/test_rules.py`
- Test: `server/tests/test_quarantine_api.py`

**Interfaces:**
- Consumes:
  - `queue_extraction`, `queued_at`, `cancel_jobs` (Task 6);
  - `remove_stored` (Task 7);
  - `housekeeping` (Task 7, used in tests);
  - `tests/fakes.py` (Task 7).
- Produces:
  - `rules.Action.RELEASE = "release"` (hospital_doctor, `quarantined → processing`, comment required).
  - `rules.Action.FILL_BY_HAND = "fill_by_hand"` (uploader or hospital_doctor, `processing → draft`). It is refused for 2 minutes after the job was queued, with 409 "The AI is still reading this record — try again in a minute".
  - `POST /api/records/{id}/reupload`. Multipart: `meta` = `{"row_version": int, "key_fingerprint": str}` plus `pages`. Only for `quarantined` records; returns `RecordDetail` (status `processing`).
  - `RecordDetail` gains:
    - `quarantine: {"at", "summary", "hits": [{"page", "kind", "box"}], "files_expired"} | null`;
    - `extraction_queued_at: datetime | null`, set only while `processing`;
    - `extraction` becomes `{"model", "fields": {path: {"colour", "confidence", "sources", "edited", "value"?}}}`, where `value` is present for hospital roles only.
  - `RecordSummary`, and with it `RecordDetail`, gains `ai_amber: int` and `ai_red: int`: the AI fields still holding an amber or red value. These are the queue's 🟡/🔴 counts (spec §8.3).
  - `service.CONFLICT_MESSAGE = "Someone else changed this record — reload"`.
  - `service.replace_pages(db, settings, user, record, *, row_version, key_fingerprint, pages) -> list[str]`.
  - `storage.save_page(..., *, suffix="")`.

- [ ] **Step 1: Extend the transition matrix and write the failing API tests**

In `server/tests/test_rules.py`, add these two entries to `EXPECTED`, after `Action.REOPEN`:

```python
    Action.RELEASE: {
        Role.UPLOADER: [403] * 6,
        Role.HOSPITAL_DOCTOR: [409, Status.PROCESSING, 409, 409, 409, 409],
        Role.NSU_REVIEWER: [403] * 6,
        Role.ADMIN: [403] * 6,
    },
    Action.FILL_BY_HAND: {
        Role.UPLOADER: [Status.DRAFT, 409, 409, 409, 409, 409],
        Role.HOSPITAL_DOCTOR: [Status.DRAFT, 409, 409, 409, 409, 409],
        Role.NSU_REVIEWER: [403] * 6,
        Role.ADMIN: [403] * 6,
    },
```

Change the count test to:

```python
def test_the_matrix_covers_every_action_role_and_status():
    assert len(MATRIX) == len(Action) * len(Role) * len(Status) == 144
```

Then add, after `test_reopen_only_approved`:

```python
@pytest.mark.parametrize("comment", [None, "", "   "])
def test_release_needs_a_comment(comment):
    assert rejected(Action.RELEASE, Role.HOSPITAL_DOCTOR, Status.QUARANTINED, comment=comment).http_status == 422
```

`server/tests/test_quarantine_api.py`:

```python
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from capture.clock import utcnow
from capture.db.models import Job
from capture.jobqueue import claim_next
from capture.worker.loop import housekeeping
from capture.worker.process import Engines
from constants import FINGERPRINT, PHOTO, STUDY_CODE
from fakes import REPORT_LINES, FakeOcr, run_once, stub_vlm

SHOWS_A_MOBILE = Engines(FakeOcr("Mobile: 01712345678", *REPORT_LINES), stub_vlm())
READS_CLEANLY = Engines(FakeOcr(*REPORT_LINES), stub_vlm())
WITH_EXIF = PHOTO[:2] + b"\xff\xe1\x00\x08Exif\x00\x00" + PHOTO[2:]


@pytest.fixture
def staff(ai_app, templates, hospital_key, make_user, login_as):
    roles = {"uploader": "uploader", "doctor": "hospital_doctor", "reviewer": "nsu_reviewer"}
    return SimpleNamespace(**{name: login_as(make_user(role), on_app=ai_app) for name, role in roles.items()})


def fresh(client, record_id: str) -> dict:
    return client.get(f"/api/records/{record_id}").json()


def held_back(db, ai_settings, staff, upload) -> dict:
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    assert run_once(db, ai_settings, SHOWS_A_MOBILE) == "quarantined"
    return fresh(staff.uploader, body["id"])


def act(client, record, action, comment=None):
    body = {"action": action, "comment": comment, "row_version": record["row_version"]}
    return client.post(f"/api/records/{record['id']}/transition", json=body)


def reupload(client, record, *, pages=(PHOTO,), fingerprint=FINGERPRINT, row_version=None):
    meta = {"row_version": record["row_version"] if row_version is None else row_version, "key_fingerprint": fingerprint}
    files = [("pages", (f"page-{i + 1}.jpg", data, "image/jpeg")) for i, data in enumerate(pages)]
    return client.post(f"/api/records/{record['id']}/reupload", data={"meta": json.dumps(meta)}, files=files)


def test_hospital_staff_see_why_a_record_was_held_back_and_nsu_sees_nothing(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    assert record["status"] == "quarantined"
    assert record["quarantine"]["summary"] == "Possible patient details found: mobile number (page 1)"
    assert record["quarantine"]["hits"] == [{"page": 1, "kind": "mobile", "box": [10, 0, 500, 30]}]
    assert staff.reviewer.get(f"/api/records/{record['id']}").status_code == 404


def test_a_doctor_releases_a_false_alarm_and_the_ai_reads_it_without_the_safety_net(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    r = act(staff.doctor, record, "release", "That number is the hospital's own helpline")
    assert r.status_code == 200, r.text
    released = r.json()
    assert (released["status"], released["quarantine"]) == ("processing", None)
    assert released["events"][-1]["action"] == "release"
    with db() as s:
        assert s.scalars(select(Job.skip_safety_net).order_by(Job.id)).all() == [False, True]
    assert run_once(db, ai_settings, SHOWS_A_MOBILE) == "done"
    assert fresh(staff.doctor, record["id"])["status"] == "draft"


@pytest.mark.parametrize(("who", "comment", "status"), [("uploader", "false alarm", 403), ("doctor", None, 422), ("doctor", "  ", 422)])
def test_release_needs_a_hospital_doctor_and_a_reason(db, ai_settings, staff, upload, who, comment, status):
    record = held_back(db, ai_settings, staff, upload)
    assert act(getattr(staff, who), record, "release", comment).status_code == status


def test_photos_deleted_after_14_days_cannot_be_released(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    housekeeping(db, ai_settings, utcnow() + timedelta(days=15))
    record = fresh(staff.doctor, record["id"])
    assert record["quarantine"]["files_expired"] is True
    assert record["files"] == []
    r = act(staff.doctor, record, "release", "false alarm")
    assert r.status_code == 409
    assert r.json()["detail"] == "The photos were deleted after 14 days — upload them again"
    assert reupload(staff.uploader, record).status_code == 200


def test_new_photos_replace_the_held_back_ones(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    old_page = ai_settings.storage_dir / "records" / STUDY_CODE / record["id"] / "page-1.jpg"
    assert old_page.exists()
    r = reupload(staff.uploader, record, pages=(PHOTO, PHOTO))
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["quarantine"]) == ("processing", None)
    assert [f["page_no"] for f in body["files"]] == [1, 2]
    assert body["events"][-1]["action"] == "reupload"
    assert not old_page.exists()
    assert staff.uploader.get(f"/api/files/{body['files'][0]['id']}").content == PHOTO
    assert run_once(db, ai_settings, READS_CLEANLY) == "done"
    assert fresh(staff.uploader, record["id"])["status"] == "draft"


def test_new_photos_are_checked_like_any_upload(db, ai_settings, staff, upload):
    record = held_back(db, ai_settings, staff, upload)
    wrong_key = reupload(staff.uploader, record, fingerprint="K-0000")
    assert (wrong_key.status_code, wrong_key.json()["detail"]) == (409, "This device's key doesn't match — ask your hospital admin.")
    stale = reupload(staff.uploader, record, row_version=record["row_version"] - 1)
    assert (stale.status_code, stale.json()["detail"]) == (409, "Someone else changed this record — reload")
    assert reupload(staff.uploader, record, pages=(WITH_EXIF,)).status_code == 422
    assert reupload(staff.reviewer, record).status_code == 403
    after = fresh(staff.uploader, record["id"])
    assert (after["status"], len(after["files"])) == ("quarantined", 1)


def test_only_held_back_records_take_new_photos(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    r = reupload(staff.uploader, fresh(staff.uploader, body["id"]))
    assert (r.status_code, r.json()["detail"]) == (409, "Only records held back for patient details can get new photos")


def test_fill_by_hand_is_offered_after_two_minutes_and_stops_the_ai(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    assert body["extraction_queued_at"] is not None
    early = act(staff.uploader, body, "fill_by_hand")
    assert (early.status_code, early.json()["detail"]) == (409, "The AI is still reading this record — try again in a minute")
    with db.begin() as s:
        s.scalar(select(Job)).created_at = utcnow() - timedelta(minutes=3)
    r = act(staff.uploader, body, "fill_by_hand")
    assert r.status_code == 200, r.text
    filled = r.json()
    assert (filled["status"], filled["extraction_status"], filled["extraction_queued_at"]) == ("draft", "skipped", None)
    assert filled["events"][-1]["action"] == "fill_by_hand"
    with db.begin() as s:
        assert s.scalar(select(Job.status)) == "cancelled"
        assert claim_next(s, "w", utcnow()) is None


def test_nsu_sees_where_values_were_found_but_never_the_ai_values(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    record = fresh(staff.uploader, body["id"])
    values = {**record["values"], "impression": "Retyped by the uploader"}
    r = staff.uploader.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})
    record = r.json()
    hospital_view = record["extraction"]["fields"]
    assert hospital_view["impression"]["edited"] is True
    assert hospital_view["impression"]["value"] == "Suspicious for primary lung malignancy."
    assert (hospital_view["modality"]["edited"], hospital_view["contrast"]["edited"]) == (False, False)
    record = act(staff.uploader, record, "submit").json()
    act(staff.doctor, record, "approve")
    nsu_view = fresh(staff.reviewer, record["id"])["extraction"]["fields"]
    assert "value" not in nsu_view["impression"]
    assert nsu_view["impression"]["edited"] is True
    assert nsu_view["modality"]["colour"] == "green"
    assert nsu_view["modality"]["sources"] == hospital_view["modality"]["sources"]


def test_record_lists_count_the_ai_fields_still_to_check(db, ai_settings, staff, upload):
    body = upload(staff.uploader, pages=(PHOTO,)).json()
    run_once(db, ai_settings, READS_CLEANLY)
    [listed] = staff.uploader.get("/api/records", params={"status": "draft"}).json()
    assert (listed["ai_amber"], listed["ai_red"]) == (1, 0)  # the stub is unsure of the short axis
    record = fresh(staff.uploader, body["id"])
    lesion = {**record["values"]["lesions"][0], "short_axis_cm": 1.9}
    values = {**record["values"], "lesions": [lesion]}
    staff.uploader.patch(f"/api/records/{record['id']}/values", json={"row_version": record["row_version"], "values": values})
    [listed] = staff.uploader.get("/api/records", params={"status": "draft"}).json()
    assert (listed["ai_amber"], listed["ai_red"]) == (0, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_rules.py tests/test_quarantine_api.py -q`
Expected:
- `test_rules.py` fails with `AttributeError: RELEASE`;
- `test_quarantine_api.py` fails: `KeyError: 'quarantine'`, and `reupload` returns 405.

- [ ] **Step 3: Add the two transitions to `server/capture/workflow/rules.py`**

Add the members to `Action`:

```python
class Action(enum.StrEnum):
    SUBMIT = "submit"
    APPROVE = "approve"
    RETURN = "return"
    REOPEN = "reopen"
    RELEASE = "release"
    FILL_BY_HAND = "fill_by_hand"
```

In `next_status`, insert before the final `raise TransitionError(f"Unknown action: {action}", 422)`:

```python
    if action == Action.RELEASE:
        if role != Role.HOSPITAL_DOCTOR:
            raise TransitionError("Only a hospital doctor can release a held-back record", 403)
        if status != Status.QUARANTINED:
            raise TransitionError("Only held-back records can be released")
        if not has_comment:
            raise TransitionError("A comment is required to release a record", 422)
        return Status.PROCESSING
    if action == Action.FILL_BY_HAND:
        if role not in HOSPITAL_ROLES:
            raise TransitionError("Only hospital staff can fill in records", 403)
        if status != Status.PROCESSING:
            raise TransitionError("This record is not waiting for the AI")
        return Status.DRAFT
```

- [ ] **Step 4: Let `save_page` take a suffix (`server/capture/storage.py`)**

Replace `save_page` with:

```python
def save_page(
    storage_dir: Path, study_code: str, record_id: uuid.UUID, page_no: int, data: bytes, *, suffix: str = ""
) -> tuple[str, str]:
    """Store one page. Re-uploads pass a suffix so new files never overwrite the old ones before the commit."""
    relative = f"records/{study_code}/{record_id}/page-{page_no}{suffix}.jpg"
    target = resolve_in_storage(storage_dir, relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative, hashlib.sha256(data).hexdigest()
```

- [ ] **Step 5: Share the upload checks and add `replace_pages` (`server/capture/records/service.py`)**

Add these imports: `from capture.jobqueue import queue_extraction, queued_at` (extend the Task 6 import) and `Status` (already imported). Below `METADATA_MESSAGE`, add:

```python
CONFLICT_MESSAGE = "Someone else changed this record — reload"
```

Then replace `create_record` with the version below, which uses two shared checks, and add `replace_pages` after it:

```python
def _check_device_key(db: Session, key_fingerprint: str) -> None:
    expected = load_app_settings(db).expected_key_fingerprint
    if expected is None:
        raise UploadRejected(409, "The hospital key has not been set up yet — ask a hospital doctor to set up a device")
    if key_fingerprint != expected:
        raise UploadRejected(409, "This device's key doesn't match — ask your hospital admin.")


def _check_pages(settings: Settings, pages: list[bytes]) -> None:
    if not 1 <= len(pages) <= settings.max_pages:
        raise UploadRejected(422, f"Upload between 1 and {settings.max_pages} pages")
    for data in pages:
        if len(data) > settings.max_page_bytes:
            raise UploadRejected(413, f"Each page must be at most {settings.max_page_bytes // (1024 * 1024)} MB")
        try:
            check_jpeg(data)
        except ValueError as e:
            if str(e) == HAS_METADATA:
                raise UploadRejected(422, METADATA_MESSAGE) from None
            raise UploadRejected(415, "Pages must be JPEG images") from None


def create_record(
    db: Session,
    settings: Settings,
    user: User,
    *,
    study_code: str,
    template_key: str,
    key_fingerprint: str,
    client_upload_id: uuid.UUID,
    pages: list[bytes],
) -> tuple[Record, bool]:
    """Validate an upload, store its pages and create the record. Nothing is written on rejection.

    Returns (record, created). A replay of an earlier upload by the same user returns that record unchanged.
    """
    _check_device_key(db, key_fingerprint)
    template = get_active(db, template_key)
    if template is None:
        raise UploadRejected(404, "Unknown form type")
    existing = db.scalar(select(Record).where(Record.client_upload_id == client_upload_id))
    if existing is not None:
        if existing.created_by == user.id:
            return existing, False
        raise UploadRejected(409, "This upload ID is already in use")
    if template.kind == "dicom":
        raise UploadRejected(422, "Use the DICOM upload for this form")
    if template.phase == 3 and not load_app_settings(db).phase3_enabled:
        raise UploadRejected(403, "Locked until Phase 3")
    _check_pages(settings, pages)

    db.execute(pg_insert(Patient).values(study_code=study_code).on_conflict_do_nothing())
    record = Record(
        id=uuid.uuid4(),
        study_code=study_code,
        template_id=template.id,
        status=Status.DRAFT,
        extraction_status=ExtractionStatus.NOT_APPLICABLE,
        field_values={},
        created_by=user.id,
        client_upload_id=client_upload_id,
    )
    db.add(record)
    db.flush()
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, study_code, record.id, page_no, data)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
    queue_extraction(db, settings, record)
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="upload"))
    db.flush()
    return record, True


def replace_pages(
    db: Session,
    settings: Settings,
    user: User,
    record: Record,
    *,
    row_version: int,
    key_fingerprint: str,
    pages: list[bytes],
) -> list[str]:
    """New redacted photos for a held-back record (spec §8.1): the old files go and the AI reads the new ones.

    Returns the old files' stored paths, to delete once the change is committed. Nothing is written on rejection.
    """
    if record.status != Status.QUARANTINED:
        raise UploadRejected(409, "Only records held back for patient details can get new photos")
    if row_version != record.row_version:
        raise UploadRejected(409, CONFLICT_MESSAGE)
    _check_device_key(db, key_fingerprint)
    _check_pages(settings, pages)
    old = list(record.files)
    for page in old:
        db.delete(page)
    suffix = "-" + uuid.uuid4().hex[:8]
    for page_no, data in enumerate(pages, start=1):
        relative, digest = save_page(settings.storage_dir, record.study_code, record.id, page_no, data, suffix=suffix)
        db.add(RecordFile(record_id=record.id, kind="page", path=relative, sha256=digest, size=len(data), page_no=page_no))
    record.quarantine = None
    record.row_version += 1
    queue_extraction(db, settings, record)
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action="reupload"))
    db.flush()
    db.expire(record, ["files"])
    return [page.path for page in old]
```

Replace `detail_for` with:

```python
def detail_for(db: Session, record: Record, viewer_role: str) -> RecordDetail:
    errors = validate_values(template_def(record.template), record.field_values, today())
    phase3_enabled = load_app_settings(db).phase3_enabled
    since = queued_at(db, record.id) if record.status == Status.PROCESSING else None
    return record_detail(
        record,
        load_events(db, record.id),
        errors,
        phase3_enabled,
        duplicates_of(db, record, viewer_role),
        viewer_role in NSU_ROLES,
        since,
    )
```

- [ ] **Step 6: Show quarantine, AI results and the queue time (`schemas.py`, `convert.py`)**

In `server/capture/api/schemas.py`, add two fields at the end of `RecordSummary` (after `last_event`):

```python
    ai_amber: int = 0
    ai_red: int = 0
```

Then add two fields at the end of `RecordDetail` (after `duplicate_of`):

```python
    quarantine: dict[str, Any] | None = None
    extraction_queued_at: datetime | None = None
```

and a new model after `TransitionIn`:

```python
class ReuploadMeta(BaseModel):
    row_version: int
    key_fingerprint: str
```

In `server/capture/api/convert.py`:
- add `from datetime import datetime`, `from typing import Any` and `from capture.formschema.diff import flatten`;
- add these three functions:

```python
def _same(a: Any, b: Any) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return isinstance(a, bool) == isinstance(b, bool) and a == b


def extraction_view(record: Record, hide_values: bool) -> dict[str, Any] | None:
    """Per-field AI results. `edited` marks values changed since the AI filled them in.

    NSU never sees the AI's own values: one the hospital changed or removed may have held an identifier.
    """
    if not record.extraction:
        return None
    current = flatten(record.field_values or {})
    fields: dict[str, Any] = {}
    for path, entry in record.extraction.get("fields", {}).items():
        view = {
            "colour": entry["colour"],
            "confidence": entry["confidence"],
            "sources": entry["sources"],
            "edited": not _same(current.get(path), entry.get("value")),
        }
        if not hide_values:
            view["value"] = entry.get("value")
        fields[path] = view
    return {"model": record.extraction.get("model"), "fields": fields}


def ai_counts(record: Record) -> tuple[int, int]:
    """Amber and red AI fields still holding the AI's value: the queue's 🟡/🔴 counts (spec §8.3)."""
    if not record.extraction:
        return 0, 0
    current = flatten(record.field_values or {})
    unchecked = [
        entry["colour"] for path, entry in record.extraction.get("fields", {}).items() if _same(current.get(path), entry.get("value"))
    ]
    return unchecked.count("amber"), unchecked.count("red")
```

In `record_summary`, compute `ai_amber, ai_red = ai_counts(record)` first, then pass `ai_amber=ai_amber, ai_red=ai_red` to `RecordSummary(...)`.

Then give `record_detail` a last parameter `extraction_queued_at: datetime | None = None`, and in its `RecordDetail(...)` call:
- replace `extraction=record.extraction,` with `extraction=extraction_view(record, hide_change_values),`;
- add `quarantine=record.quarantine,` and `extraction_queued_at=extraction_queued_at,`.

- [ ] **Step 7: Transition side effects and the re-upload route (`server/capture/api/routes_records.py`)**

Update the imports:

```python
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from capture.api.convert import record_summary
from capture.api.deps import current_user, get_db, get_settings, require_roles
from capture.api.schemas import CreateMeta, RecordDetail, RecordSummary, ReuploadMeta, TransitionIn, ValuesIn
from capture.clock import today, utcnow
from capture.config import Settings
from capture.db.models import NSU_ROLES, ExtractionStatus, Record, ReviewEvent, Role, Status, Template, User
from capture.formschema.diff import diff_values
from capture.formschema.store import template_def
from capture.formschema.validate import document_date_of, validate_values
from capture.jobqueue import cancel_jobs, queue_extraction, queued_at
from capture.records.service import CONFLICT_MESSAGE, UploadRejected, create_record, detail_for, last_events, replace_pages
from capture.storage import remove_stored
from capture.workflow.rules import Action, TransitionError, can_edit, can_view, next_status

router = APIRouter(tags=["records"])
FILL_BY_HAND_AFTER = timedelta(minutes=2)  # spec §11.2
```

In `update_values`, use `CONFLICT_MESSAGE` in place of the literal 409 text. Replace `transition` with:

```python
@router.post("/records/{record_id}/transition", response_model=RecordDetail)
def transition(
    record_id: uuid.UUID,
    body: TransitionIn,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecordDetail:
    record = _load_visible(db, user, record_id, for_update=True)
    if body.row_version != record.row_version:
        raise HTTPException(status_code=409, detail=CONFLICT_MESSAGE)
    errors = validate_values(template_def(record.template), record.field_values, today())
    try:
        new_status = next_status(
            action=body.action,
            role=user.role,
            status=record.status,
            actor_id=user.id,
            creator_id=record.created_by,
            comment=body.comment,
            has_errors=bool(errors),
        )
    except TransitionError as e:
        raise HTTPException(status_code=e.http_status, detail=e.message) from None
    if body.action == Action.RELEASE and (record.quarantine or {}).get("files_expired"):
        raise HTTPException(status_code=409, detail="The photos were deleted after 14 days — upload them again")
    if body.action == Action.FILL_BY_HAND:
        since = queued_at(db, record.id)
        if since is not None and utcnow() - since < FILL_BY_HAND_AFTER:
            raise HTTPException(status_code=409, detail="The AI is still reading this record — try again in a minute")
    record.status = new_status
    record.row_version += 1
    if body.action == Action.RELEASE:
        record.quarantine = None
        queue_extraction(db, settings, record, skip_safety_net=True)
    elif body.action == Action.FILL_BY_HAND:
        cancel_jobs(db, record.id)
        record.extraction_status = ExtractionStatus.SKIPPED
    comment = (body.comment or "").strip() or None
    db.add(ReviewEvent(record_id=record.id, actor_id=user.id, action=body.action, comment=comment, field_flags=body.field_flags))
    db.commit()
    return detail_for(db, record, user.role)


@router.post("/records/{record_id}/reupload", response_model=RecordDetail)
def reupload(
    record_id: uuid.UUID,
    meta: str = Form(...),
    pages: list[UploadFile] = File(...),
    user: User = Depends(require_roles(Role.UPLOADER, Role.HOSPITAL_DOCTOR)),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RecordDetail:
    """New redacted photos for a record the safety net held back (spec §8.1)."""
    try:
        parsed = ReuploadMeta.model_validate_json(meta)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=_meta_error(e)) from None
    if len(pages) > settings.max_pages:
        raise HTTPException(status_code=422, detail=f"Upload between 1 and {settings.max_pages} pages")
    data = [page.file.read(settings.max_page_bytes + 1) for page in pages]
    record = _load_visible(db, user, record_id, for_update=True)
    try:
        old_paths = replace_pages(
            db, settings, user, record, row_version=parsed.row_version, key_fingerprint=parsed.key_fingerprint, pages=data
        )
    except UploadRejected as e:
        db.rollback()
        raise HTTPException(status_code=e.status, detail=e.message) from None
    db.commit()
    remove_stored(settings.storage_dir, old_paths)
    return detail_for(db, record, user.role)
```

`_meta_error` already starts its message with "Invalid upload details:", so it serves both routes.

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_rules.py tests/test_quarantine_api.py -q`
Expected: all pass. `test_quarantine_api.py` has 12 tests.

Run: `cd server && uv run pytest -q`
Expected: all pass. The route-inventory tests in `test_route_auth.py` also cover the new route with the 401 sweep.

- [ ] **Step 9: Commit**

```bash
git add server/capture/workflow/rules.py server/capture/storage.py server/capture/records/service.py server/capture/api server/tests/test_rules.py server/tests/test_quarantine_api.py
git commit -m "feat(api): release, re-upload and fill-by-hand for AI records; NSU sees AI colours but not AI values

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 9: PaddleOCR, the worker process, and the dev server's worker modes

**Files:**
- Modify: `server/pyproject.toml` (`ocr` extra; the `paddle` pytest marker), `server/capture/config.py`, `server/capture/devserver.py`, `server/tests/test_devserver.py`, `server/README.md`
- Create: `server/capture/extraction/paddle.py`, `server/capture/worker/__main__.py`
- Test: `server/tests/test_paddle_ocr.py`, `server/tests/test_devserver.py`

**Interfaces:**
- Consumes:
  - `Engines` (Task 7);
  - `run_worker` (Task 7);
  - `client_from_settings` (Task 5);
  - `stub_transport` (Task 5);
  - `OcrLine` (Task 1).
- Produces:
  - `Settings`: `ocr_det_model: str = "PP-OCRv5_mobile_det"`, `ocr_rec_model: str = "en_PP-OCRv5_mobile_rec"`, `ocr_enable_mkldnn: bool = False`.
  - `PaddleOcrEngine(settings)`, an `OcrEngine`. It creates PaddleOCR lazily, on the first `read` call, in the thread that runs the jobs.
  - `python -m capture.worker`.
  - `devserver.start_worker(settings, mode: str) -> threading.Event`.
  - `devserver --worker off|stub|vlm` (default `off`, the M2 behaviour). The e2e tests use `--worker stub`.

These were measured on this machine (Windows 11, PaddleOCR 3.7.0, PaddlePaddle 3.3.1, CPU):
- PaddlePaddle 3.3's oneDNN path crashes on Windows with `ConvertPirAttribute2RuntimeAttribute not support`. `enable_mkldnn=False` avoids it.
- The mobile models read `web/e2e/fixtures/report.jpg` correctly in about 4 s, including inside a background thread with a numpy BGR array.
- The first run downloads the models into `~/.paddlex`.

- [ ] **Step 1: Add the OCR extra, the test marker and the settings**

```bash
cd server && uv add --optional ocr "paddleocr>=3.7" "paddlepaddle>=3.3"
```

Expected: `pyproject.toml` gains `[project.optional-dependencies] ocr = [...]`, and `uv.lock` resolves.

In `server/pyproject.toml`, extend `[tool.pytest.ini_options]` to:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
filterwarnings = ["ignore::starlette.exceptions.StarletteDeprecationWarning"]
markers = ["paddle: real PaddleOCR; needs the OCR extra and downloads models (run: uv run --extra ocr pytest -m paddle)"]
addopts = "-m 'not paddle'"
```

At the end of `Settings` in `server/capture/config.py`:

```python
    ocr_det_model: str = "PP-OCRv5_mobile_det"  # PaddleOCR text detection (CPU-friendly)
    ocr_rec_model: str = "en_PP-OCRv5_mobile_rec"  # PaddleOCR English recognition
    ocr_enable_mkldnn: bool = False  # PaddlePaddle 3.3's oneDNN path crashes on Windows CPUs
```

- [ ] **Step 2: Write the failing tests**

`server/tests/test_paddle_ocr.py`:

```python
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
```

Append to `server/tests/test_devserver.py` (add `import subprocess`, `import sys` and `import pytest` at the top):

```python
def test_the_worker_needs_the_ocr_extra(monkeypatch, settings):
    monkeypatch.setattr(devserver.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(SystemExit, match="OCR extra"):
        devserver.start_worker(settings, "stub")


def test_the_api_process_never_loads_the_ocr_engine_or_the_worker():
    code = (
        "import sys, capture.api.app; "
        "print(sorted(m for m in sys.modules if m.startswith(('paddle', 'capture.worker', 'capture.extraction'))))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == "[]"
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_devserver.py -q`
Expected: FAIL, `AttributeError: module 'capture.devserver' has no attribute 'importlib'`. The second test already passes.

Run: `cd server && uv run --extra ocr pytest -m paddle -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'capture.extraction.paddle'`. The first run installs PaddlePaddle, which takes a few minutes.

- [ ] **Step 4: Write `server/capture/extraction/paddle.py`**

```python
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
```

- [ ] **Step 5: Write `server/capture/worker/__main__.py`**

```python
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
```

- [ ] **Step 6: Give the dev server a worker (`server/capture/devserver.py`)**

Add `import importlib.util`, `import logging` and `import threading` to the imports. Add `start_worker` after `prepare`, and replace `main`:

```python
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
```

- [ ] **Step 7: Document the worker in `server/README.md`**

In the "Operate" paragraph, change `` `CAPTURE_EXTRACTION_ENABLED` (stays `false` until the M3 worker exists) `` to `` `CAPTURE_EXTRACTION_ENABLED` (`true` once a worker runs, see below) ``. Then append:

````markdown
## AI worker

The worker reads each upload with PaddleOCR (CPU). It holds back pages where a patient identifier is still readable, and asks the self-hosted model (vLLM, OpenAI-compatible) to fill the form.

```bash
uv sync --extra ocr                                                    # PaddleOCR + PaddlePaddle; models download on first use
uv run --extra ocr python -m capture.devserver --reset --worker stub   # API + worker with a fixed-answer model
uv run --extra ocr pytest -m paddle                                    # the real-OCR test (left out of plain `uv run pytest`)
uv run --extra ocr python -m capture.worker                            # the worker process (API needs CAPTURE_EXTRACTION_ENABLED=true)
```

A plain `uv sync` removes the OCR extra again; `uv run` leaves it installed.

Use `--worker vlm` to send pages to the model at `CAPTURE_VLM_URL` (model name: `CAPTURE_VLM_MODEL`) instead of the stub. Fields below `CAPTURE_CONFIDENCE_THRESHOLD` (default 0.85) are shown amber. Keep `CAPTURE_OCR_ENABLE_MKLDNN=false` on Windows.
````

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd server && uv run pytest -q`
Expected: all pass, with the `paddle` test deselected (shown as "1 deselected").

Run: `cd server && uv run --extra ocr pytest -m paddle -q`
Expected: 1 passed. The first run downloads about 20 MB of models.

Smoke-test the dev server with the worker:
```bash
cd server && uv run --extra ocr python -m capture.devserver --reset --worker stub
```
Expected: it logs `worker devserver started` and serves on 127.0.0.1:8000. Stop it with Ctrl+C.

- [ ] **Step 9: Commit**

```bash
git add server/pyproject.toml server/uv.lock server/capture/config.py server/capture/extraction/paddle.py server/capture/worker/__main__.py server/capture/devserver.py server/tests/test_devserver.py server/tests/test_paddle_ocr.py server/README.md
git commit -m "feat(worker): PaddleOCR engine, python -m capture.worker, and dev server --worker modes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Golden-set evaluation

**Files:**
- Create: `eval/make_golden.py`, `eval/README.md`, `eval/golden/` (generated: 20 cases), `server/capture/evaluation.py`
- Modify: `server/capture/cli.py`, `server/README.md`
- Test: `server/tests/test_evaluation.py`

**Interfaces:**
- Consumes:
  - `VlmClient`, `VlmError`, `VlmUnavailable`, `client_from_settings` (Task 5);
  - `stub_transport` (Task 5);
  - `conform` (Task 4);
  - `flatten` (existing, `capture.formschema.diff`).
- Produces:
  - `evaluation.py`:
    - `S3_TARGET = 0.90`;
    - `CaseResult(template, case, style, correct, total, extra, wrong, error)`;
    - `score(tpl, expected, actual, ignore) -> (correct, total, extra, wrong)`;
    - `run_eval(golden_dir, templates_dir, client) -> list[CaseResult]`;
    - `report(results) -> str`.
  - `capture eval [--golden DIR] [--stub]`.
  - The golden layout is `eval/golden/<template_key>/case-NN/page-1.jpg` plus `expected.json`, holding `{"style": "typed" | "handwritten", "values": {...}, "ignore": [paths]}`.

- [ ] **Step 1: Write the generator and generate the golden set**

`eval/make_golden.py`:

```python
"""Writes the synthetic golden set: made-up documents with known values (spec §11.3). No real patient appears.

Run from the repository root:  uv run --no-project --with pillow python eval/make_golden.py
The values come from a fixed random seed, so re-running it writes the same documents and expected values.
"""

import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

GOLDEN = Path(__file__).resolve().parent / "golden"
SEED = 2026
LOBES = {
    "RUL": "right upper lobe",
    "RML": "right middle lobe",
    "RLL": "right lower lobe",
    "LUL": "left upper lobe",
    "LLL": "left lower lobe",
}
DESCRIPTIONS = ["spiculated mass", "ground-glass nodule", "cavitating lesion", "part-solid nodule", "lobulated mass"]
IMPRESSIONS = [
    "Suspicious for primary lung malignancy.",
    "Findings likely represent primary bronchogenic carcinoma.",
    "Stable appearance compared with the previous study.",
    "Interval progression of the known pulmonary lesion.",
]
CHANGES = {
    "new": "This lesion is new compared with the previous study.",
    "increased": "The lesion has increased in size since the previous study.",
    "decreased": "The lesion has decreased in size since the previous study.",
    "stable": "The lesion is stable compared with the previous study.",
}
EFFUSION_TEXT = {
    "none": "No pleural effusion.",
    "left": "Small left pleural effusion.",
    "right": "Moderate right pleural effusion.",
    "bilateral": "Bilateral pleural effusions.",
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def write_case(template: str, number: int, image: Image.Image, values: dict, ignore: list[str] | None = None) -> None:
    folder = GOLDEN / template / f"case-{number:02d}"
    folder.mkdir(parents=True)
    image.save(folder / "page-1.jpg", quality=85)
    expected = {"style": "typed", "values": values, "ignore": ignore or []}
    (folder / "expected.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


def redacted_header(draw: ImageDraw.ImageDraw, y: int) -> int:
    """Hospital header with the identifier lines already blacked out, as the worker receives them."""
    draw.text((80, y), "AHSANIA MISSION CANCER & GENERAL HOSPITAL (SYNTHETIC)", fill="black", font=font(34))
    for label in ("Patient Name:", "Reg No:", "Mobile:"):
        y += 60
        draw.text((80, y), label, fill="black", font=font(30))
        draw.rectangle((330, y - 6, 900, y + 40), fill="black")
    return y + 90


def radiology(rng: random.Random, number: int) -> None:
    modality = rng.choice(["CT", "CT", "MRI", "X-ray", "PET-CT"])
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    contrast = rng.choice([True, False, None]) if modality in ("CT", "MRI") else None
    title = {"CT": "CT CHEST", "MRI": "MRI THORAX", "X-ray": "CHEST X-RAY", "PET-CT": "PET-CT WHOLE BODY"}[modality]
    if contrast is True:
        title += " WITH CONTRAST"
    elif contrast is False:
        title += " WITHOUT CONTRAST"
    lesions = []
    findings = []
    for _ in range(rng.randrange(0, 3)):
        lobe = rng.choice(list(LOBES))
        long_axis = round(rng.uniform(0.8, 6.5), 1)
        short_axis = round(rng.uniform(0.5, long_axis), 1)
        description = rng.choice(DESCRIPTIONS)
        if rng.random() < 0.3:
            size = f"{round(long_axis * 10)} x {round(short_axis * 10)} mm"
        else:
            size = f"{long_axis} x {short_axis} cm"
        findings.append(f"A {size} {description} in the {LOBES[lobe]}.")
        lesions.append({"lobe": lobe, "long_axis_cm": long_axis, "short_axis_cm": short_axis, "description": description})
    effusion = rng.choice(list(EFFUSION_TEXT))
    findings.append(EFFUSION_TEXT[effusion])
    change = rng.choice([None, *CHANGES]) if lesions else None
    if change:
        findings.append(CHANGES[change])
    nodes = rng.choice([None, "Enlarged right hilar lymph node, 1.4 cm.", "Subcarinal lymphadenopathy."])
    if nodes:
        findings.append(nodes)
    impression = rng.choice(IMPRESSIONS)

    image = Image.new("RGB", (1240, 1754), "white")
    draw = ImageDraw.Draw(image)
    y = redacted_header(draw, 70)
    draw.text((80, y), title, fill="black", font=font(38))
    y += 70
    draw.text((80, y), f"Date: {study:%d/%m/%Y}", fill="black", font=font(30))
    y += 80
    draw.text((80, y), "FINDINGS", fill="black", font=font(32))
    for line in findings:
        y += 55
        draw.text((80, y), line, fill="black", font=font(28))
    y += 90
    draw.text((80, y), f"Impression: {impression}", fill="black", font=font(28))

    values = {
        "modality": modality,
        "study_date": study.isoformat(),
        "contrast": contrast,
        "lesions": lesions,
        "lymph_nodes": nodes,
        "metastasis_sites": None,
        "pleural_effusion": effusion,
        "reported_change": change,
        "impression": impression,
    }
    write_case("radiology_report", number, image, values)


def film_canvas(rng: random.Random) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    shade = rng.randrange(10, 40)
    image = Image.new("RGB", (1200, 1500), (shade, shade, shade))
    draw = ImageDraw.Draw(image)
    draw.ellipse((220, 300, 980, 1300), fill=(shade + 70,) * 3)
    return image, draw


def xray(rng: random.Random, number: int) -> None:
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    view, view_text = rng.choice([("PA", "PA"), ("AP", "AP"), ("lateral", "LAT")])
    side = rng.choice(["L", "R"])
    image, draw = film_canvas(rng)
    draw.text((40, 40), "AMCGH RADIOLOGY (SYNTHETIC)", fill="white", font=font(36))
    draw.text((40, 95), f"{study:%d-%m-%Y}", fill="white", font=font(36))
    draw.text((1000, 40), view_text, fill="white", font=font(48))
    draw.text((1060 if side == "R" else 60, 700), side, fill="white", font=font(90))
    values = {"study_date": study.isoformat(), "view": view, "side_marker": side, "capture_source": None}
    write_case("xray_film_photo", number, image, values, ignore=["capture_source"])


def ct_film(rng: random.Random, number: int) -> None:
    study = date(2025, 1, 1) + timedelta(days=rng.randrange(600))
    modality = rng.choice(["CT", "MRI"])
    window, window_text = rng.choice([("lung", "LUNG WINDOW  W:1500 L:-600"), ("mediastinal", "MEDIASTINAL WINDOW  W:350 L:40")])
    slice_label = f"IM {rng.randrange(10, 200)}"
    image, draw = film_canvas(rng)
    draw.text((40, 40), f"{modality}  {study:%d/%m/%Y}", fill="white", font=font(40))
    draw.text((40, 1380), window_text, fill="white", font=font(34))
    draw.text((900, 1380), slice_label, fill="white", font=font(40))
    values = {"modality": modality, "study_date": study.isoformat(), "window": window, "slice_label": slice_label, "capture_source": None}
    write_case("ct_mri_film_photo", number, image, values, ignore=["capture_source"])


def main() -> None:
    if GOLDEN.exists():
        shutil.rmtree(GOLDEN)
    rng = random.Random(SEED)
    for n in range(1, 13):
        radiology(rng, n)
    for n in range(1, 5):
        xray(rng, n)
    for n in range(1, 5):
        ct_film(rng, n)
    print(f"wrote {sum(1 for _ in GOLDEN.glob('*/*/expected.json'))} cases to {GOLDEN}")


if __name__ == "__main__":
    main()
```

Run from the repository root:

```bash
uv run --no-project --with pillow python eval/make_golden.py
```

Expected: `wrote 20 cases to …/eval/golden`. That is 12 `radiology_report`, 4 `xray_film_photo` and 4 `ct_mri_film_photo`, about 1.8 MB in all. Open one `page-1.jpg` and check that it shows a synthetic report with blacked-out identifier lines.

`eval/README.md`:

```markdown
# Extractor golden set

Synthetic documents with known values, used to measure the model's per-field accuracy (spec §1 S3, §11.3).
Every document is made up; no real patient appears.

    cd server
    uv run capture eval            # the model at CAPTURE_VLM_URL (needs the GPU server)
    uv run capture eval --stub     # checks the harness only (fixed answers, not a model)

Run it after every model or prompt change. S3 asks for at least 90 % field accuracy on typed documents.

## Layout

    golden/<template_key>/case-NN/page-1.jpg (more pages: page-2.jpg, ...)
    golden/<template_key>/case-NN/expected.json   {"style": "typed" | "handwritten", "values": {...}, "ignore": [...]}

`values` uses the form's value format (see `templates/<template_key>.yaml`). Fields listed in `ignore`
(for example `capture_source`, which can only be judged from the photo itself) are not scored.

## Adding cases

- Typed: extend `make_golden.py` and re-run it (`uv run --no-project --with pillow python eval/make_golden.py`).
- Handwritten (still to collect): staff write made-up values on blank AMCGH forms, black out nothing real,
  photograph them with the app's capture settings, and add a case folder with `"style": "handwritten"`.
```

- [ ] **Step 2: Write the failing tests**

`server/tests/test_evaluation.py`:

```python
import json
from datetime import date

import httpx
import yaml
from typer.testing import CliRunner

from capture.cli import app as cli
from capture.evaluation import report, run_eval, score
from capture.extraction.stub import STUB_VALUES, stub_transport
from capture.extraction.vlm import VlmClient
from capture.formschema.model import TemplateDef
from capture.formschema.validate import validate_values
from constants import PHOTO, REPO_DIR, TEMPLATES_DIR

GOLDEN = REPO_DIR / "eval" / "golden"
runner = CliRunner()


def template(key: str) -> TemplateDef:
    return TemplateDef.model_validate(yaml.safe_load((TEMPLATES_DIR / f"{key}.yaml").read_text(encoding="utf-8")))


def model(transport=None) -> VlmClient:
    return VlmClient("http://vlm.test/v1", "test-model", timeout=5, max_image_side=1600, transport=transport or stub_transport())


def write_case(root, template_key: str, name: str, values: dict, ignore=()) -> None:
    folder = root / template_key / name
    folder.mkdir(parents=True)
    (folder / "page-1.jpg").write_bytes(PHOTO)
    (folder / "expected.json").write_text(json.dumps({"style": "typed", "values": values, "ignore": list(ignore)}))


def test_scoring_counts_right_wrong_and_invented_values():
    expected = {
        "modality": "CT",
        "study_date": "2026-09-01",
        "contrast": None,
        "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}],
        "impression": "Suspicious for primary lung malignancy.",
    }
    actual = {
        "modality": "CT",
        "study_date": "2026-09-02",
        "contrast": True,
        "lesions": [{"lobe": "RUL", "long_axis_cm": 2.30}],
        "impression": "suspicious for primary lung malignancy",
    }
    assert score(template("radiology_report"), expected, actual, set()) == (4, 5, 1, ["study_date"])


def test_ignored_fields_are_not_scored():
    expected = {"study_date": "2026-09-01", "capture_source": None}
    actual = {"study_date": "2026-09-01", "capture_source": "monitor screen"}
    assert score(template("xray_film_photo"), expected, actual, {"capture_source"}) == (1, 1, 0, [])


def test_a_run_scores_each_case_and_reports_against_the_s3_target(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    write_case(tmp_path, "radiology_report", "case-02", {**STUB_VALUES["radiology_report"], "modality": "MRI"})
    results = run_eval(tmp_path, TEMPLATES_DIR, model())
    assert [(r.case, r.correct, r.total, r.wrong) for r in results] == [("case-01", 7, 7, []), ("case-02", 6, 7, ["modality"])]
    text = report(results)
    assert "radiology_report" in text
    assert "S3: typed accuracy 92.9% meets the 90% target" in text
    assert "radiology_report/case-02: wrong modality" in text


def test_a_model_error_counts_every_field_as_wrong(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    [result] = run_eval(tmp_path, TEMPLATES_DIR, model(httpx.MockTransport(lambda request: httpx.Response(500))))
    assert (result.correct, result.total, result.error) == (0, 7, "model server answered 500")


def test_the_cli_runs_a_golden_set_with_the_stub(tmp_path):
    write_case(tmp_path, "radiology_report", "case-01", STUB_VALUES["radiology_report"])
    r = runner.invoke(cli, ["eval", "--golden", str(tmp_path), "--stub"])
    assert r.exit_code == 0, r.output
    assert "S3: typed accuracy 100.0% meets the 90% target" in r.output


def test_the_cli_fails_on_a_folder_without_cases(tmp_path):
    r = runner.invoke(cli, ["eval", "--golden", str(tmp_path), "--stub"])
    assert r.exit_code == 1
    assert "no golden documents found" in r.output


def test_the_committed_golden_set_is_valid_for_its_templates():
    cases = sorted(GOLDEN.glob("*/*/expected.json"))
    assert len(cases) == 20
    for expected_file in cases:
        tpl = template(expected_file.parent.parent.name)
        spec = json.loads(expected_file.read_text(encoding="utf-8"))
        assert (expected_file.parent / "page-1.jpg").is_file()
        values = {key: value for key, value in spec["values"].items() if value is not None}
        errors = [e for e in validate_values(tpl, values, date(2026, 10, 5)) if e["path"] not in spec["ignore"]]
        assert errors == [], expected_file
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd server && uv run pytest tests/test_evaluation.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'capture.evaluation'`.

- [ ] **Step 4: Write `server/capture/evaluation.py`**

```python
"""Golden-set evaluation (spec §11.3): the model's per-field accuracy on synthetic documents with known values."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from capture.extraction.assemble import conform
from capture.extraction.vlm import VlmClient, VlmError, VlmUnavailable
from capture.formschema.diff import flatten
from capture.formschema.model import GroupField, NumberField, TemplateDef, TextField

S3_TARGET = 0.90  # spec §1: at least 90 % field accuracy on typed reports


@dataclass
class CaseResult:
    template: str
    case: str
    style: str
    correct: int = 0
    total: int = 0
    extra: int = 0  # values the model filled in where the document has none
    wrong: list[str] = field(default_factory=list)
    error: str | None = None


def _general(path: str) -> str:
    """lesions[1].lobe -> lesions[].lobe"""
    return re.sub(r"\[\d+\]", "[]", path)


def _field_types(fields: list, prefix: str = "") -> dict[str, Any]:
    types: dict[str, Any] = {}
    for f in fields:
        path = f"{prefix}.{f.key}" if prefix else f.key
        if isinstance(f, GroupField):
            types.update(_field_types(f.fields, f"{path}[]" if f.repeat else path))
        else:
            types[path] = f
    return types


def _normal(text: str) -> str:
    return " ".join(text.casefold().split()).rstrip(".")


def _same(f: Any, expected: Any, actual: Any) -> bool:
    if actual is None:
        return False
    if isinstance(f, NumberField):
        return not isinstance(actual, bool) and isinstance(actual, (int, float)) and abs(actual - expected) < 1e-6
    if isinstance(f, TextField):
        return isinstance(actual, str) and fuzz.ratio(_normal(expected), _normal(actual)) >= 90
    return actual == expected


def score(tpl: TemplateDef, expected: dict, actual: dict, ignore: set[str]) -> tuple[int, int, int, list[str]]:
    """(correct, total, extra, wrong paths). Only values the document holds are scored; invented ones count as extra."""
    types = _field_types(tpl.fields)
    want, got = flatten(expected), flatten(actual)
    correct = total = extra = 0
    wrong: list[str] = []
    for path, value in want.items():
        if value is None or _general(path) in ignore:
            continue
        total += 1
        if _same(types[_general(path)], value, got.get(path)):
            correct += 1
        else:
            wrong.append(path)
    for path, value in got.items():
        if value is not None and want.get(path) is None and _general(path) not in ignore:
            extra += 1
    return correct, total, extra, wrong


def run_eval(golden: Path, templates_dir: Path, client: VlmClient) -> list[CaseResult]:
    results: list[CaseResult] = []
    for expected_file in sorted(Path(golden).glob("*/*/expected.json")):
        case_dir = expected_file.parent
        key = case_dir.parent.name
        tpl = TemplateDef.model_validate(yaml.safe_load((templates_dir / f"{key}.yaml").read_text(encoding="utf-8")))
        spec = json.loads(expected_file.read_text(encoding="utf-8"))
        result = CaseResult(key, case_dir.name, spec.get("style", "typed"))
        pages = [page.read_bytes() for page in sorted(case_dir.glob("page-*.jpg"))]
        try:
            actual = conform(tpl, json.loads(client.extract(tpl, pages).text))
        except (VlmError, VlmUnavailable, ValueError) as e:
            result.error = str(e)
            actual = {}
        result.correct, result.total, result.extra, result.wrong = score(tpl, spec["values"], actual, set(spec.get("ignore", [])))
        results.append(result)
    return results


def _pct(correct: int, total: int) -> str:
    return f"{100 * correct / total:.1f}%" if total else "n/a"


def report(results: list[CaseResult]) -> str:
    lines = [f"{'template':<28} {'cases':>5} {'fields':>6} {'accuracy':>8} {'extra':>5}"]
    for key in sorted({r.template for r in results}):
        rows = [r for r in results if r.template == key]
        correct, total = sum(r.correct for r in rows), sum(r.total for r in rows)
        lines.append(f"{key:<28} {len(rows):>5} {total:>6} {_pct(correct, total):>8} {sum(r.extra for r in rows):>5}")
    for style in sorted({r.style for r in results}):
        rows = [r for r in results if r.style == style]
        correct, total = sum(r.correct for r in rows), sum(r.total for r in rows)
        lines.append(f"{style}: {_pct(correct, total)} of {total} fields")
    typed = [r for r in results if r.style == "typed"]
    correct, total = sum(r.correct for r in typed), sum(r.total for r in typed)
    if total:
        verdict = "meets" if correct / total >= S3_TARGET else "is below"
        lines.append(f"S3: typed accuracy {_pct(correct, total)} {verdict} the {S3_TARGET:.0%} target")
    for r in results:
        if r.error:
            lines.append(f"{r.template}/{r.case}: {r.error}")
        elif r.wrong:
            lines.append(f"{r.template}/{r.case}: wrong {', '.join(r.wrong)}")
    return "\n".join(lines)
```

- [ ] **Step 5: Add `capture eval` to `server/capture/cli.py`**

Add these imports:

```python
from capture.evaluation import report, run_eval
from capture.extraction.stub import stub_transport
from capture.extraction.vlm import client_from_settings
```

Below `REPO_TEMPLATES`, add:

```python
REPO_GOLDEN = Path(__file__).resolve().parents[2] / "eval" / "golden"
```

At the end of the file, add:

```python
@app.command("eval")
def eval_command(
    golden: Path = typer.Option(REPO_GOLDEN, help="Folder of <template>/<case>/ golden documents"),
    stub: bool = typer.Option(False, help="Use the built-in stub model: checks the harness, not a real model"),
) -> None:
    """Measure the model's per-field accuracy on the synthetic golden set (spec §11.3)."""
    client = client_from_settings(Settings(), stub_transport() if stub else None)
    results = run_eval(golden, REPO_TEMPLATES, client)
    if not results:
        _fail(f"no golden documents found in {golden}")
    typer.echo(report(results))
```

In `server/README.md`, add this line to the "Operate" code block:

```bash
uv run capture eval                            # model accuracy on ../eval/golden (needs CAPTURE_VLM_URL)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd server && uv run pytest tests/test_evaluation.py -q`
Expected: 7 passed.

Run: `cd server && uv run capture eval --stub`
Expected: a table for the three templates and the line `S3: typed accuracy …`. The stub only knows the e2e report, so most golden values count as wrong; this run checks the harness, not a model.

Run: `cd server && uv run pytest -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add eval server/capture/evaluation.py server/capture/cli.py server/tests/test_evaluation.py server/README.md
git commit -m "feat(eval): synthetic golden set and capture eval for per-field model accuracy

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 11: The review screen shows what the AI filled in

**Files:**
- Modify: `web/src/api/types.ts`, `web/src/records/RecordList.tsx`, `web/src/records/permissions.ts`, `web/src/records/permissions.test.ts`, `web/src/records/FormRenderer.tsx`, `web/src/records/FormRenderer.test.tsx`, `web/src/records/PageViewer.tsx`, `web/src/records/RecordPage.tsx`, `web/src/home/HomePage.tsx`, `web/playwright.config.ts`, `web/e2e/flow.spec.ts`
- Create: `web/src/records/aiMarkers.ts`, `web/src/records/aiMarkers.test.ts`, `web/src/ui/useNow.ts`

**Interfaces:**
- Consumes: the `RecordDetail` fields from Task 8 (`extraction`, `quarantine`, `extraction_queued_at`), the `fill_by_hand` transition, and the dev server's `--worker stub` (Task 9). With the stub model, the e2e report reads as:
  - Modality `CT`, study date `2026-09-01`;
  - one lesion: `RUL`, 2.3 × 1.8 cm, "spiculated mass";
  - the impression.
  The short axis is amber; every other filled field is green.
- Produces:
  - `types.ts`: `AiColour`, `SourceBox`, `AiField`, `Extraction`, `QuarantineHit`, `Quarantine`, and the new `RecordDetail` fields.
  - `aiMarkers.ts`: `AI_LABEL` and `aiMarker(extraction, path, current) -> AiField | null`.
  - `permissions.ts`: `UiAction` gains `"fill_by_hand"`; new `FILL_BY_HAND_AFTER_MS` and `fillByHandOffered(role, status, queuedAt, now)`.
  - `FormRenderer`: optional props `extraction` and `onFieldFocus(path, ai)`. Each field wrapper carries `data-ai="<colour>"` while it still holds the AI's value.
  - `PageViewer`: optional prop `marks: PageMark[]`, where `PageMark = SourceBox & { tone: "source" | "hit" }`. Overlays use `data-testid="source-box"` or `data-testid="phi-box"`.
  - `ui/useNow.ts`: `useNow(intervalMs) -> number`.
  - `RecordList` shows `🟡 N to check` and `🔴 N failing` from `ai_amber` and `ai_red`.

- [ ] **Step 1: Types**

In `web/src/api/types.ts`, add before `RecordSummary`:

```ts
export type AiColour = "green" | "amber" | "red" | "grey";

/** Where a value was read on a page: box = [x0, y0, x1, y1] in the stored page's pixels. */
export interface SourceBox {
  page: number;
  box: [number, number, number, number];
}

/** The AI's result for one field. `value` (what the AI filled in) is sent to hospital roles only. */
export interface AiField {
  colour: AiColour;
  confidence: number | null;
  sources: SourceBox[];
  edited: boolean;
  value?: unknown;
}

export interface Extraction {
  model: string;
  fields: Record<string, AiField>;
}

export interface QuarantineHit extends SourceBox {
  kind: string;
}

/** Why the safety net held a record back. Names kinds and pages, never the text that was found. */
export interface Quarantine {
  at: string;
  summary: string;
  hits: QuarantineHit[];
  files_expired: boolean;
}
```

In `RecordSummary`, add after `last_event: LastEvent | null;`:

```ts
  /** AI fields still holding an amber / red value (the queue's 🟡/🔴 counts). */
  ai_amber: number;
  ai_red: number;
```

In `RecordDetail`, replace `extraction: unknown;` with:

```ts
  extraction: Extraction | null;
  quarantine: Quarantine | null;
  extraction_queued_at: string | null;
```

- [ ] **Step 2: Write the failing unit tests**

`web/src/records/aiMarkers.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import type { Extraction } from "../api/types";
import { aiMarker } from "./aiMarkers";

const HOSPITAL_VIEW: Extraction = {
  model: "m",
  fields: {
    modality: { colour: "green", confidence: 0.99, sources: [{ page: 1, box: [0, 0, 10, 10] }], edited: false, value: "CT" },
    contrast: { colour: "grey", confidence: null, sources: [], edited: false, value: null },
    impression: { colour: "amber", confidence: 0.5, sources: [], edited: true, value: "old text" },
  },
};

describe("aiMarker", () => {
  it("shows the AI result while the field holds what the AI filled in", () => {
    expect(aiMarker(HOSPITAL_VIEW, "modality", "CT")?.colour).toBe("green");
  });
  it("drops it as soon as the value changes, even before saving", () => {
    expect(aiMarker(HOSPITAL_VIEW, "modality", "MRI")).toBeNull();
  });
  it("keeps grey on a field that is still empty", () => {
    expect(aiMarker(HOSPITAL_VIEW, "contrast", undefined)?.colour).toBe("grey");
    expect(aiMarker(HOSPITAL_VIEW, "contrast", "")?.colour).toBe("grey");
    expect(aiMarker(HOSPITAL_VIEW, "contrast", true)).toBeNull();
  });
  it("drops it for a value saved after the AI", () => {
    expect(aiMarker(HOSPITAL_VIEW, "impression", "old text")).toBeNull();
  });
  it("works without the AI's own values, as NSU receives them", () => {
    const nsuView: Extraction = { model: "m", fields: { modality: { colour: "green", confidence: 0.99, sources: [], edited: false } } };
    expect(aiMarker(nsuView, "modality", "CT")?.colour).toBe("green");
  });
  it("has nothing for fields the AI did not fill or records it did not read", () => {
    expect(aiMarker(HOSPITAL_VIEW, "lesions[0].lobe", "RUL")).toBeNull();
    expect(aiMarker(null, "modality", "CT")).toBeNull();
  });
});
```

Append to `web/src/records/permissions.test.ts`, and add `fillByHandOffered` to its import:

```ts
describe("fillByHandOffered", () => {
  const queued = "2026-10-05T10:00:00Z";
  const after = (minutes: number) => Date.parse(queued) + minutes * 60_000;

  it("waits two minutes", () => {
    expect(fillByHandOffered("uploader", "processing", queued, after(1.9))).toBe(false);
    expect(fillByHandOffered("uploader", "processing", queued, after(2))).toBe(true);
  });
  it("is only for hospital staff on a record the AI is reading", () => {
    expect(fillByHandOffered("hospital_doctor", "processing", queued, after(5))).toBe(true);
    expect(fillByHandOffered("nsu_reviewer", "processing", queued, after(5))).toBe(false);
    expect(fillByHandOffered("uploader", "draft", queued, after(5))).toBe(false);
    expect(fillByHandOffered("uploader", "processing", null, after(5))).toBe(false);
  });
});
```

Append to `web/src/records/FormRenderer.test.tsx`, and add `import type { AiField, Extraction } from "../api/types";` at the top:

```tsx
describe("FormRenderer AI markers", () => {
  const extraction: Extraction = {
    model: "m",
    fields: { modality: { colour: "amber", confidence: 0.6, sources: [{ page: 1, box: [1, 2, 3, 4] }], edited: false, value: "CT" } },
  };

  it("marks a field the AI filled, reports its sources on focus, and drops the mark once changed", async () => {
    const focused: Array<[string, AiField | null]> = [];
    function AiHarness() {
      const [values, setValues] = useState<Record<string, unknown>>({ modality: "CT" });
      return (
        <FormRenderer
          fields={FIELDS}
          values={values}
          onChange={setValues}
          errors={{}}
          readOnly={false}
          extraction={extraction}
          onFieldFocus={(path, ai) => focused.push([path, ai])}
        />
      );
    }
    const { container } = render(<AiHarness />);
    expect(container.querySelector('[data-ai="amber"]')).not.toBeNull();
    expect(screen.getByText("AI: please check")).toBeTruthy();
    const select = screen.getByLabelText(/Modality/);
    await userEvent.click(select);
    expect(focused.at(-1)).toEqual(["modality", extraction.fields.modality]);
    await userEvent.selectOptions(select, "MRI");
    expect(container.querySelector("[data-ai]")).toBeNull();
  });

  it("lets a read-only reviewer tap a field to see its sources", async () => {
    const focused: string[] = [];
    render(
      <FormRenderer fields={FIELDS} values={{ modality: "CT" }} onChange={() => {}} errors={{}} readOnly extraction={extraction} onFieldFocus={(path) => focused.push(path)} />,
    );
    await userEvent.click(screen.getByText("AI: please check"));
    expect(focused).toContain("modality");
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/records`
Expected:
- FAIL: `Failed to resolve import "./aiMarkers"`;
- `fillByHandOffered is not a function`;
- no `[data-ai]` element.

- [ ] **Step 4: Write `web/src/records/aiMarkers.ts` and `web/src/ui/useNow.ts`**

`web/src/records/aiMarkers.ts`:

```ts
import type { AiColour, AiField, Extraction } from "../api/types";

/** What each spec §5.2 colour tells the person checking the form. */
export const AI_LABEL: Record<AiColour, string> = {
  green: "AI: found on the page",
  amber: "AI: please check",
  red: "AI: fails a check",
  grey: "AI: not in the document",
};

const isEmpty = (v: unknown) => v === null || v === undefined || (typeof v === "string" && v.trim() === "");

/** The AI's result for a field, as long as the field still holds what the AI filled in. */
export function aiMarker(extraction: Extraction | null | undefined, path: string, current: unknown): AiField | null {
  const field = extraction?.fields[path];
  if (!field || field.edited) return null;
  if ("value" in field && !(isEmpty(field.value) ? isEmpty(current) : field.value === current)) return null;
  return field;
}
```

`web/src/ui/useNow.ts`:

```ts
import { useEffect, useState } from "react";

/** The current time, refreshed every `intervalMs`. */
export function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
```

- [ ] **Step 5: Permissions (`web/src/records/permissions.ts`)**

Change the `UiAction` line, and add the offer rule at the end:

```ts
export type UiAction = "submit" | "approve" | "return" | "reopen" | "fill_by_hand";
```

```ts
/** Spec §11.2: after 2 minutes of waiting for the AI, hospital staff may fill the form in by hand. */
export const FILL_BY_HAND_AFTER_MS = 2 * 60_000;

export function fillByHandOffered(role: Role, status: Status, queuedAt: string | null, now: number): boolean {
  if (!isHospital(role) || status !== "processing" || queuedAt === null) return false;
  return now - Date.parse(queuedAt) >= FILL_BY_HAND_AFTER_MS;
}
```

`availableActions` is unchanged. "Fill by hand now" has its own button in the processing banner.

- [ ] **Step 6: Markers in the form (`web/src/records/FormRenderer.tsx`)**

1. Change the imports at the top to:

```tsx
import { useEffect, useState } from "react";
import type { AiColour, AiField, Extraction, FieldDef } from "../api/types";
import { card, inputClass, secondaryButton } from "../ui/styles";
import { AI_LABEL, aiMarker } from "./aiMarkers";
import { getIn, humanize, pathToString, setIn, type PathPart } from "./fieldPaths";
```

2. Add to `Props`:

```tsx
  /** AI results: fields still holding the AI's value get a coloured marker (spec §5.2). */
  extraction?: Extraction | null;
  /** Called when a field gets focus or is tapped, with its AI result (null when it has none). */
  onFieldFocus?: (path: string, ai: AiField | null) => void;
```

3. Add to `Context`:

```tsx
  extraction: Extraction | null;
  onFieldFocus?: (path: string, ai: AiField | null) => void;
```

4. Replace the `FormRenderer` function's signature and `ctx` line with:

```tsx
export function FormRenderer({ fields, values, onChange, errors, readOnly, flags = {}, extraction = null, onFieldFocus }: Props) {
  const ctx: Context = { values, set: (parts, value) => onChange(setIn(values, parts, value)), errors, flags, readOnly, extraction, onFieldFocus };
```

5. Below the `FormRenderer` function, add:

```tsx
const AI_BORDER: Record<AiColour, string> = {
  green: "border-green-600",
  amber: "border-amber-500",
  red: "border-red-600",
  grey: "border-slate-300",
};
const AI_TEXT: Record<AiColour, string> = {
  green: "text-green-700",
  amber: "text-amber-700",
  red: "text-red-700",
  grey: "text-slate-500",
};
```

6. In `FieldView`, replace the leaf branch from `const id = \`f-${path}\`;` down to the closing `</label>`. That is: compute `ai`, wrap the field, and add the marker text to the label. The rest of the leaf JSX (inputs, hint, flag, error) and its closing `</div>` stay as they are.

```tsx
  const id = `f-${path}`;
  const inputCls = `${inputClass} ${error ? "border-red-500" : ""}`;
  const set = (v: unknown) => ctx.set(parts, v);
  const ai = aiMarker(ctx.extraction, path, value);
  const reportFocus = () => ctx.onFieldFocus?.(path, ai);
  return (
    <div data-ai={ai?.colour} className={ai ? `border-l-4 pl-2 ${AI_BORDER[ai.colour]}` : undefined} onFocus={reportFocus} onClick={reportFocus}>
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
        {field.required && <span className="text-red-700"> *</span>}
        {field.type === "number" && field.unit && <span className="text-slate-500"> ({field.unit})</span>}
        {ai && <span className={`ml-2 text-xs font-normal ${AI_TEXT[ai.colour]}`}>{AI_LABEL[ai.colour]}</span>}
      </label>
```

The marker text sits inside the `<label>`. The input's accessible name therefore includes it ("Long axis (cm) AI: found on the page"), so a screen reader announces the AI status. Label lookups by substring (`getByLabel("Long axis")`) still work.

- [ ] **Step 7: Source boxes on the page (`web/src/records/PageViewer.tsx`)**

Replace the file with:

```tsx
import { useEffect, useState } from "react";
import { TransformComponent, TransformWrapper } from "react-zoom-pan-pinch";
import type { FileOut, SourceBox } from "../api/types";
import { card, secondaryButton } from "../ui/styles";

/** A box drawn over a page: where a value was read ("source") or where the safety net found an identifier ("hit"). */
export type PageMark = SourceBox & { tone: "source" | "hit" };

export function PageViewer({ files, marks = [] }: { files: FileOut[]; marks?: PageMark[] }) {
  const pages = files.filter((f) => f.kind === "page");
  const [index, setIndex] = useState(0);
  const [size, setSize] = useState<{ id: string; w: number; h: number } | null>(null);
  const marksKey = marks.map((m) => `${m.page}:${m.box.join(",")}`).join("|");

  // Show the page of the first mark whenever the marks change (e.g. another field was tapped).
  useEffect(() => {
    if (marks.length > 0) setIndex(marks[0].page - 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [marksKey]);

  if (pages.length === 0) return <p className={card}>No images.</p>;
  const current = Math.min(Math.max(index, 0), pages.length - 1);
  const file = pages[current];
  const natural = size?.id === file.id ? size : null;
  const shown = natural ? marks.filter((m) => m.page === current + 1) : [];
  const pct = (value: number, total: number) => `${(value / total) * 100}%`;
  return (
    <details open className={`${card} space-y-2 self-start`}>
      <summary className="cursor-pointer font-medium">
        Page {current + 1} of {pages.length} — pinch or scroll to zoom
      </summary>
      <TransformWrapper key={file.id}>
        <TransformComponent wrapperClass="!w-full" contentClass="!w-full">
          <div className="relative w-full">
            <img
              src={`/api/files/${file.id}`}
              alt={`Page ${current + 1}`}
              className="w-full"
              onLoad={(e) => setSize({ id: file.id, w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            />
            {natural &&
              shown.map((m, i) => (
                <div
                  key={i}
                  data-testid={m.tone === "hit" ? "phi-box" : "source-box"}
                  className={`pointer-events-none absolute border-2 ${m.tone === "hit" ? "border-red-600 bg-red-500/10" : "border-blue-600 bg-blue-500/10"}`}
                  style={{
                    left: pct(m.box[0], natural.w),
                    top: pct(m.box[1], natural.h),
                    width: pct(m.box[2] - m.box[0], natural.w),
                    height: pct(m.box[3] - m.box[1], natural.h),
                  }}
                />
              ))}
          </div>
        </TransformComponent>
      </TransformWrapper>
      {pages.length > 1 && (
        <div className="flex gap-2">
          <button type="button" disabled={current === 0} onClick={() => setIndex(current - 1)} className={secondaryButton}>Previous</button>
          <button type="button" disabled={current === pages.length - 1} onClick={() => setIndex(current + 1)} className={secondaryButton}>Next</button>
        </div>
      )}
    </details>
  );
}
```

- [ ] **Step 8: The review screen (`web/src/records/RecordPage.tsx`)**

Replace the file with:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, json } from "../api/client";
import { useRecord } from "../api/hooks";
import type { EventOut, RecordDetail, SourceBox } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { StatusBadge } from "../ui/StatusBadge";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";
import { useNow } from "../ui/useNow";
import { FormRenderer } from "./FormRenderer";
import { PageViewer, type PageMark } from "./PageViewer";
import { availableActions, canEdit, fillByHandOffered, type UiAction } from "./permissions";

/** The server's 409 for a stale row_version. Any other 409 carries its own reason, which is shown as it is. */
const CONFLICT = "Someone else changed this record — reload";

const DONE: Record<UiAction, string> = {
  submit: "Submitted for doctor review",
  approve: "Approved",
  return: "Returned to the uploader",
  reopen: "Reopened",
  fill_by_hand: "The AI was stopped — fill the form in by hand",
};

const EVENT_LABEL: Record<string, string> = {
  upload: "uploaded",
  edit: "edited",
  submit: "submitted",
  approve: "approved",
  return: "returned",
  reopen: "reopened",
  quarantine: "held it back",
  release: "released it",
  reupload: "uploaded new photos",
  fill_by_hand: "chose to fill it in by hand",
};

export default function RecordPage() {
  const { id = "" } = useParams();
  const record = useRecord(id);
  if (record.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  return <RecordView key={record.data.id} record={record.data} />;
}

function RecordView({ record: r }: { record: RecordDetail }) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const now = useNow(5_000);
  const [values, setValues] = useState(r.values);
  const [syncedVersion, setSyncedVersion] = useState(r.row_version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [dialog, setDialog] = useState<"return" | "reopen" | null>(null);
  const [comment, setComment] = useState("");
  const [sources, setSources] = useState<SourceBox[]>([]);

  // When the server copy changes (save, action, the AI finishing, reload), show its values.
  if (syncedVersion !== r.row_version) {
    setSyncedVersion(r.row_version);
    setValues(r.values);
  }

  const editable = canEdit(me.role, r.status);
  const dirty = JSON.stringify(values) !== JSON.stringify(r.values);
  const actions = availableActions(me.role, r.status, r.created_by_id === me.id);
  const errors = Object.fromEntries(r.errors.map((e) => [e.path, e.message]));
  const lastReturn = r.status === "draft" ? [...r.events].reverse().find((e) => e.action === "return" || e.action === "reopen") : undefined;
  const marks: PageMark[] = sources.map((s) => ({ ...s, tone: "source" as const }));

  function store(updated: RecordDetail) {
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
  }

  function failed(e: unknown, fallback: string) {
    if (e instanceof ApiError && e.status === 409 && e.message === CONFLICT) setConflict(true);
    else setMessage(e instanceof Error ? e.message : fallback);
  }

  /** Saves the form; returns the updated record, or null after showing the error. */
  async function save(): Promise<RecordDetail | null> {
    try {
      const updated = await api<RecordDetail>(`/records/${r.id}/values`, { method: "PATCH", body: json({ row_version: r.row_version, values }) });
      store(updated);
      return updated;
    } catch (e) {
      failed(e, "Save failed");
      return null;
    }
  }

  async function onSave() {
    setBusy(true);
    setMessage(null);
    if (await save()) setMessage("Saved");
    setBusy(false);
  }

  async function run(action: UiAction, withComment?: string) {
    setBusy(true);
    setMessage(null);
    try {
      // Unsaved edits are saved first; the action then names the row_version it was taken on.
      let current = r;
      if (editable && dirty) {
        const saved = await save();
        if (!saved) return;
        current = saved;
      }
      store(
        await api<RecordDetail>(`/records/${r.id}/transition`, {
          method: "POST",
          body: json({ action, comment: withComment ?? null, row_version: current.row_version }),
        }),
      );
      setDialog(null);
      setComment("");
      setMessage(DONE[action]);
    } catch (e) {
      failed(e, "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{r.template_title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <span>
            Study code <span className="font-mono">{r.study_code}</span>
          </span>
          <StatusBadge status={r.status} />
          <span>Uploaded by {r.created_by_name}</span>
        </p>
      </header>

      {r.duplicate_of.length > 0 && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          This looks already uploaded for this patient:
          {r.duplicate_of.map((d) => (
            <Link key={d} to={`/records/${d}`} className="ml-2 underline">
              {d.slice(0, 8)}
            </Link>
          ))}
        </p>
      )}
      {lastReturn && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          Returned by {lastReturn.actor_name}: {lastReturn.comment}
        </p>
      )}
      {r.status === "processing" && (
        <div className="space-y-2 rounded-md bg-slate-100 p-3">
          <p>The AI is reading this document…</p>
          {fillByHandOffered(me.role, r.status, r.extraction_queued_at, now) && (
            <>
              <p className="text-sm text-slate-600">This is taking longer than usual.</p>
              <button type="button" disabled={busy} onClick={() => run("fill_by_hand")} className={secondaryButton}>
                Fill by hand now
              </button>
            </>
          )}
        </div>
      )}
      {r.status === "draft" && r.extraction_status === "failed" && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">The AI could not read this document — fill the form in by hand.</p>
      )}
      {r.status === "draft" && r.extraction && (
        <p className="text-sm text-slate-600">The AI filled in this form. Check every amber field; tap a field to see where it was read on the page.</p>
      )}
      {conflict && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-red-800">
          {CONFLICT}
          <button
            type="button"
            className={`${secondaryButton} ml-2`}
            onClick={() => {
              setConflict(false);
              void queryClient.invalidateQueries({ queryKey: ["record", r.id] });
            }}
          >
            Reload
          </button>
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <PageViewer files={r.files} marks={marks} />
        <div className="space-y-4">
          <FormRenderer
            fields={r.template.definition.fields}
            values={values}
            onChange={setValues}
            errors={errors}
            readOnly={!editable}
            flags={lastReturn?.field_flags ?? {}}
            extraction={r.extraction}
            onFieldFocus={(_, ai) => setSources(ai?.sources ?? [])}
          />
          <div className="flex flex-wrap gap-2">
            {editable && (
              <button type="button" disabled={busy || !dirty} onClick={onSave} className={secondaryButton}>
                Save
              </button>
            )}
            {actions.includes("submit") && (
              <button type="button" disabled={busy} onClick={() => run("submit")} className={primaryButton}>
                Submit for doctor review
              </button>
            )}
            {actions.includes("approve") && (
              <button type="button" disabled={busy} onClick={() => run("approve")} className={primaryButton}>
                Approve
              </button>
            )}
            {actions.includes("return") && (
              <button type="button" disabled={busy} onClick={() => setDialog("return")} className={secondaryButton}>
                Return…
              </button>
            )}
            {actions.includes("reopen") && (
              <button type="button" disabled={busy} onClick={() => setDialog("reopen")} className={secondaryButton}>
                Reopen…
              </button>
            )}
          </div>
          {me.role === "hospital_doctor" && r.status === "pending_doctor" && r.created_by_id === me.id && (
            <p className="text-sm text-slate-600">You uploaded this record, so another doctor must approve it.</p>
          )}
          {dialog && (
            <div className={`${card} space-y-2`}>
              <label className="block text-sm font-medium">
                {dialog === "return" ? "What needs fixing?" : "Reason for reopening"}
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} className={inputClass} />
              </label>
              <div className="flex gap-2">
                <button type="button" disabled={busy || !comment.trim()} onClick={() => run(dialog, comment)} className={primaryButton}>
                  Confirm
                </button>
                <button type="button" onClick={() => setDialog(null)} className={secondaryButton}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {message && (
            <p role="status" className="text-sm">
              {message}
            </p>
          )}
        </div>
      </div>
      <History events={r.events} />
    </div>
  );
}

function History({ events }: { events: EventOut[] }) {
  return (
    <section className={card}>
      <h2 className="mb-2 font-semibold">History</h2>
      <ol className="space-y-1 text-sm">
        {events.map((e) => (
          <li key={e.id}>
            {new Date(e.created_at).toLocaleString()} — {e.actor_name} {EVENT_LABEL[e.action] ?? e.action}
            {e.action === "edit" && e.field_changes ? ` ${e.field_changes.length} field(s)` : ""}
            {e.comment ? `: ${e.comment}` : ""}
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 9: Home lists the records the AI is still reading (`web/src/home/HomePage.tsx`)**

In `HospitalHome`, below `const drafts = ...`, add:

```tsx
  const reading = useRecords({ status: "processing", mine: true });
```

Insert directly before `<section className="space-y-2">` with the "My drafts" heading:

```tsx
      {(reading.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold">Being read by the AI</h2>
          <RecordList records={reading.data ?? []} empty="" />
        </section>
      )}
```

- [ ] **Step 10: 🟡/🔴 counts in record lists (`web/src/records/RecordList.tsx`)**

Directly after the "Returned" badge's closing `)}`, add:

```tsx
              {r.ai_amber > 0 && <span className="mb-1 ml-1 inline-block rounded bg-amber-100 px-2 text-amber-800">🟡 {r.ai_amber} to check</span>}
              {r.ai_red > 0 && <span className="mb-1 ml-1 inline-block rounded bg-red-100 px-2 text-red-800">🔴 {r.ai_red} failing</span>}
```

- [ ] **Step 11: Run the unit tests and the type check**

Run: `cd web && npm test && npm run typecheck`
Expected: all pass (148: the 138 after Task 2, plus 6 aiMarkers, 2 permissions and 2 FormRenderer), and no type errors.

- [ ] **Step 12: Run the e2e story with the worker**

In `web/playwright.config.ts`, make the first `webServer` entry:

```ts
    {
      command: "uv run --project ../server --extra ocr python -m capture.devserver --reset --port 8000 --worker stub",
      url: "http://127.0.0.1:8000/api/health",
      timeout: 300_000,
      reuseExistingServer: false,
    },
```

In `web/e2e/flow.spec.ts`:

(a) At the end of `test("names are boxed on the device and only the redacted page is uploaded", …)`, after the three brightness checks, add:

```ts
  // The worker reads the page (PaddleOCR, then the stub model) and turns the record into a pre-filled draft.
  await page.goto(`/records/${recordId}`);
  await expect(page.getByTestId("record-status")).toHaveText("Draft", { timeout: 90_000 });
```

(b) Replace `test("the uploader fills the form, sees a validation error, fixes it and submits", …)` with:

```ts
test("the AI fills the form; the uploader checks the amber field, fixes a mistake and submits", async () => {
  await page.goto(`/records/${recordId}`);
  await expect(page.getByRole("heading", { name: /Radiology report/ })).toBeVisible();
  await expect(page.getByRole("img", { name: "Page 1" })).toBeVisible();
  await expect(page.getByTestId("record-status")).toHaveText("Draft");
  await expect(page.getByLabel("Modality")).toHaveValue("CT");
  await expect(page.getByLabel("Study date")).toHaveValue("2026-09-01");
  await expect(page.getByLabel("Lobe")).toHaveValue("RUL");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.3");
  await expect(page.locator('[data-ai="amber"]')).toHaveCount(1);
  await expect(page.locator('[data-ai="amber"]')).toContainText("Short axis");
  await expect(page.locator('[data-ai="green"]', { hasText: "Long axis" })).toBeVisible();

  // Tapping a field outlines where the AI read it.
  await page.getByLabel("Short axis").focus();
  await expect(page.getByTestId("source-box")).toBeVisible();

  // A mistake the server flags, then the fix. A changed value loses its AI marker.
  await page.getByLabel("Long axis").fill("abc");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByText("must be a number")).toBeVisible();
  await page.getByLabel("Long axis").fill("2.");
  await page.getByLabel("Long axis").pressSequentially("4");
  await expect(page.getByLabel("Long axis")).toHaveValue("2.4");
  await expect(page.locator("[data-ai]", { hasText: "Long axis" })).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(page.getByText("must be a number")).toHaveCount(0);
  await page.getByRole("button", { name: "Submit for doctor review" }).click();
  await expect(page.getByTestId("record-status")).toHaveText("Waiting for doctor");
  await expect(page.getByLabel("Modality")).toBeDisabled();
  await logout();
});
```

(c) In `test("NSU returns the record with a comment and the uploader sees it on the home screen", …)`:
- replace the comment `"Please add the short axis"` with `"Please check the short axis"`;
- replace the banner regex with `/^Returned by .+: Please check the short axis$/`;
- replace `await page.getByLabel("Short axis").fill("1.8");` with `await page.getByLabel("Short axis").fill("1.9");`.

(d) In `test("a second hospital doctor approves from the doctor queue", …)`, replace `await openFromQueue("Doctor queue");` with:

```ts
  await page.getByRole("link", { name: "Doctor queue" }).click();
  await expect(page.getByText("🟡 1 to check")).toBeVisible(); // the short axis is still the AI's unsure value
  await page.getByRole("link", { name: new RegExp(studyCode) }).click();
```

(e) In the last test ("an upload made while the server is unreachable…"), replace the final link assertion with:

```ts
  await expect(page.getByRole("link", { name: new RegExp(queuedCode) }).first()).toBeVisible();
```

Here `.first()` is needed: the new record can briefly show both under "Being read by the AI" and under "My drafts" while the lists refresh.

Run: `cd web && npm run e2e`
Expected: 9 passed. The first run installs the OCR extra into the server environment and may take a few minutes.

- [ ] **Step 13: Commit**

```bash
git add web/src web/playwright.config.ts web/e2e/flow.spec.ts
git commit -m "feat(web): AI pre-fill on the review screen with colour markers, source boxes and Fill by hand now

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 12: Held-back records — release, new photos, and the home list

**Files:**
- Modify: `web/src/records/permissions.ts`, `web/src/records/permissions.test.ts`, `web/src/records/RecordPage.tsx`, `web/src/capture/RedactStep.tsx`, `web/src/capture/RedactStep.test.tsx`, `web/src/capture/CapturePage.tsx`, `web/src/App.tsx`, `web/src/home/HomePage.tsx`, `web/e2e/flow.spec.ts`
- Create: `web/src/capture/ReuploadPage.tsx`

**Interfaces:**
- Consumes:
  - `POST /api/records/{id}/reupload` (Task 8), with multipart `meta` = `{"row_version", "key_fingerprint"}` and `pages`;
  - the `release` transition (Task 8);
  - `RecordDetail.quarantine` (Tasks 8 and 11);
  - `PageMark` with `tone: "hit"` (Task 11).
- Produces:
  - `UiAction` gains `"release"`; `availableActions("hospital_doctor", "quarantined", _)` returns `["release"]`.
  - `RedactStep` props become `{ pages, onChange, onUpload(redacted: Blob[]): Promise<void>, onBack }`. Boxes are still burned in inside `RedactStep`. `CapturePage` sends through the outbox, as before. `ReuploadPage` posts directly while online, with no outbox.
  - New route `/records/:id/reupload`.

- [ ] **Step 1: Write the failing unit tests**

Append to the `availableActions` block in `web/src/records/permissions.test.ts`:

```ts
  it("lets a hospital doctor release a held-back record", () => {
    expect(availableActions("hospital_doctor", "quarantined", false)).toEqual(["release"]);
    expect(availableActions("uploader", "quarantined", true)).toEqual([]);
  });
```

Replace `web/src/capture/RedactStep.test.tsx` with:

```tsx
// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { burnRedactions } from "../imaging/render";
import { RedactStep } from "./RedactStep";
import type { PageDraft } from "./types";

vi.mock("../redaction/ocr", () => ({ ocrLines: vi.fn(async () => []) }));
vi.mock("./RedactionCanvas", () => ({
  RedactionCanvas: (props: { url: string; onShown: () => void }) => {
    useEffect(() => {
      props.onShown();
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [props.url]);
    return <div data-testid="canvas">{props.url}</div>;
  },
}));
vi.mock("../imaging/render", () => ({ burnRedactions: vi.fn(async (blob: Blob) => blob) }));

const draft = (id: string): PageDraft => ({
  id,
  blob: new Blob(["x"], { type: "image/jpeg" }),
  url: `blob:${id}`,
  width: 1000,
  height: 1400,
  blur: 100,
  boxes: [],
  ocrDone: true,
});

function Harness({ onUpload }: { onUpload: (redacted: Blob[]) => Promise<void> }) {
  const [pages, setPages] = useState<PageDraft[]>([draft("p1"), draft("p2")]);
  return <RedactStep pages={pages} onChange={setPages} onUpload={onUpload} onBack={() => undefined} />;
}

afterEach(cleanup);

async function openEveryPageAndConfirm() {
  const checkbox = screen.getByLabelText("All names and numbers are covered.") as HTMLInputElement;
  await userEvent.click(screen.getByRole("button", { name: /^Page 2/ }));
  await waitFor(() => expect(checkbox.disabled).toBe(false));
  await userEvent.click(checkbox);
  return checkbox;
}

describe("RedactStep", () => {
  it("needs every page opened before upload, and unticks the confirmation when boxes change", async () => {
    render(<Harness onUpload={vi.fn(async () => {})} />);
    const checkbox = screen.getByLabelText("All names and numbers are covered.") as HTMLInputElement;
    const upload = screen.getByRole("button", { name: "Upload" }) as HTMLButtonElement;

    expect(checkbox.disabled).toBe(true);
    expect(screen.getByText("Open every page and check it before uploading.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Page 2 · 0 boxes · not checked" })).toBeTruthy();

    await openEveryPageAndConfirm();
    expect(upload.disabled).toBe(false);

    await userEvent.click(screen.getByRole("button", { name: "Add box" }));
    expect(checkbox.checked).toBe(false);
    expect(upload.disabled).toBe(true);
  });

  it("burns the boxes in, hands only the redacted pages on, and shows a refusal", async () => {
    const onUpload = vi.fn(async () => {
      throw new Error("Upload refused: wrong key");
    });
    render(<Harness onUpload={onUpload} />);
    await openEveryPageAndConfirm();
    await userEvent.click(screen.getByRole("button", { name: "Upload" }));
    expect(vi.mocked(burnRedactions)).toHaveBeenCalledTimes(2);
    expect(onUpload).toHaveBeenCalledWith([expect.any(Blob), expect.any(Blob)]);
    expect((await screen.findByRole("alert")).textContent).toBe("Upload refused: wrong key");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/records/permissions.test.ts src/capture/RedactStep.test.tsx`
Expected:
- FAIL: the release case returns `[]`;
- `RedactStep` ignores `onUpload` (`onUpload` is never called; `useNavigate() may be used only in the context of a <Router>`).

- [ ] **Step 3: Permissions (`web/src/records/permissions.ts`)**

```ts
export type UiAction = "submit" | "approve" | "return" | "reopen" | "fill_by_hand" | "release";
```

In `availableActions`, add before the final `return [];`:

```ts
  if (status === "quarantined" && role === "hospital_doctor") return ["release"];
```

- [ ] **Step 4: `RedactStep` hands the redacted pages to its caller (`web/src/capture/RedactStep.tsx`)**

Replace the file with:

```tsx
import { useEffect, useState } from "react";
import type { Rect } from "../imaging/geometry";
import { burnRedactions } from "../imaging/render";
import { suggestBoxes } from "../redaction/labels";
import { ocrLines } from "../redaction/ocr";
import { primaryButton, secondaryButton } from "../ui/styles";
import { RedactionCanvas } from "./RedactionCanvas";
import type { PageDraft } from "./types";

interface Props {
  pages: PageDraft[];
  onChange: (pages: PageDraft[]) => void;
  /** Receives the redacted JPEGs (boxes burned in). Throw an Error to show its message here. */
  onUpload: (redacted: Blob[]) => Promise<void>;
  onBack: () => void;
}

export function RedactStep({ pages, onChange, onUpload, onBack }: Props) {
  const [index, setIndex] = useState(0);
  const [seen, setSeen] = useState<Set<string>>(new Set());
  const [selected, setSelected] = useState<number | null>(null);
  const [ocrBusy, setOcrBusy] = useState(() => pages.some((p) => !p.ocrDone));
  const [ocrWarning, setOcrWarning] = useState<string | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Suggest boxes once per page, on this device only. Editing is disabled until this finishes.
  useEffect(() => {
    const pending = pages.filter((p) => !p.ocrDone);
    if (pending.length === 0) return;
    let cancelled = false;
    void (async () => {
      let next = pages;
      for (const page of pending) {
        let found: Rect[] = [];
        try {
          found = suggestBoxes(await ocrLines(page.blob));
        } catch {
          setOcrWarning("Automatic name finding failed — draw the boxes by hand.");
        }
        if (cancelled) return;
        next = next.map((p) => (p.id === page.id ? { ...p, boxes: [...p.boxes, ...found], ocrDone: true } : p));
      }
      onChange(next);
      setOcrBusy(false);
    })();
    return () => {
      cancelled = true;
    };
    // Runs once when the step opens; `pages` cannot change while OCR is running because editing is disabled.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const page = pages[Math.min(index, pages.length - 1)];
  const setBoxes = (boxes: Rect[]) => {
    setConfirmed(false); // any change to the boxes needs a fresh look
    onChange(pages.map((p) => (p.id === page.id ? { ...p, boxes } : p)));
  };

  function addBox() {
    setBoxes([...page.boxes, { x: page.width * 0.1, y: page.height * 0.1, w: page.width * 0.4, h: page.height * 0.06 }]);
    setSelected(page.boxes.length);
  }

  function deleteBox() {
    if (selected === null) return;
    setBoxes(page.boxes.filter((_, i) => i !== selected));
    setSelected(null);
  }

  async function upload() {
    setUploading(true);
    setError(null);
    try {
      // The boxes are burned in here, on the device: only redacted pixels are handed on.
      await onUpload(await Promise.all(pages.map((p) => burnRedactions(p.blob, p.boxes))));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  }

  const count = page.boxes.length;
  const locked = ocrBusy || uploading;
  const allSeen = pages.every((p) => seen.has(p.id));
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold">Hide names and numbers</h2>
      <p className="text-sm text-slate-600">
        Black boxes are burned into the photo before it leaves this device. Cover every patient name, phone number, address and ID.
      </p>
      {ocrBusy && <p className="rounded-md bg-slate-100 p-3">Finding names…</p>}
      {ocrWarning && <p className="rounded-md bg-amber-50 p-3 text-amber-900">{ocrWarning}</p>}
      {pages.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {pages.map((p, i) => (
            <button
              key={p.id}
              type="button"
              onClick={() => {
                setIndex(i);
                setSelected(null);
              }}
              className={i === index ? primaryButton : secondaryButton}
            >
              Page {i + 1} · {p.boxes.length} {p.boxes.length === 1 ? "box" : "boxes"}
              {seen.has(p.id) ? "" : " · not checked"}
            </button>
          ))}
        </div>
      )}
      <RedactionCanvas key={page.id} url={page.url} width={page.width} height={page.height} boxes={page.boxes} disabled={locked} selected={selected} onSelect={setSelected} onChange={setBoxes} onShown={() => setSeen((s) => (s.has(page.id) ? s : new Set(s).add(page.id)))} />
      <p data-testid="box-count" className="text-sm">
        {count} {count === 1 ? "box" : "boxes"}
      </p>
      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={locked} onClick={addBox} className={secondaryButton}>Add box</button>
        <button type="button" disabled={selected === null || locked} onClick={deleteBox} className={secondaryButton}>Delete box</button>
      </div>
      {!allSeen && pages.length > 1 && <p className="text-sm text-amber-800">Open every page and check it before uploading.</p>}
      <label className="flex items-start gap-2">
        <input type="checkbox" checked={confirmed} disabled={ocrBusy || !allSeen} onChange={(e) => setConfirmed(e.target.checked)} className="mt-1" />
        <span>All names and numbers are covered.</span>
      </label>
      {error && <p role="alert" className="text-red-700">{error}</p>}
      <div className="flex gap-2">
        <button type="button" disabled={uploading} onClick={onBack} className={secondaryButton}>Back</button>
        <button type="button" disabled={!confirmed || !allSeen || locked} onClick={upload} className={primaryButton}>
          {uploading ? "Uploading…" : "Upload"}
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 5: The capture wizard keeps sending through the outbox (`web/src/capture/CapturePage.tsx`)**

1. Change the imports:

```tsx
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate } from "react-router";
import type { TemplateOut } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { useOutbox } from "../outbox/OutboxContext";
import { enqueue, flushOutbox, type SendResult } from "../outbox/outbox";
import type { OutboxMeta } from "../storage/idb";
import { PatientStep } from "./PatientStep";
import { PhotosStep } from "./PhotosStep";
import { RedactStep } from "./RedactStep";
import { TemplateStep } from "./TemplateStep";
import type { PageDraft } from "./types";
```

2. Directly below `const deviceKey = useDeviceKey();`, add:

```tsx
  const navigate = useNavigate();
  const outbox = useOutbox();
```

3. Directly below `const key = deviceKey.data;`, add the outbox upload that used to live in `RedactStep`:

```tsx
  async function uploadViaOutbox(meta: OutboxMeta, redacted: Blob[]) {
    const item = await enqueue(meta, redacted, me.id);
    let result: SendResult | undefined = (await flushOutbox(me.id)).get(item.id);
    if (!result) result = (await flushOutbox(me.id)).get(item.id); // a flush that started earlier did not include it
    await outbox.refresh();
    if (result?.outcome === "done" && result.recordId) {
      navigate(`/records/${result.recordId}`);
    } else if (result?.outcome === "fail") {
      throw new Error(`Upload refused: ${result.error}. The redacted copy is listed on the home screen.`);
    } else {
      navigate("/", { state: { notice: "Saved on this device — it will upload when the connection is back." } });
    }
  }
```

4. Replace the `<RedactStep … />` element with:

```tsx
        <RedactStep
          pages={pages}
          onChange={setPages}
          onBack={() => setStep("photos")}
          onUpload={(redacted) => uploadViaOutbox({ study_code: studyCode, template_key: template.key, key_fingerprint: key.fingerprint }, redacted)}
        />
```

- [ ] **Step 6: The re-upload page (`web/src/capture/ReuploadPage.tsx`) and its route**

`web/src/capture/ReuploadPage.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { api } from "../api/client";
import { useRecord } from "../api/hooks";
import type { RecordDetail } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { useDeviceKey } from "../crypto/keyStore";
import { PhotosStep } from "./PhotosStep";
import { RedactStep } from "./RedactStep";
import type { PageDraft } from "./types";

/** New redacted photos for a record the safety net held back (spec §8.1). Sent while online; there is no outbox. */
export default function ReuploadPage() {
  const { id = "" } = useParams();
  const me = useCurrentUser();
  const record = useRecord(id);
  const deviceKey = useDeviceKey();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [step, setStep] = useState<"photos" | "redact">("photos");
  const [pages, setPages] = useState<PageDraft[]>([]);
  const pagesRef = useRef(pages);

  useEffect(() => {
    pagesRef.current = pages;
  }, [pages]);
  useEffect(() => () => pagesRef.current.forEach((p) => URL.revokeObjectURL(p.url)), []);

  if (!isHospital(me.role)) return <p>Only hospital staff can upload photos.</p>;
  if (record.isPending || deviceKey.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  const r = record.data;
  if (r.status !== "quarantined") {
    return (
      <p>
        This record is not held back. <Link to={`/records/${r.id}`} className="underline">Back to the record</Link>
      </p>
    );
  }
  if (!deviceKey.data) {
    return (
      <p>
        This device has no hospital key.{" "}
        {me.role === "hospital_doctor" ? <Link to="/setup" className="underline">Set it up</Link> : "Ask a hospital doctor to set it up."}
      </p>
    );
  }
  const fingerprint = deviceKey.data.fingerprint;

  async function send(redacted: Blob[]) {
    const form = new FormData();
    form.append("meta", JSON.stringify({ row_version: r.row_version, key_fingerprint: fingerprint }));
    redacted.forEach((blob, i) => form.append("pages", blob, `page-${i + 1}.jpg`));
    const updated = await api<RecordDetail>(`/records/${r.id}/reupload`, { method: "POST", body: form });
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
    navigate(`/records/${updated.id}`);
  }

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">New photos for {r.template_title}</h1>
      <p className="text-sm">
        Patient <span className="font-mono">{r.study_code}</span> · {r.quarantine?.summary}
      </p>
      {step === "photos" && <PhotosStep pages={pages} onChange={setPages} onBack={() => navigate(`/records/${r.id}`)} onNext={() => setStep("redact")} />}
      {step === "redact" && <RedactStep pages={pages} onChange={setPages} onBack={() => setStep("photos")} onUpload={send} />}
    </div>
  );
}
```

In `web/src/App.tsx`, add `import ReuploadPage from "./capture/ReuploadPage";`, and add a route after `records/:id`:

```tsx
      <Route path="records/:id/reupload" element={<ReuploadPage />} />
```

- [ ] **Step 7: The review screen explains a held-back record (`web/src/records/RecordPage.tsx`)**

Replace the file with the Task 11 version plus the quarantine banner, the release dialog and the red hit outlines:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { ApiError, api, json } from "../api/client";
import { useRecord } from "../api/hooks";
import type { EventOut, RecordDetail, SourceBox } from "../api/types";
import { useCurrentUser } from "../auth/RequireAuth";
import { isHospital } from "../auth/roles";
import { StatusBadge } from "../ui/StatusBadge";
import { card, inputClass, primaryButton, secondaryButton } from "../ui/styles";
import { useNow } from "../ui/useNow";
import { FormRenderer } from "./FormRenderer";
import { PageViewer, type PageMark } from "./PageViewer";
import { availableActions, canEdit, fillByHandOffered, type UiAction } from "./permissions";

/** The server's 409 for a stale row_version. Any other 409 carries its own reason, which is shown as it is. */
const CONFLICT = "Someone else changed this record — reload";

const DONE: Record<UiAction, string> = {
  submit: "Submitted for doctor review",
  approve: "Approved",
  return: "Returned to the uploader",
  reopen: "Reopened",
  fill_by_hand: "The AI was stopped — fill the form in by hand",
  release: "Released — the AI is reading it again",
};

const EVENT_LABEL: Record<string, string> = {
  upload: "uploaded",
  edit: "edited",
  submit: "submitted",
  approve: "approved",
  return: "returned",
  reopen: "reopened",
  quarantine: "held it back",
  release: "released it",
  reupload: "uploaded new photos",
  fill_by_hand: "chose to fill it in by hand",
};

export default function RecordPage() {
  const { id = "" } = useParams();
  const record = useRecord(id);
  if (record.isPending) return <p>Loading…</p>;
  if (record.isError) return <p role="alert" className="text-red-700">{record.error.message}</p>;
  return <RecordView key={record.data.id} record={record.data} />;
}

function RecordView({ record: r }: { record: RecordDetail }) {
  const me = useCurrentUser();
  const queryClient = useQueryClient();
  const now = useNow(5_000);
  const [values, setValues] = useState(r.values);
  const [syncedVersion, setSyncedVersion] = useState(r.row_version);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [conflict, setConflict] = useState(false);
  const [dialog, setDialog] = useState<"return" | "reopen" | "release" | null>(null);
  const [comment, setComment] = useState("");
  const [sources, setSources] = useState<SourceBox[]>([]);

  // When the server copy changes (save, action, the AI finishing, reload), show its values.
  if (syncedVersion !== r.row_version) {
    setSyncedVersion(r.row_version);
    setValues(r.values);
  }

  const editable = canEdit(me.role, r.status);
  const dirty = JSON.stringify(values) !== JSON.stringify(r.values);
  // A record whose photos expired cannot be released: there is nothing left for the AI to read.
  const actions = availableActions(me.role, r.status, r.created_by_id === me.id).filter(
    (a) => a !== "release" || !r.quarantine?.files_expired,
  );
  const errors = Object.fromEntries(r.errors.map((e) => [e.path, e.message]));
  const lastReturn = r.status === "draft" ? [...r.events].reverse().find((e) => e.action === "return" || e.action === "reopen") : undefined;
  const marks: PageMark[] =
    r.status === "quarantined" && r.quarantine
      ? r.quarantine.hits.map((h) => ({ page: h.page, box: h.box, tone: "hit" as const }))
      : sources.map((s) => ({ ...s, tone: "source" as const }));

  function store(updated: RecordDetail) {
    queryClient.setQueryData(["record", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["records"] });
  }

  function failed(e: unknown, fallback: string) {
    if (e instanceof ApiError && e.status === 409 && e.message === CONFLICT) setConflict(true);
    else setMessage(e instanceof Error ? e.message : fallback);
  }

  /** Saves the form; returns the updated record, or null after showing the error. */
  async function save(): Promise<RecordDetail | null> {
    try {
      const updated = await api<RecordDetail>(`/records/${r.id}/values`, { method: "PATCH", body: json({ row_version: r.row_version, values }) });
      store(updated);
      return updated;
    } catch (e) {
      failed(e, "Save failed");
      return null;
    }
  }

  async function onSave() {
    setBusy(true);
    setMessage(null);
    if (await save()) setMessage("Saved");
    setBusy(false);
  }

  async function run(action: UiAction, withComment?: string) {
    setBusy(true);
    setMessage(null);
    try {
      // Unsaved edits are saved first; the action then names the row_version it was taken on.
      let current = r;
      if (editable && dirty) {
        const saved = await save();
        if (!saved) return;
        current = saved;
      }
      store(
        await api<RecordDetail>(`/records/${r.id}/transition`, {
          method: "POST",
          body: json({ action, comment: withComment ?? null, row_version: current.row_version }),
        }),
      );
      setDialog(null);
      setComment("");
      setMessage(DONE[action]);
    } catch (e) {
      failed(e, "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <h1 className="text-2xl font-semibold">{r.template_title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-700">
          <span>
            Study code <span className="font-mono">{r.study_code}</span>
          </span>
          <StatusBadge status={r.status} />
          <span>Uploaded by {r.created_by_name}</span>
        </p>
      </header>

      {r.duplicate_of.length > 0 && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          This looks already uploaded for this patient:
          {r.duplicate_of.map((d) => (
            <Link key={d} to={`/records/${d}`} className="ml-2 underline">
              {d.slice(0, 8)}
            </Link>
          ))}
        </p>
      )}
      {lastReturn && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">
          Returned by {lastReturn.actor_name}: {lastReturn.comment}
        </p>
      )}
      {r.status === "processing" && (
        <div className="space-y-2 rounded-md bg-slate-100 p-3">
          <p>The AI is reading this document…</p>
          {fillByHandOffered(me.role, r.status, r.extraction_queued_at, now) && (
            <>
              <p className="text-sm text-slate-600">This is taking longer than usual.</p>
              <button type="button" disabled={busy} onClick={() => run("fill_by_hand")} className={secondaryButton}>
                Fill by hand now
              </button>
            </>
          )}
        </div>
      )}
      {r.status === "draft" && r.extraction_status === "failed" && (
        <p className="rounded-md bg-amber-50 p-3 text-amber-900">The AI could not read this document — fill the form in by hand.</p>
      )}
      {r.status === "draft" && r.extraction && (
        <p className="text-sm text-slate-600">The AI filled in this form. Check every amber field; tap a field to see where it was read on the page.</p>
      )}
      {r.status === "quarantined" && r.quarantine && (
        <div role="alert" className="space-y-2 rounded-md bg-red-50 p-3 text-red-900">
          <p className="font-medium">Held back. {r.quarantine.summary}.</p>
          <p className="text-sm">
            Nothing has been shared with NSU.{" "}
            {r.quarantine.files_expired
              ? "The photos were deleted after 14 days — upload them again."
              : "The red outlines show where the details were found."}
          </p>
          {isHospital(me.role) && (
            <Link to={`/records/${r.id}/reupload`} className={`${primaryButton} inline-block`}>
              Upload new photos
            </Link>
          )}
        </div>
      )}
      {conflict && (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-red-800">
          {CONFLICT}
          <button
            type="button"
            className={`${secondaryButton} ml-2`}
            onClick={() => {
              setConflict(false);
              void queryClient.invalidateQueries({ queryKey: ["record", r.id] });
            }}
          >
            Reload
          </button>
        </p>
      )}

      <div className="grid gap-4 md:grid-cols-2">
        <PageViewer files={r.files} marks={marks} />
        <div className="space-y-4">
          <FormRenderer
            fields={r.template.definition.fields}
            values={values}
            onChange={setValues}
            errors={errors}
            readOnly={!editable}
            flags={lastReturn?.field_flags ?? {}}
            extraction={r.extraction}
            onFieldFocus={(_, ai) => setSources(ai?.sources ?? [])}
          />
          <div className="flex flex-wrap gap-2">
            {editable && (
              <button type="button" disabled={busy || !dirty} onClick={onSave} className={secondaryButton}>
                Save
              </button>
            )}
            {actions.includes("submit") && (
              <button type="button" disabled={busy} onClick={() => run("submit")} className={primaryButton}>
                Submit for doctor review
              </button>
            )}
            {actions.includes("approve") && (
              <button type="button" disabled={busy} onClick={() => run("approve")} className={primaryButton}>
                Approve
              </button>
            )}
            {actions.includes("return") && (
              <button type="button" disabled={busy} onClick={() => setDialog("return")} className={secondaryButton}>
                Return…
              </button>
            )}
            {actions.includes("reopen") && (
              <button type="button" disabled={busy} onClick={() => setDialog("reopen")} className={secondaryButton}>
                Reopen…
              </button>
            )}
            {actions.includes("release") && (
              <button type="button" disabled={busy} onClick={() => setDialog("release")} className={secondaryButton}>
                Release — false alarm…
              </button>
            )}
          </div>
          {me.role === "hospital_doctor" && r.status === "pending_doctor" && r.created_by_id === me.id && (
            <p className="text-sm text-slate-600">You uploaded this record, so another doctor must approve it.</p>
          )}
          {dialog && (
            <div className={`${card} space-y-2`}>
              <label className="block text-sm font-medium">
                {dialog === "return" ? "What needs fixing?" : dialog === "reopen" ? "Reason for reopening" : "Why is this a false alarm?"}
                <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={3} className={inputClass} />
              </label>
              <div className="flex gap-2">
                <button type="button" disabled={busy || !comment.trim()} onClick={() => run(dialog, comment)} className={primaryButton}>
                  Confirm
                </button>
                <button type="button" onClick={() => setDialog(null)} className={secondaryButton}>
                  Cancel
                </button>
              </div>
            </div>
          )}
          {message && (
            <p role="status" className="text-sm">
              {message}
            </p>
          )}
        </div>
      </div>
      <History events={r.events} />
    </div>
  );
}

function History({ events }: { events: EventOut[] }) {
  return (
    <section className={card}>
      <h2 className="mb-2 font-semibold">History</h2>
      <ol className="space-y-1 text-sm">
        {events.map((e) => (
          <li key={e.id}>
            {new Date(e.created_at).toLocaleString()} — {e.actor_name} {EVENT_LABEL[e.action] ?? e.action}
            {e.action === "edit" && e.field_changes ? ` ${e.field_changes.length} field(s)` : ""}
            {e.comment ? `: ${e.comment}` : ""}
          </li>
        ))}
      </ol>
    </section>
  );
}
```

- [ ] **Step 8: Home lists held-back records (`web/src/home/HomePage.tsx`)**

In `HospitalHome`, below `const reading = ...`, add:

```tsx
  const heldBack = useRecords({ status: "quarantined", mine: me.role === "uploader" });
```

Insert directly before the `{me.role === "hospital_doctor" && (` doctor-queue link:

```tsx
      {(heldBack.data?.length ?? 0) > 0 && (
        <section className="space-y-2">
          <h2 className="text-lg font-semibold text-red-800">Held back — possible patient details</h2>
          <RecordList records={heldBack.data ?? []} empty="" />
        </section>
      )}
```

An uploader sees their own held-back uploads. A hospital doctor sees all of them, because a doctor can release any.

- [ ] **Step 9: Run the unit tests and the type check**

Run: `cd web && npm test && npm run typecheck`
Expected: all pass (150: 148 plus 1 permissions and 1 RedactStep), and no type errors.

- [ ] **Step 10: Add the quarantine story to the e2e test**

Append to `web/e2e/flow.spec.ts`:

```ts
test("a page with an uncovered mobile number is held back until new photos are uploaded", async () => {
  await login("uploader@amcgh.test");
  await page.getByRole("link", { name: "New capture" }).click();
  await page.getByLabel("Hospital registration number").fill("AMH-55555");
  await page.getByRole("button", { name: "Get study code" }).click();
  const code = (await page.getByTestId("study-code").textContent()) ?? "";
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByRole("button", { name: /Radiology report/ }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Use this page" }).click();
  await page.getByRole("button", { name: "Next: hide names" }).click();
  await expect(page.getByText("Finding names…")).toBeHidden({ timeout: 90_000 });

  // Delete the box over "Mobile: 01712345678" (line 3 of the 1800 × 1100 fixture), as if by mistake.
  const before = Number(((await page.getByTestId("box-count").textContent()) ?? "0").split(" ")[0]);
  const canvas = page.locator("canvas").first();
  const area = (await canvas.boundingBox())!;
  await page.mouse.click(area.x + area.width * (280 / 1800), area.y + area.height * (286 / 1100));
  await page.getByRole("button", { name: "Delete box" }).click();
  const after = before - 1;
  await expect(page.getByTestId("box-count")).toHaveText(`${after} ${after === 1 ? "box" : "boxes"}`);
  await page.getByLabel("All names and numbers are covered.").check();
  await page.getByRole("button", { name: "Upload" }).click();

  // The server's safety net reads the number and holds the record back, out of NSU's sight.
  await expect(page.getByTestId("record-status")).toHaveText("Quarantined", { timeout: 90_000 });
  await expect(page.getByRole("alert")).toContainText("mobile number (page 1)");
  await expect(page.getByTestId("phi-box").first()).toBeVisible();
  await page.goto("/");
  await expect(page.getByRole("heading", { name: /Held back/ })).toBeVisible();
  await page.getByRole("link", { name: new RegExp(code) }).first().click();

  // New photos, properly covered this time, go back to the AI and come out as a draft.
  await page.getByRole("link", { name: "Upload new photos" }).click();
  await page.getByTestId("gallery-input").setInputFiles(REPORT);
  await page.getByRole("button", { name: "Use this page" }).click();
  await page.getByRole("button", { name: "Next: hide names" }).click();
  await expect(page.getByText("Finding names…")).toBeHidden({ timeout: 90_000 });
  await page.getByLabel("All names and numbers are covered.").check();
  await page.getByRole("button", { name: "Upload" }).click();
  await expect(page).toHaveURL(/\/records\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("record-status")).toHaveText("Draft", { timeout: 90_000 });
  await expect(page.getByLabel("Modality")).toHaveValue("CT");
  await logout();
});
```

Run: `cd web && npm run e2e`
Expected: 10 passed.

- [ ] **Step 11: Commit**

```bash
git add web/src web/e2e/flow.spec.ts
git commit -m "feat(web): held-back records show why, can be released by a doctor, and take new redacted photos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the last task

The controller runs the SDD close-out, as in M1 and M2:
1. a final whole-branch review on opus;
2. one fix wave;
3. one scoped re-review;
4. list every new `Ruling:` line to the user;
5. use superpowers:finishing-a-development-branch. Ask before merging or pushing.

Also carry these to the user:
- **Running a real model:** the golden set can only be scored against a real model once the Big-Matrix GPU server runs vLLM (`capture eval`). This machine has an 8 GB RTX 5060 Ti but no vLLM, which needs Linux or WSL. A local smoke test would need an OpenAI-compatible server (e.g. vLLM under WSL) with a 4-bit Qwen-VL model.
- **Handwritten cases:** the golden set still needs handwritten cases (see `eval/README.md`).
- **Prose false alarms:** clinical prose that starts an OCR line with "Patient", "Pt", "Contact" or "Cell" quarantines by design. Watch the pilot's release rate.
