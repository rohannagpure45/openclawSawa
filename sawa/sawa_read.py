"""Supabase PostgREST reader -- GET-only, public markets, no PII.

Every query hard-codes ``isPrivate=eq.false`` & ``isHidden=eq.false`` and selects
only an explicit allowlist of market columns. The ``User`` table
(email/phone/password/googleId) is never queried and never embedded, so no PII
can reach chat. Current odds come from the latest OddsSnapshot per option.
"""

from __future__ import annotations

from typing import List, Optional

from . import http
from .discover import Market, Outcome

# Column allowlist -- market data only. No User join, no PII columns.
# OddsSnapshot has no PostgREST-detectable FK to Option, so we embed it as a
# SIBLING of Option (both hang off Prediction) and join odds->option in Python.
_SELECT = (
    "id,title,description,category,deadline,resolved,isPrivate,isHidden,createdAt,"
    "Option(id,label),"
    "OddsSnapshot(optionId,percentage,createdAt)"
)

_BASE_PATH = "/rest/v1/Prediction"


def _headers(cfg):
    return {
        "apikey": cfg.supabase_key,
        "Authorization": "Bearer %s" % cfg.supabase_key,
        "Accept": "application/json",
    }


def _latest_pct_by_option(snapshots):
    """Map each optionId to the percentage of its most recent OddsSnapshot.

    Snapshots arrive as a flat list for the whole prediction (sibling embed), so
    we keep the latest-by-createdAt per option.
    """
    latest = {}  # optionId -> (createdAt, percentage)
    for snap in snapshots or []:
        option_id = snap.get("optionId")
        if option_id is None:
            continue
        created = snap.get("createdAt") or ""
        current = latest.get(option_id)
        if current is None or created >= current[0]:
            latest[option_id] = (created, snap.get("percentage"))
    return {
        option_id: (float(pct) if pct is not None else None)
        for option_id, (created, pct) in latest.items()
    }


def _market_url(pred_id, url_template):
    """Build a tappable Sawa market link from the optional URL template.

    Template carries an ``{id}`` placeholder (e.g. "https://<domain>/market/{id}").
    Returns None when unconfigured or the template is malformed.
    """
    if not (pred_id and url_template):
        return None
    try:
        return url_template.format(id=pred_id)
    except (KeyError, IndexError, ValueError):
        return None


def _market_from_prediction(pred, url_template=""):
    pct_by_option = _latest_pct_by_option(pred.get("OddsSnapshot"))
    options = []  # type: List[Outcome]
    for opt in pred.get("Option") or []:
        options.append(Outcome(opt.get("label", ""), pct_by_option.get(opt.get("id"))))
    status = "resolved" if pred.get("resolved") else "open"
    pred_id = pred.get("id", "")
    return Market(
        venue="sawa",
        ref="sawa:%s" % pred_id,
        title=pred.get("title", ""),
        status=status,
        deadline=pred.get("deadline"),
        options=options,
        activity=None,
        description=pred.get("description"),
        url=_market_url(pred_id, url_template),
    )


def list_markets(cfg, *, search=None, category=None, limit=20):
    """List public, unresolved markets (newest first). GET-only."""
    params = {
        "select": _SELECT,
        "isPrivate": "eq.false",
        "isHidden": "eq.false",
        "resolved": "eq.false",
        "order": "createdAt.desc",
        "limit": max(1, limit),
    }
    if search:
        params["title"] = "ilike.*%s*" % search
    if category:
        params["category"] = "eq.%s" % category
    url = http.build_url("%s%s" % (cfg.supabase_url, _BASE_PATH), params)
    rows = http.get_json(url, headers=_headers(cfg))
    return [_market_from_prediction(pred, cfg.market_url_template) for pred in (rows or [])]


def get_market(cfg, pred_id):
    """Fetch one public market by id. Private/hidden ids resolve to None."""
    params = {
        "select": _SELECT,
        "id": "eq.%s" % pred_id,
        "isPrivate": "eq.false",
        "isHidden": "eq.false",
        "limit": 1,
    }
    url = http.build_url("%s%s" % (cfg.supabase_url, _BASE_PATH), params)
    rows = http.get_json(url, headers=_headers(cfg))
    if not rows:
        return None
    return _market_from_prediction(rows[0], cfg.market_url_template)
