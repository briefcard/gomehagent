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

### A mask is advisory to `gpt-image-1`, and this module said otherwise — FIXED

`imagegen.place_product` was written asserting that masking the product meant
"the product's pixels come back exactly as they were sent", and returned
`protected: True` to say so. Gomeh ran it against the real API: the pitcher's
clear acrylic handle came back **opaque white** and the body lost its depth.

The alpha rules out the obvious explanations. Only **0.77%** of that image is
partially transparent, so the handle is opaque pixels with pale RGB, sitting
comfortably inside the protected region — it was not a flattening artefact and
not a mask that missed. The endpoint regenerates the frame; it is not a
classical inpaint, and a mask steers it rather than binding it.

Two things were wrong and only one was code. The claim was wrong, and a claim
in a docstring is load-bearing here — the next caller reads "fidelity by
construction" and stops checking. `protected` is now `False`, the caveat names
the measured failure rather than a hypothetical, and the assertion that pinned
the original claim was rewritten to pin the correction.

**The route that cannot be wrong** is `scene_with_real_product`: the model
paints an empty plate, and the actual photograph is composited onto it by us.
The clear handle survives because those are the photographed pixels and no
model ever sees them. `compose._surface_tint` samples the plate where the
product will stand and tints the contact shadow to it — a shadow is the surface
with the light taken out, and a neutral grey one on warm linen is what makes a
composite read as a sticker.

What it still gives up, stated rather than hidden: the light on the product is
the light from the product shoot, not from the generated scene. A shot taken
under very different light will read as inserted no matter how good the shadow.

## 3. Still broken — in priority order

Updated 2026-08-17.

### `add_claim` and `add_audience` disagree about what holds a row back — OPEN

Two conventions for the same decision, in the same module:

* `add_audience` derives review from **origin**:
  `review or (prov.APPROVED if prov.lands_approved(origin) else prov.PROPOSED)`.
* `add_claim` derives it from **status**: `prov.PROPOSED if status == "pending"
  else prov.APPROVED`. `origin` is recorded but does not gate anything, so
  `add_claim(..., origin="harvest")` with the default status lands **approved
  and immediately selectable**, even though `prov.lands_approved("harvest")`
  is `False`.

Not a live leak: both real callers (`harvest.py:546`, `email_harvest.py:321`)
pass `status="pending"` explicitly, and `claims()` filters on
`review == APPROVED`, so nothing unapproved reaches a bundle today.

It is a trap for the next caller, and it has already caught one — the first
draft of `test_bridge.py` used `origin="harvest"` alone, got an approved row,
and appeared to prove a leak in the bridge that did not exist. A convention
that is right in one function and inverted in its neighbour will be got wrong
again. Fix is to make `add_claim` consult `lands_approved(origin)` as well, so
neither axis alone can wave a machine-written claim through. Everything here is measured, not assumed.

### Blocks producing anything a client sees

**~~Nothing generates.~~** Superseded 2026-08-17. `app/skill.py` plus the four
skills in `app/skill_pack.py` produce, validate and ledger output inside the
systems spine. Still true of the *visual* half: no imagery, because build-map
steps 05 and 06 are unbuilt. `feedback_block` still has no caller.

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

### 2.23 A number with no owner — fixed 2026-08-14

Reported: `proves` was empty on every claim, and the example given showed why
it could not have been otherwise. `"1,652 residential & hotel units"` was
harvested correctly and means nothing on its own. It is an Opus Communities
development, and that is the only thing that makes it usable as proof.

Two causes, and the second is the interesting one.

**The deterministic path produces no interpretation at all.** `_claims_from`
appends `{"text", "evidence": "", "proof_type": "data"}` — there is no
`proves` in it and there could not be, since writing one is a judgement. So on
the live agency run, which reported `extractor: "deterministic filter"`, every
claim was always going to arrive with an empty field. An empty `proves` means
the model never ran; it does not mean the model had nothing to say, and the
review editor now says which.

