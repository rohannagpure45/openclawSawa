from sawa import discover
from sawa.config import Config
from sawa.discover import Market

CFG = Config(supabase_url="https://db", supabase_key="k", kalshi_base="x")


def test_search_merges_and_labels_both_venues(monkeypatch):
    monkeypatch.setattr(
        "sawa.sawa_read.list_markets", lambda cfg, **k: [Market("sawa", "sawa:1", "S", "open")]
    )
    monkeypatch.setattr(
        "sawa.kalshi_read.list_markets", lambda cfg, **k: [Market("kalshi", "kalshi:T", "K", "open")]
    )
    out = discover.search(CFG, query="x", venues=("sawa", "kalshi"), limit=20)
    venues = sorted(m.venue for m in out)
    assert venues == ["kalshi", "sawa"]
    assert {m.ref for m in out} == {"sawa:1", "kalshi:T"}


def test_search_single_venue_skips_the_other(monkeypatch):
    def must_not_run(cfg, **k):
        raise AssertionError("sawa_read.list_markets should not be called")

    monkeypatch.setattr("sawa.sawa_read.list_markets", must_not_run)
    monkeypatch.setattr(
        "sawa.kalshi_read.list_markets", lambda cfg, **k: [Market("kalshi", "kalshi:T", "K", "open")]
    )
    out = discover.search(CFG, query=None, venues=("kalshi",), limit=20)
    assert [m.venue for m in out] == ["kalshi"]


def test_search_zero_results(monkeypatch):
    monkeypatch.setattr("sawa.sawa_read.list_markets", lambda cfg, **k: [])
    monkeypatch.setattr("sawa.kalshi_read.list_markets", lambda cfg, **k: [])
    assert discover.search(CFG, venues=("sawa", "kalshi")) == []


def test_search_caps_to_limit(monkeypatch):
    monkeypatch.setattr(
        "sawa.sawa_read.list_markets",
        lambda cfg, **k: [Market("sawa", "sawa:%d" % i, "S", "open") for i in range(10)],
    )
    monkeypatch.setattr(
        "sawa.kalshi_read.list_markets",
        lambda cfg, **k: [Market("kalshi", "kalshi:%d" % i, "K", "open") for i in range(10)],
    )
    out = discover.search(CFG, venues=("sawa", "kalshi"), limit=5)
    assert len(out) == 5


def test_search_interleaves_so_neither_venue_starves(monkeypatch):
    # Sawa returns 10, Kalshi returns 10; with a small limit the old concat-then-cap
    # showed only Sawa. Round-robin must include Kalshi within the first few slots.
    monkeypatch.setattr(
        "sawa.sawa_read.list_markets",
        lambda cfg, **k: [Market("sawa", "sawa:%d" % i, "S", "open") for i in range(10)],
    )
    monkeypatch.setattr(
        "sawa.kalshi_read.list_markets",
        lambda cfg, **k: [Market("kalshi", "kalshi:%d" % i, "K", "open") for i in range(10)],
    )
    out = discover.search(CFG, venues=("sawa", "kalshi"), limit=4)
    venues = [m.venue for m in out]
    assert venues == ["sawa", "kalshi", "sawa", "kalshi"]  # fair interleave
