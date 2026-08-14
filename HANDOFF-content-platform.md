# Handoff — Multi-tenant Content Platform

Everything a fresh thread needs to continue this build. Written 2026-08-10,
revised 2026-08-12. Check §2 for what is deployed and what is not — they are
no longer the same thing.

---

## 1. What this is and why

Gomeh runs a marketing agency (MarketingThatWorks.co), co-owns Baci Milano USA,
owns Eien Health, and has Coverings Etc and Miami Ironside as clients. Agency
revenue has been stuck in an $80k–$250k band for years.

**The diagnosis that drove this build:** client churn runs 4–6 months, and the
stated reason is always "not seeing results." The root cause is that he sells
*strategy* to $2–10M owner-operated businesses that have no capacity to execute
it, and strategy takes 9–18 months to prove — well past their patience.

**The fix:** installed systems that produce a verifiable number inside weeks,
run without him, and survive handoff. This platform is that, built multi-tenant
from the start so system #2 and #3 cost days rather than weeks.

Supporting evidence lives in `.claude/projects/.../memory/content-platform-buildout.md`
and six reference artifacts (§11).

---

## 2. Status board

Last verified 2026-08-13 at commit `aa83de0`.

**The "seven unpushed commits" this section used to warn about are pushed.**
`origin/main` is at `aa83de0`, the working tree was clean, and everything from
`81bcb50` on — `email_harvest`, `sources.py` / `/admin/fill`, the Data layer tab
— is deployed. Verify rather than trust that sentence:

```bash
git -C ~/Documents/gomehagent-build log --oneline -1 origin/main
```

| Component | State |
|---|---|
| Telegram ops channel · tenant registry · user scoping | live |
| Knowledge base (8 tables) | live, all five accounts seeded |
| **Ingest provenance spine** (`provenance.py`) | live — origin · review · fingerprint · conflicts on every KB table |
| **Model claim extractor** (`extract.py`) | live, **recall never measured** |
| **Email miner** (`email_harvest.py`) | built, **not pushed** |
| **Source registry** (`sources.py`) — `/admin/fill` | built, **not pushed** |
| Knowledge · Content · Systems · Accounts tabs | live |
| **Data layer tab** | built, **not pushed** |
| Catalogue sync (Shopify → KbEntity) | live — **251 entities on Baci** |
| Website compliance · harvest | live |
| Console session · client credentials · connect links | live |
| **OAuth (`oauth.py`) — Google · Meta** | built, 45 offline checks, **never run against a real provider** |
| **Gmail reads client-connected credentials** | built — `credentials.google_config`, the bridge without which OAuth stores a token nothing reads |
| **Meta token renewal** | built — daily worker tick, 14-day window |
| Operational half tenant-scoped | live, enforced by `test_tenant_isolation.py` |
| Generator / validator / send (rec 4) | **not built** — nothing produces output |
| Spreadsheet upload | **not built** — one `sources.SOURCES` entry when it is |
| Reports · media layer · Canva | not started |

**Where the platform actually is:** the knowledge layer is built and the
ingest side is four sources deep. Nothing generates. The single measurement
that would change what we know is `scripts/test_extract.py --live`, which has
never been run.

**Env:** `CREDENTIAL_KEY` is still **not set** in the env group. Set it before
any client connects anything — it is the encryption key, and changing it later
orphans every stored credential. `ANTHROPIC_API_KEY` must also be present or
harvest silently falls back to a filter measured at 0% recall on qualitative
claims; the run reports `extractor: "deterministic filter"` when that happens.

Live service: `https://assistant-web-zm2d.onrender.com`
Bot: `@Gomehadmin_bot`

---

## 2b. Where each account actually stands (measured 2026-08-12)

| Account | KB | Site enumerable | Compliance |
|---|---|---|---|
| agency | ready (12 claims, 4 aud, 6 obj) | 19 pages via **wp-json** | ready |
| baci | 3 claims, 3 aud, 0 obj, **251 entities**, 24 rules | 400 pages via sitemap | **3 real violations found** |
| eien | ban list only | 289 pages via sitemap | ready |
| ironside | 1 claim, 1 aud, 8 venues, 6 rules | 169 pages via sitemap | ready |
| coverings | 1 audience only | **TLS chain broken** | blocked: no `banned_claims` |