**Evidence was verified against the claim's own span.** `if ev not in text:
ev = ""` — written to stop fabrication, and it also made attribution
impossible. "Opus Communities" is in the block ABOVE the number, so the one
fact that turns a figure into proof was unrecordable by construction. The rule
was tighter than the guarantee needed: the guarantee is that nothing is
asserted which the page does not say, and a neighbouring block is still the
page.

`KbClaim.context` carries verbatim text from near the claim — the heading it
sat under, the sentence that names whose it is — selected like any other span
and verified in code.

**Verified against NEARBY blocks, not the page.** A portfolio page lists a
dozen developments. Page-wide verification would cheerfully attach one
project's heading to another project's unit count, and the result would be
verbatim, checkable and wrong — §2.4 in a new place, structural proximity
mistaken for relation. `CONTEXT_BLOCKS = 2` either side of the block the claim
was found in.

*Rule: when a verbatim check is used as a fabrication guard, check the size of
the haystack separately from the fact of checking. Too small a haystack throws
away true things; too large attaches them to the wrong subject.*

### 2.22 Two situations doing one job, and no way to see it — fixed 2026-08-14

Reported from the agency's own vocabulary:

    solo_operator_doubt   wonders whether one person can carry it
                          triggers: one person, just you, freelance
    team_exists           wonders whether there is a team behind it
                          triggers: team, capacity, bandwidth

The same doubt from two sides. Split across both, neither accumulates the
approved examples that make the learned tagger work, and selection reaches half
the evidence it should.

**The lexical guard added the same day cannot see this, and it was measured
rather than assumed:**

    similarity(tag, tag)   = 0.00
    similarity(desc, desc) = 0.25        threshold 0.65
    similarity(patterns)   = 0.00

`similar_situation` catches spelling variants — `scale_proof` against
`proof_of_scale` — and nothing else. Two tags that mean one thing in different
words share no words, which is the definition of the problem. Same shape as
§2.21 one level up: open-class semantic judgement on a token matcher.

Three signals now, and they answer different questions:

- **`used_together`** — the share of rows carrying both tags. Empirical, and it
  sees what words cannot: however differently two tags read, if every claim
  under one is under the other they are one tag.
- **`reads_alike`** — descriptions and triggers overlapping. Weakest, and blind
  to the reported case.
- **`extract.review_vocabulary`** — a model pass over the whole vocabulary,
  proposing merges. The only thing that can pair the reported two. Constrained
  as everywhere else: it may only name tags that already exist, may not cross
  `kind`, and a human decides.

**The floor matters more than the threshold.** The first version reported four
pairs on the agency seed, of which three were noise — `food_bev` with
`no_traffic` among them, on a single shared claim. Two tags co-occurring once
score 100%. `MIN_ROWS_FOR_OVERLAP = 3`; below that a ratio is a coincidence
with a percent sign on it. Same reasoning as the standing note that holdouts
are meaningless on small lists. *Rule: a ratio needs a denominator big enough
to have been able to come out differently.*

**`situation_neighbours` is the context-priority map.** When a situation has
thin proof, the alternative to returning nothing is reaching to its nearest
neighbours — in a known order, and while saying so. `basis` names which signal
fired, because widened context is not matched context and reporting one as the
other is §2.5 exactly.

**Merging retags before it deletes.** `add_claim` refuses tags outside the
vocabulary, so a claim left holding a retired tag can never be re-approved and
can never be selected — silent retirement of real proof. `merge_situations`
moves every row first, and dry-runs by default.

### 2.21 The model was asked what a claim IS, never what it is FOR — fixed 2026-08-14

Reported off a real harvest of the agency site. `"15,000 + Trained across 30+
seminars worldwide"` was extracted correctly and filed with **no situations**,
so nothing downstream knew it was credibility or when to reach for it.

`extract` returned `{text, proof_type, evidence, entity_scoped}`. Situations
were assigned afterwards by `suggest_tags`, which has two paths and no model
call: literal substring matching against the tenant's triggers, and word
overlap against already-approved claims. Neither gets from "trained ... seminars
... worldwide" to *credibility*. Measured on the reporting account, **both paths
were structurally dead**: `situation_patterns("agency")` was `{}` and there were
zero approved claims to learn from, so it returned `[]` for everything, always.

