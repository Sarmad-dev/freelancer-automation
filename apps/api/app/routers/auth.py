from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select

from app import audit
from app.clock import as_utc, utcnow
from app.db.models import (
    FreelancerProfile,
    Membership,
    OnboardingProgress,
    PasswordResetToken,
    User,
    Workspace,
)
from app.db.models import Session as LoginSession
from app.deps import (
    AuthDep,
    DbDep,
    LimiterDep,
    MailerDep,
    SettingsDep,
    session_lifetime,
)
from app.errors import AppError, ErrorResponse
from app.schemas.auth import (
    Accepted,
    AuthConfig,
    MeResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    SignInRequest,
    SignUpRequest,
    UserOut,
    WorkspaceOut,
)
from app.security import passwords
from app.security.cookies import clear_session_cookie, cookie_name, set_session_cookie
from app.security.tokens import hash_token, new_token, short_hash

logger = logging.getLogger("freelancer_os.auth")
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_ERR: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
}


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _me(db: DbDep, user: User) -> MeResponse:
    rows = db.execute(
        select(Membership, Workspace, OnboardingProgress.status)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .outerjoin(OnboardingProgress, OnboardingProgress.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Workspace.created_at)
    ).all()
    return MeResponse(
        user=UserOut(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            email_verified=user.email_verified_at is not None,
        ),
        workspaces=[
            WorkspaceOut(
                id=w.id,
                name=w.name,
                kind=w.kind,
                role=m.role,
                timezone=w.timezone,
                demo_mode=w.demo_mode,
                onboarding_status=ob or "not_started",
            )
            for m, w, ob in rows
        ],
    )


def _rate_limited(retry_after: int) -> AppError:
    return AppError(
        429,
        "rate_limited",
        "Too many attempts. Please wait a moment and try again.",
        headers={"Retry-After": str(retry_after)},
    )


def _start_session(
    db: DbDep, response: Response, settings: SettingsDep, user: User, ua: str | None
) -> LoginSession:
    token = new_token()
    now = utcnow()
    session = LoginSession(
        user_id=user.id,
        token_hash=hash_token(token),
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=settings.session_absolute_timeout_days),
        user_agent=ua,
    )
    db.add(session)
    db.flush()
    set_session_cookie(response, settings, token, session_lifetime(session))
    return session


@router.get("/config", response_model=AuthConfig, summary="Public authentication capabilities")
def auth_config(mailer: MailerDep) -> AuthConfig:
    return AuthConfig(password_reset_enabled=mailer.enabled)


