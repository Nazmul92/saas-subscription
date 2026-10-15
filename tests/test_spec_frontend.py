"""Regression tests for the served frontend (``static/``).

The page toggles its overlays with the ``hidden`` attribute.  An author rule
that declares ``display`` on the same class beats that attribute, so
``#modal-scrim`` stayed on top of the app after load and swallowed every click
(the page rendered but nothing was clickable).

These tests compute the ``display`` value the cascade would apply to each
element that ships with ``hidden``, following the cascade for the simple
selectors this stylesheet uses, and require it not to be a visible value.  No
browser is needed.  ``test_checker_*`` prove the check itself can fail.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from collections.abc import Callable, Iterable
from typing import Any

from meteroid.api import STATIC_DIR
from server import bootstrap

_COMMENT = re.compile(r"/\*.*?\*/", re.S)
_SELECTOR_PART = re.compile(
    r"\.[A-Za-z0-9_-]+|#[A-Za-z0-9_-]+|\[[A-Za-z0-9_-]+\]|^[A-Za-z][A-Za-z0-9_-]*"
)
_COMBINATOR = re.compile(r"[\s>+~]")


class _HiddenTags(HTMLParser):
    """Collects ``(tag, id, classes)`` for every element carrying ``hidden``."""

    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, str, set[str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if "hidden" not in data:
            return
        classes = set((data.get("class") or "").split())
        self.elements.append((tag, data.get("id") or "", classes))


def _parse_css(css: str) -> list[tuple[str, dict[str, str]]]:
    """Flatten a stylesheet into ``(selector, declarations)`` pairs, in source order."""
    css = _COMMENT.sub("", css)
    rules: list[tuple[str, dict[str, str]]] = []
    for chunk in css.split("}"):
        selector_text, has_brace, body = chunk.partition("{")
        if not has_brace:
            continue
        decls: dict[str, str] = {}
        for decl in body.split(";"):
            prop, colon, value = decl.partition(":")
            if colon:
                decls[prop.strip().lower()] = value.strip()
        for selector in selector_text.split(","):
            if selector.strip():
                rules.append((selector.strip(), decls))
    return rules


def _specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[A-Za-z0-9_-]+", selector))
    classes = len(re.findall(r"\.[A-Za-z0-9_-]+", selector)) + selector.count("[")
    tags = len(re.findall(r"(?:^|[\s>+~])([A-Za-z][A-Za-z0-9_-]*)", selector))
    return (ids, classes, tags)


def _matches(selector: str, tag: str, ident: str, classes: set[str]) -> bool:
    """True when every simple part of the selector matches the element.

    Descendant/child selectors are ignored on purpose: the toggled overlays are
    addressed with a single compound selector, and skipping combinators keeps
    this conservative (it never invents a match it cannot justify).
    """
    if _COMBINATOR.search(selector):
        return False
    parts = _SELECTOR_PART.findall(selector)
    if not parts:
        return False
    for part in parts:
        if part.startswith("."):
            if part[1:] not in classes:
                return False
        elif part.startswith("#"):
            if part[1:] != ident:
                return False
        elif part.startswith("["):
            if part[1:-1] != "hidden":
                return False
        elif part.lower() != tag.lower():
            return False
    return True


def winning_display(css: str, tag: str, ident: str, classes: set[str]) -> str | None:
    """The ``display`` value the cascade applies to the element (``None`` if unset)."""
    best: tuple[tuple[int, int, int, int], str] | None = None
    for order, (selector, decls) in enumerate(_parse_css(css)):
        if "display" not in decls or not _matches(selector, tag, ident, classes):
            continue
        key = (*_specificity(selector), order)
        if best is None or key > best[0]:
            best = (key, decls["display"])
    return best[1] if best else None


def _visible(value: str | None) -> bool:
    """A hidden element is invisible when nothing sets ``display`` or it sets ``none``."""
    return value is not None and value != "none"


def _css() -> str:
    return (STATIC_DIR / "styles.css").read_text(encoding="utf-8")


def _hidden_elements() -> list[tuple[str, str, set[str]]]:
    parser = _HiddenTags()
    parser.feed((STATIC_DIR / "index.html").read_text(encoding="utf-8"))
    return parser.elements


def test_hidden_overlays_are_not_left_visible() -> None:
    css = _css()
    elements = _hidden_elements()
    assert elements, "index.html should ship at least one element with the hidden attribute"
    offenders = [
        (tag, ident or sorted(classes), value)
        for tag, ident, classes in elements
        if _visible(value := winning_display(css, tag, ident, classes))
    ]
    assert not offenders, f"elements toggled by `hidden` are still displayed: {offenders}"


def test_checker_detects_a_rule_that_beats_hidden() -> None:
    buggy = """
      .modal-scrim { position: fixed; inset: 0; z-index: 20; }
      .modal-scrim { display: grid; place-items: center; }
    """
    value = winning_display(buggy, "div", "modal-scrim", {"modal-scrim"})
    assert value == "grid"
    assert _visible(value), "the guard must flag this as still visible"


def test_checker_honours_a_hidden_rule_and_specificity() -> None:
    fixed = """
      .modal-scrim { display: grid; place-items: center; }
      .modal-scrim[hidden] { display: none; }
    """
    assert winning_display(fixed, "div", "modal-scrim", {"modal-scrim"}) == "none"
    # a bare `[hidden]` rule after the display rule must also win
    tail = ".modal-scrim { display: grid; }\n[hidden] { display: none; }"
    assert winning_display(tail, "div", "modal-scrim", {"modal-scrim"}) == "none"


def _get(app: Callable[..., Iterable[bytes]], path: str) -> tuple[str, dict[str, str], bytes]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]], exc_info: Any = None) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    body = b"".join(app({"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": ""}, start_response))
    return captured["status"], captured["headers"], body


def test_frontend_assets_are_served_uncached(db_file: str) -> None:
    app = bootstrap(db_file, reset=True, seed=False)
    for path, mime in (("/", "text/html"), ("/styles.css", "text/css"), ("/app.js", "text/javascript")):
        status, headers, body = _get(app, path)
        assert status.startswith("200"), f"{path} -> {status}"
        assert headers["Content-Type"].startswith(mime), f"{path} -> {headers['Content-Type']}"
        assert headers["Cache-Control"] == "no-store", path
        assert body, path

    _, _, html = _get(app, "/")
    assert b"/styles.css" in html and b"/app.js" in html, "index.html must load the stylesheet and script"

    _, _, served_css = _get(app, "/styles.css")
    assert served_css.decode("utf-8") == _css(), "served stylesheet must be the one checked above"
