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
