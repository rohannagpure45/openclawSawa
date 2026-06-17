"""Stub create -- the only write-shaped command.

Pure local: performs NO I/O of any kind (no network, no DB, no disk). It echoes
what *would* be created and states plainly that nothing was created. Real creation
lands in the order-engine phase. This module deliberately imports neither ``http``
nor ``config`` so there is no code path to a side effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

_STUB_MESSAGE = (
    "Not created -- create lands in the order-engine phase (writes not wired yet)."
)


@dataclass
class StubResult:
    created: bool
    stub: bool
    message: str
    would_create: Dict[str, object]


def stub_create(question, outcomes, league=None):
    """Echo a would-be market without creating anything. No I/O."""
    return StubResult(
        created=False,
        stub=True,
        message=_STUB_MESSAGE,
        would_create={
            "question": question,
            "outcomes": list(outcomes),
            "league": league,
        },
    )
