"""What a connector can report. Messages are written for people and never include tokens, bodies or provider text."""

from __future__ import annotations


class EmailError(Exception):
    code = "email_error"
    user_message = "The email provider could not complete that request."

    def __init__(self, retry_after: int | None = None) -> None:
        super().__init__(self.user_message)
        self.retry_after = retry_after


class NotConfigured(EmailError):
    code = "provider_not_configured"
    user_message = "This email provider is not set up on this server."


class NotSupported(EmailError):
    code = "not_supported"
    user_message = "This email provider does not support that."


class AuthExpired(EmailError):
    """The access token was rejected (expired or invalid). A refresh may fix it."""

    code = "auth_expired"
    user_message = "The email connection needs to be refreshed."


class AccessRevoked(EmailError):
    """The refresh token no longer works (revoked, expired or password changed): the user must reconnect."""

    code = "access_revoked"
    user_message = "Access to this mailbox was removed or expired. Reconnect it to continue."


class InsufficientScopes(EmailError):
    code = "insufficient_scopes"
    user_message = "The mailbox was connected without all the permissions Freelancer OS needs. Reconnect and allow them."


class RateLimited(EmailError):
    code = "rate_limited"
    user_message = "The email provider asked us to slow down. Try again later."


class TransientError(EmailError):
    """Network trouble or a provider 5xx on a request that is safe to repeat."""

    code = "provider_unavailable"
    user_message = "The email provider is not responding right now. Try again shortly."


class PermanentError(EmailError):
    """The provider refused the request and repeating it will not help."""

    code = "provider_rejected"
    user_message = "The email provider rejected the request."


class RemoteNotFound(EmailError):
    code = "not_found"
    user_message = "The provider no longer has that item."


class HistoryExpired(EmailError):
    """The sync cursor is too old: do a full sync."""

    code = "history_expired"
    user_message = "The sync position expired, so a full sync is needed."


class SendOutcomeUnknown(EmailError):
    """A send request may or may not have been delivered (timeout or 5xx after the request left)."""

    code = "send_outcome_unknown"
    user_message = "The provider did not confirm whether the message was sent."
