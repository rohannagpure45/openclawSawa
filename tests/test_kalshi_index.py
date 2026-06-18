import pytest

from sawa import kalshi_index
from sawa.config import Config

CFG = Config(supabase_url="", supabase_key="", kalshi_base="https://k.example/v2")


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAWA_CACHE_DIR", str(tmp_path / "c"))


def _series_payload(rows):
    def fake(url, headers=None, timeout=10):
        return {"series": rows}
    return fake


def test_tokenize_drops_stopwords_and_short():
    assert kalshi_index._tokenize("Who wins the World Cup game?") == ["world", "cup"]


def test_find_series_ranks_title_over_tag(monkeypatch):
    rows = [
        {"ticker": "T_TAG", "title": "European Football", "tags": ["world"], "category": "Sports"},
        {"ticker": "T_TITLE", "title": "World Cup Winner", "tags": [], "category": "Sports"},
    ]
    monkeypatch.setattr(kalshi_index.http, "get_json", _series_payload(rows))
    out = kalshi_index.find_series(CFG, "world cup")
    assert out[0]["ticker"] == "T_TITLE"  # title (+phrase) beats tag-only


def test_find_series_phrase_bonus(monkeypatch):
    rows = [
        {"ticker": "SCATTER", "title": "Cup of Nations and World Tour", "tags": [], "category": "Sports"},
        {"ticker": "PHRASE", "title": "World Cup Final", "tags": [], "category": "Sports"},
    ]
    monkeypatch.setattr(kalshi_index.http, "get_json", _series_payload(rows))
    out = kalshi_index.find_series(CFG, "world cup")
    assert out[0]["ticker"] == "PHRASE"


def test_find_series_category_filter(monkeypatch):
    rows = [
        {"ticker": "SPORT", "title": "Cup Winner", "tags": [], "category": "Sports"},
        {"ticker": "POL", "title": "Cup Winner", "tags": [], "category": "Politics"},
    ]
    monkeypatch.setattr(kalshi_index.http, "get_json", _series_payload(rows))
    out = kalshi_index.find_series(CFG, "cup", category="Sports")
    assert [s["ticker"] for s in out] == ["SPORT"]


def test_find_series_no_match_returns_empty(monkeypatch):
    rows = [{"ticker": "X", "title": "World Cup", "tags": [], "category": "Sports"}]
    monkeypatch.setattr(kalshi_index.http, "get_json", _series_payload(rows))
    assert kalshi_index.find_series(CFG, "zzzqqq nonsense") == []


def test_find_series_no_usable_tokens(monkeypatch):
    monkeypatch.setattr(kalshi_index.http, "get_json", _series_payload([]))
    assert kalshi_index.find_series(CFG, "the on for") == []


def test_get_series_index_uses_cache(monkeypatch):
    calls = {"n": 0}

    def fake(url, headers=None, timeout=10):
        calls["n"] += 1
        return {"series": [{"ticker": "A", "title": "World Cup", "tags": [], "category": "Sports"}]}

    monkeypatch.setattr(kalshi_index.http, "get_json", fake)
    kalshi_index.get_series_index(CFG)
    kalshi_index.get_series_index(CFG)
    assert calls["n"] == 1  # second call served from disk cache


def test_get_series_index_serves_stale_when_expired(monkeypatch):
    """Interactive reads serve a stale index rather than block on a cold rebuild."""
    calls = {"n": 0}

    def fake(url, headers=None, timeout=10):
        calls["n"] += 1
        return {"series": [{"ticker": "A", "title": "World Cup", "tags": [], "category": "Sports"}]}

    monkeypatch.setattr(kalshi_index.http, "get_json", fake)
    monkeypatch.setattr(kalshi_index, "SERIES_TTL_SECONDS", 0)  # always "expired"
    kalshi_index.get_series_index(CFG)          # cold -> builds once
    kalshi_index.get_series_index(CFG)          # expired but present -> stale, no rebuild
    assert calls["n"] == 1


def test_get_series_index_refresh_forces_rebuild(monkeypatch):
    """sawa warm passes refresh=True to refetch off the interactive critical path."""
    calls = {"n": 0}

    def fake(url, headers=None, timeout=10):
        calls["n"] += 1
        return {"series": []}

    monkeypatch.setattr(kalshi_index.http, "get_json", fake)
    kalshi_index.get_series_index(CFG, refresh=True)
    kalshi_index.get_series_index(CFG, refresh=True)
    assert calls["n"] == 2  # refresh always refetches and re-stores
