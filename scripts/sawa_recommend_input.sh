#!/bin/sh
# Sawa background recommender input gatherer (local-only, read-only).
#
# Prints the `sawa suggest` JSON envelope -- recent group messages (ingested from
# the OpenClaw session transcript) plus a market snapshot -- on stdout, for the
# scheduled cron agent turn to reason over and post 1-3 demo suggestions.
#
# Run as ONE command (the OpenClaw agent must not split the pipe across calls).
# Override the group via SAWA_GROUP_SESSION_KEY if the chat id changes.

SESSION_KEY="${SAWA_GROUP_SESSION_KEY:-agent:main:telegram:group:-5351712127}"
RECENT="/Users/rohan/Documents/openclawSawa/scripts/sawa_recent_messages.py"
SAWA="${SAWA_BIN:-/Users/rohan/Library/Python/3.9/bin/sawa}"

python3 "$RECENT" --session-key "$SESSION_KEY" --limit 30 \
  | "$SAWA" suggest --messages - --limit 20 --json
