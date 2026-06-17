"""Read-only-by-construction guarantee, pinned statically.

These tests assert that no source file in the ``sawa`` package can issue an HTTP
write: no write-method tokens anywhere, urllib.request is confined to http.py,
and http.py constructs only GET requests with no body.
"""

import pathlib
import re

SAWA_DIR = pathlib.Path(__file__).resolve().parent.parent / "sawa"

# HTTP write methods as standalone uppercase words. Case-sensitive so that
# substrings like "PostgREST" (Post) or "computed" (PUT) never match.
WRITE_METHOD = re.compile(r"\b(POST|PUT|PATCH|DELETE)\b")


def _sources():
    return {path.name: path.read_text(encoding="utf-8") for path in SAWA_DIR.glob("*.py")}


def test_no_http_write_method_tokens_anywhere():
    offenders = {name: WRITE_METHOD.findall(text) for name, text in _sources().items()}
    offenders = {name: hits for name, hits in offenders.items() if hits}
    assert not offenders, "write HTTP method tokens found: %r" % offenders


def test_only_http_module_touches_urllib_request():
    for name, text in _sources().items():
        if name == "http.py":
            continue
        assert "urllib.request" not in text, "%s references urllib.request" % name
        assert "urlopen" not in text, "%s references urlopen" % name


def test_no_other_http_clients():
    for name, text in _sources().items():
        assert "http.client" not in text, "%s uses http.client" % name
        assert "import requests" not in text, "%s imports requests" % name


def test_http_module_is_get_only():
    text = _sources()["http.py"]
    assert 'method="GET"' in text, "http.py must pin the request method to GET"
    # A request body (data=) would turn urlopen into a write; it must not appear.
    assert "data=" not in text, "http.py must never send a request body"
