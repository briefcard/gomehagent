# Defect log — what broke, why, and what is still broken

Written 2026-08-11. Read this before changing `kb.py`, `brief.py` or `systems.py`.

Every defect below was found by **running the thing**, not by reading it. Several
were in code that looked correct and had passing tests around it. The patterns in
§1 are the reusable part — the individual bugs matter less than the shapes they
share, because those shapes will recur in the generator, the validator and every
adapter after them.

---

## 1. The patterns — what to watch for

**Silent loss.** A writer returns a status string, the caller ignores it, rows
vanish. Hit us once for real (§2.1) and would have shipped a knowledge base
missing a third of its proof. *Rule: after any bulk write, assert the count
changed. Never trust a return value nobody reads.*

**Unknown collapsed into a value.** The single most common defect here — three
separate instances (§2.5, §2.6, §2.11). Missing data was treated as `False`, or
as `True`, or silently removed. All three are forms of inventing. *Rule: absence
is a third state and must survive all the way to the output.*

**Structural metadata mistaken for content.** Matching searched attribute
*names* as though they were values, so `seated_capacity` "contained" the word
seated (§2.4). *Rule: match against what a thing says, never against how it is
stored.*

**String-matching instead of state-checking.** Whether an answer was accepted
was decided by reading the reply text (§2.3). *Rule: ask the data. `did the gap
close?` is robust; `does the message start with "Format:"` is not.*

**Migration adds columns, not values.** Auto-migration cannot know what a new
column should contain, so every existing row comes back empty and behaviour
silently regresses (§2.9). *Rule: a new column with meaningful defaults needs a
backfill in the same change.*

**Ranking across incomparable scales.** Two scoring modes produced numbers that
were sorted together, so a weak signal outranked a strong one (§2.4, §2.5).
*Rule: when evidence types differ in kind, one must be authoritative and the
other may only break ties.*

---

## 2. Defects found and fixed

### 2.1 The seed silently dropped three claims
`add_claim` correctly refused claims tagged with situations outside the tenant's
own vocabulary. The return value went nowhere, so the seed reported success while
Baci lost its Four Seasons placement claim and Ironside lost its only claim.
**Fix:** `scripts/seed_kb.py::_claim()` compares row counts and aborts.

### 2.2 A misrouted intake answer wrote garbage into the brand voice
Answering the *tone* question with a pipe-formatted objection stored
`["Corporate","planners","hate","slow","replies"]` as the brand's voice. Nothing
downstream could have detected it.
**Fix:** a pipe in a scalar brand field is treated as a misrouted answer and
refused; tone longer than eight words is refused.

### 2.3 Whether an answer landed was decided by reading the reply text
The intake re-opened a question only if the reply began with `Format:`.
**Fix:** re-check `kb.gaps()` — if the gap is still open the answer was rejected,
whatever the message said.

### 2.4 A 200-seat room was offered for 220 seated guests
Keyword matching searched attribute *names*, so every room with a
`seated_capacity` field "matched" the word seated, and that keyword score was
sorted against genuine capacity comparisons. Glassbox (seats 200) ranked first
for a party of 220.
**Fix:** the searchable blob is name + description + attribute **values**. A
stated requirement is authoritative; keyword relevance only breaks ties.

### 2.5 A keyword match asserted `fits: True`
Relevance was being reported as satisfaction — a generator would have written
"this room fits your party" on the strength of a word appearing in a description.
**Fix:** `fits` is tri-state — `True` checked and satisfied, `False` checked and
not, `None` could not be checked. Keyword matches are always `None`.

### 2.6 Entities lacking the attribute were silently dropped
A space with no seated capacity recorded vanished from results, which implies it
was ruled out when it was never measured.
**Fix:** surfaced as `basis: unknown`, ranked between fits and known-short.

### 2.7 Generic words dragged in the whole catalogue
"colourful" matches every Baci product; "space" matches every Ironside venue. No
hand-written stoplist would generalise to clients we haven't onboarded.
**Fix:** a word appearing in more than 60% of a catalogue is discarded as
uninformative, computed per catalogue from document frequency. No stoplist
anywhere.

