from __future__ import annotations

import pytest

from app.schemas.text import clean_source_ref, multi_line, single_line, strip_invisible

RLO, ZWSP, BOM, WORD_JOINER, ZWJ, ZWNJ = (
    chr(c) for c in (0x202E, 0x200B, 0xFEFF, 0x2060, 0x200D, 0x200C)
)


def test_invisible_and_bidi_characters_are_removed() -> None:
    assert strip_invisible(f"a{ZWSP}b{RLO}c{BOM}d{WORD_JOINER}e") == "abcde"
    assert single_line(f"  Hid{ZWSP}den   {RLO}text ") == "Hidden text"
    assert multi_line(f"Line{ZWSP} one\nLine two{BOM}") == "Line one\nLine two"


def test_joiners_needed_by_emoji_and_scripts_are_kept() -> None:
    family = f"\U0001f468{ZWJ}\U0001f469{ZWJ}\U0001f467"
    assert single_line(family) == family
    assert single_line(f"\u0915\u094d{ZWNJ}\u0937") == f"\u0915\u094d{ZWNJ}\u0937"


def test_control_characters_are_rejected_not_silently_dropped() -> None:
    with pytest.raises(ValueError, match="invalid characters"):
        single_line("a\x00b")
    with pytest.raises(ValueError):
        multi_line("a\x1bb")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Resume 2026.pdf", "Resume 2026.pdf"),
        ("Notes: kickoff call", "Notes: kickoff call"),
        ("  Spaced   label  ", "Spaced label"),
        ("https://Example.com/About", "https://example.com/About"),
    ],
)
def test_valid_source_references(raw: str, expected: str) -> None:
    assert clean_source_ref(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,x",
        "vbscript:x",
        "file:///etc/passwd",
        "ftp://x.example.com",
        "mailto:a@b.example",
        "x://y",
        "http://localhost",
        "https://u:p@example.com",
        "",
        "   ",
        "a" * 501,
        f"java{ZWSP}script:alert(1)",
    ],
)
def test_unsafe_source_references_are_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        clean_source_ref(raw)
