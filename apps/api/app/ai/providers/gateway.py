"""An OpenAI-compatible chat-completions gateway (``POST {base}/chat/completions``).

STATUS: written against the widely used chat-completions request/response shape and exercised in tests with a
simulated server. It has NOT been run against a live vendor or against "Jev": no credentials or verified API
documentation were available. Point ``AI_BASE_URL`` at a compatible gateway and check ``docs/AI.md`` before relying on it.

Security properties: the key travels only in the Authorization header; redirects are not followed (a redirect could
carry the key elsewhere); response bodies are never copied into errors or logs; replies over 256 KB are refused.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx

from app.ai.errors import (
    ProviderAuthError,
    ProviderBadRequest,
    ProviderBadResponse,
    ProviderRateLimited,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.ai.providers.base import ProviderRequest, ProviderResponse

MAX_RESPONSE_BYTES = 256 * 1024


def _retry_after(response: httpx.Response) -> int | None:
    raw = response.headers.get("retry-after", "")
    return min(int(raw), 120) if raw.isdigit() else None


class GatewayProvider:
    name = "gateway"
    is_mock = False

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        fast_model: str = "",
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._key = api_key
        self._models = {"quality": model, "fast": fast_model or model}
        self._client = httpx.Client(transport=transport, follow_redirects=False)

    def model_for(self, tier: Literal["fast", "quality"]) -> str:
        return self._models[tier]

    def __repr__(self) -> str:  # never show the key
        return f"GatewayProvider(url={self._url!r}, models={self._models!r})"

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        model = self.model_for(request.tier)
        body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            "temperature": 0,
            "max_tokens": request.max_output_tokens,
            "response_format": {"type": "json_object"},
        }
        try:
            response = self._client.post(
                self._url,
                json=body,
                headers={"Authorization": f"Bearer {self._key}"},
                timeout=httpx.Timeout(request.timeout_seconds),
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout() from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable() from exc

        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError()
        if status == 429:
            raise ProviderRateLimited(retry_after=_retry_after(response))
        if status in (408, 504):
            raise ProviderTimeout()
        if status >= 500:
            raise ProviderUnavailable(retry_after=_retry_after(response))
        if (
            status >= 300
        ):  # 4xx, and 3xx: redirects are never followed because they could carry the key elsewhere
            raise ProviderBadRequest()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise ProviderBadResponse()
        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise ProviderBadResponse() from exc
        if not isinstance(text, str):
            raise ProviderBadResponse()
        usage = data.get("usage") if isinstance(data, dict) else None
        return ProviderResponse(
            text=text,
            model=str(data.get("model") or model)[:80],
            input_tokens=_count(usage, "prompt_tokens"),
            output_tokens=_count(usage, "completion_tokens"),
        )


def _count(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None