### 2.8 Auto-migration silently stripped the agency's offer
`selection` and `next_steps` were added to `KbBrand`. Existing rows came back
empty, `next_step_for` returned nothing, and every agency brief produced a blank
ask. The tests passed; only the rendered output showed it.
**Fix:** `scripts/seed_kb.py::backfill()`. `next_steps` is now also an intake
question so an unconfigured tenant is visibly incomplete.

### 2.9 Gaps that cost nothing were logged as gaps
Recording every unmeasurable entity on every enquiry would bury the ones that
actually lose business.
**Fix:** unknowns are logged only when nothing fit the enquiry.

### 2.10 `n/a` silenced the question but not the noise
Marking an attribute inapplicable removed it from the queue but it still appeared
as an unknown in every future result.
**Fix:** `not_applicable` excludes the entity from that requirement entirely.

### 2.11 A misrouted answer became a banned phrase
The scalar-field guard from §2.2 covered tone and positioning but not
`banned_claims`. A pipe-formatted objection stored as a banned phrase would
silently reject legitimate drafts forever — fail-closed in the wrong direction
is still wrong.
**Fix:** the guard now covers `banned_claims` and `next_steps` too.

### 2.12 Naive vs aware datetimes
SQLite drops the timezone even on `DateTime(timezone=True)`; Postgres keeps it.
Any comparison against `utcnow()` therefore works in production and raises
locally. **Fix:** `db.as_utc()` — always compare through it.

### 2.13 The Knowledge tab showed a third of the knowledge base
The console rendered claims, audiences, objections and entities, and of those only
the headline fields. Never rendered anywhere: the per-tenant **situation
vocabulary** (the controlled list that decides whether a claim is accepted at
all), `next_steps`, `selection`, `approval_policy`, `elevator`, `voice.do_say` /
`never_say`, claim `proof_type` / `verified_at` / `expires_at`, audience
`buying_trigger` / `decision_timeline`, objection `escalate` / `audience_key`,
entity `availability` / `source` / `freshness_days`, and the whole `KbUnknown`
queue.

This is the same shape as §2.8 and it is why §2.8 took so long to see: the
migration emptied `next_steps`, the tests passed, and the only place the damage
showed was a rendered brief — because the console never displayed the field.
A field nobody can read is a field nobody maintains.
**Fix:** `render_kb` shows every column the KB stores, and
`kb.claim_inventory()` / `kb.situation_rows()` were added so it can. Verified by
`scripts/test_kb_ui.py`, which asserts against the rendered HTML per tenant using
the real seed data — if a fact is in the KB and not on the page, it fails.

### 2.14 Non-selectable proof was invisible rather than explained
`claims()` correctly drops pending, retired and expired rows. The console called
it directly, so an account whose proof expired last month looked identical to one
that never had any — the §1 *unknown collapsed into a value* pattern, in the
surface this time rather than the data.
**Fix:** `claim_inventory()` splits every claim by *why* it is or isn't
selectable and the page shows all four states, each labelled. Same for entities:
an `oos` item is now marked rather than listed as if sellable.

### 2.15 Three of the four verification suites had been broken since e9f3460
`kb_seed` moved into `app/` so the web service could reach it, leaving
`scripts/seed_kb.py` a thin CLI wrapper. `test_kb`, `test_selection` and
`test_intake` loaded that file by path and called `m.seed_baci`, which no longer
existed — all three died on `AttributeError` at import. DEFECTS.md meanwhile
claimed all four suites passed, which is worse than the breakage: the document
used to decide whether the system works was asserting something nobody had re-run.
**Fix:** the three scripts import `app.kb_seed` and call `seed_all()`. *Rule: a
refactor that moves a module must be verified by running the suites, not by
reasoning that the callers look fine.*

### 2.16 The operational half enforced uniqueness globally
`Contact.email`, `Shipment.name` and `RFQ.shipment_name` were `unique=True` —
across every client at once. The same freight forwarder could not be a contact
for two clients, and two clients could not both run a `Turkey-Mar2026`. Not a
design debate: an `IntegrityError` on the second client, during onboarding.

