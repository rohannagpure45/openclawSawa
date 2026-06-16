# Sawa — Group-Chat Market Discovery Bot (Phase 1, read-only)

## What this is
A Telegram group-chat bot, driven by OpenClaw, that lets a group **discover prediction
markets by talking to it** — searching the *existing* live Sawa product and Kalshi side by
side — plus a **stubbed** create-market flow and a **one-shot** chat-analysis that suggests
markets. **No writes, no bets, no real money.** The "money half" (the order engine) is a
deliberate later phase. This doc is written to be **handed to a Claude Code instance on the
OpenClaw device and built directly** (see Build Sequence + Module Contracts).

Reviewed: `/plan-ceo-review` (SCOPE REDUCTION) + `/plan-eng-review` (read-only re-run).

## Decisions locked
- **D1 (premise):** Sawa stays **virtual** ("Sawa coins, no cash value"). Real-USD pivot
  dropped. Kalshi = real-world **data source**, not a trading venue.
- **D2/D3 (scope):** Phase-1 **read-only discovery** — read/search both venues, stub create,
  defer all writes/bets to the order-engine phase.
- **D-read (access, confined to what exists today):** **No Supabase definition changes** (no
  new grants/roles/views). Live check showed RLS off + zero `anon` grants on the market
  tables, so the only working credential today is the existing **service_role** key. We use
  it via **PostgREST GET-only**, and the CLI is **read-only by construction** (no code path
  issues a write). Write-capable-key-on-device is a **documented accepted risk**; the proper
  fix (a dedicated read-only role or a `public_markets` view + `anon` grant) is **deferred**
  to the order-engine phase. See Security.
- **Runtime:** Python **3.9**, **stdlib only** (`urllib`, `json`, `argparse`, `sqlite3` only
  if a tiny local buffer is used). No `cryptography`, no DB driver, no third-party deps.
  `from __future__ import annotations`, no `X|Y`, no `match`.
- **Surface:** OpenClaw agent in a Telegram group; `/<cmd>` or `@bokchoy`, each = one skill
  action; CLI called by absolute path with `--json`.
- **Analysis:** **one-shot**, loose bounds. **Reasoning lives in the OpenClaw agent
  (gpt-5.5-mini)**; the CLI only supplies data (`sawa markets --json`) + a message snapshot.
  No LLM key in the CLI.

## Reality check (live Supabase, read-only inspection) — why scope is read-only
Sawa is a **live, marketed product** (@sawapredictions; Next.js + Postgres, Prisma-style),
**313 users**, deliberately virtual (`PlatformSettings.platformMode='virtual'`, "Sawa coins",
"No cash value", `feePercent=1`, `monthlyGrantAmount=1000`, `maxBetAmount=100`). Markets use
**dynamic odds** (`creatorLiquidityPct`, `OddsSnapshot`), not flat parimutuel. A
`WhatsAppInbound` channel already exists. Phase 1 only **reads**; writes reuse the app's logic
in a later phase (its API or new bot endpoints) rather than re-implementing it.

## Live schema we READ (Phase 1) — `https://vmuuxsjafmkcdrcxouot.supabase.co`
- **`Prediction`** — `id,title,description,category,deadline,resolved,winningOptionId,leagueId,
  isPrivate,isHidden,createdAt`. Discover with `isPrivate=eq.false&isHidden=eq.false&resolved=eq.false`.
- **`Option`** — `id,label,predictionId` (outcomes; embed via PostgREST `select=...,Option(*)`).
- **`OddsSnapshot`** — `predictionId,optionId,percentage,createdAt`; **latest per option = current odds**.
> **PII guardrail:** `User` holds `email/phone/password/googleId`. The bot reads ONLY the
> market tables above and selects ONLY the columns listed. It never queries `User` and never
> surfaces PII into chat.

