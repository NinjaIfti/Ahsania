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
