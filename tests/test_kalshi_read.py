import re

import pytest

from sawa import kalshi_read
from sawa.config import Config

CFG = Config(supabase_url="", supabase_key="", kalshi_base="https://k.example/v2")


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    # Isolate the kalshi_index series cache so tests never touch a real ~/.sawa/cache.
    monkeypatch.setenv("SAWA_CACHE_DIR", str(tmp_path / "c"))


def _raw(ticker, title="", subtitle="", yes_sub_title="", last_price=60, volume=10,
         status="open", event_ticker=""):
    # Kalshi's live schema: prices are dollar-denominated strings (0.0000-1.0000)
    # and volume is a fixed-point string; plain last_price/yes_bid/volume are gone.
    raw = {
        "ticker": ticker,
        "title": title or ticker,
        "subtitle": subtitle,
        "yes_sub_title": yes_sub_title,
        "status": status,
        "close_time": "2026-07-01T00:00:00Z",
        "volume_fp": str(volume),
    }
    if last_price is not None:
        raw["last_price_dollars"] = "%.4f" % (last_price / 100.0)
    if event_ticker:
        raw["event_ticker"] = event_ticker
    return raw


def _single(payload, captured):
    """Fake for the explicit-series / snapshot path: one payload, record URLs."""
    def fake(url, headers=None, timeout=10):
        captured.append(url)
        return payload
    return fake


def _router(series=None, markets_by_series=None, markets_by_event=None,
            events=None, snapshot=None, captured=None):
    """Route /series, /events, /markets?series_ticker=…, /markets?event_ticker=…,
    and the bare snapshot; record URLs."""
    series = series or []
    markets_by_series = markets_by_series or {}
    markets_by_event = markets_by_event or {}
    events = events or []
    snapshot = snapshot or []
    cap = captured if captured is not None else []

    def fake(url, headers=None, timeout=10):
        cap.append(url)
        if "/series" in url and "series_ticker=" not in url:
            return {"series": series}
        if "/events" in url and "event_ticker=" not in url:
            return {"events": events, "cursor": None}
        m = re.search(r"series_ticker=([^&]+)", url)
        if m:
            return {"markets": markets_by_series.get(m.group(1), [])}
        m = re.search(r"event_ticker=([^&]+)", url)
        if m:
            return {"markets": markets_by_event.get(m.group(1), [])}
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


def test_dollars_price_volume_and_url(monkeypatch):
    captured = []
    raw = {
        "ticker": "KXMENWORLDCUP-26-PT",
        "title": "Will Portugal win the 2026 Men's World Cup?",
        "last_price_dollars": "0.5700",   # 57%
        "volume_fp": "123456.78",
        "status": "open",
        "close_time": "2026-07-01T00:00:00Z",
    }
    monkeypatch.setattr(kalshi_read.http, "get_json", _single({"markets": [raw]}, captured))
    m = kalshi_read.list_markets(CFG, series="KXMENWORLDCUP")[0]
    assert [(o.label, o.odds_pct) for o in m.options] == [("Yes", 57.0), ("No", 43.0)]
    assert m.activity == 123456
    assert m.url == "https://kalshi.com/markets/kxmenworldcup"


def test_bid_ask_midpoint_when_no_last_price(monkeypatch):
    captured = []
    raw = {
        "ticker": "X-Y",
        "title": "Q",
        "yes_bid_dollars": "0.4000",
        "yes_ask_dollars": "0.5000",  # midpoint 45%
        "volume_fp": "0",
        "status": "open",
    }
    monkeypatch.setattr(kalshi_read.http, "get_json", _single({"markets": [raw]}, captured))
    m = kalshi_read.list_markets(CFG, series="X")[0]
    assert m.options[0].odds_pct == 45.0
    assert m.activity is None  # volume 0 -> None


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


# --- event-index supplement: bare team names (the England/Croatia regression) ---

def test_search_supplements_with_events_for_bare_team_names(monkeypatch):
    captured = []
    # "england" matches a Bank-of-England series; "croatia" matches NO series.
    series = [{"ticker": "KXCBDECISIONENGLAND", "title": "Bank of England Decision",
               "tags": [], "category": "Economics"}]
    events = [
        {"event_ticker": "KXWCTEAMH2H-26ENGESP", "title": "England vs Spain: Who Will Go Further",
         "sub_title": "ENG vs ESP", "series_ticker": "KXWCTEAMH2H", "category": "Sports"},
        {"event_ticker": "KXWCTEAMH2H-26CROURU", "title": "Croatia vs Uruguay: Who Will Go Further",
         "sub_title": "CRO vs URU", "series_ticker": "KXWCTEAMH2H", "category": "Sports"},
    ]
    markets_by_series = {"KXCBDECISIONENGLAND": [
        _raw("KXCBDECISIONENGLAND-C25", title="Will the Bank of England cut rates?")]}
    markets_by_event = {
        "KXWCTEAMH2H-26ENGESP": [_raw("KXWCTEAMH2H-26ENGESP-ENG",
            title="Will England advance further than Spain?", yes_sub_title="England advances",
            event_ticker="KXWCTEAMH2H-26ENGESP")],
        "KXWCTEAMH2H-26CROURU": [_raw("KXWCTEAMH2H-26CROURU-CRO",
            title="Will Croatia advance further than Uruguay?", yes_sub_title="Croatia advances",
            event_ticker="KXWCTEAMH2H-26CROURU")],
    }
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(
        series=series, markets_by_series=markets_by_series,
        events=events, markets_by_event=markets_by_event, captured=captured))

    out = kalshi_read.list_markets(CFG, search="england croatia", limit=10)
    refs = {m.ref for m in out}
    # The fix: both World Cup team markets surface (croatia was unfindable before)...
    assert "kalshi:KXWCTEAMH2H-26ENGESP-ENG" in refs
    assert "kalshi:KXWCTEAMH2H-26CROURU-CRO" in refs
    # ...and they outrank the Bank-of-England market (which only matches one token).
    assert out[0].ref.startswith("kalshi:KXWCTEAMH2H")
    assert out[1].ref.startswith("kalshi:KXWCTEAMH2H")
    assert out[0].url == "https://kalshi.com/markets/kxwcteamh2h"


def test_search_topic_word_returns_series_market(monkeypatch):
    # A topic query still resolves via the series index; with no matching events the
    # merged pool is just the series markets.
    captured = []
    series = [{"ticker": "KXMENWORLDCUP", "title": "Men's World Cup winner",
               "tags": ["Soccer"], "category": "Sports"}]
    markets = {"KXMENWORLDCUP": [_raw("KXMENWORLDCUP-26-PT",
        title="Will Portugal win the 2026 Men's World Cup?", yes_sub_title="Portugal")]}
    monkeypatch.setattr(kalshi_read.http, "get_json", _router(
        series=series, markets_by_series=markets, captured=captured))
    out = kalshi_read.list_markets(CFG, search="world cup", limit=5)
    assert out and out[0].ref == "kalshi:KXMENWORLDCUP-26-PT"


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
