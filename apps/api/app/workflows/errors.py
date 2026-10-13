"""Why a step failed, in a fixed vocabulary.

A failure is recorded as a *category* plus a fixed, plain-language summary. Exception text, provider responses and message
content are never stored, so a failed run cannot leak anything. Only some categories are worth retrying automatically:
the same request can succeed later (a busy AI service, a rate limit), or it can never succeed without a person changing
something (a contact who opted out, an unapproved draft).
"""

from __future__ import annotations

from app.errors import AppError

# category -> (summary shown to the person, retry automatically?)
CATEGORIES: dict[str, tuple[str, bool]] = {
    "validation": ("This step's settings or this workflow's structure are not valid.", False),
    "missing_data": (
        "Something this step needs is missing (for example the lead has no contact email).",
        False,
    ),
    "subject_missing": ("The lead or conversation this run was about no longer exists.", False),
    "ai_unavailable": ("The AI service is not responding right now.", True),
    "ai_rate_limited": ("Too many AI requests right now.", True),
    "ai_invalid_output": ("The AI's answer was rejected by the safety checks.", True),
    "ai_disabled": ("AI is not set up for this installation.", False),
    "insufficient_context": (
        "There is not enough approved information in your profile to write this without guessing.",
        False,
    ),
    "suppressed": ("This person asked not to be contacted (or the address bounced).", False),
    "not_approved": ("The draft is not approved, or it changed after it was approved.", False),
    "approval_invalidated": (
        "The draft was edited after approval was requested, so that approval no longer applies.",
        False,
    ),
    "rate_limited": ("A sending or request limit was reached.", True),
    "provider_error": ("The mail provider could not be reached or refused the request.", True),
    "reconnect_required": ("The mailbox needs to be reconnected.", False),
    "send_failed": ("The message was not sent.", False),
    "outcome_unknown": (
        "The mail provider did not confirm whether the message was sent. Check your mailbox, "
        "then resolve it on the draft before retrying.",
        False,
    ),
    "limit_exceeded": ("A limit for this workspace was reached.", False),
    "timeout": ("The step took too long.", True),
    "interrupted": ("The worker stopped while this step was running.", True),
    "no_owner": ("This workspace has no owner to run the workflow as.", False),
    "ended_as_failure": ("The workflow ended as a failure.", False),
    "internal": ("An unexpected error occurred.", True),
}


class StepFailure(Exception):
    """Raised by an executor. ``summary`` may override the category's text; it must be fixed text written by us."""

    def __init__(
        self,
        category: str,
        *,
        retryable: bool | None = None,
        retry_after: int | None = None,
        summary: str | None = None,
    ) -> None:
        if category not in CATEGORIES:
            category = "internal"
        super().__init__(category)
        self.category = category
        self.retryable = CATEGORIES[category][1] if retryable is None else retryable
        self.retry_after = retry_after
        self.summary = (summary or CATEGORIES[category][0])[:500]


# AppError codes raised by the services the executors call, and what they mean for a run.
_APP_ERROR_CATEGORY: dict[str, str] = {
    "contact_stopped": "suppressed",
    "recipient_suppressed": "suppressed",
    "insufficient_context": "insufficient_context",
    "ai_unavailable": "ai_disabled",
    "ai_disabled": "ai_disabled",
    "rate_limited": "rate_limited",
    "send_rate_limited": "rate_limited",
    "timeout": "ai_unavailable",
    "unavailable": "ai_unavailable",
    "invalid_output": "ai_invalid_output",
    "draft_not_approved": "not_approved",
    "draft_changed": "not_approved",
    "send_outcome_unknown": "outcome_unknown",
    "send_in_progress": "outcome_unknown",
    "idempotency_key_conflict": "outcome_unknown",
    "already_sent": "send_failed",
    "invalid_recipient": "missing_data",
    "nothing_to_reply_to": "missing_data",
    "lead_not_found": "subject_missing",
    "conversation_not_found": "subject_missing",
    "email_account_not_found": "missing_data",
    "reconnect_required": "reconnect_required",
    "provider_unavailable": "provider_error",
    "provider_rejected": "provider_error",
    "provider_not_configured": "reconnect_required",
    "provider_mismatch": "reconnect_required",
}


def from_app_error(exc: AppError) -> StepFailure:
    category = _APP_ERROR_CATEGORY.get(exc.code)
    if category is None:
        category = "validation" if 400 <= exc.status_code < 500 else "internal"
    retry_after = None
    headers = getattr(exc, "headers", None) or {}
    raw = headers.get("Retry-After") if isinstance(headers, dict) else None
    if raw and str(raw).isdigit():
        retry_after = int(raw)
    return StepFailure(category, retry_after=retry_after)


_AI_FAILURE_CATEGORY: dict[str, str] = {
    "ai_disabled": "ai_disabled",
    "insufficient_context": "insufficient_context",
    "rate_limited": "ai_rate_limited",
    "provider_rate_limited": "ai_rate_limited",
    "invalid_output": "ai_invalid_output",
    "policy_violation": "ai_invalid_output",
    "bad_response": "ai_invalid_output",
    "timeout": "ai_unavailable",
    "unavailable": "ai_unavailable",
    "auth_failed": "ai_unavailable",
    "bad_request": "ai_unavailable",
}


def from_ai_failure(code: str, *, retryable: bool, retry_after: int | None) -> StepFailure:
    category = _AI_FAILURE_CATEGORY.get(code, "ai_unavailable")
    if code in ("auth_failed", "bad_request"):
        return StepFailure(category, retryable=False)
    return StepFailure(
        category,
        retryable=retryable and CATEGORIES[category][1],
        retry_after=retry_after,
    )