Baci's live violations, found by the real scanner:
`/pages/wholesale` (bespoke + "personalization"), `/pages/best-italian-espresso-cups…`
(craftsmanship), `/pages/care-guide` (hand-painted).

**Objections are 0 on every account** — but that sentence changed meaning this
session, twice.

First: a count of 0 no longer means nobody has answered. A client filling an
intake link now files a **proposal** — recorded, not re-asked, and not counted
until approved. Read the number beside it: `completeness()` reports
`kb_objections (2 waiting for review)` rather than `(none)`. Zero with
proposals waiting is an approval job; zero with none waiting is an authoring job.

Second, and more useful: **objections are no longer underivable.** A product
FAQ is an objection with its approved answer, and so is any support thread —
the brand has been answering the same questions for years. `email_harvest`
mines sent mail for exactly this. What that leaves is accounts with no mailbox,
where they genuinely have to be authored. Ironside is one.

---

## 2c. Start here — connectors

The next thread is connector setup, and it starts from one uncomfortable fact:

> **The client connect page has never worked in production.** `python-multipart`
> was missing from `requirements.txt`, so every form POST 500'd from the day
> form parsing landed until `6a04e65` deployed this session. Anyone who was ever
> sent a connect link pasted a key and got an Internal Server Error. It is fixed
> and **has still never been used successfully by a client.**

So the first job is not building anything. It is proving the path end to end,
yourself, before a client sees it again.

**Before touching a connector**

1. `CREDENTIAL_KEY` in the `assistant-env` group. It is the Fernet key. Setting
   it later orphans every credential stored before it, so this comes first and
   it must not live where the database backups live.
2. `ANTHROPIC_API_KEY` in the same group, or every harvest silently runs the
   0%-recall filter. The response says `extractor: "deterministic filter"` when
   it happens — check that field, not the proposal count.
3. Push the seven unpushed commits.

**Then prove it, on yourself**

```bash
curl -b ~/.gomeh-console -s ".../admin/connect_new?tenant=baci&label=self-test&days=1"
```

Open the returned URL in a browser, paste a real key, submit. A wrong key must
fail in front of you; a right one must verify against the live API before it is
stored. If that works, the path is real for the first time.

**What is self-serve today**

| Provider | Path |
|---|---|
| Shopify · Omnisend · Klaviyo · WordPress | API key, self-serve, verified on save |
| Google (Gmail · Drive · Calendar · GSC · GA4) | OAuth, self-serve — **built 2026-08-13, never run against Google** |
| Meta Ads | OAuth, self-serve — **built 2026-08-13, never run against Meta** |

OAuth was the gap and the code is now there; what is left is proving it, plus
four env vars (`GOOGLE_CLIENT_ID` / `_SECRET`, `META_APP_ID` / `_SECRET`) and a
redirect URI registered in each provider's console. Until those exist the
connect page shows the provider as "on a call" **and names the missing
variable**.

This still matters most of anything on the board, for the same reason as
before: Google is what `email_harvest` needs, and `email_harvest` is the only
source objections can be derived from. **Ironside has no mailbox at all**, which
is why its objections are an authoring job and Baci's are a mining job.

Three things about the OAuth work worth carrying forward:

- **The bridge was the real work, not the flow.** `gmail_client.creds_for` read
  `config.GMAIL_ACCOUNTS` directly, so a client could complete consent, have the
  credential store, verify, and show as connected — and `email_harvest` would
  still read the env blob, find nothing, and report an account with no mailbox.
  A connection that is real and unreadable is worse than an absent one.
  `credentials.google_config` mirrors `shopify_config`, which had solved exactly
  this a session earlier for the other provider.
- **`capabilities()` had drifted into a clause per capability**, and `ads` and
  `analytics` never got one — so a Meta connection would have stored, worked,
  and still read `ads: False`. It now derives from `credentials.GRANTS`, one
  table saying what each provider turns on. A Google sign-in grants `inbox` and
  `analytics` together, which no clause had ever said.
