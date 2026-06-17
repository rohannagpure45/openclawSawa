import re

import pytest

from sawa import kalshi_read
from sawa.config import Config

CFG = Config(supabase_url="", supabase_key="", kalshi_base="https://k.example/v2")


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    # Isolate the kalshi_index series cache so tests never touch a real ~/.sawa/cache.
    monkeypatch.setenv("SAWA_CACHE_DIR", str(tmp_path / "c"))


def _raw(ticker, title="", subtitle="", yes_sub_title="", last_price=60, volume=10, status="open"):
    return {
        "ticker": ticker,
        "title": title or ticker,
        "subtitle": subtitle,
        "yes_sub_title": yes_sub_title,
        "last_price": last_price,
        "volume": volume,
        "status": status,
        "close_time": "2026-07-01T00:00:00Z",
    }


def _single(payload, captured):
    """Fake for the explicit-series / snapshot path: one payload, record URLs."""
    def fake(url, headers=None, timeout=10):
        captured.append(url)
        return payload
    return fake


def _router(series=None, markets_by_series=None, snapshot=None, captured=None):
    """Route /series vs /markets?series_ticker=… vs snapshot; record URLs."""
    series = series or []
    markets_by_series = markets_by_series or {}
    snapshot = snapshot or []
    cap = captured if captured is not None else []

    def fake(url, headers=None, timeout=10):
        cap.append(url)
        if "/series" in url and "series_ticker=" not in url:
            return {"series": series}
        m = re.search(r"series_ticker=([^&]+)", url)
        if m:
            return {"markets": markets_by_series.get(m.group(1), [])}
        return {"markets": snapshot}

    return fake


# --- explicit series= path (unchanged behavior, carried over) ---

def test_explicit_series_substring_filter(monkeypatch):
    captured = []
    payload = {"markets": [_raw("A", title="Temperature in NYC"), _raw("B", title="Rainfall")]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _single(payload, captured))
    out = kalshi_read.list_markets(CFG, search="temperature", series="KXHIGHNY")
    assert [m.ref for m in out] == ["kalshi:A"]
    assert len(captured) == 1  # one request, no series index


def test_explicit_series_limit_cap(monkeypatch):
    captured = []
    payload = {"markets": [_raw("T%d" % i) for i in range(50)]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _single(payload, captured))
    out = kalshi_read.list_markets(CFG, series="KXHIGHNY", limit=5)
    assert len(out) == 5


def test_explicit_series_outcomes_and_labels(monkeypatch):
    captured = []
    payload = {"markets": [_raw("ABC", title="Will it rain?", last_price=70)]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _single(payload, captured))
    out = kalshi_read.list_markets(CFG, series="KXRAINNYC")
    assert len(out) == 1
    m = out[0]
    assert m.ref == "kalshi:ABC"
    assert [(o.label, o.odds_pct) for o in m.options] == [("Yes", 70.0), ("No", 30.0)]
    assert m.activity == 10


def test_explicit_series_empty(monkeypatch):
    captured = []
    monkeypatch.setattr(kalshi_read.http, "get_json", _single({"markets": []}, captured))
    assert kalshi_read.list_markets(CFG, series="KXHIGHNY") == []


# --- snapshot path (no search, no series) ---

def test_snapshot_is_single_cheap_call(monkeypatch):
    captured = []
    monkeypatch.setattr(kalshi_read.http, "get_json", _single({"markets": [_raw("S1")]}, captured))
    out = kalshi_read.list_markets(CFG)
    assert [m.ref for m in out] == ["kalshi:S1"]
    assert len(captured) == 1
    assert "status=open" in captured[0]
    assert "series_ticker" not in captured[0] and "/series" not in captured[0]


# --- keyword search via the series index ---

