# Sawa bot — deployment runbook (Phase 1, read-only)

Plain-English steps to run the bot in a Telegram group via OpenClaw. The dense design doc is
[`docs/SAWA_PHASE1_PLAN.md`](SAWA_PHASE1_PLAN.md); this is the "what do I actually type" version.
OpenClaw commands are verified against the running install (OpenClaw 2026.6.8) and the official
docs (links at the bottom).

> **Status (this Mac IS the OpenClaw device):** the bot is **installed and working** —
> OpenClaw runs as a LaunchAgent, the `sawa` CLI is installed, the skill is loaded ("✓ ready"),
> and a live `/markets` agent turn returns markets. What's left is **3 manual steps you must do**
> (see "Remaining manual steps" at the end): BotFather Group Privacy, add the bot to your group,
> and resume the Supabase database.

---

## Which repo is which (you only deploy ONE)

| Thing | Repo / location | What you do with it |
|---|---|---|
| **The bot** | **this repo** `openclawSawa` | Already installed on this Mac. It's a Python CLI (`sawa/`) + the OpenClaw skill (`skills/sawa/SKILL.md`). |
| **The Sawa product** (web app) | a **separate** Next.js + Prisma repo (NOT here) | Nothing. Phase 1 only **reads** its database. |
| **The database** | Supabase project `vmuuxsjafmkcdrcxouot` | The bot reads it (GET-only). Keep it un-paused. |

You never touch the web app or write to the database in Phase 1.

---

## What is already configured on this Mac

| Piece | State | Where |
|---|---|---|
| `sawa` CLI | installed (editable) | `~/Library/Python/3.9/bin/sawa` |
| Secrets | set, mode 600 | `~/.sawa/env` (`SAWA_SUPABASE_URL`, `SAWA_SUPABASE_KEY`, `SAWA_KALSHI_ENV=prod`) |
| Skill | installed, placeholder substituted | `~/.openclaw/skills/sawa/SKILL.md` |
| Exec policy | `security: full` (required — see below) | `~/.openclaw/exec-approvals.json` |
| Telegram | `requireMention: false` + 5 menu commands | `~/.openclaw/openclaw.json` → `channels.telegram` |
| iMessage channel | disabled (was crash-looping for lack of Full Disk Access) | `~/.openclaw/openclaw.json` → `channels.imessage.enabled: false` |
| Gateway | running as LaunchAgent | `openclaw daemon status` |

---

## ⚠️ Exec security: why it is `full` (important)

The agent runs through the **Codex harness** (OpenAI `gpt-5.4-mini` over your OpenAI OAuth).
That harness **cannot run under `security: deny` or `security: allowlist`** — it spawns its own
local processes, so anything stricter than `full` makes every message fail with
*"Codex app-server local execution is not available when tools.exec.mode=..."* (this was the
"something went wrong" bug). Valid values are `deny | allowlist | full`; the harness needs `full`.

**Consequence + mitigations:** under `full` the agent can run *any* shell command, not just the
`sawa` CLI — so a group member could, in principle, prompt-inject it into reading `~/.sawa/env`
(your **write-capable** service_role key). Mitigate by:
1. Keep the group to **trusted members** and turn **Group Privacy ON** (below) so only `/commands`
   reach the agent.
2. Do the deferred hardening: **rotate the key and/or create a read-only Postgres role** in
   Supabase so the device key can't write. (Until then, the CLI is read-only by construction, but
   `full` exec means that's no longer the only thing protecting the key.)

To change the level (gateway must reload — restart after editing):
```bash
openclaw daemon stop
# edit ~/.openclaw/exec-approvals.json  -> "security": "full"  (defaults + agents.main)
openclaw daemon start
openclaw approvals get   # confirm Effective: security=full
```

---

## Reproducing on a DIFFERENT machine

If you ever set this up on another OpenClaw host, here's the full sequence.

### 1. Install the CLI
```bash
git clone https://github.com/rohannagpure45/openclawSawa.git
cd openclawSawa
# Old pip (<21.3) can't editable-install a pyproject-only project and silently builds an
# "UNKNOWN" wheel with no console script. Upgrade the user toolchain first:
python3 -m pip install --user --upgrade pip setuptools wheel
python3 -m pip install --user -e .
SAWA_BIN="$(python3 -m site --user-base)/bin/sawa"
"$SAWA_BIN" --help    # preflight
```

### 2. Secrets (`~/.sawa/env`, mode 600)
```bash
mkdir -p ~/.sawa && chmod 700 ~/.sawa
cat > ~/.sawa/env <<'ENV'
SAWA_SUPABASE_URL=https://vmuuxsjafmkcdrcxouot.supabase.co
SAWA_SUPABASE_KEY=<paste the service_role key>
SAWA_KALSHI_ENV=prod
ENV
chmod 600 ~/.sawa/env
```
`prod` matters — Kalshi **demo** returns no markets. Kalshi prod is public, read-only, no money.

