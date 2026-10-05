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
