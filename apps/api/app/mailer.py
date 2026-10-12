"""Outbound mail abstraction. Real providers arrive with the email integration phase."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger("freelancer_os.mail")


class Mailer(Protocol):
    @property
    def enabled(self) -> bool: ...

    def send_password_reset(self, to_email: str, reset_url: str) -> None: ...


class DisabledMailer:
    enabled = False

    def send_password_reset(self, to_email: str, reset_url: str) -> None:  # pragma: no cover
        raise RuntimeError("Mail backend is disabled")


class ConsoleMailer:
    """DEVELOPMENT ONLY: prints the reset link. Rejected in production by config validation."""

    enabled = True

    def send_password_reset(self, to_email: str, reset_url: str) -> None:
        logger.warning("DEV MAIL to=%s password reset link: %s", to_email, reset_url)


class InMemoryMailer:
    """Test double that records messages."""

    enabled = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_password_reset(self, to_email: str, reset_url: str) -> None:
        self.sent.append((to_email, reset_url))