### 3. Allowlist the bin + set exec to `full`
```bash
openclaw approvals allowlist add --agent main "$SAWA_BIN"
# then set security=full in ~/.openclaw/exec-approvals.json (see the section above) — the
# Codex harness requires it; allowlist alone is not enough.
```

### 4. Install the skill, then restart the gateway
```bash
mkdir -p ~/.openclaw/skills/sawa
sed "s#__SAWA_BIN__#$SAWA_BIN#g" skills/sawa/SKILL.md > ~/.openclaw/skills/sawa/SKILL.md
openclaw daemon restart        # the gateway is a LaunchAgent; this reloads skills + config
openclaw skills list | grep sawa   # expect "✓ ready"
```
> Note: do NOT run `openclaw gateway` (foreground) when it's already a LaunchAgent — you'll get
> `EADDRINUSE`. Use `openclaw daemon start|stop|restart|status`.

### 5. Telegram channel (in `~/.openclaw/openclaw.json` under `channels.telegram`)
Token comes from **@BotFather** (`/newbot`, or reuse **@Ifhsbebtbot**). Already set here as:
```jsonc
"telegram": {
  "enabled": true,
  "botToken": "<from BotFather>",
  "groups": { "*": { "requireMention": false } },   // /markets works without @-mention
  "customCommands": [
    { "command": "markets", "description": "List or search markets (Sawa + Kalshi)" },
    { "command": "search",  "description": "Search markets by keyword" },
    { "command": "show",    "description": "Show one market in detail" },
    { "command": "create",  "description": "Preview a new market (stub, nothing created)" },
    { "command": "suggest", "description": "Suggest market ideas from recent chat" }
  ]
}
```
OpenClaw pushes the menu via `setMyCommands` at startup — no BotFather `/setcommands` needed.

---

## Remaining manual steps (only you can do these)

**A. BotFather → Group Privacy — pick a posture:**
- **Privacy ON** = command-only bot: ignores ordinary chatter; only `/commands` and @mentions reach
  it. Simplest/most private, but the bot can't read group chat, so the background recommender has
  nothing to ingest.
- **Privacy OFF + `requireMention: true`** (*what is configured now*) = the bot **receives** and
  buffers group messages (so the recommender can read recent chat) but only **replies** to
  `/commands`, @mentions, and its own scheduled run. Required for the background recommender below.
- ⚠️ Either change only applies after you **remove and re-add** the bot to the group.
- Trade-off of Privacy OFF: the bot buffers recent messages on disk (capped at
  `messages.groupChat.historyLimit: 40`, owned 0600). Accept only for a trusted group; the
  `exec: full` agent can read that buffer, so the deferred key-hardening matters more.

**B. Add @Ifhsbebtbot to your group** (after A). Then `/markets`, `/search lakers`,
`/show sawa:<id>`, `/create … Yes,No`, `/suggest`.

**C. Resume the Supabase database.** It currently returns `503 PGRST002` — the project is
**paused/unreachable** (NOT a key problem; the key authenticates). Open
<https://supabase.com/dashboard/project/vmuuxsjafmkcdrcxouot> → **Restore/Resume**. Until then,
`/markets` shows **Kalshi only** (the Sawa half 503s). See the 503 section below.

---

## Use it in the group

| You type | Bot does |
|---|---|
| `/markets` | newest markets across Sawa + Kalshi |
| `/search lakers` | markets matching "lakers" on both venues |
| `/show sawa:<id>` or `/show kalshi:<TICKER>` | one market with current odds + deadline |
| `/create Will it snow? Yes,No` | **preview only — says nothing was created** |
| `/suggest` | posts 1–3 `💡 suggestion (demo)` ideas |

Sawa replies are framed as **virtual Sawa coins (no cash value)**; Kalshi is real-world reference
data. No bets, no writes, no real money in Phase 1.

---

## Background recommender (scheduled suggestions)

A cron job (`sawa-recommender`, id `18e740fe-9840-4591-a815-15c18aa60747`) posts 1–3
`💡 suggestion (demo)` market ideas to the group **twice daily** (09:00 & 21:00 America/New_York),
grounded in the recent group chat.

**How it works (and the OpenClaw limitation it works around):** OpenClaw cron turns run in a fresh
isolated session and do **not** inherit a group's chat history (`--session-key` does not load it).
So the job runs one local helper that reads recent group messages from the on-disk transcript and
pipes them into `sawa suggest`:
- `scripts/sawa_recent_messages.py` — last N human messages from
  `~/.openclaw/agents/main/sessions/<group-session>.jsonl` (text only, sender stripped; prints
  nothing on any error).
- `scripts/sawa_recommend_input.sh` — runs `recent_messages | sawa suggest --messages - --json`.
- The cron agent turn runs that one script, reasons over the JSON, and posts. It posts **nothing**
  if the CLI errors, there are no recent messages, or nothing is market-worthy (no spam, no errors).

