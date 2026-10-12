"""Onboarding domain logic: applying validated steps to the profile and tracking progress.

Every function takes a ``WorkspaceContext`` and only touches rows for ``ctx.workspace_id``.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.clock import utcnow
from app.db.models import FreelancerProfile, OnboardingProgress
from app.deps import WorkspaceContext
from app.errors import AppError
from app.schemas.onboarding import (
    REQUIRED_STEPS,
    STEP_IDS,
    STEP_LABELS,
    ExperienceStep,
    GoalStep,
    IndustriesStep,
    OnboardingState,
    OnboardingStepInput,
    PortfolioStep,
    ProfileDraft,
    RoleStep,
    ServicesStep,
    SkillsStep,
    StepStatus,
    TargetClientsStep,
    TimezoneStep,
    ToneStep,
)


def get_or_create_rows(
    db: DbSession, ctx: WorkspaceContext
) -> tuple[OnboardingProgress, FreelancerProfile]:
    progress = db.scalar(
        select(OnboardingProgress).where(OnboardingProgress.workspace_id == ctx.workspace_id)
    )
    if progress is None:
        progress = OnboardingProgress(workspace_id=ctx.workspace_id, completed_steps=[])
        db.add(progress)
    profile = db.scalar(
        select(FreelancerProfile).where(FreelancerProfile.workspace_id == ctx.workspace_id)
    )
    if profile is None:
        profile = FreelancerProfile(workspace_id=ctx.workspace_id)
        db.add(profile)
    db.flush()
    return progress, profile


def _next_step(completed: list[str]) -> str:
    for step in STEP_IDS:
        if step not in completed:
            return step
    return STEP_IDS[-1]


def build_state(
    ctx: WorkspaceContext, progress: OnboardingProgress, profile: FreelancerProfile
) -> OnboardingState:
    completed = list(progress.completed_steps)
    return OnboardingState(
        status=progress.status,
        current_step=_next_step(completed),
        steps=[
            StepStatus(
                id=s, label=STEP_LABELS[s], required=s in REQUIRED_STEPS, completed=s in completed
            )
            for s in STEP_IDS
        ],
        completed_count=len([s for s in STEP_IDS if s in completed]),
        total_count=len(STEP_IDS),
        profile=ProfileDraft(
            role_title=profile.role_title,
            summary=profile.summary,
            services=list(profile.services),
            skills=list(profile.skills),
            target_clients=profile.target_clients,
            industries=list(profile.industries),
            portfolio_urls=list(profile.portfolio_urls),
            years_experience=profile.years_experience,
            experience_summary=profile.experience_summary,
            tone=profile.tone,
            tone_notes=profile.tone_notes,
            timezone=ctx.workspace.timezone,
            business_goal=profile.business_goal,
            business_goal_notes=profile.business_goal_notes,
        ),
        demo_mode=ctx.workspace.demo_mode,
    )


def apply_step(
    ctx: WorkspaceContext, profile: FreelancerProfile, data: OnboardingStepInput
) -> None:
    match data:
        case RoleStep():
            profile.role_title = data.role_title
            profile.summary = data.summary or None
        case ServicesStep():
            profile.services = data.services
        case SkillsStep():
            profile.skills = data.skills
        case TargetClientsStep():
            profile.target_clients = data.description
        case IndustriesStep():
            profile.industries = data.industries
        case PortfolioStep():
            profile.portfolio_urls = data.urls
        case ExperienceStep():
            profile.years_experience = data.years
            profile.experience_summary = data.summary or None
        case ToneStep():
            profile.tone = data.tone
            profile.tone_notes = data.notes or None
        case TimezoneStep():
            ctx.workspace.timezone = data.timezone
        case GoalStep():
            profile.business_goal = data.goal
            profile.business_goal_notes = data.notes or None


def save_step(db: DbSession, ctx: WorkspaceContext, data: OnboardingStepInput) -> OnboardingState:
    progress, profile = get_or_create_rows(db, ctx)
    apply_step(ctx, profile, data)
    if data.step not in progress.completed_steps:
        progress.completed_steps = [*progress.completed_steps, data.step]
    # Editing after completion keeps the workspace "completed"; otherwise (re)enter in_progress,
    # which is also how a user resumes after skipping.
    if progress.status != "completed":
        progress.status = "in_progress"
    progress.current_step = _next_step(list(progress.completed_steps))
    db.flush()
    return build_state(ctx, progress, profile)


def skip(db: DbSession, ctx: WorkspaceContext) -> OnboardingState:
    progress, profile = get_or_create_rows(db, ctx)
    if progress.status != "completed":
        progress.status = "skipped"
    db.flush()
    return build_state(ctx, progress, profile)


def complete(db: DbSession, ctx: WorkspaceContext) -> OnboardingState:
    progress, profile = get_or_create_rows(db, ctx)
    missing = [s for s in STEP_IDS if s in REQUIRED_STEPS and s not in progress.completed_steps]
    if missing:
        raise AppError(
            409,
            "onboarding_incomplete",
            "Finish the required steps first: " + ", ".join(STEP_LABELS[s] for s in missing) + ".",
            fields={s: "Required" for s in missing},
        )
    progress.status = "completed"
    progress.completed_at = progress.completed_at or utcnow()
    db.flush()
    return build_state(ctx, progress, profile)
