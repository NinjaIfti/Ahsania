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
