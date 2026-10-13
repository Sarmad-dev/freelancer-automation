"""The inbox: conversations, threads, classification and reply suggestions. Reading is open to members; every change needs the
owner role and is audited without content."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response, status

from app.ai.factory import ai_service_for
from app.ai.schemas import REPLY_CATEGORIES
from app.api.pagination import Page, PageParams, page_params
from app.api.scoping import get_scoped_or_404
from app.clock import utcnow
from app.db.models_email import Conversation
from app.deps import DbDep, SettingsDep, WorkspaceDep, require_owner
from app.errors import AppError
from app.routers._common import ERRORS, audit_event
from app.schemas.inbox import (
    ClassifyQueued,
    ConversationDetail,
    ConversationSummary,
    InboxCounts,
    SetClassification,
    SuggestReplyOut,
)
from app.services import email_jobs, inbox, replies
from app.services.email_out import draft_out

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/inbox", tags=["inbox"])


def _get(db: DbDep, ctx: WorkspaceDep, conversation_id: uuid.UUID) -> Conversation:
    return get_scoped_or_404(
        db,
        Conversation,
        ctx,
        conversation_id,
        code="conversation_not_found",
        message="Conversation not found.",
    )


@router.get(
    "/counts",
    response_model=InboxCounts,
    responses=ERRORS,
    summary="Unread and needs-review counts",
)
def get_counts(ctx: WorkspaceDep, db: DbDep) -> InboxCounts:
    return inbox.counts(db, ctx)


@router.get(
    "/conversations",
    response_model=Page[ConversationSummary],
    responses=ERRORS,
    summary="List conversations",
)
def list_conversations(
    ctx: WorkspaceDep,
    db: DbDep,
    params: Annotated[PageParams, Depends(page_params)],
    q: Annotated[
        str | None,
        Query(
            max_length=100,
            description="Subject, sender, preview, message text, contact name or lead title contains.",
        ),
    ] = None,
    unread: Annotated[bool | None, Query()] = None,
    classification: Annotated[
        Literal[
            "interested",
            "question",
            "objection",
            "not_now",
            "referral",
            "out_of_office",
            "unsubscribe",
            "irrelevant",
            "unclassified",
        ]
        | None,
        Query(),
    ] = None,
    needs_review: Annotated[bool | None, Query()] = None,
    account_id: Annotated[uuid.UUID | None, Query()] = None,
    lead_id: Annotated[uuid.UUID | None, Query()] = None,
    conversation_status: Annotated[Literal["open", "archived"], Query(alias="status")] = "open",
) -> Page[ConversationSummary]:
    items, total = inbox.list_conversations(
        db,
        ctx,
        params,
        q=q,
        unread=unread,
        classification=classification,
        needs_review=needs_review,
        account_id=account_id,
        lead_id=lead_id,
        status=conversation_status,
    )
    return Page[ConversationSummary](
        items=items, total=total, limit=params.limit, offset=params.offset
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationDetail,
    responses=ERRORS,
    summary="A thread with its messages",
)
def get_conversation(
    conversation_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep
) -> ConversationDetail:
    return inbox.get_detail(db, ctx, _get(db, ctx, conversation_id))


@router.post(
    "/conversations/{conversation_id}/read",
    response_model=ConversationSummary,
    responses=ERRORS,
    summary="Mark a conversation read",
)
def mark_read(conversation_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> ConversationSummary:
    require_owner(ctx)
    conversation = _get(db, ctx, conversation_id)
    inbox.set_read(conversation, True)
    db.commit()
    return inbox.summarize(db, ctx.workspace_id, [conversation])[0]


@router.post(
    "/conversations/{conversation_id}/unread",
    response_model=ConversationSummary,
    responses=ERRORS,
    summary="Mark a conversation unread",
)
def mark_unread(conversation_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> ConversationSummary:
    require_owner(ctx)
    conversation = _get(db, ctx, conversation_id)
    inbox.set_read(conversation, False)
    db.commit()
    return inbox.summarize(db, ctx.workspace_id, [conversation])[0]


@router.post(
    "/conversations/{conversation_id}/classify",
    response_model=ClassifyQueued,
    status_code=status.HTTP_202_ACCEPTED,
    responses=ERRORS,
    summary="Classify the latest reply again (runs in the background)",
)
def reclassify(
    conversation_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    background: BackgroundTasks,
) -> ClassifyQueued:
    require_owner(ctx)
    conversation = _get(db, ctx, conversation_id)
    latest = email_jobs.latest_inbound(db, conversation.id)
    if latest is None:
        raise AppError(
            409, "no_reply_to_classify", "This thread has no incoming message to classify."
        )
    job = email_jobs.enqueue(db, ctx.workspace_id, conversation.id, latest.id, force=True)
    db.commit()
    queued = job.status == "queued"
    if queued:
        background.add_task(email_jobs.run_worker, request.app, workspace_id=ctx.workspace_id)
    return ClassifyQueued(
        queued=queued,
        message="Classification started." if queued else "Classification is already running.",
    )


@router.put(
    "/conversations/{conversation_id}/classification",
    response_model=ConversationSummary,
    responses=ERRORS,
    summary="Set (or confirm) the category yourself",
)
def set_classification(
    conversation_id: uuid.UUID,
    body: SetClassification,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> ConversationSummary:
    require_owner(ctx)
    if body.category not in REPLY_CATEGORIES:
        raise AppError(422, "validation_error", "Unknown category.")
    conversation = _get(db, ctx, conversation_id)
    suppressed = inbox.set_classification(db, ctx, conversation, body.category, utcnow())
    audit_event(
        db, ctx, request, settings, "email.classification_set", "conversation", conversation.id,
        kind=body.category, state="manual",
    )  # fmt: skip
    if suppressed:
        audit_event(
            db,
            ctx,
            request,
            settings,
            "email.auto_suppressed",
            "conversation",
            conversation.id,
            reason="unsubscribe",
        )
    db.commit()
    return inbox.summarize(db, ctx.workspace_id, [conversation])[0]


@router.post(
    "/conversations/{conversation_id}/suggest-reply",
    response_model=SuggestReplyOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERRORS,
        200: {"model": SuggestReplyOut, "description": "An earlier AI draft was replaced."},
    },
    summary="Draft a reply with AI (never sent automatically)",
)
def suggest_reply(
    conversation_id: uuid.UUID,
    response: Response,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
) -> SuggestReplyOut:
    require_owner(ctx)
    conversation = _get(db, ctx, conversation_id)
    ai = ai_service_for(request, ctx, settings)
    draft, regenerated, warnings, label, is_demo = replies.suggest_reply(
        db, ctx, conversation, ai, utcnow()
    )
    audit_event(
        db, ctx, request, settings, "drafts.suggested", "draft", draft.id,
        count=len(draft.facts_used or []), state="regenerated" if regenerated else "created",
    )  # fmt: skip
    db.commit()
    if regenerated:
        response.status_code = status.HTTP_200_OK
    return SuggestReplyOut(
        draft=draft_out(db, draft),
        regenerated=regenerated,
        warnings=warnings,
        ai_label=label,
        is_demo_ai=is_demo,
    )