The shape is the one this log already contains. `extract.py`'s own docstring
records that the deterministic filter was measured at **0% recall** on *"is this
a claim"* because that is open-class semantic judgement. *"What is this claim
for"* is the same class of problem, and it was left on a keyword matcher one
step downstream. *Rule: when a measurement retires a heuristic, check whether
the same heuristic is doing the same job elsewhere in the pipeline.*

The model now returns `situations` in the same call, with the tenant's
vocabulary and descriptions in front of it, and `_verify` drops any tag not in
that vocabulary — the same model-proposes/code-decides discipline that already
guards the spans. Zero extra model calls.

**Three things this opened, each guarded:**

- **A no-fit claim now names the tag it would have needed**, filed as a
  proposed `KbSituation`, so the vocabulary grows from real claims rather than
  needing to be authored up front. Without a guard that is a tag generator:
  `proof_of_scale`, `scale_proof` and `training_volume` all mean one thing, and
  a vocabulary of near-synonyms is worse than a short one because selection
  splits across them and no tag accumulates the approved examples the learned
  tagger needs. `kb.similar_situation()` compares a proposed slug against every
  existing tag AND its description — `credibility` and `proof_of_expertise`
  share no characters, but their meanings do — and refuses a machine a synonym
  while still letting a human add one. `MAX_NEW_SITUATIONS = 3` per crawl: past
  that the shortfall is the vocabulary, not the site.

- **`add_situation` wrote `review=APPROVED` unconditionally.** Harmless while
  only the seed wrote there; a hole the moment a machine could propose a tag,
  since this table decides which claims may exist at all. Now follows
  `lands_approved(origin)` like every other table.

- **`situations()` did not filter by review** — so a machine-proposed tag would
  have been immediately valid for `add_claim`, review gate intact and bypassed
  in the same breath. Caught by a test written to assert the opposite. The
  filter is `!= PROPOSED` rather than `== APPROVED` deliberately: rows written
  before this table carried a review state have none and have been in use all
  along, and excluding them would empty every tenant's vocabulary and fall back
  to the shared constant — which is how the agency got here.

**`KbClaim.proves`** is new: one model-written sentence saying what a reader
should conclude, because a tag says *when* to use a claim and not *what it
demonstrates*. It is the only model-WRITTEN field on the table — everything
else is copied verbatim or chosen by a human — so it is rendered in the review
editor with that said plainly, and is editable to empty. Empty on every
pre-existing row, which is correct: nobody has interpreted those yet.

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

### 2.24 One shared word asserted a situation tag — fixed 2026-08-14

Found by reading `suggest_tags` against the job it is about to be given, not by
a failing run — so it is the first entry here that was caught before it cost
anything.

The function was written to seed a review queue. Its docstring says so: *"best
guess situation tags for a **candidate claim**"*. In that setting a bad guess
is cheap, because a human reads `basis`, sees "resembles approved claims tagged
gifting", disagrees and retags. It is also the **only classifier an account
has**, so everything that routes on situations inherits it — and a service desk
choosing which objections to answer with, or a voice caller picking a script
branch, has no human reading `basis`.

Two things made those uses incompatible:

- **The score was computed and discarded.** `scored` held
  `len(shared) / sqrt(len(words))` and the return threw it away, so a caller
  could not tell a twelve-word overlap from a one-word one.
- **The gate was `if shared:`** — a single word in common qualified a tag.

That is §1 *unknown collapsed into a value* and it is the fourth instance
(2.5, 2.6, 2.11). It is closest to 2.5: a keyword match asserting `fits: True`,
where relevance was reported as satisfaction. Here resemblance was reported as
placement.

Fixed with **two floors, checked separately**, because either alone is
defeatable:

- `MIN_SHARED_WORDS = 2` — one word is a coincidence.
- `MIN_LEARNED_SCORE = 0.5` — normalised, so a couple of words shared with a
  long sentence does not qualify.

`test_classify.py` carries one case per floor, and they are the interesting
part: *"The registry of our warehouse locations changed."* shares one word and
scores **exactly 0.500**, so the score floor alone would have passed it — the
shared-word floor is what refuses it. *"Wedding registry aside, the logistics
team…"* shares two words over twenty-two and scores 0.426, clearing the
shared-word floor and refused by the score. Neither floor is redundant.

