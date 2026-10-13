"""The OpenAI-compatible gateway adapter against a simulated server. No live vendor was available, so this is the
whole of its verification: request shape, credentials, error mapping, size and redirect handling."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai.errors import (
    AiError,
    ProviderAuthError,
    ProviderBadRequest,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.ai.providers.base import ProviderRequest
from app.ai.providers.gateway import MAX_RESPONSE_BYTES, GatewayProvider

REQUEST = ProviderRequest(
    task="classify_reply",
    tier="fast",
    system="SYSTEM RULES",
    user="USER TEXT",
    timeout_seconds=5,
    max_output_tokens=123,
)
KEY = "test-key-not-a-real-secret-123456"


def provider(handler: httpx.MockTransport | None = None, fn=None, **kw: str) -> GatewayProvider:  # type: ignore[no-untyped-def]
    transport = handler or httpx.MockTransport(fn)
    return GatewayProvider(
        base_url=kw.get("base_url", "https://gateway.example/v1/"),
        api_key=KEY,
        model=kw.get("model", "big-model"),
        fast_model=kw.get("fast_model", "small-model"),
        transport=transport,
    )


def ok(content: str = '{"a":1}', **extra: object) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "served-model",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            **extra,
        },
    )


def test_request_shape_credentials_and_usage_parsing() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return ok()

    result = provider(fn=handler).complete(REQUEST)
    req = seen[0]
    assert str(req.url) == "https://gateway.example/v1/chat/completions" and req.method == "POST"
    assert req.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(req.content)
    assert body["model"] == "small-model"  # fast tier -> fast model
    assert body["messages"] == [
        {"role": "system", "content": "SYSTEM RULES"},
        {"role": "user", "content": "USER TEXT"},
    ]
    assert body["temperature"] == 0 and body["max_tokens"] == 123
    assert body["response_format"] == {"type": "json_object"}
    assert KEY not in req.content.decode()  # the key is never in the body
    assert (result.text, result.model, result.input_tokens, result.output_tokens) == (
        '{"a":1}',
        "served-model",
        12,
        7,
    )


def test_quality_tier_uses_the_main_model_and_a_single_model_covers_both() -> None:
    models: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        models.append(json.loads(req.content)["model"])
        return ok()

    p = provider(fn=handler)
    p.complete(ProviderRequest(task="t", tier="quality", system="s", user="u"))
    solo = GatewayProvider(
        base_url="https://g.example",
        api_key=KEY,
        model="only",
        transport=httpx.MockTransport(handler),
    )
    solo.complete(REQUEST)
    assert models == ["big-model", "only"]


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (401, ProviderAuthError),
        (403, ProviderAuthError),
        (429, ProviderRateLimited),
        (408, ProviderTimeout),
        (504, ProviderTimeout),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
        (400, ProviderBadRequest),
        (404, ProviderBadRequest),
        (302, ProviderBadRequest),  # redirects are not followed
    ],
)
def test_http_statuses_map_to_stable_errors(status: int, error: type[AiError]) -> None:
    echo = "ECHO of the user's private email text"
    p = provider(
        fn=lambda req: httpx.Response(
            status, text=echo, headers={"location": "https://evil.example/"}
        )
    )
    with pytest.raises(error) as exc:
        p.complete(REQUEST)
    assert (
        echo not in str(exc.value)
        and KEY not in str(exc.value)
        and echo not in repr(exc.value.__cause__)
    )


def test_rate_limit_retry_after_is_passed_on_and_bounded() -> None:
    p = provider(fn=lambda r: httpx.Response(429, headers={"retry-after": "9999"}))
    with pytest.raises(ProviderRateLimited) as exc:
        p.complete(REQUEST)
    assert exc.value.retry_after == 120
    p = provider(fn=lambda r: httpx.Response(429, headers={"retry-after": "Wed, 21 Oct"}))
    with pytest.raises(ProviderRateLimited) as exc:
        p.complete(REQUEST)
    assert exc.value.retry_after is None


def test_network_failures_map_to_timeout_or_unavailable() -> None:
    def slow(req: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=req)

    def down(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(ProviderTimeout):
        provider(fn=slow).complete(REQUEST)
    with pytest.raises(ProviderUnavailable):
        provider(fn=down).complete(REQUEST)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>oops</html>"),
        httpx.Response(200, json={"choices": []}),
        httpx.Response(200, json={"choices": [{"message": {}}]}),
        httpx.Response(200, json={"choices": [{"message": {"content": ["not", "text"]}}]}),
        httpx.Response(200, json=["list"]),
        httpx.Response(200, content=b"x" * (MAX_RESPONSE_BYTES + 1)),
    ],
)
def test_unreadable_or_oversized_envelopes_are_bad_responses(response: httpx.Response) -> None:
    with pytest.raises(ProviderBadResponse):
        provider(fn=lambda r: response).complete(REQUEST)


def test_missing_or_odd_usage_is_none_not_an_error() -> None:
    p = provider(
        fn=lambda r: httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{}"}}],
                "usage": {"prompt_tokens": -3, "completion_tokens": True},
            },
        )
    )
    result = p.complete(REQUEST)
    assert (
        result.input_tokens is None
        and result.output_tokens is None
        and result.model == "small-model"
    )


def test_the_key_never_appears_in_repr_or_string_forms() -> None:
    p = provider(fn=lambda r: ok())
    assert KEY not in repr(p) and KEY not in str(p)