Twenty of thirty-one models had no `tenant` column at all, including every table
Activity Reporting and the AI VA run on (`EmailLog`, `Contact`, `DocIndex`,
`Usage`, `Deadline`, `FollowUp`, `Shipment`, `VoiceProfile`).
**Fix:** `tenant` on 18 operational models; the three global uniques regraded to
composite `(tenant, …)`; `db.tenant_filter()` as the single definition of "belongs
to this client"; `app/tenant_scope.py` backfills what is derivable.

**I called two tables underivable that were not.** `Expense` has an `account`
column written straight from the inbox alias, and `Approval.payload` carries
`{"account": alias}` or `{"site": profile}` at every call site — roughly 620
production rows written off as unrecoverable when the answer was on the row.
The classification had been reasoned about rather than checked against the
writers. *Rule: before declaring data unrecoverable, read the code that wrote
it.* Both now derive; `doc_index` and `usage` genuinely do not, and the
distinction is the useful part — see below.

Four decisions worth keeping:

- **The dry run predicts per row, not per table.** The first version of
  `report()` returned `derivable: true` per table, which reads as "these 3,897
  rows will be attributed" when it only means "a rule exists for this table" —
  most chat threads are called `admin` and name no client at all. That is the
  §1 *structural metadata mistaken for content* pattern, in a report someone
  was about to act on before a 13,772-row write. `preview()` now counts real
  rows and shares `_derive()` with `backfill()`, so the prediction cannot drift
  from the write it predicts; `test_tenant_scope.py` asserts they are equal.

- **Unassigned is not "everyone".** `db.UNASSIGNED` is excluded from per-client
  queries unless a caller asks for it by name. Folding unattributed rows into
  whoever is asking is how one client's shipment reaches another's report.
- **"Unrecoverable" has two very different causes.** `usage` never knew its
  client. `doc_index` *did* — Drive is looked up per inbox — and stored it
  nowhere. The first is a data limit; the second is a missing column on the
  writer, and no backfill will ever fix it. `tenant_scope.resolve()` exists so
  writers attribute at capture time, which is the only point where it is cheap.
- **The backfill derives, it does not guess.** An inbox belongs to one client
  (`account` → `Tenant.gmail_alias`), a site belongs to one client (`domain` →
  `Tenant.domain`), and `system:baci:blog` names its own. A shipment records
  nothing that says whose it is, so it stays unassigned and is counted in
  `report()`. A wrongly attributed row is worse than an unattributed one,
  because nothing downstream will ever question it.

### 2.17 Allowing duplicates opened a cross-client trust path
`worker.is_trusted(sender)` looked a contact up by email alone and returned the
first match. Once the same email can exist for several clients, one client's
`trusted=yes` would authorise auto-send on another client's inbox.
**Fix:** scoped to the inbox's tenant, matching that tenant *or* unassigned —
unassigned still counts, because dropping it would silently switch auto-send off
for every pre-tenant contact (§2.8 again), but a *different* client's row never
does. Verified in `test_tenant_scope.py`.

### 2.18 Smaller ones
- `admin_ui` reported "Runs (8)" when there were more — capped count shown as total.
- FastAPI does not accept `**fields` for query params; read `request.query_params`.
- Published artifact: SVG markers referenced across fragments, and HTML entities
  broke XML parsing. Caught pre-publish by parsing each `<svg>` as XML.
- `TestClient` only fires startup events as a context manager; and
  `sqlite:///:memory:` gives each pooled connection its own empty database.

---

## 3. Still broken — in priority order

**Recommendation 2 — the readiness bar is a floor, not a standard.** *Not built.*
`completeness()` passes on one or more of each. Ironside reports **ready** on one
claim and one objection; one objection cannot cover what a planner asks. Worse,
a hollow brief still passes: an enquiry that produces no situations, no matched
entity and no offer returns `blocked=False` and would be handed to a generator.

**Recommendation 3 — half wired (2026-08-12).** `worker.systems_tick` now calls
`start_run`/`finish_run` daily, so the Systems tab shows real runs and
`blocked_reasons()` ranks the KB backlog by what actually costs an output. It
sends nothing: a system that is not live is skipped, and one on the `shadow`
rung records and stops.

Still unwired: **`feedback_block` has no caller.** Guidance written into a
system thread is stored and never reaches a drafting prompt — it will, when the
generator lands, which is the same slice.

