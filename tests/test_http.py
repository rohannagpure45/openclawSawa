import io
import json
import urllib.error

import pytest

from sawa import http


class _FakeResponse:
    def __init__(self, body, status=200):
        self._body = body
        self._status = status

    def read(self):
        return self._body

    def getcode(self):
        return self._status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_build_url_preserves_postgrest_syntax():
    url = http.build_url(
        "https://x.example/rest/v1/Prediction",
        {"select": "id,Option(id,label)", "isPrivate": "eq.false", "title": "ilike.*temp*"},
    )
    assert "select=id,Option(id,label)" in url
    assert "isPrivate=eq.false" in url
    assert "title=ilike.*temp*" in url


def test_build_url_no_params_returns_base():
    assert http.build_url("https://x.example/markets") == "https://x.example/markets"


def test_get_json_parses_body(monkeypatch):
    payload = {"markets": [{"ticker": "T1"}]}
    monkeypatch.setattr(
        http.urllib.request,
        "urlopen",
        lambda req, timeout=10: _FakeResponse(json.dumps(payload).encode("utf-8")),
    )
    assert http.get_json("https://x.example/markets") == payload


def test_get_json_http_error_becomes_typed_error(monkeypatch):
    def boom(req, timeout=10):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b""))

    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    with pytest.raises(http.HttpError) as info:
        http.get_json("https://x.example/markets")
    assert info.value.status == 401


def test_get_json_network_error_becomes_typed_error(monkeypatch):
    def boom(req, timeout=10):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(http.urllib.request, "urlopen", boom)
    with pytest.raises(http.HttpError):
        http.get_json("https://x.example/markets")


def test_get_json_invalid_json_becomes_typed_error(monkeypatch):
    monkeypatch.setattr(
        http.urllib.request,
        "urlopen",
        lambda req, timeout=10: _FakeResponse(b"not json"),
    )
    with pytest.raises(http.HttpError):
        http.get_json("https://x.example/markets")


def test_get_json_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)  # no real delay
    calls = {"n": 0}

    def flaky(req, timeout=10):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(b""))
        return _FakeResponse(json.dumps({"ok": 1}).encode("utf-8"))

    monkeypatch.setattr(http.urllib.request, "urlopen", flaky)
    assert http.get_json("https://x.example/markets") == {"ok": 1}
    assert calls["n"] == 2  # one retry


def test_get_json_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr(http.time, "sleep", lambda *_: None)

    def always_429(req, timeout=10):
        raise urllib.error.HTTPError("u", 429, "Too Many", {}, io.BytesIO(b""))

    monkeypatch.setattr(http.urllib.request, "urlopen", always_429)
    with pytest.raises(http.HttpError) as info:
        http.get_json("https://x.example/markets")
    assert info.value.status == 429
