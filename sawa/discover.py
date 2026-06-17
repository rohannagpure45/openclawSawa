"""Venue-neutral market types and cross-venue fan-out/merge.

The dataclasses are the common shape every reader returns; ``search`` (added at
the WALK stage) fans out to each venue reader and merges the results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import List, Optional


@dataclass
class Outcome:
    label: str
    odds_pct: Optional[float] = None


@dataclass
class Market:
    venue: str                                  # "sawa" | "kalshi"
    ref: str                                    # "sawa:<id>" | "kalshi:<TICKER>"
    title: str
    status: str
    deadline: Optional[str] = None
    options: List[Outcome] = field(default_factory=list)
    activity: Optional[int] = None
    description: Optional[str] = None           # detail-only (show); list views may omit
    url: Optional[str] = None                   # tappable market-page link (None if unknown)


def market_to_dict(market):
    """Serialize a Market (with nested Outcomes) into plain dict for --json."""
    return asdict(market)


def _interleave(groups):
    """Round-robin merge of per-venue result lists so neither venue starves the
    other when the combined total exceeds ``limit`` (a small limit otherwise gets
    filled entirely by whichever venue is concatenated first)."""
    merged = []  # type: List[Market]
    i = 0
    while True:
        took = False
        for group in groups:
            if i < len(group):
                merged.append(group[i])
                took = True
        if not took:
            break
        i += 1
    return merged


def search(cfg, query=None, venues=("sawa", "kalshi"), limit=20):
    """Fan out to the requested venue readers, round-robin merge, cap to ``limit``.

    Each reader labels its own results (venue/ref). Results are interleaved across
    venues (not concatenated venue-by-venue) so a small ``limit`` shows a fair mix
    rather than only the first venue's markets.
    """
    groups = []  # type: List[List[Market]]
    if "sawa" in venues:
        from . import sawa_read
        groups.append(sawa_read.list_markets(cfg, search=query, limit=limit))
    if "kalshi" in venues:
        from . import kalshi_read
        groups.append(kalshi_read.list_markets(cfg, search=query, limit=limit))
    return _interleave(groups)[:limit]
