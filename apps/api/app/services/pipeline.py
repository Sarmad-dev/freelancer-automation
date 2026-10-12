from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session as DbSession

from app.db.models_crm import PipelineStage
from app.domain import DEFAULT_PIPELINE_STAGES


def ensure_default_stages(db: DbSession, workspace_id: uuid.UUID) -> list[PipelineStage]:
    """Create the default pipeline stages for a workspace. Idempotent: existing keys are left untouched."""
    existing = {
        s.key: s
        for s in db.scalars(select(PipelineStage).where(PipelineStage.workspace_id == workspace_id))
    }
    stages: list[PipelineStage] = []
    for position, (key, name, is_won, is_lost) in enumerate(DEFAULT_PIPELINE_STAGES):
        stage = existing.get(key)
        if stage is None:
            stage = PipelineStage(
                workspace_id=workspace_id,
                key=key,
                name=name,
                position=position,
                is_won=is_won,
                is_lost=is_lost,
            )
            db.add(stage)
        stages.append(stage)
    db.flush()
    return stages
