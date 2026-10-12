"""Which connectors exist on this server, built from configuration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.mailbox.connector import EmailConnector
from app.mailbox.demo import DemoConnector
from app.mailbox.errors import NotConfigured
from app.mailbox.gmail import GmailConnector

if TYPE_CHECKING:
    from app.config import Settings


class ConnectorRegistry:
    def __init__(self, connectors: dict[str, EmailConnector]) -> None:
        self._connectors = connectors

    def get(self, provider: str) -> EmailConnector:
        connector = self._connectors.get(provider)
        if connector is None:
            raise NotConfigured()
        return connector

    def all(self) -> list[EmailConnector]:
        return list(self._connectors.values())


def build_registry(settings: Settings) -> ConnectorRegistry:
    return ConnectorRegistry(
        {
            "demo": DemoConnector(),
            "gmail": GmailConnector(
                client_id=settings.google_client_id.strip(),
                client_secret=settings.google_client_secret.get_secret_value(),
                timeout=settings.email_http_timeout_seconds,
            ),
        }
    )
