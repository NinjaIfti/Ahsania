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
