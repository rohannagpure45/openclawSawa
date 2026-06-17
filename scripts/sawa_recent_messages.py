#!/usr/bin/env python3
"""Print the recent group (human) messages from an OpenClaw session transcript.

OpenClaw cron jobs run in a fresh/isolated session and do NOT inherit a Telegram
group's buffered chat history, so the background recommender can't "see" recent
messages on its own. This helper bridges that gap: it reads the local session
transcript for a group and emits the last N human message texts (one per line,
TEXT ONLY -- no sender names/handles/metadata) so they can be piped into
`sawa suggest --messages -`.

Local files only -- no network. On ANY problem (missing/again-changed format,
unreadable file) it prints nothing and exits 0, so the recommender simply posts
nothing rather than erroring.

Caveat: this depends on OpenClaw's on-disk session format under
``~/.openclaw/agents/<agent>/sessions/``. If a future OpenClaw release changes
that layout, update the extractor here.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import List, Optional

_SESSIONS_DIR = "~/.openclaw/agents/{agent}/sessions"
# Leading "Name:" / "@handle:" sender prefix some channels embed in message text.
_SENDER_PREFIX = re.compile(r"^\s*[@A-Za-z0-9][\w .'\-]{0,40}:\s+")


def _sessions_dir(agent):
    return os.path.expanduser(_SESSIONS_DIR.format(agent=agent))


def _iter_index_records(index):
    if isinstance(index, list):
        for item in index:
            if isinstance(item, dict):
                yield item
    elif isinstance(index, dict):
        inner = index.get("sessions")
        if isinstance(inner, (list, dict)):
            for rec in _iter_index_records(inner):
                yield rec
            return
        for key, value in index.items():
            if isinstance(value, dict):
                rec = dict(value)
                rec.setdefault("key", key)
                yield rec


def resolve_session_id(agent, session_key):
    """Map a session key (agent:main:telegram:group:<id>) to its stored id."""
    path = os.path.join(_sessions_dir(agent), "sessions.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            index = json.load(fh)
    except (OSError, ValueError):
        return None
    for rec in _iter_index_records(index):
        key = rec.get("key") or rec.get("sessionKey") or rec.get("_key")
        if key == session_key:
            return rec.get("id") or rec.get("sessionId")
    return None


def _texts_from_content(content):
    out = []  # type: List[str]
    if isinstance(content, str):
        out.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text" and part.get("text"):
                out.append(str(part["text"]))
    return out


def _clean(text):
    text = _SENDER_PREFIX.sub("", text.strip(), count=1)
    return " ".join(text.split())


def extract_user_messages(transcript_lines, limit):
    """Return up to ``limit`` most-recent human message texts from a transcript."""
    messages = []  # type: List[str]
    for line in transcript_lines:
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        for text in _texts_from_content(message.get("content")):
            cleaned = _clean(text)
            if cleaned:
                messages.append(cleaned)
    return messages[-limit:]


def recent_messages(agent, session_key, limit):
    session_id = resolve_session_id(agent, session_key)
    if not session_id:
        return []
    path = os.path.join(_sessions_dir(agent), "%s.jsonl" % session_id)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    return extract_user_messages(lines, limit)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Print recent group messages for an OpenClaw session.")
    parser.add_argument("--agent", default="main")
    parser.add_argument("--session-key", required=True)
    parser.add_argument("--limit", type=int, default=30)
    args = parser.parse_args(argv)
    for text in recent_messages(args.agent, args.session_key, args.limit):
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
