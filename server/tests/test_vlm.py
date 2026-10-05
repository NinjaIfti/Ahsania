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