## Architecture
```
Telegram group ⇄ OpenClaw (gpt-5.5-mini, device)
   │  /command or @bokchoy
   ▼
 sawa CLI (Python 3.9, stdlib, --json)
   │   READ-ONLY BY CONSTRUCTION (only GET requests; no write codepath exists)
   ├─ markets/search/show ─┬─ GET PostgREST  (Supabase, existing key, public markets only)
   │                       └─ GET Kalshi public API (no auth)
   ├─ create  → STUB (pure local echo; never touches any network/DB)
   └─ suggest → emits {markets snapshot + chat messages} as JSON for the AGENT to reason over
```

## Module contracts (for the device build — clean separation, explicit interfaces)
```
sawa/config.py
  get_config() -> Config(supabase_url:str, supabase_key:str, kalshi_base:str)
    reads SAWA_SUPABASE_URL / SAWA_SUPABASE_KEY / SAWA_KALSHI_ENV(demo|prod→base url);
    raises ConfigError (exit 4) with a clear message if a needed var is missing.

sawa/http.py            # tiny stdlib GET helper (urllib), JSON parse, timeout, status→typed error
  get_json(url, headers={}, timeout=10) -> dict|list    # GET ONLY; module has no POST/PATCH/DELETE

sawa/sawa_read.py       # Supabase PostgREST, GET-only
  list_markets(cfg, *, search=None, category=None, limit=20) -> list[Market]
  get_market(cfg, pred_id:str) -> MarketDetail|None
    builds GET /rest/v1/Prediction?select=<safe cols>,Option(*)&isPrivate=eq.false
       &isHidden=eq.false&resolved=eq.false&order=createdAt.desc&limit=N  (+ optional ilike search)
    headers: apikey + Authorization: Bearer <key>; odds via latest OddsSnapshot per option.

sawa/kalshi_read.py     # Kalshi public API, GET-only
  list_markets(cfg, *, search=None, series=None, limit=20) -> list[Market]
  get_market(cfg, ticker:str) -> MarketDetail|None
    series allowlist (config const, ~5-10 tickers) → GET /markets?series_ticker=...&status=open;
    client-side substring filter on title/subtitle/ticker; hard --limit cap.

sawa/discover.py        # venue-neutral types + fan-out/merge
  @dataclass Market: venue:str, ref:str, title:str, status:str, deadline:str|None,
                     options:list[Outcome], activity:int|None      # ref = "sawa:<id>" | "kalshi:<TICKER>"
  @dataclass Outcome: label:str, odds_pct:float|None
  search(cfg, query, venues=("sawa","kalshi"), limit=20) -> list[Market]   # calls each reader, merges, labels

sawa/create_stub.py     # the ONLY write-shaped command — pure local, no I/O
  stub_create(question:str, outcomes:list[str], league:str|None=None) -> StubResult
    StubResult(created=False, stub=True, message="Not created — create lands in the order-engine
      phase (writes not wired yet).", would_create={question, outcomes, league})

sawa/analyze.py         # one-shot data provider for the agent (NO LLM call here)
  suggest_payload(cfg, messages:list[str]) -> dict
    returns {market_snapshot:[Market…], messages:[…], guidance:"propose 1-3 NEW market ideas"}
    the OpenClaw agent (gpt-5.5-mini) reasons over this and posts suggestions.

sawa/cli.py             # argparse dispatch; --json on every command; REJECTS unknown flags
  --json envelope: {"ok":bool,"command":str,"data":...,"error":null|{"code":str,"message":str}}
  exit codes: 0 ok · 2 usage/unknown-flag · 3 upstream/network · 4 config missing
```

## CLI commands (all read-only except the pure-local stub)
- `sawa markets [--venue sawa|kalshi|all] [--search KW] [--category C] [--limit N] [--json]`
- `sawa show --venue sawa|kalshi (--id <predId> | --ticker <T>) [--json]`
- `sawa create --question "..." --outcomes "YES,NO" [--league L] [--json]` → **STUB** (not created).
- `sawa suggest [--messages -|<file>] [--json]` → one-shot payload for the agent to reason over.

