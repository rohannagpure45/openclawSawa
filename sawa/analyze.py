"""One-shot data provider for the OpenClaw agent.

``suggest_payload`` gathers a read-only market snapshot plus the supplied chat
messages and returns them as a plain dict. There is NO LLM call here -- the
reasoning ("propose new market ideas") happens in the OpenClaw agent, which
reads this payload. Keeping the model out of the CLI means no LLM key on device.
"""

from __future__ import annotations

from typing import List

from . import discover

_GUIDANCE = (
    "Propose 1-3 NEW market ideas the group could create. Markets are virtual "
    "(Sawa coins, no cash value). Label every suggestion as a demo. Never surface PII."
)


def suggest_payload(cfg, messages, limit=20):
    """Return {market_snapshot, messages, guidance} for the agent to reason over."""
    snapshot = discover.search(cfg, query=None, venues=("sawa", "kalshi"), limit=limit)
    return {
        "market_snapshot": [discover.market_to_dict(market) for market in snapshot],
        "messages": list(messages),
        "guidance": _GUIDANCE,
    }
