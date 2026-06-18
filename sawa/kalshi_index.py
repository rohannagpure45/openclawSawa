"""Kalshi series index + query ranking (GET-only).

Kalshi has no full-text search endpoint, but ``GET /series`` returns the entire
catalog of ~11k series in one call, each with a human title, tags, and category.
That is the small, stable topic index we match a user's query against; the caller
then fetches open markets for the top-ranked series. The index is cached on disk
(it changes slowly) so only the first search per TTL window pays the fetch.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from . import cache
from . import http

SERIES_CACHE_KEY = "kalshi_series"
SERIES_TTL_SECONDS = 12 * 60 * 60  # series change slowly; refetch twice a day

# Scoring weights for matching query tokens against a series.
_W_TITLE = 3.0
_W_TAG = 2.0
_W_CATEGORY = 1.0
_W_TICKER = 1.0
_W_PHRASE = 2.0  # bonus when the whole multi-word query appears in the title

# Low-signal words that should not drive matching.
_STOPWORDS = frozenset([
    "the", "a", "an", "of", "on", "in", "for", "to", "and", "or", "is", "are",
    "be", "will", "who", "what", "which", "when", "where", "game", "games",
    "match", "find", "me", "show", "get", "market", "markets", "bet", "bets",
    "odds", "win", "wins", "winner", "next", "this", "that", "any", "some",
])


def _tokenize(text):
    """Lowercase, split on non-alphanumerics, drop stopwords/short tokens, dedupe."""
    tokens = []  # type: List[str]
    seen = set()
    current = []
    for ch in (text or "").lower():
        if ch.isalnum():
            current.append(ch)
        elif current:
            tokens.append("".join(current))
            current = []
    if current:
        tokens.append("".join(current))
    out = []  # type: List[str]
    for tok in tokens:
        if len(tok) < 2 or tok in _STOPWORDS or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
    return out


def _fetch_series_index(cfg):
    """GET the full series catalog, keeping only the fields we rank on."""
    url = http.build_url("%s/series" % cfg.kalshi_base)
    payload = http.get_json(url)
    rows = payload.get("series", []) if isinstance(payload, dict) else (payload or [])
    index = []  # type: List[Dict]
    for row in rows:
        index.append({
            "ticker": row.get("ticker", ""),
            "title": row.get("title", "") or "",
            "tags": [t for t in (row.get("tags") or []) if isinstance(t, str)],
            "category": row.get("category", "") or "",
        })
    return index


def get_series_index(cfg, refresh=False):
    """Return the series index.

    Interactive callers (``refresh=False``) read stale-while-revalidate: a fresh
    cache is used, else an expired on-disk copy is served WITHOUT a blocking
    rebuild (only a truly-empty cache fetches inline). ``refresh=True`` forces a
    live fetch and re-stores it -- used by ``sawa warm`` to refresh off the
    interactive critical path. Building this index cold is slow (a large
    ``GET /series``), so it must never block a user's search once warmed.
    """
    if refresh:
        value = _fetch_series_index(cfg)
        cache.store(SERIES_CACHE_KEY, value)
        return value
    return cache.load_or_fetch_stale(
        SERIES_CACHE_KEY, SERIES_TTL_SECONDS, lambda: _fetch_series_index(cfg)
    )


def _score_series(series, query_tokens, query_text):
    title = (series.get("title") or "").lower()
    ticker = (series.get("ticker") or "").lower()
    category = (series.get("category") or "").lower()
    tags = " ".join(series.get("tags") or []).lower()
    score = 0.0
    for tok in query_tokens:
        if tok in title:
            score += _W_TITLE
        if tok in tags:
            score += _W_TAG
        if tok in category:
            score += _W_CATEGORY
        if tok in ticker:
            score += _W_TICKER
    if len(query_tokens) > 1 and query_text and query_text in title:
        score += _W_PHRASE
    return score


def find_series(cfg, query, category=None, top_k=8):
    """Return up to top_k series matching the query, highest score first.

    ``category`` (optional) restricts to a Kalshi category (case-insensitive).
    Returns [] when the query has no usable tokens or nothing scores above zero.
    """
    tokens = _tokenize(query)
    if not tokens:
        return []
    query_text = " ".join(tokens)
    index = get_series_index(cfg)
    cat = category.lower() if category else None

    scored = []  # type: List[tuple]
    for series in index:
        if cat and (series.get("category") or "").lower() != cat:
            continue
        score = _score_series(series, tokens, query_text)
        if score > 0:
            # tie-break: higher score, then shorter title, then ticker
            scored.append((-score, len(series.get("title") or ""), series.get("ticker") or "", series))
    scored.sort()
    return [item[3] for item in scored[:top_k]]
