"""Sawa Phase-1 read-only market discovery CLI (stdlib only, Python 3.9).

Read-only by construction: the only network module is ``sawa.http`` and it
exposes a single GET helper. No code path in this package issues a write.
"""

__version__ = "0.1.0"
