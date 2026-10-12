"""Failures a provider or the service can report. Messages are written for people and never carry content."""

from __future__ import annotations


class AiError(Exception):
    """A failed model call. ``code`` is stable and machine-readable; ``str(error)`` is safe to show and log."""

    code = "ai_error"
    retryable = False
    user_message = "The AI request failed."

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__(self.user_message)
        self.retry_after = retry_after


class ProviderTimeout(AiError):
    code = "timeout"
    retryable = True
    user_message = "The AI provider took too long to answer."


class ProviderUnavailable(AiError):
    code = "unavailable"
    retryable = True
    user_message = "The AI provider is unavailable right now."


class ProviderRateLimited(AiError):
    code = "provider_rate_limited"
    retryable = True
    user_message = "The AI provider asked us to slow down."


class ProviderAuthError(AiError):
    code = "auth_failed"
    user_message = "The AI provider rejected the configured credentials."


class ProviderBadRequest(AiError):
    code = "bad_request"
    user_message = "The AI provider rejected the request."


class ProviderBadResponse(AiError):
    code = "bad_response"
    retryable = True
    user_message = "The AI provider sent a reply we could not read."


class InvalidOutput(AiError):
    """The reply was readable but failed schema or safety validation."""

    code = "invalid_output"
    retryable = True
    user_message = "The AI reply did not pass our checks, so it was not used."

    def __init__(self, reason: str = "schema") -> None:
        super().__init__()
        self.reason = (
            reason  # short machine tag ("schema", "unsupported_claim", ...), never content
        )


class PolicyViolation(AiError):
    """The reply broke a safety rule (leaked instructions, unsupported claims, private notes)."""

    code = "policy_violation"
    retryable = True
    user_message = "The AI reply broke a safety rule, so it was not used."

    def __init__(self, reason: str) -> None:
        super().__init__()
        self.reason = reason


class RateLimited(AiError):
    code = "rate_limited"
    user_message = "Too many AI requests in a short time. Try again shortly."


class Unavailable(AiError):
    """AI is switched off (``AI_PROVIDER=disabled``) or not configured."""

    code = "ai_disabled"
    user_message = "AI features are not set up for this installation."


class InsufficientContext(AiError):
    code = "insufficient_context"
    user_message = "There is not enough approved information to do this without guessing."

    def __init__(self, missing: list[str]) -> None:
        super().__init__()
        self.missing = missing