> ⚠️ The helper depends on OpenClaw's on-disk session format. If a future OpenClaw release changes
> that layout, update `scripts/sawa_recent_messages.py` (its tests use a synthetic fixture).

**Manage it:**
```bash
openclaw cron list                                  # see the job + next run time
openclaw cron run <id> --wait --expect-final        # trigger once now (posts to the group)
openclaw cron edit <id> --cron "0 9 * * *"          # e.g. once daily (or: --every 12h)
openclaw cron disable <id>   /   openclaw cron rm <id>
```
Bound to group chat id `-5351712127`; if the group changes, set `SAWA_GROUP_SESSION_KEY` in
`scripts/sawa_recommend_input.sh` and update the job's `--to`.

**Prereqs (already configured):** Group Privacy OFF + `requireMention: true` +
`messages.groupChat.historyLimit: 40` (step A). The buffer fills going forward, so the first runs
after enabling may see few messages and post nothing.

---

## The Supabase 503 (`PGRST002`) — what it actually was (RESOLVED)

- **Symptom:** every REST query (even `select=id&limit=1`, and the REST root) returned
  `HTTP 503 {"code":"PGRST002","message":"Could not query the database for the schema cache. Retrying."}`.
- **Root cause (confirmed from Postgres logs):** the project's **Exposed schemas** list was
  **empty**, so PostgREST had nothing to introspect. The logs showed
  `ERROR: schema "pg_pgrst_no_exposed_schemas" does not exist` — the sentinel PostgREST queries when
  no schemas are configured. Auth + Storage stayed `200` throughout (the DB was up); only the Data
  API was broken. It was NOT a pause, NOT the key (auth worked; `PGRST002` is pre-auth), and NOT a
  platform incident. A project restart did **not** fix it because the *config*, not the process, was
  the problem. Likely wiped while on the Settings → API page during the API-key migration.
- **Fix (done):** Dashboard → **Project Settings → API → Exposed schemas** = `public, graphql_public`
  (and **Extra search path** = `public, extensions`), Save. PostgREST reloads in seconds. SQL fallback:
  `alter role authenticator set pgrst.db_schemas = 'public, graphql_public'; notify pgrst, 'reload config';`

## The follow-on 400 (`PGRST200`) — what it was (RESOLVED in code)

- **Symptom:** once the 503 cleared, `markets --venue sawa` returned `400`; the PostgREST body was
  `PGRST200 "Could not find a relationship between 'Option' and 'OddsSnapshot'"`.
- **Cause:** `OddsSnapshot` has no foreign key to `Option` that PostgREST can auto-embed, so odds
  could not be nested under each option.
- **Fix (done, in [`sawa/sawa_read.py`](../sawa/sawa_read.py)):** fetch `OddsSnapshot` as a **sibling
  embed** of `Option` under `Prediction` (still one GET) and join odds→option by `optionId` in Python
  (latest snapshot per option). Read-only, no DB changes, no PII. Verify:
  ```bash
  python3 -m sawa.cli markets --venue sawa --limit 5    # want markets with odds, not 503/400
  ```

---

## Quick troubleshooting

| Symptom | Meaning | Fix |
|---|---|---|
| Every message → "something went wrong" | exec policy too strict for Codex harness | set `security: full` in `exec-approvals.json`, restart |
| `Codex app-server local execution is not available when tools.exec.mode=...` | same as above | same |
| `error [upstream] ... 503` / `PGRST002` | PostgREST has no exposed schema (not a pause, not the key) | Settings → API → Exposed schemas = `public, graphql_public` |
| `error [upstream] ... 400` / `PGRST200` | embed relationship missing | already handled in `sawa_read.py` (sibling embed + client-side join) |
| `error [upstream] ... 401` | bad/missing Supabase key | check `~/.sawa/env` |
| `error [config_missing]` (exit 4) | env not loaded | recreate `~/.sawa/env` |
| Kalshi markets always empty | `SAWA_KALSHI_ENV=demo` | set `prod`, restart |
| Bot answers normal chat too | Group Privacy OFF | BotFather → Group Privacy ON, re-add bot |
| `EADDRINUSE` on `openclaw gateway` | gateway already runs as LaunchAgent | use `openclaw daemon restart` |
| iMessage errors flood logs | no Full Disk Access | `channels.imessage.enabled: false` (or grant FDA) |

## Sources (OpenClaw + Supabase)
- Exec approvals / allowlist: <https://docs.openclaw.ai/cli/approvals>
- Exec security values (`deny`/`allowlist`/`full`): <https://docs.openclaw.ai/tools/exec-approvals>
- Telegram channel setup: <https://docs.openclaw.ai/channels/telegram>
- Skills location & install: <https://docs.openclaw.ai/tools/skills>
- Supabase status: <https://status.supabase.com>