- **Scope narrowness stopped being invisible, for OAuth.** Both providers report
  what was actually granted, so an unticked permission is named on the console
  the moment it happens. The DEFECTS entry stays open for API keys — a Shopify
  token with too few scopes still fails quietly later.

**What a connector unlocks, per source** — this is the argument for doing
connectors before anything else:

| Connect | Source it turns on | What the KB gains |
|---|---|---|
| Shopify | `catalogue` | entities with live price and stock, and the keys that scope product claims |
| Google | `sent_mail` | claims already made, and **objections** |
| (domain only) | `website` · `compliance` | claim proposals, and what the live site says that it should not |

Check any account's position with:

```bash
curl -b ~/.gomeh-console -s ".../admin/fill?tenant=ironside"
```

It reports every source, whether it is usable, and why not — and ends with the
questions only a human can answer.

---

## 3. Locked decisions — do not re-litigate

These were argued out with evidence. Changing one needs a reason, not a preference.

1. **AI at the edges only.** Model calls belong in ingest drafting, media
   semantic descriptions, content drafting, and digest summaries. Brief
   assembly, selection, validation, rendering and publishing are deterministic
   code. Evidence: Gomeh's rep app (zero AI in runtime) works and is in daily
   use; his WhatsApp agent (agentic) failed and was shelved.

2. **A model may never validate a model.** The validator is pure code and fails
   closed.

3. **Customisation lives in the KB as data, never forked code.** The first
   `git clone` for a client is the moment the platform stops existing.

4. **The system refuses rather than invents.** When the KB lacks a field, the
   pipeline blocks and names it. This is the product, not a limitation.

5. **One MCP server (ours) → our backend → client credentials → platforms.**
   Never Claude wired directly to client platforms. API-first; MCP, the admin
   console and Telegram are all clients of the same API.

6. **Adapters are ours; vendors are implementations behind them.** If Composio
   or Nango is adopted, it sits behind our interface, called from backend code
   via SDK — never as agent tools in the runtime.

7. **Autonomy is earned:** shadow → human approves all → approves exceptions →
   auto with alerting. Nothing starts autonomous.

8. **Every system needs the 8-part contract before code:** job replaced, owner,
   baseline, primary metric, counterfactual, kill criteria, failure mode,
   weekly artifact. If any can't be filled, don't build it.

---

## 4. Code map

New this session:

| File | Purpose |
|---|---|
| `app/telegram.py` | Bot API client. `send_text`, `send_approval` (inline keyboards), `ask`/`resolve` (edits messages in place), voice download + transcribe, `is_allowed`, `set_webhook`, `wire_secret` |
| `app/channel.py` | Routes to Telegram when configured, WhatsApp otherwise. Pass-through when `TELEGRAM_ENABLED` is false |
| `app/tenants.py` | Registry, capability resolution, live `verify()`, user scoping, context switching, seed |
| `app/kb.py` | Deterministic KB read layer, `SITUATIONS` vocabulary, `completeness()`, agency seed |
| `app/brief.py` | The decision layer: classify → enrich → diagnose → select → decide |
| `app/ops_commands.py` | Telegram fast-path commands, handled before the agent |
| `app/admin_ui.py` | Server-rendered console with per-field setup instructions |
| `scripts/test_brief.py` | Offline test harness for the assembler |
| `app/systems.py` | Systems registry: catalogue, `ready()` blockers, autonomy ladder + gates, run ledger, per-system feedback threads, `board()` |
| `scripts/test_systems.py` | Offline harness for the registry — 22 checks, no network |
| `scripts/seed_kb.py` | Seeds baci/ironside/eien/coverings from established facts only; `--report` shows remaining gaps; `backfill()` fills columns added after a tenant was first seeded |
| `scripts/test_selection.py` | Tenant-shaped selection + the unknowns loop |
| `scripts/test_kb_ui.py` | Asserts every seeded KB fact reaches the rendered Knowledge tab, per tenant. Catches the class of bug where a field exists, is used by the pipeline, and is invisible to the person meant to maintain it |

