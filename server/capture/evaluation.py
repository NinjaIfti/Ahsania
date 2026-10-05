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
