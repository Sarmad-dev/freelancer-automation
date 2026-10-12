"""Request dependencies: database session, settings, current user/session, workspace scoping."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import as_utc, utcnow
from app.config import Settings, get_settings
from app.db.models import Membership, Session, User, Workspace
from app.db.session import get_session
from app.errors import AppError
from app.mailer import Mailer
from app.ratelimit import RateLimiter
from app.security.cookies import clear_cookie_header, cookie_name
from app.security.tokens import hash_token

# Refresh last_seen_at (and the cookie's Max-Age) at most this often to avoid a write per request.
TOUCH_INTERVAL = timedelta(minutes=5)

SettingsDep = Annotated[Settings, Depends(get_settings)]
DbDep = Annotated[DbSession, Depends(get_session)]


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.rate_limiter
    return limiter


def get_mailer(request: Request) -> Mailer:
    mailer: Mailer = request.app.state.mailer
    return mailer


LimiterDep = Annotated[RateLimiter, Depends(get_limiter)]
MailerDep = Annotated[Mailer, Depends(get_mailer)]


@dataclass(frozen=True)
class AuthContext:
    user: User
    session: Session


def session_lifetime(session: Session) -> timedelta:
    """Cookie lifetime = time left until the absolute expiry.

    Idle expiry is enforced server-side only. The cookie is deliberately not re-issued on activity:
    server-rendered pages cannot update the browser's cookie, so a short sliding Max-Age could expire
    in the browser while the server session is still valid.
    """
    return as_utc(session.expires_at) - utcnow()


def _unauthenticated(settings: Settings, code: str, message: str, *, clear: bool) -> AppError:
    return AppError(401, code, message, headers=clear_cookie_header(settings) if clear else None)


def get_auth(request: Request, db: DbDep, settings: SettingsDep) -> AuthContext:
    token = request.cookies.get(cookie_name(settings))
    if not token:
        raise _unauthenticated(settings, "not_authenticated", "Sign in to continue.", clear=False)

    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))
    if session is None:
        raise _unauthenticated(settings, "not_authenticated", "Sign in to continue.", clear=True)

    now = utcnow()
    idle_deadline = as_utc(session.last_seen_at) + timedelta(
        minutes=settings.session_idle_timeout_minutes
    )
    if now >= as_utc(session.expires_at) or now >= idle_deadline:
        db.delete(session)
        db.commit()
        raise _unauthenticated(
            settings, "session_expired", "Your session has expired. Sign in again.", clear=True
        )

    user = db.get(User, session.user_id)
    if user is None or not user.is_active:
        db.delete(session)
        db.commit()
        raise _unauthenticated(settings, "not_authenticated", "Sign in to continue.", clear=True)

    if now - as_utc(session.last_seen_at) >= TOUCH_INTERVAL:
        session.last_seen_at = now
        db.commit()
    return AuthContext(user=user, session=session)


AuthDep = Annotated[AuthContext, Depends(get_auth)]


@dataclass(frozen=True)
class WorkspaceContext:
    user: User
    workspace: Workspace
    membership: Membership

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id


def get_workspace_context(workspace_id: uuid.UUID, auth: AuthDep, db: DbDep) -> WorkspaceContext:
    """Resolve a workspace from the URL *only if the signed-in user is a member*.

    Non-members get the same 404 as a workspace that does not exist, so ids cannot be probed.
    Every workspace-scoped query must filter on ``ctx.workspace_id``.
    """
    row = db.execute(
        select(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(Membership.workspace_id == workspace_id, Membership.user_id == auth.user.id)
    ).first()
    if row is None:
        raise AppError(404, "workspace_not_found", "Workspace not found.")
    membership, workspace = row
    return WorkspaceContext(user=auth.user, workspace=workspace, membership=membership)


WorkspaceDep = Annotated[WorkspaceContext, Depends(get_workspace_context)]


def require_owner(ctx: WorkspaceContext) -> None:
    if ctx.membership.role != "owner":
        raise AppError(403, "forbidden", "You don't have permission to do that.")
