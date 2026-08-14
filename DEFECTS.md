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

Updated 2026-08-12. Everything here is measured, not assumed.

### Blocks producing anything a client sees

**Nothing generates.** No generator, no validator, no send. `systems_tick`
evaluates readiness daily and records "no generator yet" on every ready system.
This is the whole of recommendation 4 and the only thing between the platform
and an output. `feedback_block` also still has no caller — guidance written into
a system thread is stored and never reaches a drafting prompt. Same slice.

**Objections are 0 on all five accounts.** Human-authored, cannot be derived
from a website, and half of what any real reply needs. `/next` is the only path.
Baci also has no `voice.tone`, which is the single highest-leverage answer for
"does this draft sound like us".

### Known bugs, small

**`seed_agency` creates no `KbSituation` rows.** The four client seeds each loop
`kb.add_situation`; the agency seed does not. So `situations("agency")` reports
29 tags from the fallback constant `kb.SITUATIONS` — a bare set with **no
patterns** — and `situation_patterns("agency")` returns `{}`. Nothing can ever
pattern-match for the agency; only the learned tagger works there. ~15 lines in
`kb.py::seed_agency`, but note it is idempotent on the brand row, so situations
need seeding separately or the guard relaxing.

**Harvest and compliance read page furniture.** `_clean` strips tags but keeps
nav, header and footer text, so candidates come back as
`"Book a 25-min intro Start the intake ↓ Agentic Core SEO Fig."` and the
compliance matcher can flag a banned word in a menu link. Prefer
`<main>`/`<article>` and drop `<nav>`, `<header>`, `<footer>`, `<aside>` before
splitting sentences. Fixes proposal quality on every site at once.

### Client-side blockers (not our code)

**coveringsetc.com serves an incomplete TLS chain.** Only the leaf certificate,
no intermediate — `openssl` reports `Verify return code: 21`. `curl` tolerates it
via the system store; `certifi` does not, and neither will strict clients,
older Android, or server-to-server integrations. Blocks all crawling of that
account and is worth fixing regardless of us.

**marketingthatworks.co has WordPress sitemaps switched off** —
`/sitemap.xml` 301s to `/wp-sitemap.xml`, which 404s. Worked around: discovery
falls through to the wp-json API. A sitemap would still be better for SEO.

**Coverings has no `banned_claims`**, so compliance correctly refuses to scan
it. That is the one input a crawler can never derive — a site records what a
brand *does* say; the ban list is what it must *not*. Baci's own site says
"handmade in Italy", which is exactly why deriving rules from a site is wrong.

### ~~The three ingest sources each had their own rules~~ Fixed 2026-08-12

The onboarding data layer had no shared answer to "where did this row come from
and who may change it", so each source invented one. All five were measured on
the write layer before anything was changed, not inferred from reading it:

1. **Two of five KB tables had an approval state.** `kb_audiences`,
   `kb_objections` and `kb_situations` went live the instant anything wrote to
   them — a client could redefine a buyer segment through an intake link and it
   was in use before anyone read it.
2. **`add_claim` and `add_objection` inserted unconditionally.** Writing the
   same objection twice produced two rows; only `kb_seed`'s own guard kept the
   seed idempotent, and the harvester's guard was an exact lowercase match.
3. **The same fact from a crawl and an upload became two unrelated rows.**
4. **Approval left no trace** — no who, no when. "Approved is final" was a
   convention.
5. **`catalog_sync` decided ownership with `source not in ("shopify", "")`.**
   Owner-approved copy on a row the store originally supplied still read
   `source="shopify"`, so the next sync overwrote it.

`app/provenance.py` is now the single answer. Every KB content table carries
`origin` (the source *kind*, deliberately separate from the free-text `source`
so precedence is never decided by string-matching prose), `review`,
`approved_by`, `approved_at`, `fingerprint` and `also_seen`.

- **Approved is final.** No machine source may change editorial content on an
  approved row. It records a `KbConflict` — both values kept, neither applied —
  which is the Bio-Glass 100"×56" vs 110"×49" case given somewhere to live.
- **Two narrow exceptions**, both in `may_write`: a store owns `price` and
  `availability` forever, and any source may refresh a row it created that no
  human has since touched. Without the second, a nightly sync would raise a
  conflict on every changed product description and bury the real ones.
- **Duplicates collapse only on an exact normalised fingerprint**; anything
  merely similar is flagged in the queue, never merged — merging two
  near-identical sentences invents a third that neither source said.
- **`review` and `origin` have no column defaults, on purpose.** Auto-migration
  applies a column default to every existing row, which would have stamped the
  whole KB "approved / human" and left the backfill nothing to derive from.
  A row written without a review state is invisible to selection instead.
