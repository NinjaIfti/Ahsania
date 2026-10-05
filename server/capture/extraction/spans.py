"""Per-field confidence (spec §5.2 step 3): map each value in the model's JSON output to its tokens.

confidence = geometric mean of the probabilities of the tokens that overlap the value's text.
Tokens are matched by bytes, because a tokenizer can split one character over several tokens.
"""

import json
import math
from dataclasses import dataclass

_WHITESPACE = " \t\r\n"
_DECODER = json.JSONDecoder()


@dataclass(frozen=True)
class Token:
    text_bytes: bytes
    logprob: float


def leaf_spans(text: str) -> dict[str, tuple[int, int]]:
    """Character span of every scalar value in a JSON document, keyed by value path ("lesions[0].lobe").

    Raises ValueError when the text is not one well-formed JSON value.
    """
    spans: dict[str, tuple[int, int]] = {}

    def skip(i: int) -> int:
        while i < len(text) and text[i] in _WHITESPACE:
            i += 1
        return i

    def expect(i: int, char: str) -> int:
        if i >= len(text) or text[i] != char:
            raise ValueError(f"expected {char!r} at {i}")
        return i + 1

    def value(i: int, path: str) -> int:
        i = skip(i)
        if i >= len(text):
            raise ValueError("unexpected end")
        if text[i] == "{":
            i = skip(i + 1)
            if i < len(text) and text[i] == "}":
                return i + 1
            while True:
                key, i = _DECODER.raw_decode(text, skip(i))
                if not isinstance(key, str):
                    raise ValueError("object keys must be strings")
                i = skip(value(expect(skip(i), ":"), f"{path}.{key}" if path else key))
                if i < len(text) and text[i] == ",":
                    i += 1
                    continue
                return expect(i, "}")
        if text[i] == "[":
            i = skip(i + 1)
            if i < len(text) and text[i] == "]":
                return i + 1
            index = 0
            while True:
                i = skip(value(i, f"{path}[{index}]"))
                index += 1
                if i < len(text) and text[i] == ",":
                    i += 1
                    continue
                return expect(i, "]")
        _, end = _DECODER.raw_decode(text, i)
        spans[path] = (i, end)
        return end

    if skip(value(0, "")) != len(text):
        raise ValueError("trailing text after the JSON value")
    return spans


def field_confidences(text: str, tokens: list[Token] | None) -> dict[str, float]:
    """Confidence per value path. Empty when there are no token logprobs or they do not line up with the text."""
    if not tokens or b"".join(t.text_bytes for t in tokens) != text.encode("utf-8"):
        return {}
    try:
        spans = leaf_spans(text)
    except ValueError:
        return {}
    starts: list[int] = []
    offset = 0
    for token in tokens:
        starts.append(offset)
        offset += len(token.text_bytes)
    result: dict[str, float] = {}
    for path, (start, end) in spans.items():
        lo, hi = len(text[:start].encode("utf-8")), len(text[:end].encode("utf-8"))
        logprobs = [t.logprob for t, s in zip(tokens, starts) if s < hi and s + len(t.text_bytes) > lo]
        if logprobs:
            result[path] = math.exp(sum(logprobs) / len(logprobs))
    return result
