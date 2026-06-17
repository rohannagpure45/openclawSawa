"""Kalshi public market data, GET-only (no auth, no trading).

Kalshi is a real-world DATA SOURCE only -- never a trading venue. Kalshi has no
text-search endpoint, so keyword search works by matching the query against the
cached series index (see ``kalshi_index``), fetching open markets for the top
matching series, and ranking those markets by query-token overlap.
"""

from __future__ import annotations

from typing import List, Optional

from . import cache
from . import http
from . import kalshi_index
from .discover import Market, Outcome

# Kalshi caps page size at 100.
_MAX_PAGE = 100
# Short cache for per-series market fetches: the agent often fires several
# overlapping query variants in a burst, and Kalshi rate-limits (429). Caching
# each series' open markets briefly keeps a burst from hammering the API.
_MARKETS_TTL_SECONDS = 90
# Bounds for a keyword search so a broad query stays cheap.
_DEFAULT_TOP_K = 6        # series considered per search
_PER_SERIES_CAP = 100     # markets fetched per matched series
_TOTAL_FETCH_CAP = 400    # ceiling on the merged pre-ranking pool
_SNAPSHOT_LIMIT_CAP = 100  # page size for the no-query snapshot

# Market-scoring weights (query tokens vs a market's text).
_MW_TITLE = 3.0
_MW_YES = 3.0       # yes_sub_title carries the team/answer (e.g. "Portugal")
_MW_SUBTITLE = 2.0
_MW_TICKER = 1.0
_MW_PHRASE = 2.0


def _market_from_kalshi(raw):
    ticker = raw.get("ticker", "")
    title = raw.get("title") or raw.get("yes_sub_title") or ticker
    subtitle = raw.get("subtitle") or ""
    full_title = title if not subtitle else "%s - %s" % (title, subtitle)
    status = raw.get("status", "")
    deadline = raw.get("close_time")

    # Kalshi quotes YES in cents (0-100) ~ implied probability of YES.
    yes_price = raw.get("last_price")
    if yes_price is None:
        yes_price = raw.get("yes_bid")
    outcomes = []  # type: List[Outcome]
    if yes_price is not None:
        outcomes = [
            Outcome("Yes", float(yes_price)),
            Outcome("No", float(100 - yes_price)),
        ]

    return Market(
        venue="kalshi",
        ref="kalshi:%s" % ticker,
        title=full_title,
        status=status,
        deadline=deadline,
        options=outcomes,
        activity=raw.get("volume"),
    )


def _haystack(raw):
    return " ".join(
        str(raw.get(k, "") or "") for k in ("title", "subtitle", "yes_sub_title", "ticker")
    ).lower()


def _matches(raw, needle):
    return needle in _haystack(raw)


def _score_market(raw, query_tokens, query_text):
    """Score a market by how many query tokens appear in its text (0 if none)."""
    title = (raw.get("title") or "").lower()
    yes = (raw.get("yes_sub_title") or "").lower()
    subtitle = (raw.get("subtitle") or "").lower()
    ticker = (raw.get("ticker") or "").lower()
    score = 0.0
    for tok in query_tokens:
        if tok in title:
            score += _MW_TITLE
        if tok in yes:
            score += _MW_YES
        if tok in subtitle:
            score += _MW_SUBTITLE
        if tok in ticker:
            score += _MW_TICKER
    if len(query_tokens) > 1 and query_text and query_text in _haystack(raw):
        score += _MW_PHRASE
    return score


def _fetch_series_markets(cfg, series_ticker, limit):
    page = max(1, min(limit, _MAX_PAGE))

    def fetch():
        url = http.build_url(
            "%s/markets" % cfg.kalshi_base,
            {"series_ticker": series_ticker, "status": "open", "limit": page},
        )
        return http.get_json(url).get("markets", []) or []

    return cache.load_or_fetch("kalshi_markets_%s_%d" % (series_ticker, page), _MARKETS_TTL_SECONDS, fetch)


def list_markets(cfg, *, search=None, series=None, category=None, limit=20):
    """List open Kalshi markets.

    - explicit ``series``: fetch that one series (optionally substring-filtered by
      ``search``). Used by callers that already know the series.
    - ``search`` (no series): match the query against the series index, fetch the
      top matching series' open markets, and rank them by query-token overlap.
      ``category`` optionally narrows the index to one Kalshi category.
    - neither: a cheap snapshot (first page of open markets) for ``/suggest``.

    Note: finding a series from a bare team name (e.g. "Portugal") relies on a
    topic word in the query (e.g. "world cup"); the agent expands such queries.
    """
    # 1) Explicit single series.
    if series:
        collected = _fetch_series_markets(cfg, series, limit)
        if search:
            needle = search.lower()
            collected = [raw for raw in collected if _matches(raw, needle)]
        return [_market_from_kalshi(raw) for raw in collected][:limit]

    # 2) Keyword search via the series index.
    if search:
        matched = kalshi_index.find_series(cfg, search, category=category, top_k=_DEFAULT_TOP_K)
        if not matched:
            return []
        pool = []  # type: List[dict]
        for s in matched:
            if len(pool) >= _TOTAL_FETCH_CAP:
                break
            pool.extend(_fetch_series_markets(cfg, s.get("ticker", ""), _PER_SERIES_CAP))
        pool = pool[:_TOTAL_FETCH_CAP]
        tokens = kalshi_index._tokenize(search)
        query_text = " ".join(tokens)
        scored = [(raw, _score_market(raw, tokens, query_text)) for raw in pool]
        if any(score > 0 for _, score in scored):
            scored.sort(key=lambda item: (-item[1], -(item[0].get("volume") or 0), item[0].get("ticker") or ""))
            ordered = [raw for raw, _ in scored]
        else:
            # series matched on tag/category but market titles are bare -- show them anyway
            ordered = pool
        return [_market_from_kalshi(raw) for raw in ordered][:limit]

    # 3) Snapshot (no query) -- cheap single page for /suggest.
    url = http.build_url(
        "%s/markets" % cfg.kalshi_base,
        {"status": "open", "limit": max(1, min(limit, _SNAPSHOT_LIMIT_CAP))},
    )
    collected = http.get_json(url).get("markets", []) or []
    return [_market_from_kalshi(raw) for raw in collected][:limit]


def get_market(cfg, ticker):
    """Fetch a single market by ticker. Returns a Market, or None if not found."""
    url = http.build_url("%s/markets/%s" % (cfg.kalshi_base, ticker))
    try:
        payload = http.get_json(url)
    except http.HttpError as exc:
        if getattr(exc, "status", None) == 404:
            return None
        raise
    raw = payload.get("market")
    if not raw:
        return None
    return _market_from_kalshi(raw)
