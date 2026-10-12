"""Allowed values for status-like columns, shared by ORM check constraints, schemas and tests.

Stored as plain strings with CHECK constraints (portable across PostgreSQL and SQLite, and cheap to
extend with a migration) rather than native database enums.
"""

from __future__ import annotations

MEMBERSHIP_ROLES = ("owner", "admin", "member")

KNOWLEDGE_KINDS = ("fact", "service", "case_study", "portfolio", "pricing", "other")
KNOWLEDGE_SOURCES = ("manual", "upload", "extracted")
# Review lifecycle. Whether an approved item is *in use* is a separate switch (``is_enabled``), so turning an
# item off and on again never loses its approval.
KNOWLEDGE_STATUSES = ("draft", "pending_review", "approved", "rejected")
PROFILE_TONES = ("professional", "friendly", "direct", "warm", "concise", "formal")

LEAD_STATUSES = ("new", "contacted", "replied", "qualified", "nurturing", "won", "lost")
ACTIVITY_KINDS = ("note", "email", "call", "meeting", "stage_change", "task", "system")
TASK_STATUSES = ("open", "done", "dismissed")
TASK_PRIORITIES = ("low", "normal", "high")
OPPORTUNITY_STATUSES = ("open", "won", "lost")

PROVIDERS = ("gmail", "outlook", "demo")
CONNECTION_STATUSES = ("connected", "demo", "needs_reauth", "disconnected", "error")
MESSAGE_DIRECTIONS = ("inbound", "outbound")
MESSAGE_DELIVERY_STATES = ("demo", "queued", "sent", "failed", "unknown")
CONVERSATION_STATUSES = ("open", "archived")
REPLY_CATEGORIES = (
    "interested",
    "question",
    "objection",
    "not_now",
    "referral",
    "out_of_office",
    "unsubscribe",
    "irrelevant",
)
DRAFT_STATUSES = ("draft", "pending_approval", "approved", "rejected", "sent", "discarded")
DRAFT_AUTHORS = ("user", "ai")
SUPPRESSION_REASONS = ("unsubscribe", "bounce", "complaint", "manual", "replied_stop")

WORKFLOW_STATUSES = ("draft", "active", "paused", "archived")
WORKFLOW_MODES = ("test", "live")
RUN_STATUSES = (
    "queued",
    "running",
    "waiting_approval",
    "waiting_delay",
    "succeeded",
    "failed",
    "cancelled",
)
STEP_STATUSES = ("pending", "running", "succeeded", "failed", "skipped", "waiting", "cancelled")
APPROVAL_STATUSES = ("pending", "approved", "rejected", "expired", "cancelled", "invalidated")

DEFAULT_PIPELINE_STAGES: tuple[tuple[str, str, bool, bool], ...] = (
    # (key, name, is_won, is_lost) - order defines position
    ("new", "New", False, False),
    ("contacted", "Contacted", False, False),
    ("replied", "Replied", False, False),
    ("qualified", "Qualified", False, False),
    ("meeting", "Meeting", False, False),
    ("proposal", "Proposal", False, False),
    ("won", "Won", True, False),
    ("lost", "Lost", False, True),
)