The return now carries `confident`, `score` and `candidates`. `candidates`
holds every tag considered **including those below the floor**, because a
reviewer should see "we wondered about gifting and weren't sure" rather than a
blank — absence surviving to the output, the same rule as tri-state `fits`.
`score` is `None` on a pattern hit: a pattern match is a decision and does not
have a confidence, and a number there would be metadata dressed as evidence.

Downstream, `tags` now comes back empty more often. That lands where it should:
`add_claim` accepts an untagged **proposal** and refuses it at approval, and
`harvest` already routes untagged candidates to `untaggable`. So a weak guess
becomes a human's decision instead of a silent one.

**Still open, found while fixing it:** `email_harvest.py:314` calls
`kb.add_claim(...)` and ignores the returned status string. That is §1 *silent
loss* — a dedupe refusal or an unknown-tag rejection vanishes without a count.
`harvest.py` has the same shape. Neither was touched here.

**Not done:** the floors are reasoned from the scoring function's own
arithmetic, not tuned against production rows — this session had no access to
the live database. Re-check them against real Baci and agency claims before
anything routes live traffic through this.

### Needs owner review

**Eien's `banned_claims` are conservative defaults, not established fact.** A
supplement brand with a GLP-1 product. Read them on the Knowledge tab.

### 2.29 Half of `capabilities()` reported "wired" on a declaration alone — fixed 2026-08-17

`tenants.capabilities()` promised in its own docstring: *"A capability is 'wired'
only if the tenant names it AND the underlying credential exists."* It kept that
for two of eight. `inbox` and `commerce` checked membership in a real registry;
`esp`, `cms`, `ads` and `crm` checked only that **a key was present in the
Tenant's own JSON column**. `credential_ref` ("OMNISEND_BACI") is dereferenced
nowhere in the codebase, and there is no Omnisend credential anywhere in it.

Live at the time of the fix: Baci reported an ESP it did not have; Coverings
reported a CMS *and* a CRM whose `creds_key` was the empty string; Ironside
reported a CMS for Squarespace, a platform with no backend implemented.

This is §1's *unknown collapsed into a value* — "declared" and "connected" are
different states reported as one — and precisely the failure the docstring said
the function existed to prevent: a system requiring `esp` passed
`systems.ready()`, went live, and would have failed deep inside a publish call
rather than refusing cleanly.

**Fix:** every capability now resolves through `credentials.wired_capabilities`,
which asks the credential store first and the env group second — the same two
sources `credentials.resolve` already unified. Declarations moved to
`tenants.declared_capabilities`, and `tenants.capability_detail` reports
`wired` / `via` / `declared` / `needs_connecting` per capability, so the gap
between intent and evidence is the connect-page backlog instead of a lie.

**Two traps found while fixing it, both worth carrying:**

1. *The env group is a registry, not a secret.* The first version tested
   `_from_env(...)["secret"]` for truthiness. `data_tools._shopify_token` falls
   back to a refreshed cached token when `cfg["token"]` is absent, and a
   GMAIL_ACCOUNTS entry need not carry a `refresh_token` inline — so that
   version reported live inboxes and stores as disconnected. Caught by
   `test_systems`. **Membership in the registry is the credential**, because
   membership is what every consumer resolves through.
2. *An env Google is not a client Google.* `GRANTS["google"]` includes
   `analytics`, because the OAuth path verifies consented scopes
   (`oauth._missing_scopes`) before storing. The env-group Google is a pasted
   refresh token whose `webmasters.readonly` / `analytics.readonly` re-consent
   may never have happened, so `ENV_GRANTS["google"]` is `("inbox",)` only.
   Granting `analytics` off it would have replaced one false positive with
   another.

Also extended `_from_env` to resolve `wordpress` through `WORDPRESS_SITES`,
which was a real env registry that nothing read.

