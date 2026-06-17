"""Tiny stdlib HTTP helper -- the ONLY network module in the package.

GET-only by construction: ``get_json`` builds a read request with no body and an
explicit GET method. There is deliberately no helper here (or anywhere else in
the package) that sends a request body or any other HTTP method. This property
is pinned by ``tests/test_readonly.py``.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 10
# Transient statuses worth a brief retry (rate-limit / temporarily unavailable).
_RETRY_STATUSES = frozenset((429, 503))
_MAX_RETRIES = 2
_MAX_BACKOFF = 5.0


class HttpError(Exception):
    """Network/upstream failure. ``status`` is the HTTP code when one exists."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def build_url(base, params=None):
    """Join a base URL with query params, preserving PostgREST/Kalshi syntax.

    Keeps ``(),*:.`` unescaped so embedded selects (``Option(id,label)``),
    operators (``eq.false``) and ilike wildcards (``*temp*``) survive intact.
    """
    if not params:
        return base
    query = urllib.parse.urlencode(params, safe="(),*:.")
    sep = "&" if "?" in base else "?"
    return base + sep + query


def _retry_after_seconds(exc, attempt):
    """Backoff before a retry: honor a Retry-After header, else exponential."""
    delay = None
    headers = getattr(exc, "headers", None)
    if headers is not None:
        raw = headers.get("Retry-After")
        if raw:
            try:
                delay = float(raw)
            except (TypeError, ValueError):
                delay = None
    if delay is None:
        delay = 0.5 * (2 ** attempt)
    return min(_MAX_BACKOFF, max(0.0, delay))


def get_json(url, headers=None, timeout=DEFAULT_TIMEOUT):
    """Perform a GET request and return parsed JSON (dict or list).

    Retries briefly on transient rate-limit / unavailable statuses (429/503).
    Raises HttpError on other non-2xx status, network failure, timeout, or
    unparseable body. No request body is ever sent and the method is fixed to GET.
    """
    attempt = 0
    while True:
        request = urllib.request.Request(url, headers=headers or {}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
                status = response.getcode()
        except urllib.error.HTTPError as exc:
            if exc.code in _RETRY_STATUSES and attempt < _MAX_RETRIES:
                time.sleep(_retry_after_seconds(exc, attempt))
                attempt += 1
                continue
            raise HttpError("upstream returned status %s" % exc.code, status=exc.code)
        except OSError as exc:
            # URLError (DNS/connection) and socket timeout both subclass OSError.
            raise HttpError("network error: %s" % exc)

        if status is not None and status >= 400:
            raise HttpError("upstream returned status %s" % status, status=status)

        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise HttpError("invalid JSON from upstream: %s" % exc)
