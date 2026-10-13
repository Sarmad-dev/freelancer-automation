"""Audit trail. Writes allow-listed, non-sensitive details only: never passwords, tokens or message bodies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session as DbSession

from app.config import Settings
from app.db.models import AuditEvent

# Keys permitted in AuditEvent.details. Anything else is dropped, so a careless caller cannot leak data.
ALLOWED_DETAIL_KEYS = frozenset(
    {
        "reason",
        "step",
        "status",
        "demo_mode",
        "email_hash",
        "missing_steps",
        "sessions_revoked",
        # Field names / counts / versions only, never values (MVP Prompt 5).
        "fields",
        "version",
        "count",
        "kind",
        # Counts and modes only (MVP Prompt 6).
        "created",
        "updated",
        "skipped",
        "errors",
        "strategy",
        # Stage keys and task-view names are fixed vocabulary, not user content (MVP Prompt 7).
        "from",
        "to",
        "view",
        # Fixed vocabulary for email accounts and sending (MVP Prompt 9): provider keys, states, counts. Never addresses
        # or content.
        "provider",
        "state",
        "messages",
        "conversations",
        # Workflow engine (MVP Prompt 11): ids, node types, states and error categories. Never content.
        "workflow_id",
        "run_id",
        "node",
        "node_type",
        "mode",
        "category",
        "decision",
        "trigger",
    }
)


@dataclass(frozen=True)
class RequestInfo:
    ip: str | None
    user_agent: str | None


def client_ip(request: Request, settings: Settings) -> str | None:
    """Client address. Honours X-Forwarded-For only for the configured number of trusted proxies."""
    n = settings.trusted_proxy_count
    if n > 0:
        parts = [
            p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()
        ]
        if len(parts) >= n:
            return parts[-n][:64]
    return request.client.host[:64] if request.client else None


def request_info(request: Request, settings: Settings) -> RequestInfo:
    ua = request.headers.get("user-agent")
    return RequestInfo(ip=client_ip(request, settings), user_agent=ua[:200] if ua else None)


def record(
    db: DbSession,
    action: str,
    *,
    info: RequestInfo | None = None,
    actor_user_id: uuid.UUID | None = None,
    workspace_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Stage an audit event in the caller's transaction (commits together with the change it describes)."""
    safe = {k: v for k, v in (details or {}).items() if k in ALLOWED_DETAIL_KEYS}
    db.add(
        AuditEvent(
            action=action,
            actor_user_id=actor_user_id,
            workspace_id=workspace_id,
            target_type=target_type,
            target_id=target_id,
            ip_address=info.ip if info else None,
            user_agent=info.user_agent if info else None,
            details=safe,
        )
    )