**And connected what was already connectable.** `CMS_PLATFORM_PROVIDER` grants
`cms` from the provider the tenant's CMS platform names, when that provider's
credential resolves. Baci publishes pages through the same Shopify Admin API
token that serves its catalogue — `shopify_seo.create_page` takes exactly that —
so requiring a separate "cms credential" was blocking the blog system on a
connection that already existed. The platform name still grants nothing on its
own: Coverings declares `shopify` with no store and stays unwired, Ironside
declares `squarespace`, which no backend implements and which is not in the map.

### 2.25 A skill could produce output that no run row ever saw — fixed 2026-08-17

The whole retrieval half of this layer was built with `systems.start_run` having
exactly two callers, neither of them in it. `resolve`, `validator`, `ledger` and
`responder` all worked, and none of them opened a run — so anything built on top
would have produced output with no autonomy rung, no `blocked_on` recorded, and
`feedback_block` still with no caller. The spine existed and the layer that
needed it was wired past it.

**Fix:** `app/skill.py`. A skill declares the context it needs; `run()` opens the
run, resolves once, gates on coverage, and closes it. `Context.emit` is the only
way for a skill body to return anything and it runs the validator first, so the
gate is structural rather than remembered.

### 2.26 A blocked skill left no trace, so the backlog could not see it — fixed 2026-08-17

The first version of `skill.run` returned on a failed preflight *before*
`start_run`. Every cheap, common, fixable refusal — system not installed,
contract blank, no ban list — was therefore the only class of failure never
recorded, and `blocked_reasons()` exists precisely to rank those. Found by the
test asserting blocked runs carry a reason.

**Fix:** a blocked preflight opens and closes a run, and files a ledger row.
`refused` (unknown skill or account) stays unrecorded on purpose — a caller
error is not something the account is missing, and filing it would put noise on
the authoring backlog.

### 2.27 A false premise refused real proof — fixed 2026-08-17

`add_claim` refused an untagged approved claim with *"Needs at least one
situation tag, or it can never be selected"*, and `review_claim` refused to
approve one for the same stated reason. **The premise is false.** `claims()`
filters on situation only when a caller asks for one (`if want and not
overlap`), so an untagged claim is fully selectable as brand-wide proof and
merely absent from *situated* retrieval.

The cost was worst exactly where it hurt most: an account with no situation
vocabulary yet — a brand-new client — could never tag anything, so could never
approve anything, so its own website could not seed its knowledge base. It also
blocked the catalogue rewrite skill, which needs brand-wide proof to compose a
compliant meta description.

**Fix:** infer, do not gatekeep. Both paths now call `suggest_tags`, apply what
it is confident about, and otherwise file the claim untagged as brand-wide proof
— saying which of the two happened, because silently choosing between them is
§1's absence-collapsed-into-a-value all over again.

*This is the second time a gate was written on an assumption about a selector's
behaviour rather than on the selector. §2.20 was the first. Read the function
you are guarding.*

### 2.28 The two known `add_claim` silent losses — fixed 2026-08-17

`harvest.py:536` and `email_harvest.py:314` both discarded `add_claim`'s return
on the apply path. `add_claim` refuses in-band and reports corroboration
in-band, so "proposed 40" and "wrote 40" were the same number whether or not a
single row landed — on the only derivable source of objections the platform has.
Carried in §3 as live since 2026-08-14.

**Fix:** both now classify every attempted write as filed, corroborated or
refused, and report `filed_count`, `corroborated_count` and `write_refused`
alongside the proposed count. `test_harvest` asserts the three account for every
proposal.

### 2.30 A refusal that named the wrong missing thing — fixed 2026-08-18

`oauth.configured` reported what was blocking an OAuth flow with a ternary:

    env = "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET" if provider == "google" \
        else "META_APP_ID / META_APP_SECRET"

Canva arrived third and inherited the `else`, so the Accounts tab and the
client connect page both told anyone trying to connect Canva to go and set
**the Meta app secret**. Confirmed in the rendered HTML, not inferred.

This is worse than a silent refusal. This codebase's whole posture is "name the
missing thing"; naming the WRONG one sends somebody to do work that cannot
help, and they will conclude the feature is broken rather than unconfigured.

