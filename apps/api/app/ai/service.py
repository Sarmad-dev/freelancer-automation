"""``AiService``: the only thing domain code calls to use a model.

For every task: clean + minimise the input -> render the versioned prompt -> call the provider with a timeout and
bounded retries -> parse and validate the reply strictly -> apply deterministic safety overrides -> meter the call.
It never raises for a provider problem: callers get an ``AiOutcome`` with ``ok=False`` and a stable failure code.
Nothing a model says is executed here; results are suggestions for a person to review.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from app.ai import rules, untrusted, validate
from app.ai.errors import (
    AiError,
    InsufficientContext,
    InvalidOutput,
    PolicyViolation,
    ProviderTimeout,
    ProviderUnavailable,
    RateLimited,
)
from app.ai.prompts import TEMPLATES, PromptTemplate
from app.ai.providers.base import ModelProvider, ProviderRequest
from app.ai.schemas import (
    AiFailure,
    AiMeta,
    AiOutcome,
    AssessLeadFitInput,
    AssessLeadFitOutput,
    ClassifyReplyInput,
    ClassifyReplyOutput,
    DraftOutreachInput,
    DraftOutreachOutput,
    ExtractedFactOut,
    ExtractProfileFactsInput,
    ExtractProfileFactsOutput,
    ExtractProfileFactsResult,
    RecommendNextActionInput,
    RecommendNextActionOutput,
    SummarizeConversationInput,
    SummarizeConversationOutput,
)
from app.db.models_workflow import UsageRecord
from app.ratelimit import RateLimiter
from app.schemas.ai_context import AiContext

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger("freelancer_os.ai")

# Profile fields each task may see. Pricing guidance, business goals and exclusions are never needed to draft.
_FIT_PROFILE = (
    "role_title",
    "summary",
    "services",
    "skills",
    "industries",
    "differentiators",
    "target_clients",
    "excluded_customers",
)
_DRAFT_PROFILE = (
    "role_title",
    "summary",
    "services",
    "skills",
    "industries",
    "differentiators",
    "target_clients",
    "portfolio_urls",
    "experience_summary",
    "years_experience",
    "preferred_cta",
    "tone",
    "tone_notes",
)
_PLACEHOLDER = re.compile(r"\[[A-Z][A-Za-z ]{2,28}\]|\{\{[^}]{1,40}\}\}")
_FENCE = re.compile(r"^```(?:json)?\s*\n(.*)\n```\s*$", re.S)


@dataclass(frozen=True)
class AiLimits:
    timeout_seconds: float = 20.0
    max_attempts: int = 2
    total_budget_seconds: float = 45.0
    rate_limit_per_minute: int = 30
    input_cost_micros_per_1k: int | None = None
    output_cost_micros_per_1k: int | None = None

    @classmethod
    def from_settings(cls, s: Settings) -> AiLimits:
        return cls(
            timeout_seconds=s.ai_timeout_seconds,
            max_attempts=s.ai_max_attempts,
            total_budget_seconds=s.ai_total_budget_seconds,
            rate_limit_per_minute=s.ai_rate_limit_per_minute,
            input_cost_micros_per_1k=s.ai_input_cost_micros_per_1k,
            output_cost_micros_per_1k=s.ai_output_cost_micros_per_1k,
        )


@dataclass
class _Spec:
    template: PromptTemplate
    payload: dict[str, Any]
    context: dict[str, Any]
    untrusted_parts: dict[str, str]
    # Turns a parsed reply into the final data (raising InvalidOutput/PolicyViolation if it is unacceptable).
    finish: Callable[[Any, list[str]], Any]
    warnings: list[str] = field(default_factory=list)
    context_hash: str | None = None
    fallback: Callable[[], Any] | None = None


def _prep(text: str | None, limit: int, warnings: list[str], label: str) -> str | None:
    if text is None:
        return None
    cleaned = untrusted.clean(text, limit)
    if cleaned.endswith("…[truncated]"):
        warnings.append(f"{label}_truncated")
    return untrusted.minimise(cleaned)


def _flatten(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, list | tuple):
        return " ".join(_flatten(v) for v in value)
    return "" if value is None else str(value)


def _profile_subset(context: AiContext, names: tuple[str, ...]) -> dict[str, Any]:
    return {k: v for k, v in context.profile.items() if k in names}


class AiService:
    def __init__(
        self,
        provider: ModelProvider,
        limits: AiLimits | None = None,
        *,
        workspace_id: uuid.UUID,
        limiter: RateLimiter | None = None,
        session_factory: sessionmaker[Session] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        backoff_seconds: float = 0.5,
        meter: bool = True,
    ) -> None:
        self.provider = provider
        self.limits = limits or AiLimits()
        self.workspace_id = workspace_id
        self._limiter = limiter
        self._session_factory = session_factory
        self._sleep = sleep
        self._now = monotonic
        self._backoff = backoff_seconds
        self._meter = meter

    # ------------------------------------------------------------------ tasks

    def classify_reply(self, inp: ClassifyReplyInput) -> AiOutcome[ClassifyReplyOutput]:
        warnings: list[str] = []
        subject = _prep(inp.subject, 500, warnings, "subject")
        body = _prep(inp.body, untrusted.MAX_UNTRUSTED_CHARS, warnings, "body") or ""
        previous = _prep(inp.previous_outbound, 4_000, warnings, "previous_message")
        signals = untrusted.injection_signals(f"{subject or ''}\n{body}")
        if signals:
            warnings.append("injection_suspected")
        parts = {"email_subject": subject or "(none)", "email_reply": body}
        if previous:
            parts["our_previous_message"] = previous

        reply_text = f"{subject or ''}\n{body}"

        def finish(out: ClassifyReplyOutput, w: list[str]) -> ClassifyReplyOutput:
            # Quotes must really be in the reply; a quote the model made up is dropped, never shown.
            quotes = [q for q in out.evidence if validate.contained_in(q, reply_text)]
            if len(quotes) != len(out.evidence):
                w.append("evidence_dropped")
            out = out.model_copy(update={"evidence": quotes})
            # An explicit request to stop is never allowed to be missed or argued away.
            if out.category != "unsubscribe" and rules.looks_like_opt_out(reply_text):
                w.append("opt_out_detected_by_rules")
                forced = rules.classify_by_rules(subject, body)
                return ClassifyReplyOutput(
                    category="unsubscribe",
                    confidence=max(out.confidence, 0.8),
                    rationale="The reply asks to stop being contacted.",
                    evidence=forced.evidence if forced.category == "unsubscribe" else [],
                )
            if signals and out.confidence > 0.6:
                w.append("confidence_capped")
                return out.model_copy(update={"confidence": 0.6})
            return out

        def fallback() -> ClassifyReplyOutput:
            out = rules.classify_by_rules(subject, body)
            return out.model_copy(update={"confidence": min(out.confidence, 0.6)})

        return self._run(
            _Spec(
                template=TEMPLATES["classify_reply"],
                payload={"input": {"subject": subject, "body": body}},
                context={},
                untrusted_parts=parts,
                finish=finish,
                warnings=warnings,
                fallback=fallback,
            )
        )

    def assess_lead_fit(
        self, inp: AssessLeadFitInput, context: AiContext
    ) -> AiOutcome[AssessLeadFitOutput]:
        warnings: list[str] = []
        lead = {k: v for k, v in inp.lead.model_dump().items() if v}
        if "notes" in lead:
            lead["notes"] = _prep(lead["notes"], 4_000, warnings, "notes")
        profile = _profile_subset(context, _FIT_PROFILE)
        facts = [
            {"id": str(f.id), "kind": f.kind, "title": f.title, "content": f.content}
            for f in context.facts
        ]
        if untrusted.injection_signals(_flatten(lead)):
            warnings.append("injection_suspected")
        citable = set(lead) | {f"profile.{k}" for k in profile}
        allowed = _flatten(lead) + " " + _flatten(profile) + " " + _flatten(facts)

        def finish(out: AssessLeadFitOutput, w: list[str]) -> AssessLeadFitOutput:
            if out.assessment != "unknown" and not out.reasons:
                raise InvalidOutput("no_reasons")
            for reason in out.reasons:
                if reason.evidence_field not in citable:
                    raise InvalidOutput("unknown_evidence")
                if validate.unsupported_claims(
                    reason.statement, allowed + f" {inp.rule_score or ''}"
                ):
                    raise PolicyViolation("unsupported_claim")
            return out

        return self._run(
            _Spec(
                template=TEMPLATES["assess_lead_fit"],
                payload={"input": {"lead": lead}, "context": {"profile": profile, "facts": facts}},
                context={
                    "freelancer": profile,
                    "approved_facts": facts,
                    "rule_based_score": inp.rule_score,
                    "citable_fields": sorted(citable),
                },
                untrusted_parts={"lead": json.dumps(lead, sort_keys=True)},
                finish=finish,
                warnings=warnings,
                context_hash=context.context_hash,
            )
        )

    def extract_profile_facts(
        self, inp: ExtractProfileFactsInput
    ) -> AiOutcome[ExtractProfileFactsResult]:
        warnings: list[str] = []
        text = _prep(inp.text, 20_000, warnings, "document") or ""
        if untrusted.injection_signals(text):
            warnings.append("injection_suspected")

        def finish(out: ExtractProfileFactsOutput, w: list[str]) -> ExtractProfileFactsResult:
            kept: list[ExtractedFactOut] = []
            seen: set[str] = set()
            dropped = 0
            for fact in out.facts:
                key = validate.fold(fact.content)
                supported = (
                    validate.contained_in(fact.source_quote, text)
                    and not validate.unsupported_claims(
                        f"{fact.title}\n{fact.content}", fact.source_quote
                    )
                    and not untrusted.injection_signals(f"{fact.content}\n{fact.source_quote}")
                    and key not in seen
                )
                if supported:
                    seen.add(key)
                    kept.append(ExtractedFactOut(**fact.model_dump()))
                else:
                    dropped += 1
            if dropped:
                w.append(f"dropped_unsupported_facts:{dropped}")
            return ExtractProfileFactsResult(facts=kept, dropped=dropped)

        return self._run(
            _Spec(
                template=TEMPLATES["extract_profile_facts"],
                payload={"input": {"text": text}},
                context={"source": inp.source_label},
                untrusted_parts={"document": text},
                finish=finish,
                warnings=warnings,
            )
        )

    def draft_outreach(
        self, inp: DraftOutreachInput, context: AiContext
    ) -> AiOutcome[DraftOutreachOutput]:
        warnings: list[str] = []
        profile = _profile_subset(context, _DRAFT_PROFILE)
        facts = [
            {"id": str(f.id), "kind": f.kind, "title": f.title, "content": f.content}
            for f in context.facts
        ]
        if not facts and not profile.get("summary") and not profile.get("services"):
            return self._refused(
                "draft_outreach",
                InsufficientContext(
                    ["approved facts", "a profile summary or services"]
                    + [m.label for m in context.missing if m.field in ("summary", "services")]
                ),
                context.context_hash,
            )
        lead = {k: v for k, v in inp.lead.model_dump().items() if v}
        if "notes" in lead:
            lead["notes"] = _prep(lead["notes"], 2_000, warnings, "notes")
        if untrusted.injection_signals(_flatten(lead)):
            warnings.append("injection_suspected")
        first_name = (inp.recipient_first_name or "").strip() or None
        ids = {f["id"] for f in facts}
        reply_parts: dict[str, str] = {}
        reply_text = ""
        if inp.reply_to is not None:
            answered = _prep(inp.reply_to.message, 8_000, warnings, "message") or ""
            earlier = _prep(inp.reply_to.previous_message, 4_000, warnings, "previous_message")
            suspicious = bool(untrusted.injection_signals(answered))
            if suspicious:
                warnings.append("injection_suspected")
            reply_parts["message_being_answered"] = answered
            if earlier:
                reply_parts["our_previous_message"] = earlier
            # A draft may repeat a time or figure the other person wrote, but never when their message is trying to steer us:
            # then only our own approved facts count as support, so an attacker cannot smuggle a commitment into the reply.
            reply_text = (
                "" if suspicious else f"{inp.reply_to.subject or ''} {answered} {earlier or ''}"
            )
        # A reply may repeat what the other person wrote (a time they proposed, a figure they quoted), nothing else new.
        allowed = " ".join(
            [
                _flatten(profile),
                _flatten(facts),
                _flatten(lead),
                inp.goal,
                first_name or "",
                reply_text,
            ]
        )

        def finish(out: DraftOutreachOutput, w: list[str]) -> DraftOutreachOutput:
            if any(str(i) not in ids for i in out.facts_used):
                raise InvalidOutput("unknown_fact_id")
            if "\n" in out.subject or "\r" in out.subject:
                raise InvalidOutput("subject_newline")
            problems = validate.unsupported_claims(f"{out.subject}\n{out.body}", allowed)
            if problems:
                raise PolicyViolation("unsupported_" + "_".join(sorted(set(problems))))
            review = list(out.needs_review)
            if _PLACEHOLDER.search(out.subject + out.body):
                w.append("placeholder_in_draft")
                review.append("The draft has a placeholder to fill in before sending.")
            if facts and not out.facts_used:
                w.append("no_facts_cited")
            return out.model_copy(update={"needs_review": review[:8]})

        return self._run(
            _Spec(
                template=TEMPLATES["draft_outreach"],
                payload={
                    "input": {
                        "lead": lead,
                        "recipient_first_name": first_name,
                        "goal": inp.goal,
                        "reply_to": (
                            {
                                "classification": inp.reply_to.classification,
                                "message": reply_parts.get("message_being_answered", ""),
                            }
                            if inp.reply_to is not None
                            else None
                        ),
                    },
                    "context": {"profile": profile, "facts": facts},
                },
                context={
                    "mode": "reply" if inp.reply_to is not None else "first_outreach",
                    "freelancer": profile,
                    "approved_facts": facts,
                    "recipient_first_name": first_name,
                    "goal": inp.goal,
                    "their_message_classified_as": inp.reply_to.classification
                    if inp.reply_to
                    else None,
                },
                untrusted_parts={"lead": json.dumps(lead, sort_keys=True), **reply_parts},
                finish=finish,
                warnings=warnings,
                context_hash=context.context_hash,
            )
        )

    def summarize_conversation(
        self, inp: SummarizeConversationInput
    ) -> AiOutcome[SummarizeConversationOutput]:
        warnings: list[str] = []
        messages = []
        for m in inp.messages:
            messages.append(
                {
                    "direction": m.direction,
                    "subject": _prep(m.subject, 500, warnings, "subject"),
                    "text": _prep(m.text, 4_000, warnings, "message") or "",
                }
            )
        parts = {
            f"message_{i + 1}_{m['direction']}": f"Subject: {m['subject'] or '(none)'}\n{m['text']}"
            for i, m in enumerate(messages)
        }
        if untrusted.injection_signals(_flatten(messages)):
            warnings.append("injection_suspected")
        allowed = _flatten(messages) + f" {len(messages)}"

        def finish(out: SummarizeConversationOutput, w: list[str]) -> SummarizeConversationOutput:
            text = " ".join([out.summary, *out.key_points, *out.open_questions])
            if validate.unsupported_claims(text, allowed):
                raise PolicyViolation("unsupported_claim")
            return out

        return self._run(
            _Spec(
                template=TEMPLATES["summarize_conversation"],
                payload={"input": {"messages": messages}},
                context={"message_count": len(messages)},
                untrusted_parts=parts,
                finish=finish,
                warnings=warnings,
            )
        )

    def recommend_next_action(
        self, inp: RecommendNextActionInput
    ) -> AiOutcome[RecommendNextActionOutput]:
        warnings: list[str] = []
        summary = _prep(inp.conversation_summary, 1_500, warnings, "summary")
        if summary and untrusted.injection_signals(summary):
            warnings.append("injection_suspected")
        data = inp.model_dump(exclude={"conversation_summary"})
        parts = {"conversation_summary": summary} if summary else {}

        def finish(out: RecommendNextActionOutput, w: list[str]) -> RecommendNextActionOutput:
            contact = out.action in ("reply", "create_follow_up_task")
            if inp.opted_out and contact:
                w.append("opt_out_respected")
                return RecommendNextActionOutput(
                    action="no_action", rationale="They asked not to be contacted.", in_days=None
                )
            if inp.last_classification == "unsubscribe" and contact:
                w.append("opt_out_respected")
                return RecommendNextActionOutput(
                    action="pause_outreach",
                    rationale="They asked to stop; pause outreach and record the opt-out.",
                    in_days=None,
                )
            if out.action not in ("wait", "create_follow_up_task") and out.in_days is not None:
                return out.model_copy(update={"in_days": None})
            return out

        return self._run(
            _Spec(
                template=TEMPLATES["recommend_next_action"],
                payload={"input": {**data, "conversation_summary": summary}},
                context=data,
                untrusted_parts=parts,
                finish=finish,
                warnings=warnings,
            )
        )

    # ------------------------------------------------------------------ engine

    def _meta(self, spec_template: PromptTemplate, **kw: Any) -> AiMeta:
        return AiMeta(
            task=spec_template.task,
            provider=kw.pop("provider", self.provider.name),
            model=kw.pop("model", None) or self.provider.model_for(spec_template.tier) or None,
            is_mock=kw.pop("is_mock", self.provider.is_mock),
            prompt_version=spec_template.version,
            **kw,
        )

    def _refused(self, task: str, error: AiError, context_hash: str | None) -> AiOutcome[Any]:
        """A request we decline before any model is involved (nothing is sent, nothing is metered)."""
        template = TEMPLATES[task]
        return AiOutcome(
            ok=False,
            failure=_failure(error),
            meta=self._meta(
                template,
                latency_ms=0,
                attempts=0,
                context_hash=context_hash,
                correlation_id=uuid.uuid4().hex[:16],
            ),
        )

    def _run(self, spec: _Spec) -> AiOutcome[Any]:
        template = spec.template
        correlation_id = uuid.uuid4().hex[:16]
        started = self._now()
        warnings = list(spec.warnings)
        tokens_in: int | None = None
        tokens_out: int | None = None
        model_name: str | None = None
        attempts = 0
        error: AiError | None = None
        result: Any = None

        if self._limiter is not None:
            decision = self._limiter.hit(
                f"ai:{self.workspace_id}", self.limits.rate_limit_per_minute, 60
            )
            if not decision.allowed:
                error = RateLimited(retry_after=decision.retry_after)

        while error is None or (error.retryable and attempts > 0):
            if attempts >= self.limits.max_attempts:
                break
            remaining = self.limits.total_budget_seconds - (self._now() - started)
            if remaining <= 0:
                error = error or ProviderTimeout()
                break
            if attempts > 0:
                assert error is not None
                wait = min(error.retry_after or self._backoff * 2 ** (attempts - 1), 5.0, remaining)
                self._sleep(wait)
            attempts += 1
            system, user, canary = template.render(
                context=spec.context, untrusted_parts=spec.untrusted_parts
            )
            request = ProviderRequest(
                task=template.task,
                tier=template.tier,
                system=system,
                user=user,
                payload=spec.payload,
                timeout_seconds=max(0.1, min(self.limits.timeout_seconds, remaining)),
                max_output_tokens=template.max_output_tokens,
                correlation_id=correlation_id,
            )
            try:
                response = self.provider.complete(request)
                model_name = response.model
                tokens_in = _add(tokens_in, response.input_tokens)
                tokens_out = _add(tokens_out, response.output_tokens)
                parsed = _parse(template.output, response.text)
                validate.reject_leaks(response.text, system, canary)
                attempt_warnings = list(spec.warnings)
                result = spec.finish(parsed, attempt_warnings)
                warnings = attempt_warnings
                error = None
                break
            except AiError as exc:
                error = exc
            except Exception as exc:  # a vendor SDK or bug: fail safely, log the type only
                logger.warning(
                    "ai_unexpected_error type=%s task=%s", type(exc).__name__, template.task
                )
                error = ProviderUnavailable()

        latency_ms = int((self._now() - started) * 1000)
        meta = self._meta(
            template,
            model=model_name,
            latency_ms=latency_ms,
            attempts=attempts,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            context_hash=spec.context_hash,
            correlation_id=correlation_id,
        )
        self._record(meta, error)

        if error is None:
            return AiOutcome(ok=True, data=result, meta=meta, warnings=warnings)

        if spec.fallback is not None and not isinstance(error, RateLimited):
            warnings.append("rules_fallback_used")
            fallback_meta = meta.model_copy(
                update={
                    "source": "rules_fallback",
                    "provider": "rules",
                    "is_mock": False,
                    "model": None,
                }
            )
            return AiOutcome(ok=True, data=spec.fallback(), meta=fallback_meta, warnings=warnings)
        return AiOutcome(ok=False, failure=_failure(error), meta=meta, warnings=warnings)

    # ------------------------------------------------------------------ metering

    def _record(self, meta: AiMeta, error: AiError | None) -> None:
        """Content-free usage row + log line. A metering failure never breaks the user's request."""
        reason = getattr(error, "reason", None)
        code = None if error is None else error.code
        logger.info(
            "ai_call task=%s provider=%s model=%s ok=%s error=%s reason=%s attempts=%s latency_ms=%s "
            "in_tokens=%s out_tokens=%s mock=%s prompt=%s correlation_id=%s workspace=%s",
            meta.task, meta.provider, meta.model, error is None, code, reason, meta.attempts,
            meta.latency_ms, meta.input_tokens, meta.output_tokens, meta.is_mock,
            meta.prompt_version, meta.correlation_id, self.workspace_id,
        )  # fmt: skip
        if not self._meter:
            return
        try:
            from app.db.session import get_sessionmaker

            factory = self._session_factory or get_sessionmaker()
            with factory() as session:
                session.add(
                    UsageRecord(
                        workspace_id=self.workspace_id,
                        kind="ai",
                        provider=meta.provider[:40],
                        model=meta.model[:80] if meta.model else None,
                        task_type=meta.task,
                        input_tokens=meta.input_tokens,
                        output_tokens=meta.output_tokens,
                        estimated_cost_micros=self._cost(meta),
                        latency_ms=meta.latency_ms,
                        success=error is None,
                        is_mock=meta.is_mock,
                        correlation_id=meta.correlation_id,
                        error_code=_error_code(code, reason),
                        prompt_version=meta.prompt_version,
                    )
                )
                session.commit()
        except Exception as exc:
            logger.warning("ai_usage_not_recorded type=%s", type(exc).__name__)

    def _cost(self, meta: AiMeta) -> int | None:
        if meta.is_mock:
            return 0
        lim = self.limits
        if lim.input_cost_micros_per_1k is None or lim.output_cost_micros_per_1k is None:
            return None
        if meta.input_tokens is None or meta.output_tokens is None:
            return None
        return (
            meta.input_tokens * lim.input_cost_micros_per_1k
            + meta.output_tokens * lim.output_cost_micros_per_1k
        ) // 1000


def _error_code(code: str | None, reason: str | None) -> str | None:
    if code is None:
        return None
    return (f"{code}:{reason}" if reason else code)[:40]


def _add(total: int | None, new: int | None) -> int | None:
    return total if new is None else (total or 0) + new


def _parse[M: BaseModel](model: type[M], text: str) -> M:
    """Strict JSON -> model. One ```json fence is tolerated (formatting only); anything else is rejected."""
    body = text.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group(1).strip()
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise InvalidOutput("not_json") from exc
    if not isinstance(data, dict):
        raise InvalidOutput("not_object")
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise InvalidOutput("schema") from exc


def _failure(error: AiError) -> AiFailure:
    return AiFailure(
        code=error.code,
        message=error.user_message,
        retryable=error.retryable and not isinstance(error, InsufficientContext),
        retry_after=error.retry_after,
        missing=list(getattr(error, "missing", [])),
    )
