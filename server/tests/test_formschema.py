import copy
from datetime import date

import pytest
from pydantic import ValidationError

from capture.formschema.diff import diff_values
from capture.formschema.model import EnumField, TemplateDef
from capture.formschema.validate import document_date_of, validate_values

TODAY = date(2026, 10, 4)
RAW = {
    "key": "radiology_report",
    "version": 1,
    "phase": 1,
    "kind": "document",
    "title": "Radiology report",
    "fields": [
        {"key": "modality", "type": "enum", "required": True, "options": ["CT", "MRI"]},
        {"key": "study_date", "type": "date", "required": True, "document_date": True},
        {"key": "contrast", "type": "boolean"},
        {
            "key": "lesions",
            "type": "group",
            "repeat": True,
            "fields": [
                {"key": "lobe", "type": "enum", "options": [{"value": "RUL", "synonyms": ["right upper lobe"]}, {"value": "LUL"}]},
                {"key": "long_axis_cm", "type": "number", "unit": "cm", "min": 0.1, "max": 20},
            ],
        },
        {"key": "impression", "type": "text"},
    ],
}
TPL = TemplateDef.model_validate(RAW)
GOOD = {
    "modality": "CT",
    "study_date": "2026-09-01",
    "contrast": False,
    "lesions": [{"lobe": "RUL", "long_axis_cm": 2.3}],
    "impression": "mass",
}


def test_plain_string_options_become_option_objects():
    modality = TPL.fields[0]
    assert isinstance(modality, EnumField)
    assert [o.value for o in modality.options] == ["CT", "MRI"]
    assert modality.options[0].synonyms == []


def test_document_date_key():
    assert TPL.document_date_key == "study_date"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda r: r["fields"][1].pop("document_date"), "exactly one top-level date field"),
        (lambda r: r["fields"].append({"key": "followup", "type": "date", "document_date": True}), "exactly one top-level date field"),
        (lambda r: r["fields"].append({"key": "modality", "type": "text"}), "duplicate field key 'modality'"),
        (lambda r: r.update(colour="blue"), "Extra inputs are not permitted"),
        (lambda r: r["fields"].append({"key": "Bad Key", "type": "text"}), "String should match pattern"),
    ],
)
def test_invalid_templates_are_rejected(change, message):
    raw = copy.deepcopy(RAW)
    change(raw)
    with pytest.raises(ValidationError, match=message):
        TemplateDef.model_validate(raw)


def test_valid_values_have_no_errors():
    assert validate_values(TPL, GOOD, TODAY) == []


def test_empty_optional_values_are_fine():
    values = {"modality": "CT", "study_date": "2026-09-01", "lesions": [], "impression": ""}
    assert validate_values(TPL, values, TODAY) == []


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ({"study_date": "2026-09-01"}, {"path": "modality", "message": "required"}),
        (dict(GOOD, modality="PET"), {"path": "modality", "message": "must be one of: CT, MRI"}),
        (dict(GOOD, study_date="01/09/2026"), {"path": "study_date", "message": "must be a date (YYYY-MM-DD)"}),
        (dict(GOOD, study_date="2026-10-05"), {"path": "study_date", "message": "cannot be in the future"}),
        (dict(GOOD, contrast="yes"), {"path": "contrast", "message": "must be yes or no"}),
        (dict(GOOD, impression=5), {"path": "impression", "message": "must be text"}),
        (dict(GOOD, lesions=[{"long_axis_cm": "2.3"}]), {"path": "lesions[0].long_axis_cm", "message": "must be a number"}),
        (dict(GOOD, lesions=[{"long_axis_cm": True}]), {"path": "lesions[0].long_axis_cm", "message": "must be a number"}),
        (dict(GOOD, lesions=[{}, {"long_axis_cm": 25}]), {"path": "lesions[1].long_axis_cm", "message": "must be at most 20"}),
        (dict(GOOD, lesions=[{"long_axis_cm": 0.05}]), {"path": "lesions[0].long_axis_cm", "message": "must be at least 0.1"}),
        (dict(GOOD, lesions={"lobe": "RUL"}), {"path": "lesions", "message": "must be a list"}),
        (dict(GOOD, lesions=[{"lobe": "RUL", "size": 1}]), {"path": "lesions[0].size", "message": "unknown field"}),
        (dict(GOOD, weight=70), {"path": "weight", "message": "unknown field"}),
    ],
)
def test_value_errors(values, expected):
    assert expected in validate_values(TPL, values, TODAY)


def test_document_date_of():
    assert document_date_of(TPL, GOOD) == date(2026, 9, 1)
    assert document_date_of(TPL, {"study_date": "garbage"}) is None
    assert document_date_of(TPL, None) is None


def test_diff_reports_changed_added_and_removed_leaves():
    old = {"modality": "CT", "lesions": [{"lobe": "RUL"}, {"lobe": "LUL"}]}
    new = {"modality": "MRI", "lesions": [{"lobe": "RUL"}], "impression": "mass"}
    assert diff_values(old, new) == [
        {"path": "impression", "old": None, "new": "mass"},
        {"path": "lesions[1].lobe", "old": "LUL", "new": None},
        {"path": "modality", "old": "CT", "new": "MRI"},
    ]


def test_diff_of_identical_values_is_empty():
    assert diff_values(GOOD, copy.deepcopy(GOOD)) == []