### Files added 2026-08-12

| File | Purpose |
|---|---|
| `app/tenant_scope.py` | Attributes the operational tables to a client. `preview()` predicts per row and shares `_derive()` with `backfill()`; `resolve()` is what writers call to attribute at capture time |
| `app/credentials.py` | Per-client credentials, Fernet at rest. `PROVIDERS` registry, `resolve()` = DB first then env blob, `store()` verifies against the live API before writing |
| `app/tool_scope.py` | **The account boundary.** `SCOPED` maps every tool that names an account to its parameter + capability; `filter_tools` strips it from the schema; `guard` injects the right one and refuses a different one |
| `app/catalog_sync.py` | Shopify → `KbEntity`. Store owns price and stock; copy using a banned phrase is flagged and not imported. **Ownership of the prose is decided by `provenance.may_write`, never by inspecting the `source` string** — the old `source not in ("shopify","")` test let an approved description on a store-supplied row be overwritten, which is the defect the spine exists to close |
| `app/compliance.py` | Website content compliance. `discover_pages` = sitemap → wp-json → homepage crawl; `_match` separates assertions from questions; `record_scan` stores findings in the run ledger |
| `app/harvest.py` | Site → **pending** claim proposals. Banned phrases dropped, reviews from JSON-LD with provenance, untagged candidates proposed for human segmentation |
| `scripts/test_tenant_isolation.py` | **The mandatory rule as a test.** A model without `tenant`, or a tool naming an account without being in `SCOPED`, fails by name |
| `scripts/test_migration.py` | Runs the migration over a database that already has rows — the case every other suite misses |
| `scripts/test_console_auth.py` · `test_credentials.py` · `test_catalog_sync.py` · `test_compliance.py` · `test_harvest.py` · `test_worker_systems.py` | one per system above |

**Key API additions:** `kb.claim_inventory()`, `kb.situation_rows()`,
`kb.suggest_tags()` (patterns, then similarity to already-approved claims),
`kb.update_claim()`, `kb.PROOF_USAGE` / `VERBATIM_ONLY`, `tenants.for_alias()`,
`tenants.agent_block()`, `db.tenant_filter()`, `worker.inboxes()`,
`worker.systems_tick()`.

### Files added 2026-08-12 (the ingest rebuild)

| File | Purpose |
|---|---|
| `app/provenance.py` | **The ingest spine.** `origin` / `review` / `fingerprint` on every KB table, `may_write` (the one precedence rule), `record_conflict`, `near_duplicates`. Approved is final: a machine that disagrees records a conflict and changes nothing |
| `app/extract.py` | **Claim extraction as span SELECTION.** The model returns verbatim substrings and `_verify` discards anything not present in the source, so fabrication is checked rather than trusted. `extract_qa` does the same for a question/answer pair, verifying each half against its own side of the exchange |
| `app/email_harvest.py` | Sent mail → claims and objections. Filters by the bucket `triage` already assigned, so the noise was sorted once, months ago. Strips quoted history and signatures before reading |
| `app/sources.py` | **The source registry.** A source declares `key · label · produces · capability · precondition · run`; the runner knows none by name. Adding the spreadsheet upload is one entry |
| `scripts/test_provenance.py` · `test_extract.py` · `test_email_harvest.py` · `test_sources.py` | One suite per system above. 19 suites total, none touching the network |

**Key API additions:** `kb.proposals()` (one review queue across all five
tables, with near-duplicates scoped), `kb.approve()`, `kb.purge_proposals()`,
`kb.support_for()` (the claims backing an objection), `kb.objections(...,
situations=)`, `compliance.text_blocks()` / `skip_url()` / `is_dead_page()`,
`gmail_client.fetch_sent_threads()`, `sources.available()` / `fill()`.

**Schema:** `KbConflict` is new. The provenance mixin is on all five content
tables. `entity_key` is on claims and objections; `situations` is on objections.

### Superseded — files added on `feat/context-architecture`