- **`gaps()` counts proposals; `completeness()` does not.** Different
  questions: "has anyone told us yet" versus "may we generate from this". The
  first version got this wrong and made the intake form re-ask a client a
  question they had already answered.

Verified end to end in `scripts/test_provenance.py`, on a legacy-schema
database in `scripts/test_migration.py` (the path that runs against production:
grandfathering, derived origins, and stability across restarts), and rendered
in `scripts/test_kb_ui.py`.

**Still open on this:** `kb.SITUATIONS` remains the fallback constant, and
`seed_agency` still creates no `KbSituation` rows.

### ~~Every form POST 500'd in production~~ Fixed 2026-08-12

`python-multipart` was never in `requirements.txt`. Starlette imports it
lazily, from inside `request.form()` — nothing in `app/` says
`import multipart`, so it is invisible to an import audit, and every local test
passed because the dev machine had it as somebody else's transitive
dependency. On Render every form POST raised
`AssertionError: The python-multipart library must be installed`.

Broken since `8b9121b`, when form parsing arrived. What that means:

- `/admin/claim_edit` — **approve and reject have never worked** on the live
  console. The review queue was readable and not actionable.
- `/connect/<token>` — **the client-facing connect page has never worked**.
  This is the self-serve onboarding path the runbook tells you to send clients:
  they paste an API key, submit, and get an Internal Server Error.

Two reasons it went unnoticed for so long. It fails on one code path only, so
everything else on the console looked healthy. And a 500 on the console was a
dead end — the traceback in the service log, the operator in a browser, and
nothing joining them. The `/admin` exception handler added in the same change
is what identified it in one click: it names the exception on the page with a
reference matching the log line.

Guarded in `test_console_auth.py`, which now matches a FEATURE to the package
it silently requires — `.form()` implies `python-multipart`, `Jinja2Templates`
implies `jinja2`, and so on. An import audit cannot catch this class; that can.
Verified by removing the line and watching the suite fail.

### ~~The crawler proposed nonsense~~ Fixed 2026-08-12, and measured

Reported from a live queue: `"32 CM (32 CM) Is it dishwasher safe?"`,
`"Powerful Closures: ... isn&#8217;t just about wrapping things up"`,
`"1 of 2 Pitcher $135 Cake stand $195 In your table Authentic Italian design"`.

Three separate causes, and the first fix attempted was wrong.

1. **Block boundaries were destroyed.** `_clean` replaced every tag with a
   space, so a spec cell, an FAQ heading and two carousel prices merged into one
   string with no sentence boundary in it. `text_blocks()` now returns one
   string per block-level element and sentences are only split WITHIN a block.

2. **Entities were never decoded**, so `isn&#8217;t` survived — and `8217` is a
   number, which is the entire test for whether a sentence is "checkable". Every
   curly apostrophe was manufacturing evidence.

3. **Facts had no entity.** The wrong first fix was to discard product FAQs and
   specs as junk. They are not junk; the KB had nowhere to put a fact true of
   one product. `entity_key` on claims and objections fixed it properly, and a
   product FAQ became the one derivable source of objections.

Then the differential that mattered. Five homepages read by hand against what
the crawler proposed:

    baci      0 proposed  ·  3 real claims on the page   ·   0% recall
    ironside  0 proposed  ·  6 real claims on the page   ·   0% recall
    eien      12 proposed ·  two testimonials mistyped as brand assertions

