"""Mailboxes: list connectors and accounts, add the demo mailbox, connect, sync, test and disconnect.

Reading is open to every member; every change requires the owner role and is audited with fixed vocabulary only.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status

from app.api.scoping import get_scoped_or_404, scoped_select
from app.clock import utcnow
from app.config import Settings
from app.db.models_email import EmailAccount
from app.deps import (
    CredentialsDep,
    DbDep,
    LimiterDep,
    SettingsDep,
    WorkspaceContext,
    WorkspaceDep,
    require_owner,
)
from app.errors import AppError
from app.mailbox.registry import ConnectorRegistry
from app.routers._common import ERRORS, audit_event
from app.schemas.email import (
    ConnectIn,
    ConnectOut,
    DisconnectOut,
    EmailAccountOut,
    ProviderOut,
    SyncOut,
    TestOut,
)
from app.services import email_accounts as svc
from app.services.email_out import account_out, provider_out

router = APIRouter(prefix="/api/v1/workspaces/{workspace_id}/email", tags=["email"])


def get_registry(request: Request) -> ConnectorRegistry:
    registry: ConnectorRegistry = request.app.state.mailbox
    return registry


RegistryDep = Annotated[ConnectorRegistry, Depends(get_registry)]


def redirect_uri(settings: Settings) -> str:
    return settings.effective_google_redirect_uri


def _account(db: DbDep, ctx: WorkspaceDep, account_id: uuid.UUID) -> EmailAccount:
    return get_scoped_or_404(
        db,
        EmailAccount,
        ctx,
        account_id,
        code="email_account_not_found",
        message="Mailbox not found.",
    )


@router.get(
    "/providers",
    response_model=list[ProviderOut],
    responses=ERRORS,
    summary="Email connectors and what each can do",
)
def list_providers(ctx: WorkspaceDep, registry: RegistryDep) -> list[ProviderOut]:
    return [provider_out(c) for c in registry.all()]


@router.get(
    "/accounts",
    response_model=list[EmailAccountOut],
    responses=ERRORS,
    summary="Connected mailboxes",
)
def list_accounts(ctx: WorkspaceDep, db: DbDep) -> list[EmailAccountOut]:
    rows = db.scalars(
        scoped_select(EmailAccount, ctx).order_by(EmailAccount.created_at, EmailAccount.id)
    )
    return [account_out(a) for a in rows]


@router.get(
    "/accounts/{account_id}",
    response_model=EmailAccountOut,
    responses=ERRORS,
    summary="One mailbox",
)
def get_account(account_id: uuid.UUID, ctx: WorkspaceDep, db: DbDep) -> EmailAccountOut:
    return account_out(_account(db, ctx, account_id))


@router.post(
    "/accounts/demo",
    response_model=EmailAccountOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        **ERRORS,
        200: {"model": EmailAccountOut, "description": "The demo mailbox already existed."},
    },
    summary="Add the demo mailbox (fictional data, nothing is delivered)",
)
def add_demo_account(
    response: Response, ctx: WorkspaceDep, db: DbDep, request: Request, settings: SettingsDep
) -> EmailAccountOut:
    require_owner(ctx)
    account, created = svc.get_demo_account(db, ctx)
    if created:
        audit_event(
            db,
            ctx,
            request,
            settings,
            "email.demo_account_created",
            "email_account",
            account.id,
            provider="demo",
        )
        db.commit()
    else:
        response.status_code = status.HTTP_200_OK
    return account_out(account)


@router.post(
    "/accounts/connect",
    response_model=ConnectOut,
    responses=ERRORS,
    summary="Start connecting a mailbox: returns the provider's consent URL",
)
def connect(
    body: ConnectIn,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
) -> ConnectOut:
    require_owner(ctx)
    url = svc.begin_authorization(
        db,
        ctx,
        store,
        registry.get(body.provider),
        redirect_uri=redirect_uri(settings),
        login_hint=body.login_hint,
    )
    audit_event(
        db,
        ctx,
        request,
        settings,
        "email.connect_started",
        "email_account",
        None,
        provider=body.provider,
    )
    db.commit()
    return ConnectOut(authorization_url=url)


@router.post(
    "/accounts/{account_id}/sync",
    response_model=SyncOut,
    responses=ERRORS,
    summary="Fetch new conversations now",
)
def sync_account(
    account_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
    limiter: LimiterDep,
) -> SyncOut:
    require_owner(ctx)
    account = _account(db, ctx, account_id)
    decision = limiter.hit(f"email-sync:{account.id}", 6, 60)
    if not decision.allowed:
        raise AppError(
            429,
            "sync_rate_limited",
            "Syncing too often. Wait a moment and try again.",
            headers={"Retry-After": str(decision.retry_after)},
        )
    summary = svc.sync_account(
        db, ctx, store, registry, account, now=utcnow(), max_pages=settings.email_sync_max_pages
    )
    audit_event(
        db, ctx, request, settings, "email.synced", "email_account", account.id,
        provider=account.provider, messages=summary.messages_created, conversations=summary.conversations_created,
    )  # fmt: skip
    db.commit()
    return SyncOut(
        account=account_out(account),
        conversations_created=summary.conversations_created,
        messages_created=summary.messages_created,
        messages_updated=summary.messages_updated,
        skipped=summary.skipped,
        pages=summary.pages,
        complete=summary.complete,
        rate_limited_until=summary.rate_limited_until,
        error_code=summary.error_code,
    )


@router.post(
    "/accounts/{account_id}/test",
    response_model=TestOut,
    responses=ERRORS,
    summary="Test the connection with a real provider call",
)
def test_account(
    account_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
) -> TestOut:
    require_owner(ctx)
    account = _account(db, ctx, account_id)
    ok = svc.test_connection(db, ctx, store, registry, account, now=utcnow())
    audit_event(
        db, ctx, request, settings, "email.tested", "email_account", account.id,
        provider=account.provider, state="ok" if ok else "failed",
    )  # fmt: skip
    db.commit()
    return TestOut(ok=ok, account=account_out(account))


@router.post(
    "/accounts/{account_id}/disconnect",
    response_model=DisconnectOut,
    responses=ERRORS,
    summary="Disconnect: revoke access and delete the stored credentials",
)
def disconnect_account(
    account_id: uuid.UUID,
    ctx: WorkspaceDep,
    db: DbDep,
    request: Request,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
) -> DisconnectOut:
    require_owner(ctx)
    account = _account(db, ctx, account_id)
    revoked = svc.disconnect(db, ctx, store, registry, account, now=utcnow())
    audit_event(
        db, ctx, request, settings, "email.disconnected", "email_account", account.id,
        provider=account.provider, state="revoked" if revoked else "revocation_unconfirmed",
    )  # fmt: skip
    db.commit()
    return DisconnectOut(account=account_out(account), revoked=revoked)


__all__ = ["WorkspaceContext", "router"]
