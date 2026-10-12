"""The do-not-contact list. Every send path asks ``find`` before anything leaves the system."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models_email import SuppressionEntry
from app.errors import AppError
from app.mailbox.mime import normalize_address


def normalize(address: str) -> str | None:
    return normalize_address(address)


def find(db: Session, workspace_id: uuid.UUID, address: str) -> SuppressionEntry | None:
    norm = normalize(address)
    if norm is None:
        return None
    return db.scalar(
        select(SuppressionEntry).where(
            SuppressionEntry.workspace_id == workspace_id,
            SuppressionEntry.email_normalized == norm,
        )
    )


def add(
    db: Session,
    workspace_id: uuid.UUID,
    address: str,
    reason: str,
    *,
    source: str | None = None,
    note: str | None = None,
    user_id: uuid.UUID | None = None,
) -> tuple[SuppressionEntry, bool]:
    """Add an address; returns ``(entry, created)``. Adding twice keeps the first entry."""
    norm = normalize(address)
    if norm is None:
        raise AppError(
            422,
            "validation_error",
            "Enter a valid email address.",
            fields={"email": "Enter a valid email address."},
        )
    existing = find(db, workspace_id, norm)
    if existing is not None:
        return existing, False
    entry = SuppressionEntry(
        workspace_id=workspace_id,
        email_normalized=norm,
        reason=reason,
        source=source,
        note=note,
        created_by_user_id=user_id,
    )
    try:
        with db.begin_nested():
            db.add(entry)
            db.flush()
    except IntegrityError:
        found = find(db, workspace_id, norm)
        if found is None:
            raise
        return found, False
    return entry, True
