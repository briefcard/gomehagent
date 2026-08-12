# Handoff — Multi-tenant Content Platform

Everything a fresh thread needs to continue this build. Written 2026-08-10.
All code referenced here is on `main` and deployed.

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

| Component | State |
|---|---|
| Telegram ops channel | **Deployed and live** |
| Tenant registry + user scoping | Deployed, tested |
| Knowledge base (5 tables) | Deployed, agency tenant seeded |
| Brief assembler (decision layer) | Deployed, tested offline |
| Admin console + live verification | Deployed |
| Systems registry + run ledger | Built, tested offline — **not yet pushed** |
| Systems tab (console) + per-system threads | Built, rendered — **not yet pushed** |
| KB write layer + guided intake (`/next`) | Built, tested — **not yet pushed** |
| Knowledge tab (console) | Built, rendered. Now shows **every** KB column per client, including the situation vocabulary, non-selectable claims, and the gap queue — **not yet pushed** |
| KB seeded for baci / ironside / eien / coverings | Script written, **not yet run against prod** |
| Tenant-shaped selection (rec 1) | Built, tested — **not yet pushed** |
| Unknowns feedback loop (`KbUnknown`, `/unknowns`) | Built, tested — **not yet pushed** |
| Client intake links (`/intake/<token>`) | Built, tested — **not yet pushed** |
| Readiness bar means something (rec 2) | **Not built** |
| Ledger + guidance wired into the path (rec 3) | **Not built** |
| Generator / validator / send (rec 4) | **Not built** |

| Reports (ads, business health) | Not started |
| Canva | Not connected (OAuth, needs auth layer) |
| Agent scoping for non-owners | **Not started — blocks client access** |

**Read `DEFECTS.md` before touching `kb.py`, `brief.py` or `systems.py`** — it
records every defect found so far, the six patterns they share, and what is
still broken.

Live service: `https://assistant-web-zm2d.onrender.com`
Bot: `@Gomehadmin_bot`

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

**The console key travels in URLs.** Every form embeds `APPROVAL_SECRET` as a
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
