"""OAuth redirect target. The provider sends the browser here after consent; we finish the flow and send the browser
back to the web app. No token, code or provider message is ever put in the redirect."""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app import audit
from app.clock import utcnow
from app.deps import AuthContext, CredentialsDep, DbDep, SettingsDep, get_auth
from app.errors import AppError
from app.routers.email import RegistryDep
from app.services import email_accounts as svc

router = APIRouter(prefix="/api/v1/email/oauth", tags=["email"])


def _back(settings: SettingsDep, **params: str) -> RedirectResponse:
    response = RedirectResponse(
        f"{settings.web_base_url.rstrip('/')}/integrations?{urlencode(params)}", status_code=303
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.get(
    "/callback",
    include_in_schema=False,
    summary="Provider redirect target (not called by the web app)",
)
def oauth_callback(
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    store: CredentialsDep,
    registry: RegistryDep,
    state: Annotated[str, Query(max_length=300)] = "",
    code: Annotated[str | None, Query(max_length=2048)] = None,
    error: Annotated[str | None, Query(max_length=100)] = None,
) -> RedirectResponse:
    try:
        auth: AuthContext = get_auth(request, db, settings)
    except AppError:
        return _back(settings, email="error", reason="signed_out")
    info = audit.request_info(request, settings)
    workspace_id: uuid.UUID | None = None
    try:
        workspace_id, account = svc.complete_authorization(
            db,
            auth.user.id,
            store,
            registry,
            state=state,
            code=code,
            provider_error=error,
            now=utcnow(),
        )
    except svc.OAuthFailure as failure:
        # The single-use pending record was consumed: persist that, and leave an audit trail when we know the workspace.
        try:
            workspace_id = uuid.UUID(state.split(".", 1)[0])
        except ValueError:
            workspace_id = None
        if workspace_id is not None and failure.reason not in (
            "invalid_state",
            "wrong_user",
            "not_allowed",
        ):
            audit.record(
                db, "email.connect_failed", info=info, actor_user_id=auth.user.id,
                workspace_id=workspace_id, target_type="email_account", details={"reason": failure.reason},
            )  # fmt: skip
        db.commit()
        return _back(settings, email="error", reason=failure.reason)
    audit.record(
        db, "email.account_connected", info=info, actor_user_id=auth.user.id,
        workspace_id=workspace_id, target_type="email_account", target_id=str(account.id),
        details={"provider": account.provider},
    )  # fmt: skip
    db.commit()
    return _back(settings, email="connected", provider=account.provider)