| File | Purpose |
|---|---|
| `app/provenance.py` | **The ingest spine.** `origin` / `review` / `fingerprint` on every KB table, `may_write` (the one precedence rule), `record_conflict`, `near_duplicates`. Approved is final: a machine that disagrees records a conflict and changes nothing |
| `scripts/test_provenance.py` | The five measured ingest defects, each as a named check |

**Further API additions:** `kb.proposals()` (one review queue across all five
tables), `kb.approve()`, `kb.purge_proposals()`, `compliance.purge_scans()`,
`compliance.skip_url()` / `page_title()` / `is_dead_page()`,
`harvest._quality()`, `provenance.*`, and the `KbConflict` model.

---

**Tenant-shaped selection (Aug 2026) — recommendation 1 of 4.** Proven broken
by running a real Ironside enquiry: "220 guests seated in March" produced
`situations: []`, an empty offer, and never consulted the eight venues whose
capacities answer the question. Three causes, all fixed:

- **`KbSituation`** — the diagnostic vocabulary is per tenant, as data. The
  shared module constant was agency-B2B language that no venue or product
  enquiry could ever match. `SITUATIONS` remains only as the fallback for a
  tenant that has authored none.
- **`kb.match_entities()`** — selection reaches what the tenant actually sells.
  A stated requirement is checked against entity attributes; keyword relevance
  only ever breaks a tie.
- **`KbBrand.next_steps` / `.selection`** — the decision layer no longer
  hardcodes `diagnostic` and `fractional_cmo`, which existed only in the
  agency's catalogue.

Three general defects found while testing, each of which would have hit any
client with any vocabulary:

1. A keyword match on the word "seated" — present only in the ATTRIBUTE NAME
   `seated_capacity` — ranked a 200-seat room first for a party of 220. The
   blob now searches values, never keys.
2. A keyword match asserted `fits: True`. Relevance is not satisfaction.
   `fits` is now tri-state: `True` checked and satisfied, `False` checked and
   not, `None` could not be checked. Keyword matches are always `None`.
3. Entities *lacking* the attribute were silently dropped, implying they had
   been ruled out. They now surface as unknown, ranked between fits and
   known-short.

A word that appears in more than 60% of a catalogue is discarded as
uninformative — computed per catalogue from document frequency, so it works
for any client with no hand-maintained stoplist anywhere.

**`KbUnknown` — the attribute-level feedback loop.** When an enquiry finds
nothing that fits, every option that could not be judged is logged and counted.
`/unknowns` poses the costliest gap; the reply writes the value onto the entity
and it becomes matchable immediately. `n/a` marks the attribute inapplicable —
it stops being asked about *and* stops appearing in results. Gaps that blocked
nothing are never logged, so the queue stays ranked by real cost.
| `scripts/test_kb.py` | Offline harness for the KB write layer + guided intake |

**KB write layer + guided intake (Aug 2026).** `kb.py` gained a write half and
an intake half. `INTAKE_STEPS` is an ordered list of what unblocks the most;
`gaps()` reports what is unmet, `next_step()` poses one question, and
`apply_answer()` parses the reply **in code** — a model deciding which field a
sentence belongs to is a silent-corruption machine, and the KB is the one place
nothing may be quietly wrong. Telegram `/next` opens a question, stores the
pending step in `Setting`, and reads the next plain message as the answer.
Whether an answer took is decided by re-checking `gaps()`, not by pattern-
matching the reply — so a rejected answer re-opens its own question.

Guards that exist because testing produced the bug: a pipe in a scalar brand
field is a misrouted answer and is refused; a tone longer than eight words is
refused. Both wrote garbage before the guard.

Modified: `app/db.py` (9 new models), `app/web.py` (Telegram webhook, admin
routes, ops-command interception, `tg_voice` consumer branch, seven
`/admin/system*` routes), `app/admin_ui.py` (tabbed shell + Systems tab),
`app/ops_commands.py` (`/systems`), `render.yaml`.