@router.post(
    "/sign-up",
    response_model=MeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERR,
    summary="Create an account, a personal workspace and a session",
)
def sign_up(
    body: SignUpRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> MeResponse:
    info = audit.request_info(request, settings)
    decision = limiter.hit(f"signup:ip:{info.ip}", 10, 3600)
    if not decision.allowed:
        raise _rate_limited(decision.retry_after)

    email = str(body.email)
    try:
        passwords.validate_password(body.password, email=email)
    except passwords.WeakPasswordError as exc:
        raise AppError(
            422, "validation_error", "Some fields are invalid.", fields={"password": str(exc)}
        ) from exc

    normalized = normalize_email(email)
    # Trade-off: without email verification we must tell the visitor the address is taken.
    # Mitigated by per-IP rate limiting; revisit when email verification ships.
    if db.scalar(select(User.id).where(User.email_normalized == normalized)) is not None:
        raise AppError(
            409,
            "email_in_use",
            "An account with this email already exists. Try signing in.",
            fields={"email": "Already registered."},
        )

    user = User(
        email=email.strip(),
        email_normalized=normalized,
        password_hash=passwords.hash_password(body.password),
        display_name=body.display_name,
        last_sign_in_at=utcnow(),
    )
    db.add(user)
    db.flush()
    workspace = Workspace(name=f"{body.display_name}'s workspace"[:120], kind="personal")
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.add(OnboardingProgress(workspace_id=workspace.id, completed_steps=[]))
    db.add(FreelancerProfile(workspace_id=workspace.id))
    _start_session(db, response, settings, user, info.user_agent)
    audit.record(
        db,
        "auth.sign_up",
        info=info,
        actor_user_id=user.id,
        workspace_id=workspace.id,
        target_type="user",
        target_id=str(user.id),
    )
    db.commit()
    return _me(db, user)


@router.post(
    "/sign-in", response_model=MeResponse, responses=_ERR, summary="Sign in with email and password"
)
def sign_in(
    body: SignInRequest,
    request: Request,
    response: Response,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> MeResponse:
    info = audit.request_info(request, settings)
    normalized = normalize_email(body.email)
    email_key = f"signin:email:{short_hash(normalized)}"
    for key, limit in ((email_key, 10), (f"signin:ip:{info.ip}", 60)):
        decision = limiter.hit(key, limit, 15 * 60)
        if not decision.allowed:
            audit.record(
                db,
                "auth.sign_in_blocked",
                info=info,
                details={"reason": "rate_limited", "email_hash": short_hash(normalized)},
            )
            db.commit()
            raise _rate_limited(decision.retry_after)

    user = db.scalar(select(User).where(User.email_normalized == normalized))
    # Always run one hash verification so response time does not reveal whether the account exists.
    stored = user.password_hash if user else passwords.DUMMY_HASH
    valid = passwords.verify_password(stored, body.password)
    if user is None or not user.is_active or not valid:
        audit.record(
            db,
            "auth.sign_in_failed",
            info=info,
            actor_user_id=user.id if user else None,
            details={"reason": "invalid_credentials", "email_hash": short_hash(normalized)},
        )
        db.commit()
        raise AppError(401, "invalid_credentials", "Incorrect email or password.")

    limiter.reset(email_key)
    if passwords.needs_rehash(user.password_hash):
        user.password_hash = passwords.hash_password(body.password)
    user.last_sign_in_at = utcnow()
    _start_session(db, response, settings, user, info.user_agent)
    audit.record(
        db,
        "auth.sign_in",
        info=info,
        actor_user_id=user.id,
        target_type="user",
        target_id=str(user.id),
    )
    db.commit()
    return _me(db, user)


@router.post("/sign-out", status_code=status.HTTP_204_NO_CONTENT, summary="Sign out (idempotent)")
def sign_out(request: Request, db: DbDep, settings: SettingsDep) -> Response:
    token = request.cookies.get(cookie_name(settings))
    if token:
        session = db.scalar(
            select(LoginSession).where(LoginSession.token_hash == hash_token(token))
        )
        if session is not None:
            audit.record(
                db,
                "auth.sign_out",
                info=audit.request_info(request, settings),
                actor_user_id=session.user_id,
            )
            db.delete(session)
            db.commit()
    out = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(out, settings)
    return out


@router.get(
    "/me",
    response_model=MeResponse,
    responses={401: {"model": ErrorResponse}},
    summary="Current user",
)
def me(auth: AuthDep, db: DbDep) -> MeResponse:
    return _me(db, auth.user)


@router.post(
    "/password-reset/request",
    response_model=Accepted,
    status_code=status.HTTP_202_ACCEPTED,
    responses={**_ERR, 503: {"model": ErrorResponse}},
    summary="Request a password-reset email (always 202 to avoid revealing registered emails)",
)
def request_password_reset(
    body: PasswordResetRequest,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
    mailer: MailerDep,
) -> Accepted:
    if not mailer.enabled:
        raise AppError(
            503, "password_reset_unavailable", "Password reset isn't available on this server yet."
        )
    info = audit.request_info(request, settings)
    normalized = normalize_email(str(body.email))
    for key, limit in ((f"reset:email:{short_hash(normalized)}", 5), (f"reset:ip:{info.ip}", 20)):
        decision = limiter.hit(key, limit, 3600)
        if not decision.allowed:
            raise _rate_limited(decision.retry_after)

    user = db.scalar(select(User).where(User.email_normalized == normalized))
    if user is not None and user.is_active:
        token = new_token()
        now = utcnow()
        # Only the newest link works.
        for old in db.scalars(
            select(PasswordResetToken).where(
                PasswordResetToken.user_id == user.id, PasswordResetToken.used_at.is_(None)
            )
        ):
            old.used_at = now
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(token),
                created_at=now,
                expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes),
            )
        )
        audit.record(db, "auth.password_reset_requested", info=info, actor_user_id=user.id)
        db.commit()
        try:
            mailer.send_password_reset(
                user.email, f"{settings.web_base_url.rstrip('/')}/reset-password?token={token}"
            )
        except Exception:  # noqa: BLE001 - never reveal delivery problems to the requester
            logger.exception("failed to send password reset email")
    return Accepted()


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={**_ERR, 400: {"model": ErrorResponse}},
    summary="Set a new password using a reset token; revokes all sessions",
)
def confirm_password_reset(
    body: PasswordResetConfirm,
    request: Request,
    db: DbDep,
    settings: SettingsDep,
    limiter: LimiterDep,
) -> Response:
    info = audit.request_info(request, settings)
    decision = limiter.hit(f"reset-confirm:ip:{info.ip}", 30, 3600)
    if not decision.allowed:
        raise _rate_limited(decision.retry_after)

    record = db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token))
    )
    now = utcnow()
    invalid = AppError(
        400, "invalid_token", "This reset link is invalid or has expired. Request a new one."
    )
    if record is None or record.used_at is not None or as_utc(record.expires_at) <= now:
        raise invalid
    user = db.get(User, record.user_id)
    if user is None or not user.is_active:
        raise invalid
    try:
        passwords.validate_password(body.password, email=user.email)
    except passwords.WeakPasswordError as exc:
        raise AppError(
            422, "validation_error", "Some fields are invalid.", fields={"password": str(exc)}
        ) from exc

    user.password_hash = passwords.hash_password(body.password)
    record.used_at = now
    revoked = 0
    for s in db.scalars(select(LoginSession).where(LoginSession.user_id == user.id)):
        db.delete(s)
        revoked += 1
    audit.record(
        db,
        "auth.password_reset_completed",
        info=info,
        actor_user_id=user.id,
        details={"sessions_revoked": revoked},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
