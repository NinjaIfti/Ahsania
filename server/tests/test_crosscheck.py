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
