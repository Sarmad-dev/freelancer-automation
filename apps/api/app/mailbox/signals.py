"""Recognising automatic mail that is not a person's reply."""

from __future__ import annotations

import re

_BOUNCE_SENDER = re.compile(
    r"^(?:mailer-daemon|postmaster|mail-daemon|mailerdaemon)(?:[+._-].*)?@", re.I
)
_BOUNCE_SUBJECT = re.compile(
    r"^\s*(?:undeliverable|delivery status notification|mail delivery (?:failed|failure|subsystem)|returned mail|"
    r"failure notice|delivery failure|message not delivered)\b",
    re.I,
)


def is_bounce(from_address: str, subject: str | None) -> bool:
    """A delivery-failure notice from a mail system, judged by the sender and the subject together.

    A person who happens to write 'undeliverable' in a subject is NOT a bounce: both the sender must look like a mail
    system and the subject like a failure notice; a mail-system sender alone is also enough when the subject is typical.
    """
    sender_is_system = bool(_BOUNCE_SENDER.match(from_address))
    subject_is_failure = bool(subject and _BOUNCE_SUBJECT.match(subject))
    return sender_is_system and (subject_is_failure or subject is None or subject.strip() == "")
