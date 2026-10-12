"""Response models for mailboxes and drafts (kept out of the routers so both can share them)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models_email import Draft, EmailAccount, Message
from app.mailbox.connector import EmailConnector
from app.schemas.drafts import DraftOut, MessageStateOut
from app.schemas.email import EmailAccountOut, ProviderOut, ScopeOut
from app.services import drafts as draft_service
from app.services.email_accounts import friendly_error

STATUS_LABELS = {
    "connected": "Connected",
    "demo": "Demo mailbox: no real email is sent or received",
    "needs_reauth": "Reconnect needed",
    "disconnected": "Disconnected",
    "error": "Problem: see the details",
}


def account_out(account: EmailAccount) -> EmailAccountOut:
    return EmailAccountOut(
        id=account.id,
        provider=account.provider,
        email_address=account.email_address,
        display_name=account.display_name,
        status=account.status,
        status_label=STATUS_LABELS.get(account.status, account.status),
        is_demo=account.is_demo,
        needs_reconnect=account.status == "needs_reauth",
        granted_scopes=list(account.granted_scopes or []),
        last_synced_at=account.last_synced_at,
        last_health_check_at=account.last_health_check_at,
        rate_limited_until=account.rate_limited_until,
        last_error_code=account.last_error_code,
        last_error=friendly_error(account.last_error_code),
        created_at=account.created_at,
    )


def provider_out(connector: EmailConnector) -> ProviderOut:
    m = connector.manifest
    return ProviderOut(
        key=m.key,
        label=m.label,
        is_demo=m.is_demo,
        configured=connector.configured(),
        capabilities=list(m.capabilities),
        scopes=[ScopeOut(scope=s.scope, why=s.why) for s in m.scopes],
        setup_doc=m.setup_doc,
        notes=list(m.notes),
        verified_live=False,
    )


def message_out(message: Message) -> MessageStateOut:
    return MessageStateOut(
        id=message.id,
        delivery_state=message.delivery_state,
        delivery_label=draft_service.delivery_label(message.delivery_state),
        delivery_error_code=message.delivery_error_code,
        is_demo=message.is_sample or message.delivery_state == "demo",
        conversation_id=message.conversation_id,
        sent_at=message.sent_at,
    )


def draft_out(db: Session, draft: Draft, message: Message | None = None) -> DraftOut:
    message = message or draft_service.get_message(db, draft.workspace_id, draft.id)
    return DraftOut(
        id=draft.id,
        lead_id=draft.lead_id,
        conversation_id=draft.conversation_id,
        email_account_id=draft.email_account_id,
        to_address=draft.to_address,
        subject=draft.subject,
        body_text=draft.body_text,
        status=draft.status,
        author=draft.author,
        version=draft.version,
        facts_used=[str(f) for f in (draft.facts_used or [])],
        approved_at=draft.approved_at,
        approval_is_current=draft_service.approval_is_current(draft),
        sent_at=draft.sent_at,
        send_locked=draft_service.send_locked(draft),
        message=message_out(message) if message else None,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )
