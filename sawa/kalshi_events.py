"""Kalshi event index + query ranking (GET-only).

The series index (``kalshi_index``) matches a query against series *titles* — great
for topic words ("world cup", "nba") but blind to team/player names, which live only
at the **event** level. e.g. the series "World Cup Team Head to Head" carries no team
name, but its events are "England vs Spain", "Croatia vs Uruguay", ... So a query like
"england croatia" can never be found via series titles alone.

This module fills that gap: ``GET /events?status=open`` enumerates every open event
(each small: ticker, title, sub_title, series, category). We page through them once,
cache the result on disk (it changes slowly), and rank events by query-token overlap —
enriched with their series' title/tags so topic words still help. The caller then
fetches open markets for the top events.
"""

from __future__ import annotations

from typing import Dict, List, Set, Tuple

from . import cache
from . import http
from . import kalshi_index

EVENTS_CACHE_KEY = "kalshi_events"
EVENTS_TTL_SECONDS = 24 * 60 * 60  # events change slowly; refetch daily
_PAGE_SIZE = 200                   # Kalshi caps /events at 200 per page
_MAX_PAGES = 45                    # ~7.6k open events today; headroom, bounds a cold build

# Scoring weights for matching query tokens against an event.
_EW_TITLE = 3.0       # event title, e.g. "England vs Spain: Who Will Go Further"
_EW_SUBTITLE = 2.0    # event sub_title, e.g. "ENG vs ESP (2026)"
_EW_SERIES = 1.0      # the event's series title/tags/category (topic context)
_EW_PHRASE = 2.0      # whole multi-word query appears in the title


def _fetch_events_index(cfg):
    """Page through all open events, keeping only the fields we rank on."""
    events = []  # type: List[Dict]
    cursor = None
    pages = 0
    while pages < _MAX_PAGES:
        params = {"status": "open", "limit": _PAGE_SIZE}
        if cursor:
            params["cursor"] = cursor
        url = http.build_url("%s/events" % cfg.kalshi_base, params)
        payload = http.get_json(url)
        batch = (payload.get("events") if isinstance(payload, dict) else None) or []
        for row in batch:
            events.append({
                "event_ticker": row.get("event_ticker", "") or "",
                "title": row.get("title", "") or "",
                "sub_title": row.get("sub_title", "") or "",
                "series_ticker": row.get("series_ticker", "") or "",
                "category": row.get("category", "") or "",
            })
        cursor = payload.get("cursor") if isinstance(payload, dict) else None
        pages += 1
        if not cursor or not batch:
            break
    return events


def get_events_index(cfg):
    """Return the cached open-events index, fetching+caching it on miss/expiry."""
    return cache.load_or_fetch(
        EVENTS_CACHE_KEY, EVENTS_TTL_SECONDS, lambda: _fetch_events_index(cfg)
    )


def _score_event(event, tokens, query_text, series_by_ticker):
    """Return (score, covered_tokens) for one event against the query tokens."""
    title = (event.get("title") or "").lower()
    sub = (event.get("sub_title") or "").lower()
    series = series_by_ticker.get(event.get("series_ticker") or "") or {}
    s_title = (series.get("title") or "").lower()
    s_tags = " ".join(series.get("tags") or []).lower()
    s_cat = (series.get("category") or "").lower()

    score = 0.0
    covered = set()  # type: Set[str]
    for tok in tokens:
        hit = False
        if tok in title:
            score += _EW_TITLE
            hit = True
        if tok in sub:
            score += _EW_SUBTITLE
            hit = True
        if tok in s_title or tok in s_tags or tok in s_cat:
            score += _EW_SERIES
            hit = True
        if hit:
            covered.add(tok)
    if len(tokens) > 1 and query_text and query_text in title:
        score += _EW_PHRASE
    return score, covered


def find_events(cfg, query, top_k=8):
    """Return up to ``top_k`` open events matching the query, best first.

    Selection is **token-coverage aware**: each query token's single best event is
    guaranteed a slot before the rest fill by score. This keeps a rarer token
    (e.g. "croatia") from being starved by a common one (e.g. "england", which
    matches many events). Returns [] when nothing scores above zero.
    """
    tokens = kalshi_index._tokenize(query)
    if not tokens:
        return []
    query_text = " ".join(tokens)
    index = get_events_index(cfg)
    series_by_ticker = {
        s.get("ticker", ""): s for s in (kalshi_index.get_series_index(cfg) or [])
    }

    scored = []  # type: List[Tuple[float, Set[str], Dict]]
    for event in index:
        score, covered = _score_event(event, tokens, query_text, series_by_ticker)
        if score > 0:
            scored.append((score, covered, event))
    if not scored:
        return []
    # Best score first; tie-break shorter title, then ticker for determinism.
    scored.sort(key=lambda it: (-it[0], len(it[2].get("title") or ""), it[2].get("event_ticker") or ""))

    selected = []  # type: List[Dict]
    seen = set()   # type: Set[str]

    def _take(event):
        et = event.get("event_ticker") or ""
        if et and et not in seen:
            seen.add(et)
            selected.append(event)

    # 1) one slot per query token: that token's highest-scoring event.
    for tok in tokens:
        for _, covered, event in scored:
            if tok in covered:
                _take(event)
                break
    # 2) fill the rest by overall score.
    for _, _, event in scored:
        if len(selected) >= top_k:
            break
        _take(event)
    return selected[:top_k]
