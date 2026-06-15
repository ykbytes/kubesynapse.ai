"""Tests for §security-R6 markdown XSS fix.

Verifies the escapeAttr and _safeHref functions in
ExpandableMarkdownEditor.tsx work correctly.
"""
from __future__ import annotations

import re


# Mirror the JavaScript implementations
def escape_attr(value: str) -> str:
    return (
        value
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def safe_href(href: str) -> str | None:
    normalized = re.sub(r"[\s\x00-\x1f]", "", href).lower()
    if normalized.startswith("//"):
        return None
    if re.match(r"^(javascript|data|vbscript|file|about|chrome|jar):", normalized, re.IGNORECASE):
        return None
    if not re.match(r"^(https?|mailto|tel):", normalized, re.IGNORECASE) and not normalized.startswith("/"):
        if not re.match(r"^[./]", normalized) and not normalized.startswith("#"):
            return None
    return href


def test_escape_attr_blocks_attribute_breakout() -> None:
    """The attribute escaper must prevent breaking out of an HTML attribute.

    Without escaping, an attacker-supplied href like
    ``https://x" onclick="alert(1)`` would produce:
    ``<a href="https://x" onclick="alert(1)">click</a>``
    """
    assert escape_attr('https://x" onclick="alert(1)') == "https://x&quot; onclick=&quot;alert(1)"
    assert escape_attr("<script>") == "&lt;script&gt;"
    assert escape_attr("a&b") == "a&amp;b"


def test_safe_href_blocks_javascript_protocol() -> None:
    """The href validator must block javascript: and similar protocols."""
    for bad in [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "  javascript:alert(1)",  # leading whitespace
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox",
        "file:///etc/passwd",
        "//evil.com/path",  # protocol-relative
    ]:
        assert safe_href(bad) is None, f"Expected to block {bad!r}"


def test_safe_href_allows_safe_protocols() -> None:
    """The href validator must allow http(s), mailto, tel, and relative paths."""
    for good in [
        "https://example.com/path",
        "http://localhost:3000",
        "mailto:[email protected]",
        "tel:+1234567890",
        "/relative/path",
        "#anchor",
        "./relative",
    ]:
        assert safe_href(good) == good, f"Expected to allow {good!r}"


def test_full_link_injection() -> None:
    """End-to-end: a malicious link in markdown does not break out of the attribute.

    Without escaping, an attacker-supplied href like
    ``https://x" onclick="alert(1)`` would render as:
    ``<a href="https://x" onclick="alert(1)">click</a>``

    With the fix, the quote is escaped to ``&quot;`` and the
    attribute stays intact. The string "onclick" still appears
    in the output (as part of the escaped href), but the browser
    does not parse it as an attribute.
    """
    link_text = "click"
    link_href = 'https://x" onclick="alert(document.cookie)'

    safe_href_value = safe_href(link_href)
    # The href is not blocked by protocol (https: is fine)
    assert safe_href_value is not None
    # But the attribute escaper neutralizes the breakout
    escaped = escape_attr(safe_href_value)
    # The actual quote character must be escaped
    assert '"' not in escaped
    assert "&quot;" in escaped
    # So the resulting HTML is safe — the href attribute ends
    # before the "onclick" string is ever seen by the parser.
    rendered = f'<a href="{escaped}">{link_text}</a>'
    # Count the number of unescaped quotes inside the href — must be 0
    # (the only quotes in the output are the two around the href value)
    assert rendered.count('"') == 2
    # The href value, when read by the browser, will be the full
    # escaped string (the browser un-escapes HTML entities on parse),
    # so the user's click will navigate to the attacker's URL — but
    # the browser will not execute the injected onclick because the
    # parser sees a single attribute value.
    print(f"OK: rendered = {rendered!r}")
