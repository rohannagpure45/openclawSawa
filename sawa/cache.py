"""Tiny on-disk TTL cache (stdlib only, local files -- never a network sink).

Used to avoid re-fetching slow-changing data (the Kalshi series index) on every
search. Reads/writes a JSON file under ``$SAWA_CACHE_DIR`` (default ~/.sawa/cache).
All failure modes degrade quietly: a miss/expired/corrupt entry returns None, and
a write failure returns False without raising, so callers fall back to live data.

This module performs only local file I/O -- no HTTP, no urllib -- so it preserves
the package's read-only-by-construction guarantee.
"""

from __future__ import annotations

import json
import os
import tempfile
import time

CACHE_ENV = "SAWA_CACHE_DIR"
DEFAULT_CACHE_DIR = "~/.sawa/cache"


def cache_dir():
    """Return the cache directory path ($SAWA_CACHE_DIR or ~/.sawa/cache)."""
    return os.path.expanduser(os.environ.get(CACHE_ENV) or DEFAULT_CACHE_DIR)


def _path_for(key):
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in key)
    return os.path.join(cache_dir(), safe + ".json")


def load(key, ttl_seconds):
    """Return the cached payload if present and younger than ttl, else None.

    Any error (missing file, unreadable, malformed JSON, missing keys) yields
    None so the caller treats it as a cache miss.
    """
    try:
        with open(_path_for(key), "r", encoding="utf-8") as fh:
            envelope = json.load(fh)
        stored_at = float(envelope["stored_at"])
        if (time.time() - stored_at) >= ttl_seconds:
            return None
        return envelope["payload"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def store(key, payload):
    """Atomically write {stored_at, payload}. Return True on success, else False.

    Never raises -- a read-only filesystem or permission error just means the
    caller keeps using the freshly fetched value in memory.
    """
    directory = cache_dir()
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        envelope = {"stored_at": time.time(), "payload": payload}
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(envelope, fh)
            os.replace(tmp, _path_for(key))
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return True
    except (OSError, TypeError, ValueError):
        return False


def load_or_fetch(key, ttl_seconds, fetch_fn):
    """Return the cached value, or call fetch_fn(), store it best-effort, return it.

    Errors raised by fetch_fn (e.g. http.HttpError) propagate to the caller.
    """
    cached = load(key, ttl_seconds)
    if cached is not None:
        return cached
    value = fetch_fn()
    store(key, value)
    return value
