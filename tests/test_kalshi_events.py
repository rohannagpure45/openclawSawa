import pytest

from sawa import kalshi_events
from sawa.config import Config

CFG = Config(supabase_url="", supabase_key="", kalshi_base="https://k.example/v2")


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAWA_CACHE_DIR", str(tmp_path / "c"))


def _router(events_pages, series_rows=None, counters=None):
    """Route /series (enrichment) vs paged /events; optionally count calls."""
    series_rows = series_rows or []
    counters = counters if counters is not None else {}
    state = {"page": 0}

    def fake(url, headers=None, timeout=10):
        if "/series" in url and "series_ticker=" not in url:
            counters["series"] = counters.get("series", 0) + 1
            return {"series": series_rows}
        if "/events" in url:
            counters["events"] = counters.get("events", 0) + 1
            page = events_pages[min(state["page"], len(events_pages) - 1)]
            state["page"] += 1
            return page
        return {}

    return fake


def _ev(event_ticker, title, sub_title="", series_ticker="", category=""):
    return {"event_ticker": event_ticker, "title": title, "sub_title": sub_title,
            "series_ticker": series_ticker, "category": category}


def test_events_index_paginates_until_no_cursor(monkeypatch):
    counters = {}
    pages = [
        {"events": [_ev("E1", "England vs Spain")], "cursor": "c2"},
        {"events": [_ev("E2", "Croatia vs Uruguay")], "cursor": None},
    ]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages, counters=counters))
    index = kalshi_events.get_events_index(CFG)
    assert [e["event_ticker"] for e in index] == ["E1", "E2"]
    assert counters["events"] == 2  # followed the cursor exactly once


def test_find_events_matches_team_in_title(monkeypatch):
    pages = [{"events": [
        _ev("KXWCTEAMH2H-26ENGESP", "England vs Spain: Who Will Go Further", series_ticker="KXWCTEAMH2H"),
        _ev("KXWCTEAMH2H-26CROURU", "Croatia vs Uruguay: Who Will Go Further", series_ticker="KXWCTEAMH2H"),
    ], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages))
    out = kalshi_events.find_events(CFG, "croatia")
    assert [e["event_ticker"] for e in out] == ["KXWCTEAMH2H-26CROURU"]


def test_find_events_token_coverage_guarantees_each_token(monkeypatch):
    # Three "england" events outscore the single "croatia" event numerically, but
    # token-coverage selection must still surface croatia within a small top_k.
    pages = [{"events": [
        _ev("ENG1", "England vs Spain World Cup"),
        _ev("ENG2", "England cricket test"),
        _ev("ENG3", "England rugby match"),
        _ev("CRO1", "Croatia vs Uruguay"),
    ], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages))
    out = kalshi_events.find_events(CFG, "england croatia", top_k=2)
    tickers = {e["event_ticker"] for e in out}
    assert len(out) == 2
    assert "CRO1" in tickers          # croatia not starved
    assert any(t.startswith("ENG") for t in tickers)


def test_find_events_no_match_returns_empty(monkeypatch):
    pages = [{"events": [_ev("E1", "England vs Spain")], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages))
    assert kalshi_events.find_events(CFG, "zzzqqq nonsense") == []


def test_find_events_no_usable_tokens(monkeypatch):
    pages = [{"events": [_ev("E1", "England vs Spain")], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages))
    assert kalshi_events.find_events(CFG, "the on for") == []


def test_events_index_uses_cache(monkeypatch):
    counters = {}
    pages = [{"events": [_ev("E1", "England vs Spain")], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages, counters=counters))
    kalshi_events.get_events_index(CFG)
    kalshi_events.get_events_index(CFG)
    assert counters["events"] == 1  # second call served from disk cache


def test_events_index_serves_stale_when_expired(monkeypatch):
    """Interactive reads serve a stale index rather than re-page ~38 /events calls."""
    counters = {}
    pages = [{"events": [_ev("E1", "England vs Spain")], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages, counters=counters))
    monkeypatch.setattr(kalshi_events, "EVENTS_TTL_SECONDS", 0)  # always "expired"
    kalshi_events.get_events_index(CFG)   # cold -> builds once
    kalshi_events.get_events_index(CFG)   # expired but present -> stale, no rebuild
    assert counters["events"] == 1


def test_events_index_refresh_forces_rebuild(monkeypatch):
    """sawa warm passes refresh=True to refetch off the interactive critical path."""
    counters = {}
    pages = [{"events": [_ev("E1", "England vs Spain")], "cursor": None}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages, counters=counters))
    kalshi_events.get_events_index(CFG, refresh=True)
    kalshi_events.get_events_index(CFG, refresh=True)
    assert counters["events"] == 2  # refresh always re-pages and re-stores


def test_find_events_series_enrichment(monkeypatch):
    # The query word "soccer" only matches via the event's SERIES tags, not its title.
    pages = [{"events": [_ev("E1", "Brazil vs Argentina", series_ticker="KXGAME")], "cursor": None}]
    series_rows = [{"ticker": "KXGAME", "title": "League Game", "tags": ["Soccer"], "category": "Sports"}]
    monkeypatch.setattr(kalshi_events.http, "get_json", _router(pages, series_rows=series_rows))
    out = kalshi_events.find_events(CFG, "soccer")
    assert [e["event_ticker"] for e in out] == ["E1"]
