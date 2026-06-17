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


def market_to_dict(market):
    """Serialize a Market (with nested Outcomes) into plain dict for --json."""
    return asdict(market)


def search(cfg, query=None, venues=("sawa", "kalshi"), limit=20):
    """Fan out to the requested venue readers, merge, and cap to ``limit``.

    Each reader labels its own results (venue/ref), so merging is concatenation
    in venue order followed by a hard cap.
    """
    results = []  # type: List[Market]
    if "sawa" in venues:
        from . import sawa_read
        results.extend(sawa_read.list_markets(cfg, search=query, limit=limit))
    if "kalshi" in venues:
        from . import kalshi_read
        results.extend(kalshi_read.list_markets(cfg, search=query, limit=limit))
    return results[:limit]
