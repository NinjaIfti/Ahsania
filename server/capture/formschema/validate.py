from datetime import date
from typing import Any

from capture.formschema.model import (
    BooleanField,
    DateField,
    EnumField,
    GroupField,
    NumberField,
    TemplateDef,
    TextField,
)


def validate_values(tpl: TemplateDef, values: Any, today: date) -> list[dict[str, str]]:
    """Every problem in `values`, as {"path": "lesions[0].long_axis_cm", "message": "..."}."""
    errors: list[dict[str, str]] = []
    _check_object(tpl.fields, values, "", errors, today)
    return errors


def parse_date(value: Any) -> date | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def document_date_of(tpl: TemplateDef, values: Any) -> date | None:
    if not isinstance(values, dict):
        return None
    return parse_date(values.get(tpl.document_date_key))


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _check_object(fields: list, values: Any, prefix: str, errors: list, today: date) -> None:
    if not isinstance(values, dict):
        errors.append({"path": prefix or "$", "message": "must be an object"})
        return
    known = {f.key for f in fields}
    for key in values:
        if key not in known:
            errors.append({"path": _join(prefix, key), "message": "unknown field"})
    for f in fields:
        path = _join(prefix, f.key)
        value = values.get(f.key)
        if _is_empty(value):
            if f.required:
                errors.append({"path": path, "message": "required"})
            continue
        _check_value(f, value, path, errors, today)


def _check_value(f: Any, value: Any, path: str, errors: list, today: date) -> None:
    def error(message: str) -> None:
        errors.append({"path": path, "message": message})

    if isinstance(f, TextField):
        if not isinstance(value, str):
            error("must be text")
    elif isinstance(f, NumberField):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            error("must be a number")
            return
        if f.min is not None and value < f.min:
            error(f"must be at least {f.min:g}")
        if f.max is not None and value > f.max:
            error(f"must be at most {f.max:g}")
    elif isinstance(f, DateField):
        parsed = parse_date(value)
        if parsed is None:
            error("must be a date (YYYY-MM-DD)")
        elif parsed > today:
            error("cannot be in the future")
    elif isinstance(f, EnumField):
        allowed = [o.value for o in f.options]
        if value not in allowed:
            error("must be one of: " + ", ".join(allowed))
    elif isinstance(f, BooleanField):
        if not isinstance(value, bool):
            error("must be yes or no")
    elif isinstance(f, GroupField):
        if f.repeat:
            if not isinstance(value, list):
                error("must be a list")
                return
            for i, item in enumerate(value):
                _check_object(f.fields, item, f"{path}[{i}]", errors, today)
        else:
            _check_object(f.fields, value, path, errors, today)
