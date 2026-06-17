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
from . import kalshi_events
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
_EVENT_TOP_K = 8          # events considered when a token isn't covered by a series
_PER_SERIES_CAP = 100     # markets fetched per matched series
_PER_EVENT_CAP = 50       # markets fetched per matched event
_TOTAL_FETCH_CAP = 400    # ceiling on the merged pre-ranking pool
_SNAPSHOT_LIMIT_CAP = 100  # page size for the no-query snapshot

# Market-scoring weights (query tokens vs a market's text).
_MW_TITLE = 3.0
_MW_YES = 3.0       # yes_sub_title carries the team/answer (e.g. "Portugal")
_MW_SUBTITLE = 2.0
_MW_TICKER = 1.0
_MW_PHRASE = 2.0

# Public web base for a tappable market link. kalshi.com routes /markets/<series>
# to the series page (which lists the event/market); we lowercase the series ticker
# derived from the market ticker's leading segment.
_KALSHI_WEB_BASE = "https://kalshi.com/markets"


def _parse_float(value):
    """Best-effort float parse for Kalshi's stringified numeric fields."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _yes_pct(raw):
    """Implied YES probability as a 0-100 percentage, or None.

    Kalshi migrated prices to dollar-denominated strings (0.0000-1.0000): prefer
    ``last_price_dollars``; fall back to the bid/ask midpoint, then the bid alone.
    """
    last = _parse_float(raw.get("last_price_dollars"))
    if last is not None and last > 0:
        return round(last * 100, 1)
    bid = _parse_float(raw.get("yes_bid_dollars"))
    ask = _parse_float(raw.get("yes_ask_dollars"))
    if bid is not None and ask is not None and (bid > 0 or ask > 0):
        return round((bid + ask) / 2 * 100, 1)
    if bid is not None and bid > 0:
        return round(bid * 100, 1)
    if last is not None:  # genuine zero last price (e.g. 0.0000)
        return round(last * 100, 1)
    return None


def _kalshi_volume(raw):
    vol = _parse_float(raw.get("volume_fp"))
    if vol is None:
        return None
    return int(vol) or None


def _kalshi_url(ticker):
    """Best-effort deep link to the market's series page on kalshi.com."""
    if not ticker:
        return None
    series = ticker.split("-")[0].lower()
    return "%s/%s" % (_KALSHI_WEB_BASE, series) if series else None


def _market_from_kalshi(raw):
    ticker = raw.get("ticker", "")
    title = raw.get("title") or raw.get("yes_sub_title") or ticker
    subtitle = raw.get("subtitle") or ""
    full_title = title if not subtitle else "%s - %s" % (title, subtitle)
    status = raw.get("status", "")
    deadline = raw.get("close_time")

    pct = _yes_pct(raw)
    outcomes = []  # type: List[Outcome]
    if pct is not None:
        outcomes = [
            Outcome("Yes", pct),
            Outcome("No", round(100 - pct, 1)),
        ]

    return Market(
        venue="kalshi",
        ref="kalshi:%s" % ticker,
        title=full_title,
        status=status,
        deadline=deadline,
        options=outcomes,
        activity=_kalshi_volume(raw),
        url=_kalshi_url(ticker),
    )


def _haystack(raw):
    return " ".join(
        str(raw.get(k, "") or "")
        for k in ("title", "subtitle", "yes_sub_title", "ticker", "event_ticker")
    ).lower()


def _matches(raw, needle):
    return needle in _haystack(raw)


def _score_market(raw, query_tokens, query_text):
    """Score a market by how many query tokens appear in its text (0 if none)."""
    title = (raw.get("title") or "").lower()
    yes = (raw.get("yes_sub_title") or "").lower()
    subtitle = (raw.get("subtitle") or "").lower()
    ticker = (raw.get("ticker") or "").lower()
    event_ticker = (raw.get("event_ticker") or "").lower()
    score = 0.0
    for tok in query_tokens:
        if tok in title:
            score += _MW_TITLE
        if tok in yes:
            score += _MW_YES
        if tok in subtitle:
            score += _MW_SUBTITLE
        if tok in ticker or tok in event_ticker:
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


def _fetch_event_markets(cfg, event_ticker, limit):
    page = max(1, min(limit, _MAX_PAGE))

    def fetch():
        url = http.build_url(
            "%s/markets" % cfg.kalshi_base,
            {"event_ticker": event_ticker, "status": "open", "limit": page},
        )
        return http.get_json(url).get("markets", []) or []

    return cache.load_or_fetch("kalshi_evmarkets_%s_%d" % (event_ticker, page), _MARKETS_TTL_SECONDS, fetch)


def _dedupe_by_ticker(raws):
    seen = set()
    out = []  # type: List[dict]
    for raw in raws:
        ticker = raw.get("ticker", "")
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(raw)
    return out


def list_markets(cfg, *, search=None, series=None, category=None, limit=20):
    """List open Kalshi markets.

    - explicit ``series``: fetch that one series (optionally substring-filtered by
      ``search``). Used by callers that already know the series.
    - ``search`` (no series): match the query against BOTH the series index (good for
      topic words like "world cup") and the event index (good for team/player names
      like "england croatia", which live only at the event level). Fetch open markets
      for the top series/events, merge, and rank by query-token overlap. ``category``
      optionally narrows the series index to one Kalshi category.
    - neither: a cheap snapshot (first page of open markets) for ``/suggest``.

    Both indexes are consulted on every keyword search: a token can be "covered" by an
    irrelevant series (e.g. "croatia" -> a President-of-Croatia series) yet the real
    markets live at the event level, so series coverage can't gate the event lookup.
    The event index is cached (and warmed by ``sawa warm``); token-overlap ranking
    floats the most on-topic markets to the top of the merged pool.
    """
    # 1) Explicit single series.
    if series:
        collected = _fetch_series_markets(cfg, series, limit)
        if search:
            needle = search.lower()
            collected = [raw for raw in collected if _matches(raw, needle)]
        return [_market_from_kalshi(raw) for raw in collected][:limit]

    # 2) Keyword search: series index (topics) + event index (team/player names).
    if search:
        tokens = kalshi_index._tokenize(search)
        query_text = " ".join(tokens)

        pool = []  # type: List[dict]
        for s in kalshi_index.find_series(cfg, search, category=category, top_k=_DEFAULT_TOP_K):
            if len(pool) >= _TOTAL_FETCH_CAP:
                break
            pool.extend(_fetch_series_markets(cfg, s.get("ticker", ""), _PER_SERIES_CAP))

        # Team/player names live at the event level; always consult the event index.
        if tokens:
            for event in kalshi_events.find_events(cfg, search, top_k=_EVENT_TOP_K):
                if len(pool) >= _TOTAL_FETCH_CAP:
                    break
                pool.extend(_fetch_event_markets(cfg, event.get("event_ticker", ""), _PER_EVENT_CAP))

        pool = _dedupe_by_ticker(pool)[:_TOTAL_FETCH_CAP]
        if not pool:
            return []
        scored = [(raw, _score_market(raw, tokens, query_text)) for raw in pool]
        if any(score > 0 for _, score in scored):
            scored.sort(key=lambda item: (-item[1], -(_kalshi_volume(item[0]) or 0), item[0].get("ticker") or ""))
            ordered = [raw for raw, _ in scored]
        else:
            # series/events matched on tag/category but market titles are bare -- show them anyway
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
