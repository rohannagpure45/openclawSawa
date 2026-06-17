from sawa import analyze
from sawa.config import Config
from sawa.discover import Market

CFG = Config(supabase_url="https://db", supabase_key="k", kalshi_base="x")


def test_suggest_payload_shape(monkeypatch):
    snapshot = [
        Market("sawa", "sawa:1", "S", "open"),
        Market("kalshi", "kalshi:T", "K", "open"),
    ]
    monkeypatch.setattr("sawa.discover.search", lambda cfg, **k: snapshot)
    payload = analyze.suggest_payload(CFG, ["who wins the game?", "lakers!"])
    assert set(payload.keys()) == {"market_snapshot", "messages", "guidance"}
    assert payload["messages"] == ["who wins the game?", "lakers!"]
    assert payload["market_snapshot"][0]["ref"] == "sawa:1"
    assert payload["market_snapshot"][1]["venue"] == "kalshi"
    assert "demo" in payload["guidance"].lower()


def test_suggest_payload_empty_messages(monkeypatch):
    monkeypatch.setattr("sawa.discover.search", lambda cfg, **k: [])
    payload = analyze.suggest_payload(CFG, [])
    assert payload["messages"] == []
    assert payload["market_snapshot"] == []


def test_suggest_payload_passes_limit(monkeypatch):
    captured = {}

    def fake_search(cfg, **k):
        captured.update(k)
        return []

    monkeypatch.setattr("sawa.discover.search", fake_search)
    analyze.suggest_payload(CFG, [], limit=7)
    assert captured["limit"] == 7