Fixed by declaring `env` on each flow and reading it off the spec, plus an
import-time assert so the next flow cannot omit it. `test_oauth` now checks all
three providers rather than the two that existed when it was written. §1 rule 4.

### 2.31 A bare `else` that would have leaked a client secret into a URL — fixed 2026-08-18

One function below §2.30, `exchange` dispatched the token call the same way:
`if canva … elif google … else` — and the `else` branch was Meta's, an
`httpx.get` carrying `client_id` and `client_secret` as **query parameters**.

Nothing was leaking, because the three declared providers each matched a
branch. But the next provider added would have inherited Meta's branch by
default and put its client secret into every access log and proxy cache between
here and the provider. The defect is the shape, not the current behaviour.

`token_style` is now declared per flow (`post_body` / `get_params` /
`basic_auth`) and asserted at import.

### 2.32 Canva would have 401'd on every real call — fixed 2026-08-18

`oauth.exchange` keeps the REFRESH token for providers declaring
`stores="refresh_token"` — deliberately; an access token dies in an hour and is
not worth a row. `canva._token` then handed that stored value to the Canva API
as a `Bearer`.

Every Canva call would have come back 401 while the console showed a green
chip: a positive claim that has stopped being tested, which is §2.13's shape in
a new subsystem. It survived because no Canva call has ever been made for real.

Fixed with a general `oauth.access_token(provider, refresh_token)` that mints
one through the flow's own `token_style`, and hands back a rotated refresh token
when the provider issues one — dropping that would make a connection work once
and then die, which looks exactly like a revocation and would be debugged as one.

### 2.33 A gate built on absent data, one layer above §2.27 — fixed 2026-08-18

`systems.ready()` was consulted for two incompatible questions: "may this system
act unsupervised" and, via `skill.preflight`, "may this produce anything at
all". So an unapproved objection, or a blank 8-part governance form, stopped a
customer getting a reply.

Owner's correction, and it is the rule this codebase already claimed to follow:
*"there should be NO block because of a lack of data. If it's not there, then
don't use it. The idea was never to stop the AI from responding, it's to guide
it on how to answer correctly."*

`can_produce` now blocks on an absent CONNECTION only. Everything else is
`thin` — noted, returned, and filed as a knowledge task.

Two things worth keeping from the fix. **The first version of the
`kb.record_unknowns` call passed `field`/`why` and would have recorded nothing
at all while returning cleanly** — that function filters on `basis == "unknown"`
and `attribute`. §1 silent loss, caught only by asserting the count. And
**`Skill.constitutive`** was needed to stop the fix going too far: a compliance
sweep against an empty ban list reports a catalogue CLEAN that nothing checked,
which is not a thinner output but a false one.

### 2.34 A new table unclassified, one commit after the last one — fixed 2026-08-18

`reset.py` derives its table list from the schema and reports what it cannot
classify. It had been naming `kb_assets` since the creative library landed: a
knowledge reset left an account's entire picture library behind while reporting
success — the `kb_brand`/`kb_brands` near-miss arrived at from the other side.

Classified as knowledge. **What that costs is recorded in the code rather than
hidden:** `uses`, `last_used_at` and the per-channel results from
`record_asset_outcome` live on the same row, are the only record of which
creative worked, and nothing can rebuild them. A table doing two jobs; splitting
outcomes out is the real fix and is not done.

Then the same check caught `assurance_events` **one commit later**, added by the
same session that had just written about the trap. That is the point of
deriving the list from the schema instead of maintaining it by hand — the
author of the rule is not exempt from the rule.

### Wiring audit, 2026-08-18 — what reaches the data layer

Not a defect; the survey the defects above came out of, kept here so the next
one can be diffed against it. Full table in `BUILD-STATE.md`.

The finding is an inversion: `shopify_seo`, `wordpress_seo` and `seo_tools`
contain **zero** references to `banned_claims`, `validator` or `compliance`, and
they are the only modules that write to live customer-facing properties. The
subsystem that reports has every guarantee; the one that publishes has none.

