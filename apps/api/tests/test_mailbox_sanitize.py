"""Email bodies are hostile input: only a short list of formatting survives, nothing can run or load, and malformed
messages never break storage."""

from __future__ import annotations

import pytest

from app.mailbox import sanitize, signals
from app.mailbox.sanitize import MAX_HTML_STORED_CHARS, MAX_TEXT_CHARS, clean_html, prepare_body

# Each payload is something real phishing/tracking mail does. After cleaning, none of the markers may remain.
HOSTILE = [
    ("<script>alert(1)</script><p>hi</p>", ["<script", "alert(1)"]),
    ('<p onclick="steal()">x</p>', ["onclick", "steal"]),
    ("<body onload=steal()>x</body>", ["onload", "steal"]),
    ('<a href="javascript:alert(1)">x</a>', ["javascript:"]),
    ('<a href="JaVaScRiPt:alert(1)">x</a>', ["javascript:", "alert"]),
    ('<a href="&#106;avascript:alert(1)">x</a>', ["javascript", "alert(1)"]),
    ('<a href="data:text/html;base64,PHNjcmlwdD4=">x</a>', ["data:"]),
    ('<a href="vbscript:msgbox(1)">x</a>', ["vbscript"]),
    ('<a href="//evil.example/x">x</a>', []),  # protocol-relative: checked separately below
    ('<img src="https://tracker.example/p.gif">', ["<img", "tracker.example"]),
    ('<img src=x onerror="alert(1)">', ["onerror", "<img"]),
    ('<iframe src="https://evil.example"></iframe>', ["<iframe", "evil.example"]),
    ('<object data="x"></object><embed src="y">', ["<object", "<embed"]),
    ('<form action="https://evil.example"><input name="pw"></form>', ["<form", "<input"]),
    (
        "<style>body{background:url(https://t.example/x)}</style><p>t</p>",
        ["<style", "t.example", "background"],
    ),
    ('<p style="background:url(https://t.example/x)">t</p>', ["style=", "t.example"]),
    ('<svg onload="alert(1)"><script>alert(2)</script></svg>', ["<svg", "alert"]),
    ('<math><mi xlink:href="javascript:alert(1)">x</mi></math>', ["<math", "javascript"]),
    ('<meta http-equiv="refresh" content="0;url=https://evil.example">', ["<meta", "evil.example"]),
    ('<base href="https://evil.example/">', ["<base", "evil.example"]),
    ('<link rel="stylesheet" href="https://evil.example/x.css">', ["<link", "evil.example"]),
    (
        "<scr<script>ipt>alert(1)</scr</script>ipt>",
        ["<script"],
    ),  # what is left is inert, escaped text
    ("<!--[if IE]><script>alert(1)</script><![endif]-->", ["alert(1)"]),
    ("<video src=x onerror=alert(1)></video><audio src=x></audio>", ["<video", "<audio", "alert"]),
    (
        '<a href="https://ok.example" target="_blank" onmouseover="x()">x</a>',
        ["onmouseover", "x()"],
    ),
    ("<template><script>alert(1)</script></template>", ["alert(1)"]),
    ("<noscript><img src=x onerror=alert(1)></noscript>", ["alert(1)"]),
    ("<textarea><script>alert(1)</script></textarea>", ["alert(1)"]),
]


@pytest.mark.parametrize(("payload", "markers"), HOSTILE)
def test_hostile_html_is_neutralised(payload: str, markers: list[str]) -> None:
    out = clean_html(payload)
    low = out.lower()
    for marker in markers:
        assert marker.lower() not in low, (marker, out)
    assert (
        "<script" not in low
        and "onerror" not in low
        and "onclick" not in low
        and "javascript:" not in low
    )


def test_formatting_survives_and_links_are_made_safe() -> None:
    html = (
        "<div><h2>Title</h2><p>Hello <b>bold</b> <i>it</i> <u>u</u> <code>c</code></p>"
        "<ul><li>one</li><li>two</li></ul><blockquote>quoted</blockquote>"
        '<table><tr><th colspan="2">h</th></tr><tr><td>a</td><td>b</td></tr></table>'
        '<a href="https://ok.example/p?q=1" title="t">link</a> <a href="mailto:a@b.example">mail</a></div>'
    )
    out = clean_html(html)
    for fragment in (
        "<h2>Title</h2>",
        "<b>bold</b>",
        "<li>one</li>",
        "<blockquote>quoted</blockquote>",
        'colspan="2"',
        "<td>a</td>",
    ):
        assert fragment in out
    assert 'href="https://ok.example/p?q=1"' in out and 'href="mailto:a@b.example"' in out
    assert out.count('rel="noopener noreferrer nofollow"') == 2  # every link, no exceptions
    assert "target=" not in out


