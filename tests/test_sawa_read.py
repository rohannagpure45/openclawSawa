import pytest

from sawa import sawa_read
from sawa.config import Config

CFG = Config(supabase_url="https://db.example", supabase_key="secret-key", kalshi_base="x")


def _capture(payload):
    captured = {}

    def fake(url, headers=None, timeout=10):
        captured["url"] = url
        captured["headers"] = headers
        return payload

    return fake, captured


def test_list_query_has_public_filters_and_no_pii(monkeypatch):
    fake, captured = _capture([])
    monkeypatch.setattr(sawa_read.http, "get_json", fake)
    sawa_read.list_markets(CFG, search="lakers", category="sports", limit=5)
    url = captured["url"]
    assert "isPrivate=eq.false" in url
    assert "isHidden=eq.false" in url
    assert "resolved=eq.false" in url
    assert "title=ilike.*lakers*" in url
    assert "category=eq.sports" in url
    assert "limit=5" in url
    # PII guardrail: no User join, no personal columns anywhere in the query.
    for forbidden in ("User", "email", "phone", "password", "googleId"):
        assert forbidden not in url, "PII token %r leaked into query" % forbidden
    # Auth headers present (key never logged elsewhere).
    assert captured["headers"]["apikey"] == "secret-key"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"


def test_list_parses_and_picks_latest_odds(monkeypatch):
    # OddsSnapshot is a SIBLING embed of Option (joined by optionId), not nested.
    payload = [
        {
            "id": "p1",
            "title": "Lakers win?",
            "description": "desc",
            "category": "sports",
            "deadline": "2026-07-01",
            "resolved": False,
            "isPrivate": False,
            "isHidden": False,
            "createdAt": "2026-06-01",
            "Option": [
                {"id": "o1", "label": "Yes"},
                {"id": "o2", "label": "No"},
            ],
            "OddsSnapshot": [
                {"optionId": "o1", "percentage": 40, "createdAt": "2026-06-01T00:00:00Z"},
                {"optionId": "o1", "percentage": 62, "createdAt": "2026-06-10T00:00:00Z"},
                # o2 has no snapshot -> odds_pct stays None
            ],
        }
    ]
    fake, _ = _capture(payload)
    monkeypatch.setattr(sawa_read.http, "get_json", fake)
    out = sawa_read.list_markets(CFG)
    assert len(out) == 1
    market = out[0]
    assert market.venue == "sawa"
    assert market.ref == "sawa:p1"
    assert market.status == "open"
    assert market.description == "desc"
    assert market.options[0].label == "Yes"
    assert market.options[0].odds_pct == 62.0   # latest snapshot wins
    assert market.options[1].odds_pct is None    # no snapshots


def test_list_empty(monkeypatch):
    fake, _ = _capture([])
    monkeypatch.setattr(sawa_read.http, "get_json", fake)
    assert sawa_read.list_markets(CFG) == []


def test_list_network_error_propagates(monkeypatch):
    def boom(url, headers=None, timeout=10):
        raise sawa_read.http.HttpError("network error: down")

    monkeypatch.setattr(sawa_read.http, "get_json", boom)
    with pytest.raises(sawa_read.http.HttpError):
        sawa_read.list_markets(CFG)


def test_get_market_found_enforces_public_filter(monkeypatch):
    fake, captured = _capture([{"id": "p9", "title": "T", "Option": []}])
    monkeypatch.setattr(sawa_read.http, "get_json", fake)
    market = sawa_read.get_market(CFG, "p9")
    assert market is not None
    assert market.ref == "sawa:p9"
    assert "id=eq.p9" in captured["url"]
    assert "isPrivate=eq.false" in captured["url"]
    assert "isHidden=eq.false" in captured["url"]


def test_get_market_not_found_returns_none(monkeypatch):
    fake, _ = _capture([])
    monkeypatch.setattr(sawa_read.http, "get_json", fake)
    assert sawa_read.get_market(CFG, "missing") is None
