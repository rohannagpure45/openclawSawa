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


def _expire(key):
    """Force an existing entry's stored_at to the epoch (very old)."""
    path = cache._path_for(key)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    data["stored_at"] = 0.0
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def test_load_allow_stale_returns_expired():
    cache.store("k", {"a": 1})
    _expire("k")
    assert cache.load("k", 60) is None                       # expired -> miss
    assert cache.load("k", 60, allow_stale=True) == {"a": 1}  # stale served
    assert cache.load("nope", 60, allow_stale=True) is None   # absent -> still None


def test_load_or_fetch_stale_fresh_hit_no_fetch():
    cache.store("k", ["fresh"])
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return ["live"]

    assert cache.load_or_fetch_stale("k", 3600, fetch) == ["fresh"]
    assert calls["n"] == 0  # fresh cache used, never fetched


def test_load_or_fetch_stale_serves_stale_without_fetch():
    """The critical path: an expired-but-present index must NOT trigger a build."""
    cache.store("k", ["old"])
    _expire("k")
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return ["rebuilt"]

    assert cache.load_or_fetch_stale("k", 60, fetch) == ["old"]
    assert calls["n"] == 0  # stale served, slow rebuild skipped


def test_load_or_fetch_stale_fetches_only_when_absent():
    calls = {"n": 0}

    def fetch():
        calls["n"] += 1
        return ["built"]

    assert cache.load_or_fetch_stale("k", 60, fetch) == ["built"]  # cold -> build
    assert calls["n"] == 1
    assert cache.load_or_fetch_stale("k", 60, fetch) == ["built"]  # now cached
    assert calls["n"] == 1
