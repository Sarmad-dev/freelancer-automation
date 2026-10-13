"""Deterministic, content-only rules shared by the demo AI, the safety overrides and the rule-based fallback.

These are deliberately simple and conservative. They exist so that (a) an opt-out can never be missed because a
model misread it, (b) classification still works when the provider is down, and (c) the demo AI is honest about being
keyword matching.
"""

from __future__ import annotations

import re
import unicodedata

from app.ai.schemas import ClassifyReplyOutput, ReplyCategory


def _flat(text: str) -> str:
    """NFKC-normalised with whitespace collapsed; case is kept so quotes can be shown as written."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


# An explicit request to stop. Matched on the reply's own words, so quoted history is not what triggers it.
_OPT_OUT = re.compile(
    r"\b(?:unsubscribe|remove me|take me off|stop (?:emailing|contacting|messaging|sending)|"
    r"do not (?:email|contact) me|don'?t (?:email|contact) me|no more emails|opt[- ]?out|"
    r"please stop|never contact me)\b",
    re.I,
)
_OUT_OF_OFFICE = re.compile(
    r"\b(?:out of (?:the )?office|on (?:annual )?leave|on vacation|on holiday|away until|"
    r"auto[- ]?reply|automatic reply|i am currently away|i'?m currently away|will be back on)\b",
    re.I,
)
_REFERRAL = re.compile(
    r"\b(?:reach out to|talk to|speak (?:to|with)|contact|loop in|cc'?ing|copying|introduce you to|"
    r"better person|right person|forwarding (?:this|your)|forwarded (?:this|your))\b",
    re.I,
)
_NOT_NOW = re.compile(
    r"\b(?:not (?:right )?now|bad timing|next quarter|next year|later this year|after the (?:holidays|new year)|"
    r"circle back|revisit|check back|reach out again|in a few months|at the moment we|no budget (?:right|at)|"
    r"not (?:a )?priority (?:right )?now)\b",
    re.I,
)
_OBJECTION = re.compile(
    r"\b(?:too expensive|out of (?:our )?budget|already have|we have (?:an? )?(?:in-house|team|vendor|agency)|"
    r"not interested|no thanks|no thank you|we don'?t need|don'?t need|not a fit|not looking|"
    r"happy with (?:our|the)|already work with)\b",
    re.I,
)
_INTERESTED = re.compile(
    r"\b(?:sounds (?:good|great|interesting)|i'?d love to|i would love to|let'?s (?:talk|chat|schedule|set up|book)|"
    r"interested|available (?:on|for|this|next)|book a (?:call|time)|send (?:me )?(?:over )?(?:your )?(?:proposal|rates|details|portfolio)|"
    r"can we (?:talk|chat|meet|schedule|jump)|happy to (?:chat|talk|meet|jump))\b",
    re.I,
)
_QUESTION = re.compile(
    r"\?|\b(?:how much|what(?:'s| is| are) your|do you (?:offer|have|work|do)|can you (?:tell|share|explain)|"
    r"could you (?:tell|share|explain)|what does|how does|how long)\b",
    re.I,
)


def looks_like_opt_out(text: str) -> bool:
    """True when the reply explicitly asks to stop being contacted."""
    return bool(_OPT_OUT.search(_flat(text)))


def _evidence(pattern: re.Pattern[str], text: str) -> list[str]:
    """The matched words with a little context, as an exact slice of ``text`` (so it can be shown as a quote)."""
    match = pattern.search(text)
    if match is None:
        return []
    start, end = max(0, match.start() - 30), min(len(text), match.end() + 30)
    return [text[start:end].strip()[:200]]


def _result(
    category: ReplyCategory, confidence: float, rationale: str, pattern: re.Pattern[str], text: str
) -> ClassifyReplyOutput:
    return ClassifyReplyOutput(
        category=category,
        confidence=confidence,
        rationale=rationale,
        evidence=_evidence(pattern, text),
    )


def classify_by_rules(subject: str | None, body: str) -> ClassifyReplyOutput:
    """Keyword classification. Order matters: stop requests and auto-replies beat everything else."""
    text = _flat(f"{subject or ''}\n{body}")
    if _OPT_OUT.search(text):
        return _result(
            "unsubscribe", 0.9, "The reply asks to stop being contacted.", _OPT_OUT, text
        )
    if _OUT_OF_OFFICE.search(text):
        return _result(
            "out_of_office",
            0.85,
            "The reply reads like an automatic away message.",
            _OUT_OF_OFFICE,
            text,
        )
    if _NOT_NOW.search(text) and not _OBJECTION.search(text):
        return _result("not_now", 0.7, "The reply says the timing is not right.", _NOT_NOW, text)
    if _OBJECTION.search(text):
        return _result(
            "objection", 0.7, "The reply gives a reason it may not be a fit.", _OBJECTION, text
        )
    if _INTERESTED.search(text):
        return _result(
            "interested", 0.7, "The reply shows interest in talking further.", _INTERESTED, text
        )
    if _REFERRAL.search(text):
        return _result("referral", 0.6, "The reply points to another person.", _REFERRAL, text)
    if _QUESTION.search(text):
        return _result("question", 0.6, "The reply asks a question.", _QUESTION, text)
    return ClassifyReplyOutput(
        category="irrelevant", confidence=0.3, rationale="No clear signal was found in the reply."
    )
