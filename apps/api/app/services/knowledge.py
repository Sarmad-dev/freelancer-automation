"""Knowledge items: provenance, review lifecycle and version history.

Lifecycle (approval is what makes a fact usable by AI):

    draft / pending_review --approve(version)--> approved --edit--> pending_review (re-review required)
    any --reject--> rejected --edit--> draft
    is_enabled is an independent on/off switch: turning an item off keeps its approval.

Extracted or imported material always arrives as ``pending_review`` and is never authoritative until a
human approves the exact version they reviewed.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models_crm import KnowledgeItem, KnowledgeItemVersion
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.knowledge import KnowledgeCreate, KnowledgePatch
from app.schemas.text import single_line

MAX_IMPORT_ITEMS = 25
MIN_FACT_CHARS = 15
MAX_FACT_CHARS = 500
_BULLET = re.compile(r"^\s*(?:[-*•●▪]|\d{1,2}[.)])\s+")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


def _stale() -> AppError:
    return AppError(
        409,
        "stale_version",
        "This item changed after you opened it. Reload it and review the latest version.",
    )


def _snapshot(db: DbSession, item: KnowledgeItem, user_id: uuid.UUID | None) -> None:
    db.add(
        KnowledgeItemVersion(
            workspace_id=item.workspace_id,
            item_id=item.id,
            version=item.version,
            kind=item.kind,
            title=item.title,
            content=item.content,
            source_ref=item.source_ref,
            changed_by_user_id=user_id,
        )
    )


def create_item(
    db: DbSession, ctx: WorkspaceContext, body: KnowledgeCreate, *, source_type: str = "manual"
) -> KnowledgeItem:
    now = utcnow()
    approved = body.approve_now and source_type == "manual"
    item = KnowledgeItem(
        workspace_id=ctx.workspace_id,
        kind=body.kind,
        title=body.title,
        content=body.content,
        source_type=source_type,
        source_ref=body.source_ref,
        status="approved"
        if approved
        else ("draft" if source_type == "manual" else "pending_review"),
        version=1,
        approved_at=now if approved else None,
        approved_by_user_id=ctx.user.id if approved else None,
        created_by_user_id=ctx.user.id,
        is_enabled=True,
    )
    db.add(item)
    db.flush()
    _snapshot(db, item, ctx.user.id)
    return item


def update_item(
    db: DbSession, ctx: WorkspaceContext, item: KnowledgeItem, patch: KnowledgePatch
) -> tuple[KnowledgeItem, list[str]]:
    """Returns the item and the changed field names (empty if nothing changed)."""
    data = patch.model_dump(exclude_unset=True)
    expected = data.pop("expected_version", None)
    enabled = data.pop("is_enabled", None)
    if expected is not None and expected != item.version:
        raise _stale()
    for required in ("kind", "title", "content"):
        if required in data and data[required] is None:
            raise AppError(
                422,
                "validation_error",
                "Some fields are invalid.",
                fields={required: "This field cannot be empty."},
            )

    content_changes = {k: v for k, v in data.items() if getattr(item, k) != v}
    changed: list[str] = sorted(content_changes)
    now = utcnow()

    if content_changes:
        values: dict[str, Any] = {**content_changes, "version": item.version + 1, "updated_at": now}
        if item.status == "approved":
            # Editing approved text voids the approval: a human must re-review the new wording.
            values.update(status="pending_review", approved_at=None, approved_by_user_id=None)
        elif item.status == "rejected":
            values["status"] = "draft"
        if enabled is not None and enabled != item.is_enabled:
            values["is_enabled"] = enabled
            changed.append("is_enabled")
        _compare_and_set(db, ctx, item, values)
        _snapshot(db, item, ctx.user.id)
    elif enabled is not None and enabled != item.is_enabled:
        item.is_enabled = enabled  # not a content change: same version, approval untouched
        item.updated_at = now
        changed.append("is_enabled")
        db.flush()
    return item, changed


def _compare_and_set(
    db: DbSession, ctx: WorkspaceContext, item: KnowledgeItem, values: dict[str, Any]
) -> None:
    result = db.execute(
        update(KnowledgeItem)
        .where(
            KnowledgeItem.id == item.id,
            KnowledgeItem.workspace_id == ctx.workspace_id,
            KnowledgeItem.version == item.version,
        )
        .values(**values)
    )
    if result.rowcount != 1:  # type: ignore[attr-defined]
        raise _stale()
    db.expire(item)


def approve_item(
    db: DbSession, ctx: WorkspaceContext, item: KnowledgeItem, version: int
) -> KnowledgeItem:
    if version != item.version:
        raise _stale()
    if item.status == "approved":
        return item  # idempotent
    if item.status == "rejected":
        raise AppError(
            409, "invalid_state", "A rejected item must be edited before it can be approved."
        )
    now = utcnow()
    _compare_and_set(
        db,
        ctx,
        item,
        {
            "status": "approved",
            "approved_at": now,
            "approved_by_user_id": ctx.user.id,
            "updated_at": now,
        },
    )
    return item


def reject_item(db: DbSession, ctx: WorkspaceContext, item: KnowledgeItem) -> KnowledgeItem:
    if item.status != "rejected":
        item.status = "rejected"
        item.approved_at = None
        item.approved_by_user_id = None
        item.updated_at = utcnow()
        db.flush()
    return item


# --- Text import (no AI): split material into candidate facts for human review -------------------------
def split_candidates(text: str) -> list[str]:
    """Split pasted material into candidate statements, verbatim.

    Bullets and paragraphs become candidates; paragraphs longer than ``MAX_FACT_CHARS`` are cut at sentence
    boundaries. Nothing is rewritten, summarised or added, so a candidate can never contain a claim the
    freelancer did not write.
    """
    units: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if lines and all(_BULLET.match(ln) for ln in lines):
            units.extend(_BULLET.sub("", ln).strip() for ln in lines)
        else:
            units.append(" ".join(ln.strip() for ln in lines))
    candidates: list[str] = []
    for unit in units:
        unit = single_line(unit)
        if len(unit) <= MAX_FACT_CHARS:
            candidates.append(unit)
            continue
        chunk = ""
        for sentence in _SENTENCE.split(unit):
            if chunk and len(chunk) + 1 + len(sentence) > MAX_FACT_CHARS:
                candidates.append(chunk)
                chunk = sentence[:MAX_FACT_CHARS]
            else:
                chunk = (
                    f"{chunk} {sentence}".strip()[:MAX_FACT_CHARS]
                    if chunk
                    else sentence[:MAX_FACT_CHARS]
                )
        if chunk:
            candidates.append(chunk)
    return [c for c in candidates if len(c) >= MIN_FACT_CHARS]


def _title_for(content: str) -> str:
    if len(content) <= 80:
        return content
    cut = content[:80].rsplit(" ", 1)[0]
    return f"{cut}…"


def import_text(
    db: DbSession, ctx: WorkspaceContext, *, source_label: str, text: str, kind: str
) -> tuple[list[KnowledgeItem], int, bool]:
    """Create ``pending_review`` items from pasted text. Returns (items, skipped_duplicates, truncated)."""
    existing = {
        c.casefold()
        for c in db.scalars(
            select(KnowledgeItem.content).where(KnowledgeItem.workspace_id == ctx.workspace_id)
        )
    }
    created: list[KnowledgeItem] = []
    skipped = 0
    candidates = split_candidates(text)
    truncated = False
    for content in candidates:
        key = content.casefold()
        if key in existing:
            skipped += 1
            continue
        if len(created) >= MAX_IMPORT_ITEMS:
            truncated = True
            break
        existing.add(key)
        body = KnowledgeCreate(
            kind=kind, title=_title_for(content), content=content, source_ref=source_label
        )
        created.append(create_item(db, ctx, body, source_type="extracted"))
    return created, skipped, truncated


def status_counts(db: DbSession, ctx: WorkspaceContext) -> dict[str, int]:
    rows = db.execute(
        select(KnowledgeItem.status, KnowledgeItem.is_enabled, func.count())
        .where(KnowledgeItem.workspace_id == ctx.workspace_id)
        .group_by(KnowledgeItem.status, KnowledgeItem.is_enabled)
    ).all()
    counts = {
        "draft": 0,
        "pending_review": 0,
        "approved": 0,
        "rejected": 0,
        "in_use": 0,
        "disabled": 0,
    }
    for status, enabled, n in rows:
        counts[status] += n
        if status == "approved":
            counts["in_use" if enabled else "disabled"] += n
    return counts
