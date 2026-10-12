"""Deterministic, content-only rules shared by the demo AI, the safety overrides and the rule-based fallback.

These are deliberately simple and conservative. They exist so that (a) an opt-out can never be missed because a
model misread it, (b) classification still works when the provider is down, and (c) the demo AI is honest about being
keyword matching.
"""

from __future__ import annotations

import re
import unicodedata

from app.ai.schemas import ClassifyReplyOutput


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).lower()


# An explicit request to stop. Matched on the reply's own words, so quoted history is not what triggers it.
_OPT_OUT = re.compile(
    r"\b(?:unsubscribe|remove me|take me off|stop (?:emailing|contacting|messaging|sending)|"
    r"do not (?:email|contact) me|don'?t (?:email|contact) me|no more emails|opt[- ]?out|"
    r"please stop|never contact me)\b"
)
_OUT_OF_OFFICE = re.compile(
    r"\b(?:out of (?:the )?office|on (?:annual )?leave|on vacation|on holiday|away until|"
    r"auto[- ]?reply|automatic reply|i am currently away|i'?m currently away|will be back on)\b"
)
_REFERRAL = re.compile(
    r"\b(?:reach out to|talk to|speak (?:to|with)|contact|loop in|cc'?ing|copying|introduce you to|"
    r"better person|right person|forwarding (?:this|your)|forwarded (?:this|your))\b"
)
_NOT_NOW = re.compile(
    r"\b(?:not (?:right )?now|bad timing|next quarter|next year|later this year|after the (?:holidays|new year)|"
    r"circle back|revisit|check back|reach out again|in a few months|at the moment we|no budget (?:right|at)|"
    r"not (?:a )?priority (?:right )?now)\b"
)
_OBJECTION = re.compile(
    r"\b(?:too expensive|out of (?:our )?budget|already have|we have (?:an? )?(?:in-house|team|vendor|agency)|"
    r"not interested|no thanks|no thank you|we don'?t need|don'?t need|not a fit|not looking|"
    r"happy with (?:our|the)|already work with)\b"
)
_INTERESTED = re.compile(
    r"\b(?:sounds (?:good|great|interesting)|i'?d love to|i would love to|let'?s (?:talk|chat|schedule|set up|book)|"
    r"interested|available (?:on|for|this|next)|book a (?:call|time)|send (?:me )?(?:over )?(?:your )?(?:proposal|rates|details|portfolio)|"
    r"can we (?:talk|chat|meet|schedule|jump)|happy to (?:chat|talk|meet|jump))\b"
)
_QUESTION = re.compile(
    r"\?|\b(?:how much|what(?:'s| is| are) your|do you (?:offer|have|work|do)|can you (?:tell|share|explain)|"
    r"could you (?:tell|share|explain)|what does|how does|how long)\b"
)


def looks_like_opt_out(text: str) -> bool:
    """True when the reply explicitly asks to stop being contacted."""
    return bool(_OPT_OUT.search(_norm(text)))


def classify_by_rules(subject: str | None, body: str) -> ClassifyReplyOutput:
    """Keyword classification. Order matters: stop requests and auto-replies beat everything else."""
    text = _norm(f"{subject or ''}\n{body}")
    if _OPT_OUT.search(text):
        return ClassifyReplyOutput(
            category="unsubscribe",
            confidence=0.9,
            rationale="The reply asks to stop being contacted.",
        )
    if _OUT_OF_OFFICE.search(text):
        return ClassifyReplyOutput(
            category="out_of_office",
            confidence=0.85,
            rationale="The reply reads like an automatic away message.",
        )
    if _NOT_NOW.search(text) and not _OBJECTION.search(text):
        return ClassifyReplyOutput(
            category="not_now", confidence=0.7, rationale="The reply says the timing is not right."
        )
    if _OBJECTION.search(text):
        return ClassifyReplyOutput(
            category="objection",
            confidence=0.7,
            rationale="The reply gives a reason it may not be a fit.",
        )
    if _INTERESTED.search(text):
        return ClassifyReplyOutput(
            category="interested",
            confidence=0.7,
            rationale="The reply shows interest in talking further.",
        )
    if _REFERRAL.search(text):
        return ClassifyReplyOutput(
            category="referral", confidence=0.6, rationale="The reply points to another person."
        )
    if _QUESTION.search(text):
        return ClassifyReplyOutput(
            category="question", confidence=0.6, rationale="The reply asks a question."
        )
    return ClassifyReplyOutput(
        category="irrelevant", confidence=0.3, rationale="No clear signal was found in the reply."
    )