**Database models added:** `Tenant`, `User`, `KbBrand`, `KbClaim`,
`KbAudience`, `KbObjection`, `KbEntity`, `System`, `SystemRun`. All KB rows
carry `tenant`.

**The systems spine (Aug 2026).** A system used to be a string in
`Tenant.systems` — a label with no state, contract, history or owner. It is now
a row:

- The **8-part contract** (decision #8) is eight columns, and `update(status=
  "live")` refuses while any is blank. A rule that can't be evaluated isn't
  enforced.
- **`ready()`** returns named blockers from three independent causes: an
  incomplete contract, an unwired capability, an ungroundable KB. Same
  refuse-and-name discipline as the assembler.
- **Autonomy is a state machine with gates** (`shadow → approve_all →
  approve_exceptions → auto`). Promotion needs run history — 20 decided runs at
  ≥90% for the third rung, 50 at ≥95% for the fourth, and a single denial in the
  recent tail closes the gate. Demotion is always ungated.
- **`SystemRun`** records blocked and failed runs, not just successes.
  `blocked_reasons()` aggregates them into the KB backlog ranked by how often
  each gap actually cost an output. `edit_diff` is the voice-learning signal.
- **Feedback has two channels, deliberately.** `note()` writes a Memory scoped
  to `system:<tenant>:<key>`, injected into that system's drafting prompt via
  `feedback_block()`. `promote_rule()` writes into `KbBrand.banned_claims`,
  where the deterministic validator enforces it. A prompt mostly obeys; a
  validator always blocks — anything phrased never/always belongs in the second.
- Conversation reuses `ChatMessage.thread`, which already isolates per agent;
  the key just gets more specific.

---

## 5. How to run and test

Offline assembler test — no API key needed, exercises diagnose/select/decide:

```bash
python3 scripts/test_brief.py --demo
python3 scripts/test_brief.py --say "our ads stopped working and margin is thin" --type ecom_inventory
```

Full chain (needs `ANTHROPIC_API_KEY` in a local `.env`):

```bash
python3 scripts/test_brief.py --email prospect.txt
```

**Testing gotcha:** FastAPI `TestClient` only fires startup events when used as
a context manager (`with TestClient(app) as c:`). Without it, `init_db()` never
runs and every DB call fails with "no such table". Also avoid
`sqlite:///:memory:` with TestClient — each pooled connection gets its own
empty database. Use a temp file.

---

## 6. Deploy

Render auto-deploys `main`. Two services (`assistant-web`, `assistant-worker`)
both read the `assistant-env` env group.

```bash
git -C /Users/gomehsaias/Documents/gomehagent-build push origin HEAD:main
```

Push needs the sandbox off for network access. Remote uses SSH alias
`github-gomehagent`, already configured in `origin`.

**Env vars must live in the GROUP, not one service.** The webhook runs on
`assistant-web` but scheduled approvals are sent from `assistant-worker`;
setting them web-only makes cron approvals silently fall back to email.

---

## 7. Owner setup still outstanding

1. **`OPENAI_API_KEY`** in `assistant-env` — voice notes fail without it
   (transport works; nothing turns audio into text).
2. **`/admin/register_owner?key=<APPROVAL_SECRET>&chat_id=<ID>&name=Gomeh`** —
   seeds the five tenants and claims his chat. Nothing works before this.
   If he doesn't know his chat id, messaging the bot returns it.
3. **Per-tenant credentials** via the console at `/admin/ui?key=<SECRET>`.
4. **Omnisend 90-day campaign export** — the baseline for the email builder.
   The Omnisend MCP's `execute` passthrough is broken (payload arrives as a
   string), so this must be a manual export from the Omnisend UI.
5. **Baci logo** — dark version, or confirm the navy `#0c074a` header band.

---

## 8. Next slices, in order

**Slice 3 — generator + validator + send.** Closes the loop on the agency
lead responder: brief → draft → validate → Gmail draft → Telegram ping.
`gmail_client.py` and `approvals.py` already exist and `approvals` already
routes through `channel.py`.