Also: two mail paths, only one guarded, and the guarded one uses a plain
substring test where `validator._banned` matches on word boundaries — so
"hand-decorated" is caught, "hand decorated" is not, and "artisan" false-fires
inside "artisanal". Ten functions nothing can reach.
`_fetch_products_live` raises `KeyError` instead of refusing by name.

### 2.35 An expiry gate enforced on read and unsettable on write — fixed 2026-08-18

`KbClaim.expires_at` has existed since the knowledge layer was built, with the
comment "stale claims stop being selectable", and THREE readers honoured it:
`claims()` skipped expired rows, `claim_inventory` bucketed them, the console
rendered the date.

**Nothing could set it.** `add_claim` had no `expires_at` parameter and no route
or form wrote one, so every claim in every account had `expires_at = NULL` and
lived for ever. A gate that is enforced by every reader and reachable by no
writer looks exactly like a working feature — the same shape as
`Approval.system_id`, `SystemRun.edit_diff` and `KbAsset` rights before it.

Owner's rule when it surfaced: *"we should just require expired claims to go
back into the approval queue and some claims can be set as unexpirable"*, and
*"but by default they expire"*.

So: one shared `kb.claim_expiry()` that all three readers now call instead of
reading the column raw, a default TTL so "expires by default" is real even when
nothing set a date, `set_claim_expiry` to mark one timeless, and `expire_due` to
return the rest to the queue.

THREE states, not two. `undatable` — approved, but with no `verified_at` and no
`approved_at`, so the due date cannot be computed — is deliberately NOT
`expired`. A missing timestamp is a gap in our bookkeeping, not evidence the
claim went false, and dropping it from selection would destroy real proof to
punish that. It stays selectable and is listed for somebody to date.

### 2.36 An approval loop caught before it shipped — 2026-08-18

Found by asking what happens on the run AFTER the fix in §2.35.

`expire_due` returns a due claim to `proposed`; the operator approves it;
`review_claim` stamps `approved_by` and `approved_at`. But `claim_expiry`
derives the due date from `verified_at` FIRST, and nothing was touching that —
so the claim was still expired the moment it was re-approved, and the next
weekly sweep would return it to the queue. For ever, every week, the same
claims.

Approving IS the act of saying a claim is still true, which is exactly what
`verified_at` records, so `review_claim` now writes it. `test_claim_expiry.py`
carries the check under its own heading.

The general point: a state machine that moves a row between two states needs a
test that runs the cycle twice. One pass proved the fix worked and would have
shipped the loop.

### 2.37 A perishable answer read as permanent — fixed 2026-08-18

Owner's case: *"an email about a cup that's out of stock is answered now and we
save that context for follow up emails. What about when it's back in stock?
That response is no longer valid."*

Half of this was already right, and worth recording because it is the part that
usually gets built wrong. Stock was never stored as a claim: `resolve` declares
it in `needs_lookup` and `responder` refuses to answer it from knowledge at all,
returning "this needs live data, not more knowledge". The FACT is read from the
store at the moment of asking.

The gap was the REPLY. It goes in the ledger, and `resolve` pulls prior
correspondence into the bundle for a follow-up, where it arrives as prose and
reads uniformly true — nothing in a sentence marks which half was a reading from
a store and which half was a fact about the brand.

