"""Client for the self-hosted vision-language model (vLLM's OpenAI-compatible API, spec §3)."""

import base64
import io
from dataclasses import dataclass

import httpx
from PIL import Image

from capture.config import Settings
from capture.extraction.schema import SYSTEM_PROMPT, json_schema_for, prompt_for
from capture.extraction.spans import Token
from capture.formschema.model import TemplateDef


class VlmUnavailable(Exception):
    """The model server cannot be reached or is overloaded. The job waits; it does not use up an attempt."""


class VlmError(Exception):
    """The model server answered, but not with a usable result. The job uses up an attempt."""


@dataclass(frozen=True)
class VlmAnswer:
    text: str
    tokens: list[Token] | None
    model: str


def image_for_model(data: bytes, max_side: int) -> bytes:
    """The page as JPEG with its long side at most max_side pixels (fewer image tokens, same text)."""
    with Image.open(io.BytesIO(data)) as image:
        if max(image.size) <= max_side:
            return data
        picture = image.convert("RGB")
    picture.thumbnail((max_side, max_side))
    out = io.BytesIO()
    picture.save(out, format="JPEG", quality=90)
    return out.getvalue()


def _tokens(logprobs: dict | None) -> list[Token] | None:
    content = (logprobs or {}).get("content")
    if not content:
        return None
    return [
        Token(bytes(entry["bytes"]) if entry.get("bytes") is not None else entry["token"].encode("utf-8"), float(entry["logprob"]))
        for entry in content
    ]


class VlmClient:
    def __init__(
        self,
        url: str,
        model: str,
        *,
        timeout: float,
        max_image_side: int,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self.max_image_side = max_image_side
        self._http = httpx.Client(base_url=url.rstrip("/"), timeout=timeout, transport=transport)

    def request_body(self, tpl: TemplateDef, pages: list[bytes]) -> dict:
        images = [
            {
                "type": "image_url",
                "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(image_for_model(page, self.max_image_side)).decode("ascii")},
            }
            for page in pages
        ]
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [{"type": "text", "text": prompt_for(tpl)}, *images]},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": tpl.key, "schema": json_schema_for(tpl), "strict": True},
            },
            "temperature": 0,
            "logprobs": True,
            "max_tokens": 4096,
        }

    def extract(self, tpl: TemplateDef, pages: list[bytes]) -> VlmAnswer:
        try:
            response = self._http.post("/chat/completions", json=self.request_body(tpl, pages))
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            raise VlmUnavailable(f"model server unreachable ({type(e).__name__})") from None
        except httpx.TimeoutException:
            raise VlmError("the model server took too long to answer") from None
        if response.status_code in (502, 503, 504):
            raise VlmUnavailable(f"model server busy or down ({response.status_code})")
        if response.status_code != 200:
            raise VlmError(f"model server answered {response.status_code}")
        try:
            choice = response.json()["choices"][0]
            text = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise VlmError("the model server's answer was not understood") from None
        if choice.get("finish_reason") == "length" or not isinstance(text, str):
            raise VlmError("the model's answer was cut off")
        return VlmAnswer(text=text, tokens=_tokens(choice.get("logprobs")), model=self.model)

    def close(self) -> None:
        self._http.close()


def client_from_settings(settings: Settings, transport: httpx.BaseTransport | None = None) -> VlmClient:
    return VlmClient(
        settings.vlm_url,
        settings.vlm_model,
        timeout=settings.vlm_timeout_s,
        max_image_side=settings.vlm_max_image_side,
        transport=transport,
    )