It now lands into the systems spine rather than beside it: open a run with
`systems.start_run()`, close it with `finish_run()`, block with the named
field in `blocked_on`, and pull standing guidance with
`systems.feedback_block(tenant, key)` at drafting time. Respect
`system.autonomy` — `shadow` records without sending.

Caveat that shapes this slice: `Approval` has **no tenant or system column**,
so approvals can't yet be filtered per client or tied back to a run. Add
`tenant` + `system_id` + `run_id` to `Approval` as part of this slice; the
auto-migration handles the columns, and the alternative is retrofitting the
join after there's live data in it.

The validator must check: every factual sentence carries a `claim_id`; no
`banned_claims` string present; referenced entities available; media rights
valid; topic not already covered; disclaimers and UTMs present.

**Slice 4 — agent scoping.** Non-owner free-text currently falls through to
`command_agent`, which is **not tenant-scoped**. This is why clients must not
be given bot access yet.

**Slice 5 — reports.** Ads and business health per tenant. The data sources are
connected; nothing generates a report.

**Slice 6 — Baci campaign email.** Needs the Omnisend export, a vision pass
over the Baci photo library to generate `semantic_description` (the Content
Organizer has per-photo Drive links), and MJML for the HTML.

Then: Coverings blog, Ironside quote responder (blocked on rate cards),
Eien reorder engine.

---

## 9. Known gaps and traps

**The seam now has a schema, but not yet call sites.** Every operational model
carries `tenant`, uniqueness is per client, and `db.tenant_filter()` is the one
definition of scope. What has *not* happened is rewriting the queries in
`ops_jobs.py`, `command_agent.py`, `data_tools.py` and `worker.py` to use it —
they still read across all clients. That is safe while Gomeh is the only
operator and becomes wrong the moment a client's data lands in those tables.
`worker.is_trusted` was scoped already because it gates auto-send.

**The codebase is two halves that don't meet yet.** The *knowledge* half
(`tenants`, `kb`, `brief`, `systems`, `ops_commands`, `admin_ui`) is genuinely
multi-tenant: every row carries `tenant` and scope is enforced server-side from
the user row. The *execution* half predates it and is **tenant-blind** —
`approvals.py`, `worker.py` and `kernel.py` contain zero references to tenants,
and `Approval` has no tenant column. `ChatMessage.thread` and `Memory.scope`
isolate by agent role, not by client. Nearly all remaining work is on that seam,
which is why "four new files on running infrastructure" understates slice 3:
the infrastructure it lands on is single-tenant.

**Blocking client access:** ops commands are correctly scoped (verified: a
client pinned to `coverings` is refused `baci`), but unrecognised text falls
through to an unscoped agent. Do not invite clients until slice 4 lands.

**The console key no longer travels in URLs (Aug 2026).** Supply it once —
`?key=` or `-H "X-Admin-Key: …"` — and it is exchanged for an httpOnly session
cookie holding an HMAC of the secret, not the secret. `/admin/logout` clears it.
The console omits the key from its own links once the session exists. Still one
shared credential with no per-user identity: this removed the leak surface, not
the need for auth before clients get logins.

The original note, still true in substance: every form embedded `APPROVAL_SECRET` as a
query param, so it lands in browser history and any proxy log. Acceptable while
the only user is the owner; it must not be the same credential the moment
clients get a login.

**The Systems tab is query-heavy** — roughly 100 queries per render at 11
systems, because `ready()` calls `kb.completeness()` per system. Fine for an
admin page on Postgres; revisit if the tenant count grows.

**Scope narrowness is invisible.** `verify()` catches a dead token but not a
token with insufficient scopes. Grant the full read set when creating each
Shopify custom app — it fails quietly later.

**`add claim:` can't be dictated.** Voice notes can't produce `|` characters.
Typed only, until a spoken format exists.

**Media layer doesn't exist.** No object storage, no CDN, no vector store.
Drive links don't hotlink reliably into email. This is the largest unbuilt
piece and it blocks the Baci email builder's media matching.

**Holdouts are meaningless on small lists.** Eien does ~45 orders/month. Set a
minimum-volume threshold below which revenue claims are labelled directional.