**Recommendation 4 — nothing generates.** *Not built.* No generator, no
validator, no send.

**Nine lookups still find a row by its old global key.** `Shipment.name` and
`RFQ.shipment_name` are queried without a tenant in `command_agent.py:421,856`,
`data_tools.py:488,505`, `ops_jobs.py:841-842` and `skills.py:148`. Correct
*today* — only one client has logistics rows, so `.first()` can only return the
right one — and a silent cross-client bug the moment a second client gets a
shipment. Fix these when logistics becomes multi-client, not before; they are
listed here so the trigger is written down rather than remembered.

**~~The Postgres constraint regrade has not run against the live database.~~
Verified 2026-08-12.** `/admin/schema_check` on the deployed service reports
`ok: true` — all three regrades landed (`uq_contact_tenant_email`,
`uq_shipment_tenant_name`, `uq_rfq_tenant_shipment` present; the old global
uniques gone) and every scoped table has its tenant column. That route is the
permanent answer to "did the migration land", since no local test can exercise
the Postgres-only path.

**Approval now has `tenant`, `system_id` and `run_id`** — added while the table
was still empty. Nothing writes them yet; `approvals.py`, `worker.py` and
`kernel.py` remain tenant-blind at the call sites.

**Idempotency on publish.** A worker restarting mid-publish double-sends.
Must land before anything sends for real.

**No edit or delete on KB rows.** `retire_claim` / `review_claim` now exist for
claims, but audiences, objections and entities remain add-only — a wrong row is
permanent without direct database access.

**Objections are zero on three accounts** (baci, coverings, eien). Human-authored,
cannot be scraped, and half the paid intake.

**Eien's banned claims are my conservative defaults, not Gomeh's.** A supplement
brand with a GLP-1 product. Needs review.

**~~Free text falls through to an unscoped agent.~~ Half fixed 2026-08-12.**
`kernel.run` now takes a tenant: the thread is qualified by it, memory and
lessons are filtered to it, and `tenants.agent_block()` injects the account's
identity, connections and banned claims. With no account selected the agent
refuses rather than assuming. Enforced by `scripts/test_tenant_isolation.py`.

**Tools are gated too (2026-08-12).** Seven of the eleven shared tools took the
account as a MODEL-SUPPLIED argument (`store`, `account`), so which client the
agent addressed was a suggestion rather than a boundary. Now, while an account
is active: the parameter is stripped from the schema the model sees, the
resolved value is injected at dispatch, a tool naming a *different* account is
refused by name, and a tool whose connection is not wired is not offered at all.
The last one also cuts context — a venue is sent 4 schemas instead of 11.

**Gating one pack was not a boundary (2026-08-12).** The first pass covered the
11 shared tools. An audit of the roles found **32 more taking an account** — 12
in admin, 27 in seo, including `queue_email_draft` (drafts mail *as* an account),
`calendar_create_event`, `save_file_to_drive`, and four `propose_*` tools that
publish to a live storefront. All 81 tools now pass through
`tool_scope.guard()` in `kernel._dispatch`, before anything is routed.

`tool_scope.ACCOUNT_PARAMS` is the completeness guard: a tool whose schema
exposes `store`, `account`, `alias` or `site` and is absent from `SCOPED` fails
the isolation test by name. Verified by removing `queue_email_draft` from the
registry and watching it fail. That is what stops tool 82 reopening this.

Note the SEO resolver: a tenant with no `sites.py` profile gets **no** SEO
tools, rather than the primary site by default — which is what the unscoped code
did, and is how one client's content work would have been done against
another's property.

### 2.19 A joined string ranked ' ' and 'e' as the costliest gaps
`SystemRun.blocked_on` is `Column(JSON, default=list)` and `blocked_reasons()`
iterates it to rank the KB backlog. The first `systems_tick` passed
`"; ".join(blockers)` instead of the list. SQLite accepted it, iterating a
string yielded characters, and the backlog came back as
`[(' ', 206), ('e', 195)]`.

Every assertion passed — the test checked that reasons existed and were sorted,
both true of characters. It was caught by reading the printed output, which is
the §12 rule in the handoff working exactly as intended.
**Fix:** pass the list. The test now asserts a reason is longer than three
characters and reads like a missing thing, so the shape cannot regress silently.

