import json

import pytest

from sawa import cli
from sawa import config as config_mod
from sawa.config import Config
from sawa.discover import Market, Outcome

CFG = Config(supabase_url="", supabase_key="", kalshi_base="https://demo.example/v2")


@pytest.fixture(autouse=True)
def _stub_config(monkeypatch):
    monkeypatch.setattr(cli.config, "get_config", lambda *a, **k: CFG)


def test_markets_kalshi_json_envelope(monkeypatch, capsys):
    sample = [Market(venue="kalshi", ref="kalshi:T1", title="High temp", status="open",
                     options=[Outcome("Yes", 60.0), Outcome("No", 40.0)])]
    monkeypatch.setattr("sawa.kalshi_read.list_markets", lambda cfg, **k: sample)
    rc = cli.main(["markets", "--venue", "kalshi", "--search", "temp", "--limit", "5", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["command"] == "markets"
    assert out["error"] is None
    assert out["data"][0]["ref"] == "kalshi:T1"
    assert out["data"][0]["options"][0] == {"label": "Yes", "odds_pct": 60.0}


def test_unknown_flag_exits_2():
    with pytest.raises(SystemExit) as info:
        cli.main(["markets", "--venue", "kalshi", "--bogus"])
    assert info.value.code == 2


def test_missing_subcommand_exits_2():
    with pytest.raises(SystemExit) as info:
        cli.main([])
    assert info.value.code == 2


def test_config_missing_exits_4_with_envelope(monkeypatch, capsys):
    # Sawa venue requires supabase creds; CFG has none -> ConfigError -> exit 4.
    rc = cli.main(["markets", "--venue", "sawa", "--json"])
    assert rc == 4
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["code"] == "config_missing"


def test_upstream_error_exits_3(monkeypatch, capsys):
    def boom(cfg, **k):
        raise cli.http.HttpError("upstream returned status 500", status=500)

    monkeypatch.setattr("sawa.kalshi_read.list_markets", boom)
    rc = cli.main(["markets", "--venue", "kalshi", "--json"])
    assert rc == 3
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["code"] == "upstream"


def test_show_kalshi_requires_ticker(monkeypatch, capsys):
    # --id with kalshi venue is a usage error -> exit 2.
    rc = cli.main(["show", "--venue", "kalshi", "--id", "abc", "--json"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "usage"


def test_markets_human_output(monkeypatch, capsys):
    sample = [Market(venue="kalshi", ref="kalshi:T1", title="High temp", status="open")]
    monkeypatch.setattr("sawa.kalshi_read.list_markets", lambda cfg, **k: sample)
    rc = cli.main(["markets", "--venue", "kalshi"])
    assert rc == 0
    assert "High temp" in capsys.readouterr().out
