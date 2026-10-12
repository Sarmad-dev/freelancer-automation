"""Opportunity (deal) and pipeline-board schemas (MVP Prompt 7)."""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

from app.schemas.crm import PipelineStageOut
from app.schemas.text import OptLine300, bounded

_CURRENCY = re.compile(r"^[A-Za-z]{3}$")


def _currency(value: str) -> str:
    cleaned = value.strip()
    if not _CURRENCY.match(cleaned):
        raise ValueError("Use a three-letter currency code such as USD or EUR.")
    return cleaned.upper()


Currency = Annotated[str, AfterValidator(_currency)]
Money = Annotated[Decimal, Field(ge=0, max_digits=14, decimal_places=2)]
Probability = Annotated[int, Field(ge=0, le=100)]
Title = Annotated[str, bounded(1, 200)]


class OpportunityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: uuid.UUID
    title: Title | None = Field(default=None, description="Defaults to the lead's title.")
    stage_id: uuid.UUID | None = Field(
        default=None,
        description="An open stage. Defaults to the lead's stage, else the first stage.",
    )
    value_amount: Money | None = None
    currency: Currency = "USD"
    probability: Probability | None = None
    expected_close_date: date | None = None
    next_action: OptLine300 = None


class OpportunityPatch(BaseModel):
    """PATCH semantics: omitted = unchanged, null clears an optional field. Stage and status change only through
    the move/reopen actions so every change is checked and written to the timeline."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    value_amount: Money | None = None
    currency: Currency | None = None
    probability: Probability | None = None
    expected_close_date: date | None = None
    next_action: OptLine300 = None
    loss_reason: OptLine300 = None


class OpportunityMove(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: uuid.UUID
    expected_stage_id: uuid.UUID | None = Field(
        default=None,
        description="The stage the client believes the deal is in. A mismatch is a 409, so a stale board "
        "can't silently overwrite someone else's move.",
    )
    loss_reason: OptLine300 = Field(
        default=None, description="Why the deal was lost (when moving to a lost stage)."
    )


class OpportunityReopen(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage_id: uuid.UUID


class OpportunityLeadRef(BaseModel):
    id: uuid.UUID
    title: str
    company_name: str | None


class OpportunityOut(BaseModel):
    id: uuid.UUID
    lead: OpportunityLeadRef
    stage: PipelineStageOut
    status: str
    title: str
    value_amount: Decimal | None
    currency: str
    probability: int | None
    weighted_value: Decimal | None = Field(
        description="value x probability, only when both are set and the deal is open."
    )
    expected_close_date: date | None
    next_action: str | None
    loss_reason: str | None
    closed_at: datetime | None
    owner_user_id: uuid.UUID | None
    is_sample: bool
    open_tasks: int
    created_at: datetime
    updated_at: datetime


class MoneyTotal(BaseModel):
    currency: str
    amount: Decimal = Field(
        description="Sum of deal values in this currency (currencies are never mixed)."
    )
    weighted: Decimal | None = Field(
        description="Sum of value x probability; null for won/lost columns."
    )


class BoardColumn(BaseModel):
    stage: PipelineStageOut
    count: int
    unvalued: int = Field(description="Deals in this column that have no value yet.")
    totals: list[MoneyTotal]
    items: list[OpportunityOut]


class PipelineBoard(BaseModel):
    columns: list[BoardColumn]
    per_column_limit: int
    generated_at: datetime