def test_search_finds_cross_topic_market_and_ranks(monkeypatch):
    captured = []
    series = [{"ticker": "KXMENWORLDCUP", "title": "Men's World Cup winner", "tags": ["Soccer"], "category": "Sports"}]
    markets = {"KXMENWORLDCUP": [
        _raw("KXMENWORLDCUP-26-BR", title="Will Brazil win the 2026 Men's World Cup?", yes_sub_title="Brazil"),
        _raw("KXMENWORLDCUP-26-PT", title="Will Portugal win the 2026 Men's World Cup?", yes_sub_title="Portugal"),
    ]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(series, markets, captured=captured))
    out = kalshi_read.list_markets(CFG, search="world cup portugal", limit=5)
    assert out[0].ref == "kalshi:KXMENWORLDCUP-26-PT"  # Portugal scores highest
    assert {m.ref for m in out} == {"kalshi:KXMENWORLDCUP-26-PT", "kalshi:KXMENWORLDCUP-26-BR"}


def test_search_no_series_match_returns_empty_and_skips_markets(monkeypatch):
    captured = []
    series = [{"ticker": "KXWX", "title": "NYC High Temperature", "tags": ["Weather"], "category": "Climate and Weather"}]
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(series, {}, captured=captured))
    assert kalshi_read.list_markets(CFG, search="portugal world cup") == []
    assert not any("series_ticker=" in u for u in captured)  # /markets never hit


def test_search_graceful_fallback_when_all_market_scores_zero(monkeypatch):
    captured = []
    # series matches on the tag "soccer" but market titles don't contain the query token
    series = [{"ticker": "KXEPL", "title": "EPL Game", "tags": ["Soccer"], "category": "Sports"}]
    markets = {"KXEPL": [_raw("KXEPL-ARS", title="Arsenal vs Chelsea"), _raw("KXEPL-MAN", title="Man City vs Spurs")]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(series, markets, captured=captured))
    out = kalshi_read.list_markets(CFG, search="soccer", limit=10)
    assert {m.ref for m in out} == {"kalshi:KXEPL-ARS", "kalshi:KXEPL-MAN"}  # not empty


def test_search_respects_limit(monkeypatch):
    captured = []
    series = [{"ticker": "KXA", "title": "Alpha Series", "tags": [], "category": "Sports"}]
    markets = {"KXA": [_raw("KXA-%d" % i, title="Alpha match %d" % i) for i in range(50)]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(series, markets, captured=captured))
    out = kalshi_read.list_markets(CFG, search="alpha", limit=5)
    assert len(out) == 5


def test_search_category_narrows_series(monkeypatch):
    captured = []
    series = [
        {"ticker": "KXSPORT", "title": "Cup Winner", "tags": [], "category": "Sports"},
        {"ticker": "KXPOL", "title": "Cup Winner", "tags": [], "category": "Politics"},
    ]
    markets = {"KXSPORT": [_raw("KXSPORT-1", title="Cup match")], "KXPOL": [_raw("KXPOL-1", title="Cup vote")]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(series, markets, captured=captured))
    out = kalshi_read.list_markets(CFG, search="cup", category="Sports", limit=10)
    assert [m.ref for m in out] == ["kalshi:KXSPORT-1"]
    assert not any("series_ticker=KXPOL" in u for u in captured)  # politics series never fetched


# --- get_market (show) -- unchanged ---

def test_get_market_found(monkeypatch):
    monkeypatch.setattr(
        kalshi_read.http,
        "get_json",
        lambda url, headers=None, timeout=10: {"market": _raw("XYZ", title="High temp")},
    )
    market = kalshi_read.get_market(CFG, "XYZ")
    assert market is not None and market.ref == "kalshi:XYZ"


def test_get_market_not_found_returns_none(monkeypatch):
    def boom(url, headers=None, timeout=10):
        raise kalshi_read.http.HttpError("missing", status=404)

    monkeypatch.setattr(kalshi_read.http, "get_json", boom)
    assert kalshi_read.get_market(CFG, "NOPE") is None


def test_get_market_other_error_propagates(monkeypatch):
    def boom(url, headers=None, timeout=10):
        raise kalshi_read.http.HttpError("server", status=500)

    monkeypatch.setattr(kalshi_read.http, "get_json", boom)
    with pytest.raises(kalshi_read.http.HttpError):
        kalshi_read.get_market(CFG, "X")