## OpenClaw skill + CLI contract (`skills/sawa/SKILL.md`)
YAML frontmatter `name`/`description`/**`triggers:`** + prose + **one few-shot per command**.
- **`triggers:`** `/markets` `/search` `/show` `/create` `/suggest` `@bokchoy` `Sawa`.
- Each command → run CLI by absolute path `__SAWA_BIN__` with `--json`; parse the envelope;
  reply into the group. Few-shot examples show the exact CLI invocation + how to render the reply.
- **`/create` reply** must state clearly: *nothing was created; this previews the flow (order
  engine is a later phase).*
- **`/suggest`:** the agent passes the last N visible group messages inline
  (`__SAWA_BIN__ suggest --messages -`), then reasons over the returned snapshot itself and
  posts 1-3 labeled "💡 suggestion (demo)".
- **No PII rule** + **virtual "Sawa coins" framing** in every reply.
- Device wiring: `openclaw approvals allowlist add --agent main "$SAWA_BIN"`; install SKILL.md
  with `__SAWA_BIN__` substituted; BotFather `/setcommands` for the `/` menu.

## Build sequence — CRAWL → WALK → RUN (each stage independently runnable + verifiable)
```
CRAWL  (no live secrets needed)
  Build: config.py, http.py, kalshi_read.py, cli.py (markets --venue kalshi + --json + unknown-flag reject)
  Tests: test_kalshi_read (mocked HTTP: search filter, --limit cap, series allowlist, empty result),
         test_cli (--json envelope shape, unknown-flag → exit 2)
  VERIFY: `SAWA_KALSHI_ENV=demo python -m sawa.cli markets --venue kalshi --search temperature --limit 5 --json`
          returns markets; `python -m pytest tests/ -v` green.

WALK   (needs the existing Supabase key)
  Build: sawa_read.py (PostgREST GET-only), discover.py (Market/Outcome, merge), cli markets --venue sawa|all + show
  Tests: test_sawa_read (mocked PostgREST: column select, isPrivate/isHidden filter present,
         odds latest-snapshot pick, empty), test_discover (merge + label both venues, zero results)
  VERIFY: `python -m sawa.cli markets --venue sawa --limit 5` lists ONLY public markets (read-only);
          `--venue all --search lakers` merges both; pytest green.

RUN    (device + OpenClaw)
  Build: create_stub.py, analyze.py, skills/sawa/SKILL.md, deploy wiring
  Tests: test_create_stub (created=False/stub=True, no network call), analyze payload shape
  VERIFY: on device — `/markets`, `/search lakers`, `/show`, `/create …` (stub message), `/suggest`
          all work in a Telegram group via OpenClaw.
```

## Test coverage (target: 100% of read-path branches)
```
[+] kalshi_read.list_markets        ├ [★★★] search filter / --limit cap / allowlist / empty   test_kalshi_read
[+] kalshi_read.get_market          ├ [★★ ] found / not-found (None)                          test_kalshi_read
[+] sawa_read.list_markets          ├ [★★★] PostgREST parse / isPrivate+isHidden filter /      test_sawa_read
                                    │        odds latest-pick / empty / network error→exit 3
[+] sawa_read.get_market            ├ [★★ ] found / None                                       test_sawa_read
[+] discover.search                 ├ [★★★] merge both / single venue / zero results / labels  test_discover
[+] create_stub.stub_create         ├ [★★★] returns created=False, stub=True, NO I/O           test_create_stub
[+] analyze.suggest_payload         ├ [★★ ] snapshot+messages shape, empty messages            test_analyze
[+] cli dispatch                    ├ [★★★] --json envelope / unknown-flag exit 2 / config     test_cli
                                    │        missing exit 4 / upstream error exit 3
[+] http.get_json                   └ [★★ ] timeout / non-200 → typed error                    test_http
GAPS at plan time: none — every branch above is assigned a test before build (boil the lake).
Framework: pytest. No E2E/eval needed Phase-1 (read-only, agent reasoning is the only LLM use,
and it's demo-labeled, not a graded output).
```

## Read path detail (confined to current Supabase — no DB changes)
- Reads go through **PostgREST GET** at `{SAWA_SUPABASE_URL}/rest/v1/...` with the **existing
  key** as `apikey` + `Authorization: Bearer`. `http.py` exposes **only** `get_json` — there is
  no POST/PATCH/DELETE anywhere in the codebase (read-only by construction).
- Every Sawa query hard-codes `isPrivate=eq.false&isHidden=eq.false` and a **column allowlist**
  (no `User` join, no PII).
- Kalshi reads need no key.

## Security guardrails + accepted risks (Phase-1)
- **Accepted risk (D-read):** the device key is **write-capable** (service_role), because we're
  confined to current Supabase with no new read-only role/grant. Mitigations: CLI is
  **read-only by construction** (only `get_json`; no write codepath — pinned by a test that
  asserts no write-method strings exist), key in a **0600 env file, never logged/echoed**,
  queries filtered to public markets + safe columns. **Production hardening (dedicated
  read-only role or `public_markets` view + `anon` grant) is deferred to the order-engine phase.**
- **No PII to chat** — market columns only; never `User` email/phone/id.
- **Stub-create** must clearly state nothing was created.

## Deployment (device, manual — Phase 1)
```bash
cd <repo-on-device>
pip3 install --user -e .                       # stdlib only, no build deps
SAWA_BIN="$(python3 -m site --user-base)/bin/sawa"; "$SAWA_BIN" --help   # preflight
openclaw approvals allowlist add --agent main "$SAWA_BIN"
openclaw approvals get | grep -q "$SAWA_BIN" && echo OK || echo "ALLOWLIST MISSING"
# Secrets (e.g. ~/.sawa/env, chmod 600 — NEVER commit/log):
#   SAWA_SUPABASE_URL=https://vmuuxsjafmkcdrcxouot.supabase.co
#   SAWA_SUPABASE_KEY=<existing key>            # write-capable; CLI uses GET-only (accepted risk)
#   SAWA_KALSHI_ENV=demo
mkdir -p ~/.openclaw/workspace/skills/sawa
sed "s#__SAWA_BIN__#$SAWA_BIN#g" skills/sawa/SKILL.md > ~/.openclaw/workspace/skills/sawa/SKILL.md
# Add @Ifhsbebtbot to the group; BotFather /setcommands.
```

## NOT in scope (deferred to the order-engine phase, with rationale)
- **Any write to Sawa** — create is a pure local stub; no app-repo access / unknown API yet.
- **Bets / order placement / payouts** — the order engine is the next phase.
- **Kalshi trading + real money + RSA signing** — Kalshi is read-only data; product stays virtual (D1).
- **A real read-only Supabase role/grant/view** — no DB changes allowed this phase (D-read);
  the write-capable key + read-only-by-construction is the Phase-1 mitigation.
- **Recurring cron, ingest hook, privacy-mode changes** — `/suggest` is one-shot, messages passed inline.
- **gstack relocation into `gstack/`** — optional/last; skip (risks the dev symlink for zero Phase-1 benefit).

## What already exists (reuse, don't rebuild)
- The Sawa economy/markets (Postgres) — we READ it, never re-implement.
- Kalshi public market API — read directly.
- OpenClaw native Telegram + exec + skills + `/setcommands`.
- `WhatsAppInbound` — the proven inbound-channel pattern to mirror when the write phase lands.

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR (SCOPE_REDUCTION) | premise→virtual (D1); cut to read-only discovery (D2/D3) |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 2 | CLEAR (PLAN) | 1 P0 resolved (read access → existing key, GET-only, no DB change); modular contracts + crawl/walk/run + test diagram added; 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | n/a | codex not installed |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | n/a (Telegram text + bot menu) |
| DX Review | `/plan-devex-review` | Dev experience | 0 | — | not run |

- **UNRESOLVED:** 0. **Accepted risk:** write-capable key on device (mitigated by read-only-by-construction; proper read-only grant deferred).
- **VERDICT:** CEO + ENG CLEARED — modular, device-handoff-ready, read-only Phase-1 plan. Build crawl→walk→run.