Every miss traced to one rule — "a claim carries a number" — written for the
agency's case-study proof and wrong for the attribute claims every other client
differentiates on ("Designed in Milan", "No PFAS. No seed oils.", "Original
sections of the Berlin Wall"). Worse, the drop reasons reported
`"no number, so nothing to check": 77`, which reads as a finding about the site
and was a finding about the filter.

**The judgement moved to a model** (`extract.py`), under one constraint: it
SELECTS verbatim spans and `_verify` discards anything not in the source, so
fabrication is checked in code rather than trusted. Every deterministic guard
stays after it — banned phrases, tag validation, fingerprint dedupe,
`review="proposed"`, human approval.

**Still open:** recall is unmeasured. `scripts/test_extract.py --live` has the
differential checked in as a fixture with a baseline of baci 0/3, ironside 0/6,
and has never been run. That is the single highest-information thing available.

### ~~Objections could not be derived~~ Partly false, fixed 2026-08-12

This log said repeatedly that objections are human-authored and cannot be
derived. True of a website. False of a mailbox, where the brand has been
answering the same questions for years, and false of a product FAQ, which is
literally an objection with its approved answer.

`email_harvest` mines sent mail — filtered by the bucket `triage` already
assigned, so the noise was sorted once, months ago, rather than re-litigated.
`extract_qa` pairs the question with the answer and verifies each half against
its own side of the exchange, so the pair cannot silently swap who said what.

What remains true: an account with no mailbox has no source. **Ironside** is
one, and its objections are an authoring job.

### ~~Situations did not reach objections~~ Fixed 2026-08-12

Claims carried situations; objections did not; `claim_id` existed and nothing
had ever written it. So selection matched proof to a buyer's problem and
matched objections by word overlap — with a fallback that looked for the
literal string `"how fast"`, which exists only in the agency's seeded rows. On
Baci and Ironside the brief went out with no objection handled at all. Third
occurrence of hardcoded agency language in `_select`.

`KbObjection.situations` closes both edges: the vocabulary IS the join, so
"which objection fits this situation" and "which claims support this answer"
are the same query. Empty means universal, matching the `audience_key`
convention, so adding the column retired nothing.

### Architecture debt

**The SEO subsystem still does not read the KB.** `seo_tools`, `sites`,
`google_seo`, `shopify_seo`, `wordpress_seo` — 1,725 lines, zero references to
`banned_claims`, while publishing titles, descriptions and collection pages to
live stores. The new compliance scanner *detects* the result; nothing prevents
it. Highest-value remaining fix in the codebase.

**A client is defined in three places** — the `Tenant` table, `SEO_SITES_JSON`
(via `sites.py`), and `SeoSiteConfig`. The SEO subsystem uses the second; the
platform uses the first. Merge before onboarding client #6.

**Console writes are GET requests.** `/admin/kb_add`, `/admin/seed_kb`,
`/admin/tenant_scope`, `/admin/harvest` mutate on a GET, so a prefetch or link
preview can fire them. `/admin/claim_edit`, `/connect/<token>`,
`/admin/connect_link` and the POST half of `/admin/connect_revoke` are the
model to follow.

**The credential layer was invisible to its own operator** — fixed 2026-08-13.
`credentials.status()` returned per-provider state, who granted it, when it
last verified and which scopes came back dark; `/admin/connect_new`,
`/admin/connections` and `/admin/connect_revoke` all existed. **The console
rendered none of it.** The Accounts tab showed capability chips and a "Test
connections" button, and its own copy still claimed "API keys and tokens live
in Render env vars" — written before client-connected credentials existed and
wrong ever since.

This is §2.13 in a second subsystem, and the same sentence applies: a field
nobody can read is a field nobody maintains. It is also why the connect page
being broken for weeks (§"Every form POST 500'd") went unnoticed — there was no
screen on which a connection's state was ever shown, so there was nothing to
look wrong. Fixed by `admin_ui._connections`, asserted against the rendered
HTML in `test_oauth.py` the way `test_kb_ui.py` asserts the Knowledge tab.

**The console is one shared credential.** A session cookie replaced the key in
URLs, but there is no per-user identity and no revocation — and it now guards
client credentials, not just data.

**`Approval` has tenant / system_id / run_id and nothing writes them.**
`approvals.py` derives the tenant from the payload; the system and run columns
are still empty, so an approval cannot be tied back to the run that produced it.

**Nine lookups still find a row by its old global key** —
`command_agent.py:421,856`, `data_tools.py:488,505`, `ops_jobs.py:841-842`,
`skills.py:148`. Correct while only one client has logistics rows; a silent
cross-client bug the moment that changes.

**`kb.SITUATIONS` is still the fallback constant**, and the agency is the
account relying on it. See the seed bug above.

### Not built

**Spreadsheet upload** (Coverings' 26-column spec data, Ironside's rate card).
Now a single entry in `sources.SOURCES` — `key · label · produces · capability
· precondition · run` — plus the parser behind it. It inherits dedupe, the
review queue, provenance and conflict-on-disagreement for free. What it still
needs is its own work: column mapping per client, and a preview before write.

~~**OAuth for Google and Meta.**~~ Built 2026-08-13 — `app/oauth.py`, one
declared flow per provider so the routes know none by name. Still unproven
against a real provider, and still needs its four env vars. Two defects found
while building it, both the same shape as things already in this log:

- **A credential nothing reads.** `gmail_client.creds_for` read
  `config.GMAIL_ACCOUNTS` directly, so the entire Google flow would have stored
  a token, verified it, shown "connected" on the console, and left
  `email_harvest` reading the env blob and reporting an account with no mailbox.
  This is §2.13 in a different surface — a thing that exists, is used by the
  pipeline, and is invisible to the path that needs it. `shopify_config` had
  already solved exactly this for the other provider a session earlier, which is
  the part worth noticing: the fix existed and was not generalised.
  *Rule: when a second instance of a bridge is needed, look for the first.*

- **`capabilities()` had a clause per capability, and two never got one.**
  `ads` and `analytics` checked only the `Tenant` JSON columns, so a Meta
  sign-in would have stored a working credential and still read `ads: False`,
  and `sources.available()` would skip every ads source with "no ads
  connection" on an account that had just wired one. Now derived from
  `credentials.GRANTS`. The general point is that a per-case clause list grows
  by being edited, and the cases added last are the ones that get missed —
  §1 *customisation in code*, one layer down.

### 2.20 Every system's declared requirements were read by nothing — fixed 2026-08-14

`systems.CATALOG` gives each system a `kb_needs` tuple — the knowledge-base
fields it cannot run without. `ready()` never read it. It called
`kb.completeness()`, one global bar of six things, so every system was gated
identically regardless of what it actually used. `kb_needs` had exactly one
consumer, `waiting_on()`, which is a prioritisation display and not a gate.

Wrong in both directions, and neither error could be seen, because the declared
list was decorative:

  · **Website content compliance** declares `banned_claims` and nothing else,
    and needs no connections at all. It was blocked until the account also had
    a tone, a claim, an audience, an objection and a product — five things it
    never touches. The cheapest system to switch on, and the one that gets a
    client a verifiable number in week one, was gated like the most expensive.
  · **`next_steps`** is in the lead responder's declared needs and
    `completeness()` does not test it at all, so a lead responder could pass
    its gate and draft with a blank ask — §2.8, still reachable through a green
    light.
  · **`reorder_engine`** carries `needs_kb=False`, so it was gated on no
    knowledge-base check whatever — including no `banned_claims` — while
    triggering customer-facing email through an ESP. Same shape as the SEO
    subsystem publishing to live stores without reading the ban list.

`kb.needs_met(tenant, fields)` tests named requirements one at a time and
`ready()` gates on the system's own list. *Rule: a declaration that nothing
reads is a comment. If a spec field is meant to constrain behaviour, find its
consumer before trusting it — and if there is none, that is the defect.*

**Still open, and a judgement call rather than a bug:** two declarations look
wrong on inspection now that they are load-bearing. `campaign_email` names no
`audience` and no `next_steps` — a campaign email with no segment and no
call to action. `reorder_engine` names neither `tone` nor `banned_claims`
despite sending customer-facing copy. Both were written before any generator
existed and have never been tested against one, because nothing generates.

### 2.19 A product answer was claimed of the whole catalogue — fixed 2026-08-14

Reported from the live Knowledge tab. Six objections harvested off Baci product
pages, every one rendered **"applies to everyone"**:

    Is it dishwasher safe?      Yes — dishwasher safe (top rack only).
    How many pieces?            This is sold as a set of 6 pieces.

Baci sells gold-rim porcelain, which is **not** dishwasher safe, and plenty that
is not sold in sixes. Each answer is true of the page it was scraped from and
false of the catalogue it was filed against. Approved, live, and exactly the
class of error the KB exists to prevent — a generator reading that row tells a
porcelain buyer to put it in the dishwasher.

Four failures in one chain, and the retrieval layer was not one of them:
`kb.objections()` has scoped by `entity_key` since the column landed, and its
docstring already named this case. The data was wrong, and everything that
could have shown that was missing.

1. **`harvest.py:347` collapsed unknown into a value.**
   `entity = handle if ("/products/" in url and handle in owned) else ""` — and
   `""` already meant *true of the whole brand*. A page whose product could not
   be resolved was filed as a fact about everything. §1, in the one place where
   being wrong misinforms a customer.
2. **The objection review form had no way to say what an answer was about.**
   Claims have had an entity picker since the queue existed; objections got
   Approve and Reject and nothing else. So a reviewer who *saw* the problem
   could only approve it wrong or throw away a real answer. **This is why the
   wrong rows are approved** — the form gave nobody a third option.
3. **The Knowledge tab rendered `audience_key` and never `entity_key`**, so a
   correctly scoped answer still displayed "applies to everyone". §2.13 again.
4. **That page called `objections(tenant)` with no entity**, which filters to
   `entity_key IN ("", None)` — the brand-wide subset — and presented it as the
   list. Every product-scoped answer was invisible on the one page whose job is
   showing what the account knows.

**The fix needed no new column.** `entity_key = ""` carried two meanings the
code could not separate — a human deciding "brand-wide" and a crawler failing
to resolve a product — and `origin` already separates them.
`kb.scope_unconfirmed()` reads machine-origin + no entity + not yet approved as
undecided, and approval is refused until the reviewer picks an item or ticks
that it really is brand-wide. Approving IS the decision, which is why the guard
sits on the approval path.

Rows already approved by the old code are the ones saying something false
today, and a guard on approval does nothing about them —
`kb.update_objection` plus a Save-scope control on every row is how those get
fixed without deleting a real answer.

*Rule, third time of asking: when a column's empty value means something, a
writer that cannot determine the value must not be able to write the empty
one.* See §2.5 (`fits` tri-state) and §2.6 (entities silently dropped).

Verified in `scripts/test_objection_scope.py`, which encodes the reported case
by name — including the check that the gold-rim porcelain is **not** told it is
dishwasher safe.

### The API-key connectors were never tried with a real address — fixed 2026-08-13

Four providers self-serve on a pasted key, and the probes had only ever been
exercised through a stubbed `_probe` in the test suite. Run against the live
APIs with the inputs a client would actually give, three of four plausible
Shopify values failed, as did the commonest WordPress one:

    https://acme.myshopify.com   built `https://https://…`  -> ConnectError
    acme.com   (the storefront)  answered, was not an API   -> HTTPStatusError
    acme.com   (WordPress)       no scheme                  -> UnsupportedProtocol
    acme.myshopify.com/          trailing slash             -> worked, by luck

Every failure surfaced an **exception class name on the client's screen**,
which is the same defect as a silent failure — nobody can act on either.
`_normalize_meta` now strips the scheme, path, slash and case a person actually
pastes, and the storefront domain is refused with where to find the admin one.
That case matters more than it looks: Baci's is `769684-2.myshopify.com`, a
number, so "use your myshopify domain" is not advice a merchant can follow
without being told where it is written down.

Also found, and NOT a version problem though it looked like one: the probe
pinned `2024-10`, twenty-two months stale. Shopify serves an unsupported
version by falling back to the oldest supported one, so it never broke and
never would have — which is precisely why it drifted. Now a dated constant.

**`connected` was a claim made once and never re-tested.** `store()` verifies
at the moment of pasting; nothing checked again, so a rotated or
provider-revoked key kept a green chip and a `last_verified` date from months
earlier. `recheck()` plus a Re-check button re-probes on demand.

The interesting part was the first version of it, which set `status="failed"`
on a failed probe. `resolve()` returns only active rows and falls through to
the env blob otherwise — so **one network blip would have silently swapped a
client's live credential for whatever Gomeh pasted into Render**, mid-flight,
with nothing downstream questioning it. A probe failing is evidence about the
probe as much as about the key. The state is now `not verifying`: recorded,
shown, and load-bearing on nothing. *Rule: a check that cannot distinguish "it
is broken" from "I could not reach it" must not be wired to anything that
changes behaviour.* Same shape as §1 *unknown collapsed into a value*, caught
by a test written to assert the opposite.

**Scope narrowness is no longer invisible, for OAuth.** Both providers report
what was actually granted, so `_missing_scopes` names an unticked permission on
the console at the moment it happens. A partial grant is stored and reported,
not refused: the connection works for what was granted, and refusing outright
leaves a client who unticked Calendar with no connection rather than most of
one. Still open for API keys — a Shopify token with too few scopes fails
quietly later, exactly as before.

Media layer (blocks the campaign email builder), reports, Canva (OAuth),
per-tenant prompt/model pinning, publish idempotency (a worker restarting
mid-publish double-sends — must land before anything sends for real).

### Needs owner review

**Eien's `banned_claims` are conservative defaults, not established fact.** A
supplement brand with a GLP-1 product. Read them on the Knowledge tab.

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
python3 scripts/test_provenance.py        # origin, review, conflict-on-disagreement
python3 scripts/test_extract.py           # spans are selected, then verified in code
python3 scripts/test_email_harvest.py     # sent mail -> claims and objections
python3 scripts/test_sources.py           # the registry; a fill is a rehearsal
python3 scripts/test_oauth.py             # signing in, scope narrowness, renewal
python3 scripts/test_objection_scope.py   # an answer about one product stays about it
python3 scripts/test_brief.py --demo
python3 scripts/seed_kb.py --report      # what each account still needs
python3 scripts/tenant_scope.py --report # what is still unattributed
```

All twenty suites pass as of 2026-08-14. None of them touch the network.

Re-run all five after any change to `kb.py` — §2.15 is what happens when the
claim in this section is trusted instead of re-checked.