def test_only_http_https_and_mailto_links_keep_their_target() -> None:
    out = clean_html(
        '<a href="ftp://x.example/f">a</a><a href="file:///etc/passwd">b</a><a href="tel:123">c</a><a href="/relative">d</a>'
    )
    assert "ftp:" not in out and "file:" not in out and "tel:" not in out and "/relative" not in out
    assert "href" not in out
    assert "href" not in clean_html('<a href="//evil.example/x">protocol-relative</a>')


def test_script_source_never_becomes_visible_text() -> None:
    stored = prepare_body(
        None, "<p>Visible</p><script>var secret = 1;</script><style>.x{color:red}</style>"
    )
    assert stored.text == "Visible" and stored.html == "<p>Visible</p>"


def test_images_are_removed_and_the_ui_is_told() -> None:
    stored = prepare_body(
        "Hello", '<p>Hello</p><img src="https://t.example/p.gif" width=1 height=1>'
    )
    assert stored.images_blocked and stored.html == "<p>Hello</p>" and stored.text == "Hello"
    assert not prepare_body("Hello", "<p>Hello</p>").images_blocked
    assert prepare_body("x", '<VIDEO src="https://t.example/v.mp4"></VIDEO><p>x</p>').images_blocked


def test_plain_text_is_cleaned_not_rendered() -> None:
    nasty = "Hi\x00 there\x07‮ evil​\r\n\r\n\r\n\r\nend"
    stored = prepare_body(nasty, None)
    assert (
        stored.text == "Hi there evil\n\nend" and stored.html is None and not stored.text_truncated
    )
    assert (
        "\x00" not in stored.text and "‮" not in stored.text
    )  # bidirectional overrides can fake file names


def test_text_comes_from_html_when_a_message_has_no_plain_part() -> None:
    stored = prepare_body(None, "<div>Line one<br>Line two</div>")
    assert "Line one" in stored.text and "Line two" in stored.text and "<" not in stored.text
    assert prepare_body("   ", "<p>from html</p>").text == "from html"
    assert prepare_body(None, None).text == "" and prepare_body("", "").html is None


def test_huge_bodies_are_capped_and_flagged() -> None:
    stored = prepare_body("x" * (MAX_TEXT_CHARS + 500), None)
    assert (
        stored.text_truncated
        and len(stored.text) <= MAX_TEXT_CHARS + 20
        and stored.text.endswith("…[truncated]")
    )
    big = prepare_body("hi", "<p>" + "a" * (MAX_HTML_STORED_CHARS + 10) + "</p>")
    assert (
        big.html is None and big.text == "hi"
    )  # an oversized formatted copy is dropped; the text remains


def test_deeply_nested_and_unbalanced_markup_cannot_break_storage() -> None:
    nested = "<div>" * 5000 + "deep" + "</div>" * 10
    unbalanced = "<p><b><i>unclosed <a href='https://ok.example'>link"
    garbage = "<<<>>><p<p>><a href=>< / >&&&;&#x;<![CDATA[x]]>"
    for html in (
        nested,
        unbalanced,
        garbage,
        "\x00<p>\x00</p>",
        "<p>\ud800</p>".encode("utf-8", "surrogatepass").decode("utf-8", "replace"),
    ):
        stored = prepare_body(None, html)
        assert isinstance(stored.text, str)
        assert stored.html is None or "<script" not in stored.html


def test_sanitiser_failure_keeps_the_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(_: str) -> str:
        raise RuntimeError("parser bug")

    monkeypatch.setattr(sanitize, "clean_html", boom)
    stored = prepare_body("keep me", "<p>x</p>")
    assert stored.text == "keep me" and stored.html is None


def test_cleaning_is_idempotent() -> None:
    once = clean_html('<p onclick="x()">a <a href="https://ok.example">b</a></p><script>1</script>')
    assert clean_html(once) == once


# ----------------------------------------------------------------------------- bounces


@pytest.mark.parametrize(
    ("sender", "subject", "expected"),
    [
        ("mailer-daemon@googlemail.com", "Delivery Status Notification (Failure)", True),
        ("MAILER-DAEMON@mail.contoso.example", "Undeliverable: Hello", True),
        ("postmaster@contoso.example", "Mail delivery failed: returning message to sender", True),
        ("mailer-daemon@x.example", None, True),
        ("mailer-daemon@x.example", "", True),
        ("mailer-daemon@x.example", "Quarterly newsletter", False),
        (
            "jordan@northwind.example",
            "Undeliverable: my invoice? just kidding",
            False,
        ),  # a person, not a mail system
        ("jordan@northwind.example", "Delivery Status Notification (Failure)", False),
        ("sam@fabrikam.example", "Re: hello", False),
        ("mailer-daemonic@x.example", "Undeliverable", False),
    ],
)
def test_bounces_need_both_a_mail_system_sender_and_a_failure_subject(
    sender: str, subject: str | None, expected: bool
) -> None:
    assert signals.is_bounce(sender, subject) is expected