### 2.20 The unattended half could send a banned claim
`worker.py` and `triage.py` run with nobody watching and can auto-send. They
were addressed by inbox alias and had no idea which client that was:
`triage.py` called `data_tools.dispatch()` with **no tenant**, so triage's own
tool loop could read another client's mail while triaging this one; its working
memory was unscoped; and it had never been able to see `banned_claims`. Baci's
ban on "made in Italy" was enforced nowhere in the code that actually sends.

**Fix:** `tenants.for_alias()` resolves the inbox to its client once in the
worker and threads it through. Triage's tool loop is filtered and gated like the
agent's, its memory is scoped, and `agent_block` supplies the account's rules.
The post-verdict guardrails moved into `triage._apply_guards()` — testable on
their own, reusable by the generator — and gained a **brand guard**: a draft
containing a banned phrase can never auto-send. An `auto_reply` carrying one is
downgraded to `escalate`, not to `draft`, because a rule violation is a signal
the model misread the account, not a wording problem.

The guard is code, and the same phrase is also in the prompt via `agent_block`.
Both, deliberately: a prompt mostly obeys, a check always blocks (decision #2).
An inbox with no tenant is **not** brand-checked and says so rather than
claiming a clean pass.

**`capabilities()` did not know about client-connected credentials.** Building
the connect page created it: a client could connect Shopify successfully and the
account still read "not wired", so the agent was never offered its tools — the
connection worked and nothing could use it. Found by the tool-gating test
failing on a correctly-connected account. `capabilities()` now counts a stored
`Credential` exactly as much as an env-group entry.

**Write operations are GET requests.** `/admin/kb_add`, `/admin/seed_kb` and
`/admin/tenant_scope` all mutate on a GET, so anything that causes a URL to load
— a browser prefetch, a link preview, a scanner walking history — can fire them.
A prefetched `/admin/tenant_scope` would run a 13,000-row backfill. Converting
the ten console forms to POST closes it; the session cookie already means the
credential is no longer in those URLs.

**~~The console key travels in every form URL.~~ Fixed 2026-08-12** — the key is
accepted once (query string or `X-Admin-Key`) and exchanged for an httpOnly
session cookie carrying an HMAC of the secret, never the secret itself, because
`APPROVAL_SECRET` also signs approval decision links. Comparisons are constant
time. What this is *not*: one shared credential remains, with no per-user
identity and no revocation — real auth is still required before any client gets
a login. See `scripts/test_console_auth.py`.

It must still not be the same credential once clients have logins.

**`kb.SITUATIONS` is still the fallback constant.** Per-tenant vocabularies now
exist as data, but a tenant with none silently inherits agency-B2B language.

---

## 4. How to verify

```bash
python3 scripts/test_selection.py   # selection + the unknowns loop
python3 scripts/test_systems.py     # registry, contract gate, autonomy ladder
python3 scripts/test_kb.py          # KB writes + guided intake
python3 scripts/test_intake.py      # client intake links, scoping, fail-closed guards
python3 scripts/test_kb_ui.py       # every KB field reaches the Knowledge tab
python3 scripts/test_tenant_scope.py  # per-client uniqueness, backfill, trust boundary
python3 scripts/test_migration.py     # the same migration over a database with rows
python3 scripts/test_console_auth.py  # console session: key once, then a cookie
python3 scripts/test_credentials.py    # client-connected credentials, encrypted
python3 scripts/test_tenant_isolation.py  # MANDATORY: every feature is tenant-scoped
python3 scripts/test_worker_systems.py    # the tick that fills the run ledger
python3 scripts/test_catalog_sync.py      # Shopify -> KbEntity, banned claims win
python3 scripts/test_compliance.py        # the live site vs the brand's own rules
python3 scripts/test_harvest.py           # site -> PENDING proposals, never facts
python3 scripts/test_brief.py --demo
python3 scripts/seed_kb.py --report      # what each account still needs
python3 scripts/tenant_scope.py --report # what is still unattributed
```

All fifteen suites pass as of 2026-08-12. None of them touch the network.

Re-run all five after any change to `kb.py` — §2.15 is what happens when the
claim in this section is trusted instead of re-checked.
