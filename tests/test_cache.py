import json

import pytest

from sawa import cache


@pytest.fixture(autouse=True)
def _cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SAWA_CACHE_DIR", str(tmp_path / "c"))


def test_store_then_load_roundtrip():
    assert cache.store("k", {"a": 1, "b": [2, 3]}) is True
    assert cache.load("k", 3600) == {"a": 1, "b": [2, 3]}


def test_load_miss_when_absent():
    assert cache.load("nope", 3600) is None


def test_load_expired_returns_none():
    cache.store("k", {"a": 1})
    path = cache._path_for("k")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["stored_at"] = 0.0  # epoch 1970 -> very old
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    assert cache.load("k", 60) is None          # expired
    assert cache.load("k", 10 ** 12) == {"a": 1}  # huge ttl -> still fresh


def test_load_corrupt_returns_none():
    cache.store("k", {"a": 1})
    with open(cache._path_for("k"), "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert cache.load("k", 3600) is None


def test_store_failure_degrades(tmp_path, monkeypatch):
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file")
    monkeypatch.setenv("SAWA_CACHE_DIR", str(blocker / "sub"))  # parent is a file
    assert cache.store("k", {"a": 1}) is False
    # load_or_fetch still returns the live value despite the failed write
    assert cache.load_or_fetch("k", 3600, lambda: "live") == "live"


def test_load_or_fetch_caches_one_fetch():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return ["payload"]

    assert cache.load_or_fetch("k", 3600, fetch) == ["payload"]
    assert cache.load_or_fetch("k", 3600, fetch) == ["payload"]
    assert calls["n"] == 1  # second call served from cache