Fixed by asking the OUTPUT instead of the sentence. `lookups.STALE_AFTER_HOURS`
turns what the registry already said in prose ("stock is true at the moment of
asking and stale by lunchtime") into a value with an import-time guard;
`Output.lookups` records which fed a body; `ledger.perishable` flags a reply
whose live facts have aged, and `resolve` files it beside the correspondence.

**Flagged, never hidden or rewritten.** What was said is a fact about the
conversation and stays true whatever the stock does now — the drafter needs to
know both that it was said and that it has aged.

Two writers, not one: `responder` files an output on the approved-answer path
AND on the draft-from-context path, and wiring only the first would have missed
every reply drafted from context — the half with no approved objection behind
it, which leans hardest on live data. A column written by one of two writers is
a column written by none.

### The wiring audit under-read its own corpus — corrected 2026-08-18

The audit that produced §2.30-2.34 reported ten unreachable functions. It was
eight, and one of the two extras is the instructive one.

The scan globbed `app/*.py`. It never recursed into `app/roles/` — which is
exactly where each role wires its tools and its per-turn context block. So
`seo_tools.seo_context_block` was reported as having no caller when
`roles/seo.py:103` passes it as `extra_context=` and it is injected into the SEO
agent every single turn. The function's own docstring says so; the scan
contradicted it and the scan was believed, because a number looks more like
evidence than a sentence does.

67 files read, 123 in the repo. A survey that under-reads its own corpus
produces confident findings about code it never opened, and those findings then
go into a handoff and get acted on.

*Rule: any repo-wide sweep uses `**/*.py`, states how many files it read, and is
diffed against the previous one rather than replacing it.*

Triage of the corrected eight, recorded because "unreachable" is not one
verdict:

  · DELETED — `credentials.granted_capabilities` (sees only client connections,
    not the env group, so reaching for it reintroduces §2.29) and
    `kb.retire_claim` (a one-line alias for `review_claim(approve=False)`; two
    names for one decision is the `add_claim`/`add_audience` trap in miniature).
  · WIRED — `approvals.pending_count` into the console tab bar, and
    `kb.assign_to_group` into a bulk grouping form.
  · LEFT, as unfinished features rather than dead weight —
    `canva.export_result`, `omnisend.upload_image`,
    `baci_backoffice.list_company_documents`,
    `ops_jobs.file_whatsapp_document`, `propose.from_gap`. Both halves of the
    Canva export path are unwired, so it is incomplete rather than broken.

### 2.38 The draft and the approval were two copies that drifted — fixed 2026-08-19

One drafted reply produced two artefacts that never spoke to each other: a Gmail
draft, and an approval built from a COPY of what that draft said at the moment
it was written. `_execute` then composed a THIRD message from that copy.

Three consequences, and the third is the one that reaches a customer:

  · Editing the draft in Gmail changed nothing anybody sent. That is also why
    `SystemRun.edit_diff` could never be written — the edit was invisible to
    every path that mattered.
  · Approving left the draft behind. Nothing deleted it, so they accumulated on
    the thread, each looking unsent.
  · Sending it yourself from Gmail — the natural thing to do — left the
    approval pending. Approving it later delivered the ORIGINAL, unedited text
    a second time, to the same customer, on the same thread.

Fixed by keeping the draft id and making approval send THE DRAFT. Whatever goes
out is what was approved; an edit travels with it; nothing is left over. A
vanished draft sends nothing at all.

`reconcile_drafts` closes the other direction on a tick, marking such approvals
`sent_outside` rather than `approved` — the second would claim we did something
the owner did. It only ever closes and never sends: the worst case of a misread
must be a closed approval, not a mailed customer.

Note what made this findable: the owner asked whether drafts appear in the UI or
in the email. The answer was "both", and "both" was the defect.

### 2.39 A fixture that made every diff score zero — caught 2026-08-19

`test_draft_sync.py` was written with doubled escapes, so its fixture strings
carried literal backslash-n rather than newlines. `edits._norm` therefore saw one
long line, every comparison scored 0.0 similarity, and the "a human changed it"
assertion passed — for entirely the wrong reason, while the quoted-history
assertion failed and exposed it.

Third instance this session of a test passing for the wrong reason: the portal
cookie over http, `test_oauth` against an all-accounts page, and this.

*Rule: when an assertion passes first time, ask what would make it fail. All
three of these would have passed against broken code.*

## 4. How to verify

```bash
python3 scripts/test_skill.py       # the skill substrate: gate, rung, ledger, refusals
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
python3 scripts/test_claim_tagging.py     # a claim knows when it applies, and what it proves
python3 scripts/test_brief.py --demo
python3 scripts/seed_kb.py --report      # what each account still needs
python3 scripts/tenant_scope.py --report # what is still unattributed
```

All thirty-three suites pass as of 2026-08-17. None of them touch the network.
Full run is ~2m30s — split it, or a single shell call hits a 2-minute timeout.

Re-run all five after any change to `kb.py` — §2.15 is what happens when the
claim in this section is trusted instead of re-checked.
