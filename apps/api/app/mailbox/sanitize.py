"""Making message bodies safe to store and show.

Email is hostile input. Two rules cover almost everything:

1. **Store only the cleaned form.** The original HTML is never kept. ``clean_html`` allows a short list of formatting tags
   and attributes and nothing else: no scripts, styles, forms, frames, SVG, MathML, ``<base>``/``<meta>``, event handlers,
   inline CSS, or remote content. ``<img>`` and every other embedded resource is removed, which also blocks tracking pixels
   (the UI says "remote images are not loaded"). Links keep only ``http``, ``https`` and ``mailto`` targets and always get
   ``rel="noopener noreferrer nofollow"``.
2. **Show it in a sandbox anyway.** The web app renders the stored HTML inside a sandboxed ``iframe`` with a no-network CSP,
   so a sanitiser bug still cannot run script or load anything.

Text is normalised: control and bidirectional-override characters removed, NULs dropped, length capped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import nh3

from app.ai.untrusted import clean as clean_text
from app.mailbox.mime import html_to_text

SANITIZER_VERSION = "1"
MAX_TEXT_CHARS = 100_000
MAX_HTML_INPUT_CHARS = 400_000
MAX_HTML_STORED_CHARS = 200_000

ALLOWED_TAGS = {
    "a", "b", "blockquote", "br", "code", "div", "em", "h1", "h2", "h3", "h4", "h5", "h6", "hr", "i", "li",
    "ol", "p", "pre", "small", "span", "strong", "sub", "sup", "table", "tbody", "td", "tfoot", "th", "thead",
    "tr", "u", "ul",
}  # fmt: skip
ALLOWED_ATTRIBUTES = {
    "a": {"href", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}
ALLOWED_SCHEMES = {"http", "https", "mailto"}
# Elements whose CONTENT must go too (not just the tag), so a script's source never turns into visible text.
DROP_WITH_CONTENT = {
    "script",
    "style",
    "iframe",
    "object",
    "embed",
    "noscript",
    "template",
    "svg",
    "math",
    "head",
    "title",
    "textarea",
    "select",
    "option",
}
_EMBEDDED = re.compile(r"<\s*(?:img|picture|video|audio|source|link|object|embed|iframe)\b", re.I)


@dataclass(frozen=True)
class StoredBody:
    text: str
    html: str | None
    text_truncated: bool
    images_blocked: bool


def clean_html(html: str) -> str:
    """The allow-listed form of ``html`` (may be empty)."""
    return nh3.clean(
        html[:MAX_HTML_INPUT_CHARS],
        tags=ALLOWED_TAGS,
        clean_content_tags=DROP_WITH_CONTENT,
        attributes=ALLOWED_ATTRIBUTES,
        url_schemes=ALLOWED_SCHEMES,
        link_rel="noopener noreferrer nofollow",
        strip_comments=True,
        generic_attribute_prefixes=set(),
        tag_attribute_values={},
        set_tag_attribute_values={},
    )


def prepare_body(text: str | None, html: str | None) -> StoredBody:
    """Turn a provider's raw text/HTML into what we store. Never raises on malformed input."""
    cleaned_html: str | None = None
    images_blocked = False
    if html:
        images_blocked = bool(_EMBEDDED.search(html[:MAX_HTML_INPUT_CHARS]))
        try:
            candidate = clean_html(html).strip()
        except Exception:  # a parser failure must not lose the message: keep the text only
            candidate = ""
        if candidate and len(candidate) <= MAX_HTML_STORED_CHARS:
            cleaned_html = candidate
    source_text = text if text and text.strip() else (html_to_text(html) if html else "")
    body = clean_text(source_text.replace("\x00", ""), MAX_TEXT_CHARS)
    return StoredBody(
        text=body,
        html=cleaned_html,
        text_truncated=body.endswith("…[truncated]"),
        images_blocked=images_blocked,
    )
