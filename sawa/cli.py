"""Sawa CLI -- argparse dispatch with a uniform --json envelope.

Envelope: {"ok": bool, "command": str, "data": ..., "error": null|{code,message}}
Exit codes: 0 ok | 2 usage/unknown-flag | 3 upstream/network | 4 config missing.

Every command is read-only except ``create``, which is a pure-local stub that
creates nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict

from . import config
from . import discover
from . import http


class UsageError(Exception):
    """Bad argument combination caught after parsing (exit 2)."""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="sawa",
        description="Sawa read-only prediction-market discovery (Phase 1).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    markets = sub.add_parser("markets", help="list/search markets across venues")
    markets.add_argument("--venue", choices=["sawa", "kalshi", "all"], default="all")
    markets.add_argument("--search", default=None, help="keyword search (topic/competition)")
    markets.add_argument("--category", default=None, help="sawa category / kalshi category")
    markets.add_argument("--limit", type=int, default=20)
    markets.add_argument("--json", action="store_true")

    show = sub.add_parser("show", help="show a single market")
    show.add_argument("--venue", choices=["sawa", "kalshi"], required=True)
    target = show.add_mutually_exclusive_group(required=True)
    target.add_argument("--id", default=None, help="sawa prediction id")
    target.add_argument("--ticker", default=None, help="kalshi ticker")
    show.add_argument("--json", action="store_true")

    create = sub.add_parser("create", help="STUB create (nothing is created)")
    create.add_argument("--question", required=True)
    create.add_argument("--outcomes", required=True, help="comma-separated, e.g. YES,NO")
    create.add_argument("--league", default=None)
    create.add_argument("--json", action="store_true")

    suggest = sub.add_parser("suggest", help="one-shot data payload for the agent")
    suggest.add_argument("--messages", default=None, help="'-' for stdin or a file path")
    suggest.add_argument("--limit", type=int, default=20)
    suggest.add_argument("--json", action="store_true")

    warm = sub.add_parser("warm", help="prefetch the Kalshi series+event caches (read-only)")
    warm.add_argument("--json", action="store_true")

    return parser


def _read_messages(spec):
    if not spec:
        return []
    if spec == "-":
        raw = sys.stdin.read()
    else:
        with open(spec, "r", encoding="utf-8") as fh:
            raw = fh.read()
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _markets(args, cfg):
    if args.venue == "kalshi":
        from . import kalshi_read
        markets = kalshi_read.list_markets(
            cfg, search=args.search, category=args.category, limit=args.limit
        )
    elif args.venue == "sawa":
        config.require_supabase(cfg)
        from . import sawa_read
        markets = sawa_read.list_markets(
            cfg, search=args.search, category=args.category, limit=args.limit
        )
    else:  # all
        config.require_supabase(cfg)
        markets = discover.search(
            cfg, query=args.search, venues=("sawa", "kalshi"), limit=args.limit
        )
    return [discover.market_to_dict(m) for m in markets]


def _show(args, cfg):
    if args.venue == "kalshi":
        if not args.ticker:
            raise UsageError("show --venue kalshi requires --ticker")
        from . import kalshi_read
        market = kalshi_read.get_market(cfg, args.ticker)
    else:
        if not args.id:
            raise UsageError("show --venue sawa requires --id")
        config.require_supabase(cfg)
        from . import sawa_read
        market = sawa_read.get_market(cfg, args.id)
    return discover.market_to_dict(market) if market is not None else None


def _create(args, cfg):
    from . import create_stub
    outcomes = [o.strip() for o in args.outcomes.split(",") if o.strip()]
    result = create_stub.stub_create(args.question, outcomes, args.league)
    return asdict(result)


def _suggest(args, cfg):
    config.require_supabase(cfg)
    from . import analyze
    messages = _read_messages(args.messages)
    return analyze.suggest_payload(cfg, messages, limit=args.limit)


def _warm(args, cfg):
    """Prefetch the Kalshi series + event indexes into the on-disk cache.

    Read-only and Kalshi-only (no Supabase). Run by the background cron so the
    24h event cache stays warm and interactive proper-noun searches are fast.
    """
    from . import kalshi_events
    from . import kalshi_index
    series = kalshi_index.get_series_index(cfg) or []
    events = kalshi_events.get_events_index(cfg) or []
    return {"series": len(series), "events": len(events)}


_DISPATCH = {
    "markets": _markets,
    "show": _show,
    "create": _create,
    "suggest": _suggest,
    "warm": _warm,
}


def _emit_ok(command, data, want_json):
    if want_json:
        envelope = {"ok": True, "command": command, "data": data, "error": None}
        sys.stdout.write(json.dumps(envelope) + "\n")
    else:
        _render_human(command, data)
    return 0


def _emit_error(command, code, message, exit_code, want_json):
    if want_json:
        envelope = {
            "ok": False,
            "command": command,
            "data": None,
            "error": {"code": code, "message": message},
        }
        sys.stdout.write(json.dumps(envelope) + "\n")
    else:
        sys.stderr.write("error [%s]: %s\n" % (code, message))
    return exit_code


def _render_human(command, data):
    if data is None:
        sys.stdout.write("(no result)\n")
        return
    if isinstance(data, list):
        if not data:
            sys.stdout.write("(no markets)\n")
            return
        for market in data:
            sys.stdout.write(
                "[%s] %s  (%s)\n" % (market.get("venue"), market.get("title"), market.get("ref"))
            )
        return
    sys.stdout.write(json.dumps(data, indent=2) + "\n")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits 2 on unknown flag / bad usage
    want_json = getattr(args, "json", False)
    try:
        cfg = config.get_config()
        data = _DISPATCH[args.command](args, cfg)
    except UsageError as exc:
        return _emit_error(args.command, "usage", str(exc), 2, want_json)
    except config.ConfigError as exc:
        return _emit_error(args.command, "config_missing", str(exc), 4, want_json)
    except http.HttpError as exc:
        return _emit_error(args.command, "upstream", str(exc), 3, want_json)
    return _emit_ok(args.command, data, want_json)


if __name__ == "__main__":
    sys.exit(main())