**Idempotency is not yet implemented on publish.** A worker restarting
mid-publish would double-send. Must land before anything sends for real.

**Work-product ownership.** The Ironside contract assigns all work product to
the client and defines it broadly enough to include code. Separate platform
(licensed) from client data (theirs) in future contracts. Lawyer conversation.

**Prompt/model pinning per tenant is designed but not built.** One prompt change
currently affects everyone.

---

## 10. Established per-tenant facts

**Baci Milano** — Shopify + **Omnisend confirmed** (app embed in published theme
"Copy of SEO Horizon", id 188713402680). Design tokens: Inter 400/500/700,
primary `#2921DC`, navy `#0c074a`, acid yellow `#f7f216`, button radius 14,
UPPERCASE. **`logo` and `logo_inverse` are both the white file** — the email
header needs a navy band or a text wordmark. Meta account 949335500698690.
Retail 4.5× landed, wholesale 2.2×. Buyer: 99.4% women, core 35–44.
Rules the validator enforces: never claim Italian manufacture or handcraft;
no product customisation; bundles never more than 10% off summed retail.

**Eien Health** — Shopify + Omnisend + Authorize.net + Zip.co. 84.9% one-time
buyers, 33 active subscribers of ~7,400 customers. Omega 3 loses $20.76/unit at
$17.99 against $36.01 CAC. **No `banned_claims` authored — a supplement brand
with a GLP-1 product and no claim boundary is the highest-risk gap in the
portfolio.**

**Coverings Etc** — B2B spec sales, Shopify in build, ESP unnamed, Salesforce
CRM. Excellent SKU-level spec data (26 columns) and a real keyword map
(13,840 monthly volume across 6 pages). Bio-Glass Emerald Forest has an
unresolved size conflict (MB 100"×56" vs cut sheet 110"×49") — the provenance
fields exist for exactly this.

**Miami Ironside** — Squarespace, no commerce, $7,500/mo retainer, 7×+ ROAS on
event campaigns. 8 venues with real capacities. **No rate card, catering rules,
load-in or curfew data** — the quote responder blocks on this and will keep
refusing to quote until it exists. Correct behaviour, not a bug.

**Agency** — seeded with 12 claims, 4 audiences, 6 objections, 3 offers. Claims
are tagged with situations from a controlled vocabulary validated at seed time.

---

## 11. Reference artifacts

1. Brand KB schema filled on 4 real clients + gap audit —
   https://claude.ai/code/artifact/ed96e501-bbc3-48a0-bbcc-945114716e09
2. Platform architecture + 10-client self-assessment —
   https://claude.ai/code/artifact/5259bbef-bd6d-4fee-8558-0dc564ae3fed
3. Three worked pipeline traces on real data —
   https://claude.ai/code/artifact/b2a935a5-9622-4cd7-8591-865480688dc6
4. Build spec — component requirements and technology verdicts —
   https://claude.ai/code/artifact/170bcd38-f9b7-4cbb-bb42-d75a332a1608
5. Operator view — how Gomeh uses it day to day —
   https://claude.ai/code/artifact/7d1c1077-4179-484d-b498-ea10ea26dd33
   *(the first diagram in this one is malformed and needs rebuilding)*
6. Ops manual — accounts, connections, commands —
   https://claude.ai/code/artifact/2b169286-6d7f-44a4-9ec7-619923938709

---

## 12. Working style that produced good results here

- **Run the thing before claiming it works.** The brief assembler test harness
  found three real bugs on first run — two keyword patterns that missed real
  prospect phrasing, and a rule that couldn't distinguish a failed page fetch
  from a genuine absence. All three would have shipped bad emails.
- **A published artifact was shipped without being rendered** and its diagram
  was malformed. Render and check before sharing.
- **When output is bad, diagnose the cause before reaching for the prompt.**
  Generic → thin KB. Irrelevant → wrong selection. Off-voice → voice layer.
  Wrong → missing validator rule. Three of four are not prompt problems. This
  taxonomy has already paid off once: a deliverability prospect was being
  answered with a Shopify exit story, and the fix was in selection ranking.
