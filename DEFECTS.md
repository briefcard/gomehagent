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

*Partly closed 2026-08-20 (§2.57).* The half that was actively breaking is
fixed: **credentials** no longer live in whichever registry the caller happens
to speak. `app/connections.py` resolves them by tenant, so a client-connected
store or install reaches the publish path, and `tool_scope` and `connections`
now share one domain normaliser rather than two that disagreed.

**Still open, and this is the whole remaining merge:** `SEO_SITES_JSON` is
env-only, so a new client still cannot get an SEO site profile without a Render
edit, and `SeoSiteConfig` remains a third row keyed by site. Deriving profiles
from the `Tenant` table is the fix.

**Do not do it naively — there is a trap in the call path.** `sites
.all_profiles()` parses that JSON on every call and sits under
`tool_scope._site_for`, which runs while a tool list is being built. Putting a
database query behind it turns one env parse into a query per turn. Decide the
caching first; the profile derivation is the easy half. Note also that widening
`all_profiles()` widens which tools each account is OFFERED, since `_site_for`
returning a value is what makes the 27 site-scoped tools visible — that is
probably correct, and it is a behaviour change that needs its own assertion in
`test_tenant_isolation.py` rather than arriving as a side effect.

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

### 2.40 The console named one client and showed another's — fixed 2026-08-19

Three separate leaks, one shape. The Systems tab rendered
`systems.all_systems()` grouped by client, so the account chosen in the sidebar
picked which INSTALLER you saw while the cards below it were every account's —
five clients' autonomy rungs and kill criteria stacked on one page, each with a
form writing to a different account. `assurance.report` was handed `tenant=""`
whenever the URL carried none, which reports every account, while `_shell` fell
back to the FIRST account for the pill — so the one page whose whole job is to
be believed showed five clients' catches under one client's name. And
`approvals.pending_count()` counted every account, so the "N waiting" beside one
client was another client's backlog, and the link opened everybody's queue.

**Fix:** `admin_ui._account()` resolves the account ONCE, for the frame and the
body alike, so the two cannot disagree; every tab goes through it. `ALL` ("*")
is the cross-account view and is reachable only by asking for it by name — it
is never where an unset value lands, and the page it produces says so on
itself. `pending_count` and `/admin/pending` take a tenant.

*Rule (new instance of §1's "unknown collapsed into a value"): an empty scope
must not fall through to "everything". "All accounts" and "the account I did
not name" are different requests, and answering the second with the first is
how one client's data reaches another.*

### 2.41 The test that said it was scoped, on an empty table — caught 2026-08-19

`test_console_frame.py` asserted "the body is single-account" for every tab, on
a database seeded with a brand row and nothing else. No system, no run, no
approval, no assurance event — so the assertion was true of empty tables, and it
passed for months while §2.40 rendered every client's pipelines on one page.

**Fix:** every account is seeded with a row in each table a tab reads, each
carrying a marker string only that account can produce. Verified by putting the
old `all_systems()` call back: the suite now fails with
`systems body is single-account — Baci Milano USA, BACIMARK`.

Fourth instance of a test passing for the wrong reason (portal cookie over http,
`test_oauth` against an all-accounts page, the doubled-escape fixture, this).
The tell is the same every time: **the assertion was about absence, and nothing
had been put there for it to find.**

*Rule: an assertion that something is NOT on a page must be run against a
database where it WOULD be, or it is testing the fixture.*

### 2.42 The knowledge base could not reach the drafts — fixed 2026-08-19

`resolve.resolve` had exactly ONE caller in the codebase: the skill substrate.
So the claims, objections and brand guidance the owner had been approving for
months reached work that ran through a registered skill, and nothing else — the
inbound mail path, which drafts the replies he reads every morning, worked from
a hardcoded prompt and a substring ban-list test.

Not a bug in any line. Every part worked; nothing joined them, and the console
gave no way to notice — approving a claim looked identical whether or not
anything would ever read it.

**Fix:** `app/grounding.py` resolves a bundle per inbound email and renders it
for the prompt; `triage` injects it and reports `claim_ids`, intersected with
what was offered so a model cannot introduce one.

*Rule: a capability with one caller is one refactor away from having none.
When something is built to be read by "every system", assert the callers exist
— `grep -c` for the function name is a test, and it would have caught this and
`feedback_block` on the day each landed.*

### 2.43 Two guards, two strengths, and the weak one was on the live path — fixed 2026-08-19

`triage` tested banned claims with a plain `in` while `validator._banned` next
door matched on word boundaries with flexible separators. So on the ONE path
that answers customers, `hand-decorated` was caught and `hand decorated` walked
through — and `artisan` false-fired inside `artisanal`. Worse,
`command_agent.queue_email_draft` checked nothing at all: it composed a reply in
the tool loop, wrote a real Gmail draft and queued it for approval, where the
owner might simply approve it.

To its credit the codebase KNEW: the assurance record deliberately said
`banned_claims_substring` rather than `banned_claims` so the weaker check could
not hide behind the stronger one's name. It was labelled honestly for a session
and shipped anyway.

**Fix:** both paths call `validator`. `triage` uses
`check(require_citation=False)` and escalates if the validator itself raises —
"we could not check this" warrants a human, not a pass. `queue_email_draft`
refuses BEFORE the write and names the phrase.

*Rule: two implementations of one rule is one implementation and one bug. If
the weaker one has to be labelled to stay honest, that is the signal to delete
it, not to document it.*

### 2.44 A reason prefix is an interface — caught 2026-08-19

Swapping `triage`'s substring test for `validator.check` (§2.43) also replaced
the reason marker `BANNED CLAIM:` with a generic `BLOCKED:`. The guard still
fired and still escalated; only the string changed. `test_tenant_isolation`
failed on it immediately — the assertion had been holding that marker since the
guard was written.

It matters because these prefixes are read by CODE, not only by a person:
`emailfmt` and `worker` both branch on `NEEDS-FACTS` in the same field. And one
marker covering two different rules (banned claim, unavailable entity) makes a
grep for either one lie.

**Fix:** the marker names the rule that fired and keeps `BANNED CLAIM`
verbatim.

*Rule: a string another module matches on is an interface. Changing it is an
API change, however much it looks like copy — grep for the literal before
editing it, and if a test is the only consumer, that test is the contract.*

### 2.45 The guidance reached every consumer except the one it was for — caught 2026-08-19

`resolve._rules` appends a system's standing guidance and edit lessons to
`rules["block"]`, which every SKILL injects at the top of its prompt. The mail
path does not inject that block — it builds its own identity prose from
`tenants.agent_block`, and `grounding.render` deliberately skipped the rules
block to avoid duplicating it. So the guidance was wired, was in the bundle,
passed every unit assertion, and never reached the drafts it was written for.

Every piece tested green in isolation. What caught it was the first test to
drive `triage_email` itself against a stubbed model and assert on the SYSTEM
PROMPT that came out.

**Fix:** `render` emits `rules["guidance"]` — that half only, since the caller
already has the identity prose and injecting it twice is how a prompt starts
contradicting itself.

*Rule: testing the pieces of an assembly does not test the assembly. When
something is wired to reach "everything", one test must drive the real entry
point and assert on what actually came out the far end.*

### 2.46 A third `stores` value would have run Meta's token swap — caught 2026-08-19

`oauth.exchange` chose what to keep with `if stores == "refresh_token": … else:
_meta_long_lived(...)`. Two providers, two arms, and the second was Meta's.
Adding Shopify — whose offline token IS the credential and which issues no
refresh token — would have sent it through Meta's long-lived exchange and
failed inside a function named for another platform.

This is §2.31's shape in the function DIRECTLY BELOW §2.31: the `token_style`
bare `else` that would have put a client secret in a URL query string. The
docstring warning against it was three lines above the code repeating it.

**Fix:** an explicit arm per value, and an unimplemented one refuses by name
rather than taking whichever arm is last.

*Rule: in a per-provider switch, `else` is not a default — it is the branch
written for whoever came second, silently inherited by whoever comes third.
Enumerate, and refuse the unknown.*

### 2.47 The one flow whose endpoint a caller supplies — built 2026-08-19

Not a defect found, a hazard designed against, recorded because the next person
adding a provider needs to know it exists. Every OAuth flow here posts its
client secret to a host compiled into `FLOWS`. Shopify's authorize and token
URLs are per shop, built from a domain that arrives in a form field and, at the
callback, in a query parameter anyone can write.

`shop=evil.example.com` would POST `client_id` + `client_secret` to an
attacker's server. One link, full credential disclosure, and it would look
exactly like a failed sign-in.

`oauth.shop_host` is an allowlist (anchored regex, userinfo and port stripped
first so `acme.myshopify.com@evil.com` cannot pass), enforced again in
`endpoint()` where the URL is built rather than trusted from the caller. The
suite asserts the attacks, and removing the gate fails six checks by name.

*Rule: when a URL is assembled from anything a request supplied, validate at
the point of assembly, not only at the door. A caller that already validated is
a caller you are trusting.*

### 2.48 A test that passed because the client was already signed in — caught 2026-08-19

`test_shopify_compliance` asserted that `/admin/privacy_requests` refuses an
unauthenticated read, using the same `TestClient` that had authenticated a few
lines earlier. It carried the console session cookie, so "no key" was a signed-in
request and the assertion passed for the wrong reason — it only surfaced because
the route happens to return `{"error": …}` with a 200 rather than a 4xx.

Fifth instance of a test passing for the wrong reason, and the SECOND caused by
this exact cookie (§ the portal `secure=True` trap). The tell is the same: the
assertion was about being refused, and nothing had been arranged for it to be
refused FOR.

**Fix:** a fresh `TestClient` for the unauthenticated check, with a comment
saying why.

*Rule: an authorisation test must run on a client that has never authorised.
Reusing the session under test is testing the session, not the guard.*

### 2.49 The one table deliberately outside the isolation boundary — 2026-08-19

Not a defect; a hazard recorded because `test_tenant_isolation` is the
mandatory suite and `craft_lessons` is the only table that does not obey it. It
has no tenant column BY DESIGN, so `reset._tenant_models()` never sees it and
the unclassified report will never name it — which is correct (resetting one
client must not delete craft learned across all of them) and is exactly the
kind of silence that hides a mistake later.

What keeps it safe is a single invariant: **craft shapes HOW something is said
and is never WHAT is asserted as true.** It cannot carry a `claim_id`, so it
can never be cited as fact. Plus a deterministic leak guard re-run at approval,
reach limited by `business_model`, and human approval.

*Rule: if something must sit outside the system's central invariant, give it
ONE narrow licence, write the licence down where the code is, and test the
boundary rather than the intention.*

**And the mandatory suite caught it, which is the point of it.**
`test_tenant_isolation` failed on `CraftLesson` — not because the design was
wrong but because the exception had not been DECLARED. Its own instructions
say it: a model that genuinely holds no client data goes in `PLATFORM_MODELS`
with a reason, and adding one without doing either fails the suite. That is the
difference between a standard and a preference. The licence now sits in the
exception list where the next person meets it before they meet the table.

### 2.50 The sweep must survive its own model — 2026-08-19

Not a defect found; a failure mode designed out and then pinned, because the
obvious version of a nightly correlation sweep has it. If the model writes the
findings, then an expired API key, a rate limit or a bad night turns the sweep
SILENT — and silence from a monitoring job is indistinguishable from "nothing
was wrong". That is the same shape as §1's absence-collapsed-into-a-value, at
the level of a whole feature.

So the correlation is deterministic Python over rows already written, and the
model only puts words around numbers it is handed. `test_correlate.py` runs the
entire sweep with `ANTHROPIC_API_KEY` unset and asserts it still delivers,
still carries every number and every suggested action, and prints "written
without the summariser" rather than quietly reading thinner.

The same reasoning covers a check that raises: it is reported as a
`sweep_error` finding rather than skipped, because a sweep that silently drops
half its checks reads as a clean night.

*Rule: when a job's PURPOSE is to notice things, its failure mode must never be
silence. Ask what it prints when its most expensive dependency is gone, and
make that the tested path.*

### 2.51 The system's best work, filed as failure — fixed 2026-08-20

The owner read a real week of Diagnostics and found it listing as "blocked"
every fraud alert, MFA warning and verification deadline the mail path had
correctly routed to him. `_finish_mail_run` mapped `escalate` -> `blocked`,
which I wrote and justified as "escalate is where a guard caught something or
the mail needed a person" — conflating two opposite outcomes in one line of
its own comment.

Worse than cosmetic. Each escalation's reasoning went into `blocked_on`, so
`blocked_reasons()` — the ranking of what to go and WRITE into the knowledge
base — filled with rows like "requires immediate out-of-band verification with
TD Bank", which no amount of writing about a client could ever satisfy. On a
real week, eight of the top ten backlog rows were not knowledge gaps at all.

Three separate collapses, all into `blocked`:
* `escalate` -> now `escalated`. Routing to a person IS the response.
* "no generator yet" (`systems_tick`) -> now `not_built`. Our build queue, not
  the account's gap.
* an unfilled contract -> no longer a gap at all; see §2.52.

**The owner's rule, adopted verbatim:** *a problem is a log showing that a
response was required and failed to happen.* `diagnostics` now counts only
`failed` and genuine `blocked` as problems.

*Rule: when one column encodes an outcome, every distinct outcome needs its
own value. A vocabulary that collapses success into failure does not just
mislabel a row — it poisons every ranking computed from it.*

### 2.52 A pipeline reported as broken while it was doing the work — fixed 2026-08-20

Giving the mail path a run ledger meant auto-creating an `inbox_triage` System
row. `systems_tick` walks every System row and evaluates it for generation — so
the one pipeline actually answering the owner's email was reported daily as
having no generator, and sat at the top of the backlog claiming it could not
run, while it drafted replies all day.

The System row exists to HOLD that ledger, not to declare the substrate should
generate for it. `systems.EXTERNALLY_DRIVEN` names the difference and the tick
skips those.

*Rule: adding a row to a table that something else iterates is joining that
loop. Ask what the loop will now do with it.*

### 2.53 The contract, demoted — 2026-08-20

Owner: *"Every system currently has to fill in the contract otherwise the
system fails. That doesn't need to happen."* Eight prose answers stood between
a system and running, were reported on every tick as something the ACCOUNT was
missing, and were filed onto the knowledge queue through `record_unknowns`.

Now advisory: computed, visible on the card as `contract_complete`, in neither
`thin` nor `blockers`. It gates ONE thing — promotion to `auto`, the rung where
nobody reads the output, which is the case *kill criteria* and *failure mode*
were written for.

Four assertions in `test_systems.py` pinned the old rule and were CHANGED
deliberately rather than worked around, which is the same treatment the two in
`test_skill.py` got when the gating rule changed.

*Rule: a quality checklist that blocks work gets filled with placeholder text
or resented. Make it visible, make it optional, and gate only the case where
its absence is genuinely dangerous.*

### 2.54 Two systems, one inbox, no owner — closed before it fired 2026-08-20

The owner asked how `inbox_triage`, `service_desk` and `lead_responder` avoid
conflicting on one mailbox. They do — because two of them have no generator and
produce nothing. That is a property of the build, not the design.

Nothing would have caught it. `already_seen` is per MESSAGE, not per thread.
`Conversation.system_key` is written on one path only. And the two paths record
in different tables — `EmailLog` + `Approval` for triage, `Output` for the
substrate — so neither could see the other's reply.

**Fix:** `replies.owner()` reads both, `may_reply()` refuses a second system by
name, and it is checked at BOTH entry points — the mail loop and `skill.run`,
which the WhatsApp agent can reach directly via the `run_skill` kernel tool.

Recorded here although nothing broke, because the interesting part is the
question: *what stops this once the missing half exists?* A guard added while
the answer is still "nothing produces yet" costs an hour; the same guard after
a customer gets two replies costs the customer.

*Rule: when a component is inert, ask what protects the system once it is not.
"It cannot happen yet" is a schedule, not a safeguard.*

### 2.55 Three answers to one question — fixed 2026-08-20

`System.status` looked like a switch and was not. `skill.preflight` blocked on
`retired` alone, so a PAUSED system kept running skills — pausing being the one
action whose entire meaning is stop. `systems_tick` ran `live` AND `designed`,
which filed a daily row against every pipeline nobody had turned on. And run
re-homing checked only that a row existed.

**Fix:** `systems.is_on()`, one question, asked by all three. Only `live` is on.

The interesting part is what it took to make the fix safe. `inbox_triage`'s row
was being created `designed` while the mail path ran regardless — the row
described nothing. Gating the mail path on a switch the row had never honestly
carried would have stopped every inbox on deploy, so the row is created and
back-filled `live` (it IS running), while anything explicitly `paused` is left
alone: `designed` was never a decision, `paused` was.

And it fails OPEN — no row, no tenant, or a raise all mean run. A switch nobody
set is not a switch turned off.

Two suites had assertions that only passed because "off" meant nothing.

*Rule: a status column is not a switch until exactly one predicate reads it. If
three call sites each interpret the values themselves, the disagreements are
already there — you just have not hit them yet.*

### 2.56 Doing on purpose what had only ever happened by accident — 2026-08-20

Six tests in this log passed for the wrong reason, and every one was found by
accident — the portal cookie over http, `test_oauth` against a page that
stacked every account, a fixture with literal backslash-n, an authorisation
check on a client that had already signed in, an assertion about absence run
against an empty table, and a go-live gate that passed by never being asked.
Three of those were found in a single day.

`scripts/sabotage.py` does it deliberately. Each entry disables ONE guard, runs
the suites that claim to cover it, and expects them to fail. Nine guards, all
currently caught: tenant scoping, the mail ban list, guidance reaching the
prompt, the cross-client leak guard, the Shopify shop-host allowlist, webhook
signature verification, one-reply-per-thread, the on/off switch, and the sweep
surviving with no model.

Three outcomes, and the third is the one worth having: `caught`, `MISSED` (the
guard can be deleted today and nothing says so), and **`STALE`** — the code no
longer contains what the entry patches, so it has been testing nothing since it
moved. A sabotage harness that silently reports a pass when its target has gone
is the same failure it exists to find, one level up.

It edits the live tree, so it restores after every entry and VERIFIES the
restore byte-for-byte before continuing; a failed restore is fatal and shouted
about. No `return` inside the `finally` that restores — that would swallow the
exception which sent it there and turn a crashed suite into a silent success.

*Rule: a test suite's coverage is a claim, and claims get checked. Run the
harness after adding a guard, and read a STALE line as loudly as a MISSED one.*

## 4. How to verify

**Run them all. The list that used to live here was hand-kept and had drifted
to naming 35 of 61 suites** — which is worse than naming none, because somebody
reading it concludes they have covered the suite. Derive it, the same rule this
codebase keeps re-learning about lists:

```bash
for f in scripts/test_*.py; do
  [ "$(basename $f)" = "test_brief.py" ] && continue
  r=$(python3 "$f" 2>&1 | tail -3)
  echo "$r" | grep -qE "all checks passed|all green" || echo "FAIL $(basename $f)"
done
```

**Check the OUTPUT, not the exit code**, and skip `test_brief.py` — it is an
argparse CLI that exits 0 whatever happens, and counting it as a passing test
is a mistake this project made for weeks. 65 suites, none touching the network,
~7 minutes; a single shell call may hit a 2-minute timeout, so background it.

**Then check the suite would notice a guard going:**

```bash
python3 scripts/sabotage.py
```

Twenty-two guards, each disabled in turn against the suites that claim to cover it.
Read a `STALE` line as loudly as a `MISSED` one — it means the code moved and
that entry has been covering nothing since.

**The two that are not optional.** `test_tenant_isolation.py` is the standard,
not a preference: a model that holds client data carries `tenant`, or it is
declared in `PLATFORM_MODELS` with a reason. And re-run everything after
touching `kb.py`, `brief.py`, `systems.py` or `resolve.py` — §2.15 is what
happens when the claim in this section is trusted instead of re-checked, and
§2.42 is what happens when one function quietly has a single caller.

Two reports rather than tests, worth running after data work:

```bash
python3 scripts/seed_kb.py --report       # what each account still needs
python3 scripts/tenant_scope.py --report  # what is still unattributed
```

---

### 2.57 A connection the client made was invisible to the code that publishes — fixed 2026-08-20

`shopify_seo` and `wordpress_seo` are the only two modules in this codebase
that write to a client's live website. Neither had ever called `credentials`.
Both read `config.SHOPIFY_STORES` / `config.WORDPRESS_SITES` directly, so the
entire client-connect path — the encrypted store, the probe, the console chip,
`wired_capabilities` granting `cms` or `commerce` — stopped at their door.

A client could finish `/connect/<token>`, be shown as connected on every screen
we have, and every publish would answer:

    Shopify store 'coverings' not configured for site 'coverings'.
    Available: ['baci']

telling them to edit a Render variable for a thing they had just connected
correctly. On WordPress it was `add it to WORDPRESS_SITES_JSON`. Had `_ok`
somehow been passed, `_base` would have raised `KeyError` reaching for a domain
that was sitting in the credential store the whole time.

This is §2.29 one floor down — two layers disagreeing about whether an account
is connected — and `credentials.google_config` had already written the verdict
in its own docstring months earlier: *the connection would be real and
unreadable, which is worse than absent.* It was written about `email_harvest`,
and nobody checked whether the same join was missing anywhere else. It was.

**Half of `shopify_seo` was already correct, which is why nothing looked wrong.**
`_headers` resolves the TOKEN through `data_tools._shopify_token`, which is
client-first. Only the DOMAIN and the existence check read the env group. One
credential, half resolved, and the half that worked is the half a person would
have spot-checked.

Fixed by `app/connections.py`, which resolves **by tenant** rather than by the
env key. That distinction is the fix rather than a workaround: a store connected
by OAuth has no env key at all, so anything joining through `creds_key` can
never find it, however many fallbacks are stacked behind it. Client connection
first, env group second, refusal by name — naming the account and the connect
page — when neither exists.

`scripts/test_connections.py`, 32 checks, verified to fail without the fix with
the exact message above. `sabotage.py` entry `client_credential_reaches_publish`.

Two more found in the same seam:

* **The account/site join had two implementations that disagreed.**
  `tool_scope._site_for` (tenant → site) and `connections.tenant_for_site`
  (site → tenant) are one rule run in two directions; the inline one lowercased
  and stripped `www.` but not a scheme, so a profile whose domain was written
  `https://acme.com` resolved one way and not the other. One normaliser now,
  and the suite asserts the join is reversible.

* **`filter_tools` resolved the account once per tool.** 48 tools are scoped
  and 27 of those by site, so building one tool list cost 48 `Tenant` reads and
  27 `SEO_SITES_JSON` parses — on every turn of every agent. Resolved once now.
  The test asserts the cost does not GROW with the tool count rather than
  pinning a threshold, because a threshold drifts and this cannot pass while
  the resolution is back inside the loop.

### 2.58 Two thirds of model spend was unrecorded, and the worst offender was on the most expensive path — fixed 2026-08-20

Twenty-six `messages.create` calls behind eleven `anthropic.Anthropic()`
clients. **Nine called `usage.log_usage`.** So a spend report covered about a
third of the spend while looking complete — and `Usage.tenant`, already on the
declared-and-never-written list, could not be filled by callers that were not
logging at all.

Three more things were inconsistent for the same reason — each was a second
thing to remember rather than a property of the call:

* **`model_error.explain` had two callers of twenty-six.** It exists because a
  spend limit once reached the console as a truncated `BadRequestError` and
  sent somebody through the ban list and the validator hunting a billing
  problem. The other twenty-four still reported the exception class.
* **Absence had three spellings** — degrade and say so, return `""`, or raise.
* **Every one of the twenty-six read `content[0].text`.** The content is a LIST
  of blocks and a thinking or tool_use block may lead it. Nothing has enabled
  thinking yet, so this is a trap rather than a bug — the kind that goes off
  during an unrelated change.

`app/llm.py` is one door. `purpose` is required and is BOTH the usage tag and
the model selector, so an unattributed call is not expressible. It does not
raise: `Reply.ok` is the gate, `.error` is the provider's condition in words
somebody can act on, `.degraded` is what was missing before the call was made.
Fifteen sites migrated (`ops_jobs` ×10, `skills` ×3, `brief`, `voice_learn`);
eleven clients became eight, and all eight already logged.

**The migration was not mechanical, and two sites proved it.**

* `voice_learn` wrapped its call in a `try/except` that logged and moved on.
  Since the gateway does not raise, a naive swap would have written an EMPTY
  voice profile — and the guard at the top of that loop skips any alias that
  already has a row, so the account would never be re-learned. A silent,
  permanent regression from a change that "only" added logging.
* `skills.meeting_scan` returned `"parse failed"` for both a model that could
  not be called and a model that answered something unreadable. Those send you
  to a billing console and to a prompt respectively, and one message covering
  both sends you to neither. Reported apart now.

**And the guard against this recurring was itself decoration at first.** The
new suite asked whether each module calling the API *mentions* `usage.log_usage`
— which `triage.py` did, twice, while holding three calls. `sabotage.py`
reported the entry UNDETECTED, and counting the sites instead found
`triage.py:490`: the JSON-repair retry, `CLAUDE_MODEL` at 2500 max tokens,
recording nothing — **on the path that is 93% of model spend**. It also read
`content[0].text` eight lines below a loop that already scans for the text
block properly.

That is the §2.15 lesson again: a test that cannot fail for its stated reason
is worse than no test. The difference this time is that `sabotage.py` said so
on the day rather than an unrelated change admitting it months later.

`scripts/test_llm.py`, 24 checks. Two sabotage entries. The structural one
counts call sites per file, so a new unattributed call fails the suite.

---

### 2.59 A route that was switched off looked exactly like a route that did not exist — fixed 2026-08-20

Owner, reading the console: *"our shopify connection still expects a shps api
code, I'd like to make sure it's as easy as possible for me to connect accounts
correctly."*

Shopify can be connected two ways and only one of them is reasonable to ask a
client for. A custom-app token means walking a merchant through their own
developer settings, ticking nine API scopes, installing the app — the token
section does not exist until it is installed, which is why it looks missing —
and copying a value revealed exactly once. OAuth is a button.

The OAuth route is built and deployed. `credentials.status()` computed whether
it could run like this:

    blocked = oauth.configured(key) if spec["kind"] == "oauth" else ""

**Shopify's `kind` is `api_key`.** It carries `oauth_optional=True`, which is
how it gets a button at all — so the blocker was never computed for the one
provider where both routes exist. With `SHOPIFY_CLIENT_ID` unset the button
rendered nowhere, on the client page or the console, and no screen anywhere
said why. The paste form was presented as the only way to connect a store.

`admin_ui._connections` had the matching hole one layer up: its branches ask
`r["kind"] == "oauth"` twice and fall to `action = ""`, so Shopify got no
button, no blocker and no redirect URI on the owner's own Connections tab.

**An absent button and an unbuilt feature look identical.** That is the whole
defect, and it is the same shape as §2.13 and the credential layer being
invisible to its own operator: the state existed and nothing rendered it.

Three things now:

* `status()` computes the OAuth blocker for any provider that HAS an OAuth
  flow, and reports `has_oauth` / `oauth_blocked_by` separately from
  `blocked_by`, whose old meaning the pure-OAuth rendering still depends on.
* `_connections` gives an api-key-plus-OAuth provider either the sign-in form
  or the named blocker plus the redirect URI to register.
* `credentials.routes()` and a **Connection routes** panel answer the question
  nothing answered: not "is this account connected" but "can anybody connect at
  all". Those have different owners — a client cannot fix an unset app
  credential, and the person who can had no screen saying one was unset.

**Two things the panel says that no code could have inferred**, both of which
fail quietly:

* `CREDENTIAL_KEY` is unset, so credentials are encrypted with a key derived
  from `APPROVAL_SECRET`. Rotating the console password would make every stored
  credential undecryptable — and `_decrypt` swallows a bad key and returns `""`,
  so they would not error, they would read as NOT CONNECTED. A silent mass
  disconnection.
* Switching Shopify's button on does not make the DATA complete.
  `read_customers` / `read_orders` need Protected Customer Data approval or the
  fields return REDACTED rather than erroring — which reads as an empty
  account — and plain `read_orders` returns only the last 60 days.

The redirect URI is now shown whether or not the route works. It was withheld
until the flow already worked, which handed the value over only once nobody
needed it, and it is the half that fails silently on a byte mismatch.

`scripts/test_connect_ui.py`, offline, asserting against the RENDERED HTML the
way `test_kb_ui.py` does — including that a stored secret never reaches the
page, checked by storing a known value rather than by hunting for a prefix that
also appears in the instructions. `sabotage.py` entry
`oauth_route_named_for_api_key_providers`.

---

### 2.60 The telemetry covered the code that never runs — fixed 2026-08-20

`toolcalls.record` had **exactly two callers**, both in `kernel.py`, plus three
adapters wrapped through `instrument`: Omnisend, Constant Contact and Canva.

Every one of those three is on this file's own *built and NEVER called for real*
list.

Meanwhile `shopify_seo`, `wordpress_seo` and `data_tools` reach live stores and
sites all day through plain `httpx`, and recorded nothing — because `instrument`
fits a signature beginning with a tenant, and those modules are keyed by a store
key and a site profile instead. So the ledger covered the code that has never
run and missed the code that runs constantly.

That is why Diagnostics reports most of this system as untimed, and the note it
carries about that — *"anything reaching a platform another way records no
duration and reads as untimed rather than fast"* — was describing nearly the
whole platform surface rather than an edge.

**`toolcalls.http_seam(provider, tenant_of, method="")`** wraps a seam whose key
is not a tenant. `tenant_of` is exactly the join `app/connections.py` was built
for a few hours earlier — `tenant_for_store` is new and public for this reason,
since a tool call filed against no account is a row Diagnostics cannot scope.
Five seams: `shopify_seo._get/_send`, `wordpress_seo._get/_send`,
`data_tools._shopify`.

Three properties the suite pins, each of which is a way this could have been
written wrong:

* **A raising seam is recorded and re-raised.** These wrap `raise_for_status`,
  so a dead token arrives as an exception — and that is exactly the call worth
  having in the ledger. Swallowing it would turn a broken connection into a
  silent empty answer.
* **A client's ids never enter our telemetry.** `products/8123456789.json` is
  filed as `shopify:GET products`. One id per segment would make every row
  unique and useless to group by, and would put order numbers in our own logs.
* **A broken attribution costs a label, never the call.** If the tenant join
  raises, the row is filed unattributed rather than lost, and no account is
  guessed.

### And the busiest model loop filed nothing

`triage.py` runs its own tool loop for inbound mail. It called
`data_tools.dispatch(..., tenant=…)`, which applies the account boundary and
records nothing — so the loop answering the owner's mail every few minutes
contributed no rows to the ledger Diagnostics reads. Its platform calls were
invisible in precisely the report you open when mail stops being answered.

Not a bug in `triage`. Three things have to happen when a model names a tool —
guard, run, record — and they were written out longhand in `kernel._dispatch`
and nowhere else. Three steps kept inside one caller are three steps the next
loop does two of.

**`app/tools.py` is the door.** `kernel._dispatch` keeps its role plumbing and
delegates; `triage` calls it directly with `source="triage"`. The boundary is
now proven ONCE against the thing both loops share.

**One assertion in `test_tenant_isolation.py` was CHANGED DELIBERATELY**, and
how it failed is the useful part. It pinned the literal source text of one call,
indentation included:

    "dispatch(\n     block.name, dict(block.input), tenant=tenant)" in tsrc

That is §1's *string-matching instead of state-checking* living inside the suite
that is called the standard rather than a preference. It failed for a change
that STRENGTHENED the property it protects, and would have passed for any
rewrite preserving the characters. It asks behaviour now — that the door refuses
a call naming another account, by name, and records the refusal as a failed call
so a blocked account does not read as an idle one — plus the durable structural
half, that the ungated call is absent.

### Adding a layer nearly corrupted the number that is read first

Instrumenting the seams means a model tool call reaching Shopify files TWO rows
— the tool the model named, and the HTTP round trip under it. `report`'s
`by_provider` counted both.

That doubles every provider total, which is merely wrong. What is dangerous is
the failure rate: `data_tools.dispatch` catches the exception and returns a
`"Tool error"` STRING, so for one failing call the platform row records a
failure and the tool row records a success. **Measured: a completely dead
Shopify token read `failure_rate 0.5`.**

`report`'s own comment two lines below says a provider failing most of the time
is a broken connection and one failing occasionally is the internet. A dead
credential landed exactly on the line between them — so the instrumentation, on
its own, would have made the headline diagnostic WORSE than no instrumentation.

`by_provider` counts one layer per provider now: the platform layer wins where a
seam exists, the tool layer is used where none does (Google, today), and `layer`
says which — because a provider counted at the tool layer has durations that
include our own work rather than the round trip, and reading those as network
time is the next version of this bug. `by_tool` still carries both, which is
correct: they answer different questions.

This is the `compliance_double_run` lesson in a second place — a new writer
added beside an existing one, halving a rate computed from the ledger — and it
was caught the same way, by reading what the function being called already did.

`scripts/test_toolcalls.py`, 23 checks. Sabotage entries
`adapter_round_trips_recorded`, `model_tool_calls_gated` and
`one_layer_per_provider`.

### A crash found by reading the call sites in order to wrap them

`wordpress_seo._send(profile, method, path, body)` takes `body` positionally and
has no `params`. Both blog READS called it as
`_send(profile, "GET", path, params={...})` — an unexpected keyword AND a
missing positional, so `list_articles` and `get_article` raised `TypeError`
before reaching WordPress.

Those two are the *"review and revise existing articles"* half of the blog path,
which the owner asked for by name. They were written to mirror `shopify_seo`'s
shape, they are reads, and `_get` was sitting next to them doing exactly the
right thing. **Nothing had ever called them** — the same sentence this file
keeps writing — which is the only reason a `TypeError` on the happy path
survived being shipped.

The suite DRIVES both functions rather than reading their source, because
reading the source is what missed it for weeks. `sabotage.py` entry
`wordpress_blog_reads_callable`.

**One deliberate change to what is recorded.** `kernel` filed every row as
`source="kernel"`; it files the ROLE now — `admin`, `seo` — and `triage` files
`triage`. Nothing branches on the old value (`diagnostics` only displays it, and
the layer rule above keys on `"adapter"`), and the log is the place where
knowing WHICH loop made a call is worth more than knowing it was a loop.
Historical rows keep saying `kernel`, which is true of them.

**A limitation this made visible rather than created.**
`data_tools.dispatch` catches every handler exception and returns a
`"Tool error (...)"` STRING, so at the tool layer a call that failed is filed as
`ok=yes` with the error inside the payload. For an instrumented provider that no
longer matters — the platform row carries the truth and is the one counted. For
a provider with no seam (Google, today) it means the tool layer cannot report a
failure at all, which is a second reason the `layer` field has to be on the
count rather than in somebody's head.

**Still not recorded:** `gmail_client`. It has no single seam — `.execute()` is
called at a dozen sites through `googleapiclient` — so instrumenting it is a
different shape of job, not another line in this one. Until it is done, the mail
path's Google round trips remain absent from the ledger.

### 2.61 The prompt builders on the live mail path had no tenant at all — fixed 2026-08-21

The audit's highest-risk isolation finding, and it was invisible to
`test_tenant_isolation` because that suite checks the *schema* and this is the
*prompt*. Two functions injected straight into every drafting prompt and took
no tenant argument:

* `memory.shipments_block()` — `s.query(db.Shipment).filter(status != "closed")`,
  every tenant's open shipments, counterparties and missing-document lists, in
  every client's triage.
* `memory.sender_history(sender)` — `EmailLog.sender.ilike("%addr%")` across
  every mailbox, so one client's prior handling of a shared forwarder seeded
  another client's draft.

This is the exact cross-client disclosure the whole architecture exists to
prevent, running on the one path that answers real customers. The schema test
could never see it: `Shipment` and `EmailLog` both *carry* `tenant`; nothing
*read* it here.

Both now take a **required** `tenant`, and the scope is a first-class value with
three meanings rather than an optional string that defaulted to "everything":

* `"*"` — an EXPLICIT all-accounts view, for a console or report that is
  deliberately cross-account. **Not for an agent turn** — see §2.63: the owner
  chose to switch accounts explicitly, so the admin agent scopes to the active
  account and never runs against all of them. Stating the intent is the point —
  the leak was that "no scope" and "every scope" were the same value.
* a concrete key — one client's, via `tenant_filter(..., include_unassigned=True)`.
  Legacy rows written before attribution are still shown, because the logistics
  ledger predates it; the backfill is what lets this tighten to strict.
* `""` — an unresolved scope sees only legacy unattributed rows, never another
  tenant's attributed ones. It fails toward less exposure, the same direction
  `db.tenant_filter` already chose.

`scripts/test_tenant_isolation.py` gained section 7 — seed two accounts, assert
each block holds its own marker and not the other's, that `"*"` sees both, and
that `""` leaks neither. `scripts/sabotage.py` gained `shipments_scope`, which
removes the filter and confirms the suite fails by name — verified caught.

**Deliberately still open (the write side and the rest of the seam).**
`memory.remember` / `add_lesson` still write unattributed because the admin tool
dispatch does not yet carry a tenant to attribute with — that is the next step,
folded into threading tenant through the tool door. And the read fix leans on
`include_unassigned`, so a real tightening waits on a backfill of the rows
written before this existed. This closed the largest leak, not the class.

### 2.62 Two live security holes on the internet-facing edge — fixed 2026-08-21

Found by the audit, patched alongside the tenant seam because both are
exploitable on the running service, not latent.

**The WhatsApp webhook had no signature check.** `POST /webhooks/whatsapp` read
JSON and processed it with zero cryptographic verification — no
`X-Hub-Signature-256`, though `META_APP_SECRET` was already in config. The only
gate was `_norm_phone(msg["from"]) == WHATSAPP_APPROVER_NUMBER`, and `from` is a
field of the caller's OWN body. A forged POST reached `_handle_button("approve",
id)` → `apply_decision` → `_execute` (sends mail, publishes SEO) and
`_handle_command` (the agent). Telegram and Shopify both verified; this one did
not. `_verify_meta_sig` now checks HMAC-SHA256 over the RAW body and **fails
closed** — an unverifiable delivery is refused 401, the same shape as
`shopify_webhooks.verify`. With `META_APP_SECRET` unset the webhook is disabled
rather than open, and says so in the log; Telegram is the active ops channel, so
this costs nothing today and closes the hole.

**Email text was rendered unescaped into the console.** `/admin/pending` and the
unauthenticated `/decide/{token}` page interpolated `ap.summary` (built from an
email's sender and subject) and `payload["body"]` (model/email content) straight
into HTML. With no CSRF token and dozens of mutating `/admin` GETs, one crafted
subject line was stored XSS running against the httpOnly console session. Both
sinks now go through `html.escape`.

`scripts/test_console_auth.py` drives the webhook end to end (fail-closed unset,
forged refused, valid accepted); `scripts/sabotage.py` gained
`whatsapp_webhook_sig`, verified caught. **Still open on this surface** (bigger
jobs, not this pass): there is no route-inventory test asserting every mutating
route checks the secret, no CSRF tokens, and the ~37 GET routes that mutate are
untouched — the escaping stops the injection, it does not make the GETs safe.
The XSS escaping itself has no render-level regression test yet.

### 2.63 Explicit account switching, and the Telegram webhook — 2026-08-21

Owner's decision, and it made the tenant seam simpler and stricter: *"I'd like
to switch accounts explicitly so that there is never a misunderstanding or data
breach."* So there is no ambient cross-account agent mode. An agent turn is
always about ONE account — the one the owner selected with `/use` and the one
its own ACTIVE ACCOUNT banner names — and never all of them.

That corrected a choice made an hour earlier in §2.61. The admin agent's context
hook had been wired to `shipments_block("*")` (every business's shipments); it
now scopes to the active account. `Role.extra_context` changed from a zero-arg
callable to `Callable[[str], str]` so the kernel passes it the active tenant;
`roles/admin.py` is `lambda tenant: memory.shipments_block(tenant)`, and
`seo_tools.seo_context_block` gained the parameter for signature parity (its
baseline is still the global primary site — audit SEO-1, a separate fix). `"*"`
survives as the reserved token for a deliberately all-accounts console view, and
is reached by no agent path.

**The tool boundary is already scoped for this on the live path.**
`kernel.run` passes the active tenant to `tool_scope.filter_tools`, so the
Telegram admin flow (which resolves the account via `_active_tenant`) already
offers only the active account's tools. The remaining fail-OPEN — `filter_tools`
returning everything unscoped when the tenant is `""` — is the keystone still to
flip (the `/admin/ask` entry point and the `"baci"` handler defaults go with it).

**Telegram hardened, because it is now the channel.** Owner is dropping WhatsApp
for the free Telegram ops channel. The WhatsApp webhook already fails closed
without `META_APP_SECRET` (§2.62), so that path is now inert — which suits. The
Telegram webhook verified its secret only `if expected:` — fail OPEN when
`TELEGRAM_WEBHOOK_SECRET` is unset, the §"secrets fail open" shape on the live
ops channel. It now fails CLOSED, same as WhatsApp and Shopify. `render.yaml`
generates the secret so prod is unaffected; a deploy that forgets it is refused
rather than exposed. `test_console_auth` drives it end to end and
`sabotage.telegram_webhook_sig` confirms the guard is caught.

### 2.64 The first real Omnisend call — connected, and a missing version header — 2026-08-21

The moment the audit kept predicting: the FIRST real call any of this made
against a live ESP found something. Eien's Omnisend, probed read-only through
`/admin/esp_probe`, resolved perfectly — `connected: true`, `provider: omnisend`,
no 401 — so the credential store, `esp.provider_for` and `esp.backend` all work
against a real account. But `segments()` came back **400 Validation failed ·
Omnisend-Version: required**. Omnisend now requires a dated `Omnisend-Version`
header on every call and `omnisend._call` sent none.

Fixed on the transport, so every Omnisend call inherits it: `_call` sends
`Omnisend-Version: config.OMNISEND_API_VERSION`, default `2024-06`, overridable
by env so a version bump is not a deploy — and if the value is ever rejected,
Omnisend's error names the versions it accepts. `test_omnisend` drives the real
`_call` through a mocked transport and asserts the header is on the wire.

The useful part is the shape of the finding: auth, resolution and the whole
credential path were RIGHT; one required header was missing. That is exactly the
kind of thing only a live call surfaces, and exactly why the probe went first.

### 2.65 The second real Omnisend call — the version VALUE was the wrong shape — 2026-08-21

§2.64's fix guessed the value: `2024-06`. The owner's re-probe answered with
**400 Validation failed · Omnisend-Version: invalid_format** — the header must
be a FULL date, and the API reference documents exactly one version:
`Omnisend-Version: 2026-03-15` (api-docs.omnisend.com/reference/overview,
checked rather than guessed this time). So the header's *presence* fix shipped
with a *format* bug inside it, and the suite could not notice: it asserted the
header was non-empty, which passes while every versioned call fails.

Fixed: default `2026-03-15`, still env-overridable (`OMNISEND_API_VERSION`).
`test_omnisend` now also pins the SHAPE — a `YYYY-MM-DD` fullmatch — because
the guarantee that broke was the format, and a check that would have passed
through this defect is decoration (§ the sabotage file's own rule).

Two lessons worth the ink. A live probe that half-works is a BETTER teacher
than one that fails outright — `connected: true` plus a field-level error
localised this to one header value in one read. And when an external API names
a format, look the value up in its docs at fix time; the first fix invented
`2024-06` from the error's shape, which is how a second deploy got spent on
one header.

### 2.66 The campaign engine, read end to end — five defects behind two complaints — 2026-08-21

The owner's report was two sentences: *"Images are still broken"* and *"the goal
is not to have one template for all emails … this is all templates."* Reading
the whole path for both turned up five defects, three of them live-reachable and
none of them visible to a passing 77-suite run. They are grouped here because
the grouping is the lesson: every one of them is a place where **two things that
had to stay identical were derived separately**, and nothing compared them.

**(a) The rendered HTML predated validation.** `emit` validates and repairs a
STRING; the HTML and the `meta` dict were built before the call. A draft that
failed the ban list, was repaired, and passed therefore filed the repaired text
and shipped the REJECTED render to the ESP. The ledger said the email was clean;
the client's ESP held the banned one. Fixed by making `meta` (and the new
`shape`) accept a callable read AFTER the loop settles, and by routing the
campaign through a single `_build(copy)` that re-renders, re-personalizes and
re-derives the checked text together. The thing validated is now the artifact
sent, by construction rather than by ordering.

**(b) The repair narrowed what was checked.** `_repair` returned only
`body_html`, and `emit` replaces the whole body with whatever it returns — so
the second pass no longer contained the subject or preheader. A banned phrase in
a SUBJECT LINE was therefore "repairable" by rewriting the body: pass two saw
clean text, `ok` went true, and the banned subject shipped. The repair now
returns the same shape it was given. Worth stating plainly: this is a validator
ESCAPE that a green suite reported as a working gate for as long as it existed.

**(c) `entity_key` opened a branch and was never used.** `resolve` fetched
entities when a key was named but passed only `requirements` to the ranker —
which, for a campaign, is empty. `match_entities` then ranked on nothing and
returned rows in NAME order, `include_unavailable=True`. So "Featured entity:
Firenze" on a plan produced the catalogue's alphabetically-first three rows,
sold-out ones included, labelled plan-scoped so no warning fired. The named
entity now leads and is fetched directly when the ranked window missed it;
`match_entities` returns `availability` so downstream can see what it was
already being blocked on.

**(d) The contract changed and its own usability check did not.** The prompt was
rewritten to ask for `blocks`; `usable` still tested `sections or body_html`.
Every well-formed composed layout was therefore discarded and the deterministic
composer served instead — the feature was off, and because the composer is a
legitimate fallback, the output looked merely dull rather than broken. Same
class as §2.64's header check: a guard that passes through the exact failure it
names. Fixed, plus the ceiling that would have produced the same silence a
different way — `max_tokens=900` truncates a 5–10 block JSON, so it is 2400 now
and a truncated reply is NAMED rather than composed over.

**(e) One error message for every cause.** Any `personalize` failure — including
the unknown-token refusal built to catch drafter typos — printed "ESP not
connected, so personalization stayed neutral" and skipped the draft. One stray
`{{TOKEN}}` made a wired account read as disconnected, with the real reason
discarded. It now reports what actually happened.

**The images, for the record, were not one bug.** They were a DATA gap (Eien's
entities predate the image-filing sync — imageless products render text-only,
silently) *and* Omnisend's importer dropping hotlinked CDN references. Fixing
either alone still looks broken, which is why the first fix appeared not to
work. The rehost path (upload to `POST /api/images`, rewrite the src) was
verified against the live API before shipping: `{"url"}`, idempotent per URL,
**5 MB cap** — and the 5 MB cap is why full-resolution originals had to be
sized down as well. Sizing uses Shopify's `_1200x` FILENAME convention rather
than `?width=`, because a query parameter adds an `&`, escaping renders it
`&amp;`, and this importer is already on record turning `&nbsp;` into visible
" bsp;" (§ the design pass). The fix for one defect must not re-create another.

Craft rules (subject length, platitudes, proof on an ask) landed as `nudge`
findings that buy one redraft, and exactly one as a `block`: urgency with no
source behind it. The severity split is deliberate — a 9-word subject is not a
compliance event, and a system that treats it as one teaches its owner to switch
the checks off. Unbacked urgency earns the block because it is a false statement
made in the client's name, over their sending domain, at scale.

### 2.67 A rule only the reviewer could see — proof usage was never wired — 2026-08-22

The owner's note was one line: *"Offer / Proof data can be derived from claims."*
It is correct, and checking it surfaced a defect older and wider than the email
engine.

`kb.PROOF_USAGE` has always encoded what each KIND of proof permits — a
testimonial is quoted verbatim with attribution and never paraphrased, a spec is
stated exactly, data may be restated but the figure may not change — with
`VERBATIM_ONLY` and `usage_rule()` beside it. Its own comment calls the
testimonial rule "the load-bearing one", and explains exactly why: a customer's
review reworded as brand copy is a fabrication however true the sentiment was.

**Nothing enforced it.** `grep` for its three names outside `kb.py` returns
`admin_ui.py` (twice, to DISPLAY the rule to a human reviewing a claim), a
comment in `extract.py`, and a test. `resolve` never put `proof_type` in a
bundle, so no generator could see it, no prompt could state it, and no validator
could check it. The rule was visible only to the person who is not writing the
copy.

That became live the moment this build gave the drafter a `quote` block. The
gate asked one question — is this claim id offered? — and a real id was treated
as permission to say anything near it. A model could cite a genuine testimonial
and put different words inside the quotation marks, under a real attribution:
a sentence invented for a named person, rendered as evidence. Of everything in
this system's reach that is the worst, and it shipped inside the fix for
"the emails all look the same".

Fixed: `resolve` carries `proof_type`, `strength` and the resolved `usage_rule`
into the bundle; the drafting prompt states each claim's rule beside the claim;
and `_proof_misuse` drops, by name, a quote whose words differ from a verbatim
claim, a customer quote with no attribution, and a stat whose figure does not
appear in the evidence it cites. Sabotage guard `proof_used_as_its_kind_allows`.

**The general shape, which is the part worth keeping:** the KB models more than
the pipeline consumes, and a rule that stops at the console is decoration. The
audit that follows from this is not "check proof_type" — it is *for every rule
the knowledge base knows, name the generator that receives it and the validator
that enforces it*. Where either is missing, the rule is advice to a human who
has already left the room. `strength` (strong | supporting, "caps how many per
asset") is the next one on that list: it now reaches the bundle and still
nothing reads it.

### 2.68 An email that recommended a product nobody could buy — 2026-08-22

Eien's first letter-format campaign told a careful story about GLP-1 and closed
by recommending **CitroBurn, a product set to `draft` in Shopify**. It also
signed off as "Maya Chen, Head of Product" — a person who does not exist — and
its button pointed at `#`. The banned-claims validator passed all of it, which
is the fact worth sitting with: every gate that existed ran and every gate that
existed was satisfied.

**Nothing was broken in the usual sense.** The Shopify connection worked. The
sync ran. CitroBurn came back from `products.json` with `"status": "draft"` in
the payload. `_available()` read `variants[]` for inventory, found untracked
variants, and returned `"available"`; `_SYNCED_ATTRS` never recorded `status`
or `published_at`. So the knowledge base held a confident, wrong answer, and
every layer downstream was right to believe it. **The API was never the
problem — the code discarded the two fields that answer the question.**

Three failures stacked, and each one is a general shape:

**(a) A composite fact was modelled as one word.** "Available" for a shop means
active AND published AND (in stock OR untracked). It was implemented as the
last clause only. `_available` now returns the REASON — `draft` / `archived` /
`unpublished` / `oos` / `available` — because "CitroBurn is draft" sends
somebody to the store admin while "out of stock" sends them to the warehouse.
The raw `status` and `published` now ride on the entity so the verdict is
auditable rather than asserted.

**(b) The right check existed at the wrong granularity.**
`validator.entity_unavailable` has always refused to "route demand to a shelf
that is empty". It takes ONE `entity_key`; campaigns pass none; and this email
named its product in a SENTENCE — no card, no key, no parameter. So the new
`fitness.named_unfit` reads the copy, because what governs is what the words
say, not what was passed. It is a block, not advice: the click goes to a dead
page and the sender pays for it in trust.

**(c) A name is a claim about a human being.** The `signature` block accepted
any non-empty name, so the drafter supplied one, with a job title, over a live
customer email. A name now comes from `theme.sender` — owner-entered brand data
— or the letter goes unsigned. Same rule as the hero: the model chooses
placement, code supplies governed content. This one is the worst of the three
and was the least visible, because invented people read perfectly.

Also fixed here: a CTA with no URL fell back to `"#"` and shipped a dead button
(now derives the storefront, and `email_craft.dead_links` blocks what is still
dead — a send is spent whether or not the link worked); and a model stutter
("…and why it matters now. now.") that no prompt reliably prevents is now
removed deterministically, case-sensitively so deliberate emphasis survives.

**The generalisation, which is the reason this is written up at length.**
Every business has facts that decide whether a thing may be named in outbound
content, and they are NOT the same facts. `app/fitness.py` declares them per
business model, so a venue's "bookable" and a shop's "purchasable" can differ
without one of them quietly meaning the other. Two rules carried into it from
this defect: absence of a fact is never permission (an entity whose
availability was never recorded is refused by name, not featured), and the
declaration starts EMPTY where the owner has not stated a requirement — the
first draft required a `price` for e-commerce and immediately refused real
products whose price had not synced, which is how a check earns its way into
being switched off.

### 2.69 "Eien Health Research" — a field the model was asked to invent — 2026-08-22

The owner asked where that attribution came from, and whether he has to tell
the model not to do things like that. The answers are worth writing down
because the second one is the whole architecture.

**Where it came from: I asked for it.** The blocks contract shipped a `quote`
block whose vocabulary read `"attribution":"optional"`, and `_assemble_blocks`
passed the value straight through — the only check was that `claim_id` named a
real claim. So a model that had been handed a genuine, approved statement and a
field labelled "attribution, optional" filled it with the most plausible thing
available: the brand's own name plus the word Research. It was not hallucinating
around a guardrail. It was completing a form nobody should have handed it.

**Do you have to tell it not to? No — and the codebase already said so.** The
`KbClaim` model has carried this comment since it was written, about `proves`:

> "The one model-WRITTEN field on this table. Everything else is either copied
> verbatim from the source or chosen by a human."

That is the rule. The defect was that a new rendering block quietly created a
SECOND model-written field, one that asserts a fact about the world (who said
this), and no review caught that it broke a rule the schema had already stated.
A prohibition would not have helped: the surface was mine, the invitation was
explicit, and "do not invent attributions" competes with a field literally
labelled optional. The fix is that the field cannot be written, not that the
model is asked twice not to write it.

**And there was nowhere honest to copy from.** The obvious source, `KbClaim.
source`, is internal PROVENANCE — its real values are "captured", "shopify",
"stated on https://…", "proposed while reading the site". Rendering any of
those under a pull-quote would have replaced an invented credit with a
nonsensical one. So the field was missing, which is why the generator was asked
to supply it in the first place. Added `KbClaim.attributed_to` (auto-migrates,
empty everywhere, human-owned): who the READER may be told said this. A quote
now renders that or nothing; a testimonial with nobody on file is dropped by
name, because PROOF_USAGE requires attribution and an uncredited customer quote
is just a sentence in quotation marks.

**The general rule this produces**, and the one to apply to every future block
and every future skill: *a generator may choose placement, order, and prose. It
may never supply an identity, a source, a number, a name, a price, a date, or a
status.* Each of those is a claim about the world, and the correct design is not
a prompt that forbids inventing them — it is a schema where they can only be
copied. Where the field does not exist yet, the honest move is to add it and
leave it empty, not to let the drafter fill the gap.

Three fields have now failed this test in two days: the hero image (fixed by
construction from the start), the signature name (§2.68), and the attribution
(here). All three were "optional" fields on a block. That pattern — an optional
field on a rendering block that happens to assert a fact — is the thing to grep
for before adding the next one.

### 2.70 An approved email that existed nowhere — 2026-08-22

The owner approved a campaign and then could not find it in Omnisend. Nothing
had deleted it. It had never been created.

`Context.emit` queues the approval the moment the copy clears the validator.
For campaign_email the ARTIFACT — the ESP draft — is attempted afterwards,
further down the same function. So every reason the draft might not happen (a
craft block, an ESP refusal, a raised exception, an un-personalized body) left
a pending approval describing an email that existed in no system. The gap had
been there since the skill was written; the craft blocks shipped a day earlier
just made it reachable, because now a perfectly valid email could be stopped
after its approval was already queued.

Approving it then did nothing and said the opposite. `_execute` has a branch
per kind — `send_email`, `refile_moves`, `seo_update`, and four more — and none
for `skill_output`, so the call fell through every branch, `apply_decision` set
the status to `executed` and returned "Approved and executed". The queue item
vanished, the log recorded success, and Omnisend was empty. Three separate
surfaces agreed that something had happened.

Two fixes, and the second is the more important one.

`approvals.withdraw(run_id, why)` closes the pending approvals for a run whose
artifact never appeared, records the reason on the payload, and prefixes the
summary "[not created]". campaign_email calls it whenever the ESP draft did not
land, and the run summary now ends "NOT DRAFTED IN ESP" rather than quietly
omitting the clause that would have said so.

And `skill_output` no longer reports execution it did not perform. Its
approval genuinely has no executable side — the draft already lives in the
destination platform and approving means "reviewed, ready to launch there" —
which is a fine design and was never the problem. Claiming to have executed it
is what made a review indistinguishable from a send.

**The rule worth extracting: an approval is a question about a real thing, and
must not outlive the thing.** Anything that queues one before the artifact
exists has to be able to take it back. Two of the four campaign_email
approval-queuing paths could already fail after the queue — and every future
skill that follows this shape inherits the same hole unless it withdraws too.

### 2.71 The gate that stopped every email — 2026-08-22

"It was working before, but now it's not creating an email in Omnisend."

`email_craft.dead_links` was added the day before and made an empty `href` a
BLOCK. A drafter writes `<a href="">the product page</a>` constantly, and
correctly: the link is a fact about the store, and the drafter is deliberately
given no facts. So the check fired on ordinary, well-formed emails and stopped
essentially all of them — a gate written to catch a broken send instead
prevented every send.

The reading was simply wrong. Every other fact in this pipeline follows the
same rule and I had just written it down: *the model chooses placement and
prose; code supplies identities, sources, names and URLs.* The hero image is
supplied. The signature is supplied. The attribution is supplied. The link was
the one that got a validator instead of a supplier.

`_fill_dead_links` now points every empty link at the email's one destination —
the CTA's, else the featured product's page, else the storefront — and says how
many it filled. `dead_links` still runs, so a genuinely destination-less email
is still stopped, but that now means the account has no URL anywhere rather
than that the drafter left a blank.

Two smaller faults in the same area, both found while fixing it:

A literal `"#"` from the drafter outranked the derived URL, because `b.get
("url") or default` treats `"#"` as a value. It means "I do not know", exactly
as an empty string does, and is now read that way.

And the craft-redraft acceptance rule compared TOTAL finding counts, so a
retry that removed the one blocking problem but added a shorter-subject nudge
scored "not fewer" and was discarded — leaving the email blocked over
something the drafter had already fixed. Blocks are now compared first.

**The lesson, and it is the same one two days running: a new gate must be
judged on what it does to the ORDINARY case, not the bad one.** Both the
CitroBurn defect and this one came from the same day's work — one gate that
was missing, one gate that was too eager. The missing gate cost a bad email.
The eager gate cost every email, and was harder to see, because nothing
malfunctioned: it reported success, withdrew nothing (until §2.70), and simply
produced less and less.

### 2.72 A link to a page that does not exist — 2026-08-22

A campaign's call to action pointed at `https://eienhealth.com/collections/all`.
That store's catalogue is at `/collections/shop`. The drafter wrote the shape
Shopify stores *usually* use, and nothing checked it against the site — so the
one click the entire email exists to earn landed on a 404.

Product links in the same email were correct, which is the whole lesson: those
came from the catalogue sync's own handles, and the collection link came from
the model. **A URL is a claim about what exists on somebody's site**, and it
had been the one fact still left to a generator after names, sources, figures,
signatories and photographs were all taken away from it.

`app/links.py` reads the real destinations — product handles from the sync,
collections from Shopify's own `custom_collections`/`smart_collections`, and
the owner-approved `theme.nav` — and answers the question a generator actually
has: where should this send people. The most specific true answer wins: the
featured product's page, else the store's real catalogue page, else home.
Anything the drafter writes is checked against that set and repointed if it is
not a page that exists, with the substitution named on the run. External links
are left alone; they are somebody else's business.

It is a module rather than four lines in the email skill because blogs
cross-linking within a domain and ads driving to a landing page ask exactly the
same question, and each would otherwise invent its own answer.

**Two smaller findings from the same email.**

The GLP-1 non-sequitur — an email about omega-3 and a joint formula that
suddenly discussed metabolic pathways — is a DATA problem, not a code one.
`kb.claims` has always scoped correctly: with no entity named you get
brand-wide claims only, and its docstring gives the reason ("a fact that is
only true of one product must not turn up in a newsletter about something
else"). So that claim is filed brand-wide in Eien's KB when it belongs to one
product. The skill now also screens claims against the featured set as a
second line, and the prompt says plainly: one email, one subject.

And a FOURTH stutter variant shipped — "read it.d it." — after "now. now.",
"every day. day." and "productionction" had each been chased with their own
pattern. They were never four bugs. The model finishes a string and emits some
suffix of it a second time, so that is now the rule: if the last N characters
repeat the N before them, one copy goes. Five characters minimum, end of
string only, longest match first — bounds set by testing against all four real
cases and a list of real words that must survive (couscous, beriberi, "no.
No."). Chasing the instances instead of the shape cost three deploys.

### 2.73 Approving a photograph did nothing — 2026-08-22

"Make sure that the approval process for photos is working, it wasn't working
before" (owner). It was not.

`may_publish` asks two questions: has this been reviewed, and are the rights
`owned`. The pictures queue only ever answered the first. So a picture the
owner explicitly approved still failed the second test, no email could select
it, and no surface said why — the queue reported success and the library
stayed unusable. Every photograph that arrived as `reference` (a crawl, and
now Drive) was in that state permanently.

`review_asset` now settles rights on approval, and says which kind of approval
it was. Per the owner's instruction, approving grants `owned`; "Reference
only" stays as a separate button, because a competitor's picture kept for
inspiration is a real and different decision from one the client may publish.

### 2.74 Three capabilities that were never reachable — 2026-08-22

Reported as gaps rather than found as bugs, which is its own lesson: each had
code, and none had a caller.

**Canva could create a design and never turn it into an image.**
`create_design` files `kind="design"`, which `hero_for_campaign` cannot select
— correctly, a blank canvas is not a photograph. The owner was meant to finish
it and have the result reach the pictures queue, but nothing exported
anything: `reconcile` reports drift and stops, and had no caller either. So
the visual loop was open at the far end. `canva.harvest` exports finished
designs and files each as an owned, entity-scoped IMAGE, which is what makes
it selectable next run. Idempotent by design id.

**Drive photographs were unreachable.** The creative library only ever
received Shopify product shots, so an account could send imageless emails with
a folder of real photography one connection away. `creative.harvest_drive`
files them — as REFERENCE, awaiting review, because Drive carries no proof of
who owns a picture. Where a filename names a product, that product is
SUGGESTED on the row for the approver to confirm; a wrong guess would put the
wrong photograph on that product's emails, so it is a recommendation and never
an action.

**Format never varied.** Warmth mapped to format one-to-one, so a warm list
got a letter every single time. Intent rotated underneath and the email still
looked identical. Warmth now BIASES and history breaks the pattern: two sends
in the same form and the next switches, and an offer leans designed whatever
the warmth because an offer wants the product shown. The intent rotation was
wrong in the same way — "first give not used" fell back to the first entry
once all three were in the window, so a list that had seen everything got
story for ever. Least-recently-used keeps it turning.

`/health/connections` now reports Canva and the ESP. Neither was visible
without the console secret, which is exactly the question that stalls a setup
— and the reason three rounds were spent asking whether Canva was connected.

### 2.75 One root folder per client, all with the same name — 2026-08-22

Found by reading `canva.folder` to answer "where do the designs get organised
inside Canva". The intended shape is two levels: a single root, "Client work —
gomehagent", with one folder per account inside it.

Only the per-account folder id was remembered, on the tenant row. The ROOT id
was not kept anywhere, so the first run for every NEW account took the
create-both branch and made another root. Five clients would have produced
five folders all called "Client work — gomehagent" at the top of the
workspace, each holding exactly one client — which is the duplicate-by-name
state that `_remember_folder`'s own docstring exists to prevent, committed one
level above it.

The root is one folder for the whole installation, not per tenant, so it now
lives in a `Setting` and is created once. Never shipped: no Canva call has
ever run live, and the account is still not connected.

### 2.76 A health page that would have written to a live Canva — 2026-08-22

Found while confirming the owner's understanding that every account defaults
to the agency's Canva until a brand connects its own. It does — `resolve`
falls back to `AGENCY_TENANT` for `SHARED_PROVIDERS` and tags the result
`source: "agency"` so a log can always say whose account did the work. The
model was right; the probe reporting on it was not.

Yesterday's addition to `/health/connections` called `canva.folder(key)` for
every tenant that resolved a token. `folder()` CREATES the folder when none is
remembered. And because the fallback gives every account the agency's token,
connecting Canva once would have meant a single **unauthenticated** GET
creating a root folder plus one folder per client inside the owner's
workspace, on first hit.

That is `segments_dry_run_gate` again — a read-only surface writing to a live
account — committed by the same person who wrote that guard, three weeks
later, in the code that reports whether the account is reachable. A health
check must never be the thing that changes what it is reporting on.

It now probes the TOKEN only, and reports the shared connection once as
"agency (shared by every account)" with a row per client that overrides it,
rather than repeating one fact under every tenant's name. Guard
`health_probe_creates_nothing`.

Worth stating as a rule, since this is the second time: **any function whose
name is a noun ("folder", "segments") may still be a constructor.** Before a
read-only surface calls one, read what it does when the thing is absent.

### 2.77 An email in which nothing was false and nothing agreed — 2026-08-22

The owner's read of a live Baci send: the hero photograph was a **tablecloth**,
the subject line and body were about **shatterproof glasses**, the featured card
was a **pitcher bundle**, the Four Seasons placement was asserted twice and
"designed in Milan" twice. Every claim in it was approved. Every product in it
was in the catalogue. The picture was owned and publishable. The banned-claims
validator passed it, correctly. It was still not client-facing.

Three causes, only one of which is a model behaving badly.

**(a) The hero was selected before the email had a subject.** `skill_pack`
narrowed the offered products to the drafter's choice under
`if not copy.get("blocks")` — the LEGACY contract. On the `blocks` contract,
which is the one that ships, the bundle was never narrowed, so
`hero_for_campaign` was handed the whole offered list and the imageless
fallback took `next(e for e in ents if e.get("image"))` — the
alphabetically-first product with a photograph. Four selectors read one
candidate list and each collapsed it differently.

**(b) Brand-wide claims passed unconditionally.** Yesterday's "one email, one
subject" scoping (§2.66) read `brand-wide OR in scope`, so every credential the
company owns arrived beside the subject's own proof under a heading reading
"your only credibility, cite by id". A drafter handed six of those uses six.

**(c) `emit` validates a STRING.** The hero, the cards and the citations are
not in it, so no rule written in `validator.py` could ever have seen a wrong
picture. This is the structural one: the other two are bugs, this was a missing
layer.

Fixed by a contract rather than a patch, because the same pathology is
available to every generator here — an ad whose creative is off-subject, a
reply that answers a shipping question and pitches the collection. `app/
coherence.py` holds it: a COMMITMENT declared before any selector runs, typed
by referent (`entity` / `situation` / `topic` / `audience` / `period`, plus a
declared `survey` mode where multiplicity is the point and the check inverts),
and `emit(commitment=…, parts=…)` checking the artifact's PARTS on the same
rail the banned-claims loop already uses — same finding shape, same repair,
same run notes. Guards `coherence_gate`, `commitment_narrowing`,
`coherence_not_a_kb_gap`.

Three things learned while building it, each one a bug I wrote and the suite
caught:

* **Background is relative to a subject.** Capping brand-wide claims
  unconditionally starved every email that features no product — where the
  brand IS the subject and its credentials are the only proof in existence.
* **Never commit to a subject nobody chose.** The first draft fell back to
  `ents[0]`, which asserts a decision the catalogue's sort order made. When
  neither the plan nor the drafter names a product there is no entity subject,
  and the parts are held to agreeing with each other instead.
* **A safety net must not be a tripwire.** Whole-word matching judged "GLP-1
  Support" absent from "Supports natural GLP-1 production" and blocked a good
  email over a plural. Subject-presence is stemmed; the checks that carry the
  weight — picture, cards, proof — match on keys, not on prose.

**A coherence failure is deliberately NOT a knowledge gap.** Its rules are
namespaced `coherence:` and `systems.blocked_reasons` skips them, because that
list ranks what to go and AUTHOR — and no amount of authoring would have
prevented an email whose hero was a photograph of something else.

### 2.78 The scoping fix that would have crashed on its first real use — 2026-08-22

Found by the suite while building §2.77. §2.66's claim scoping ended:

    ctx.claims = _in_scope
    ctx.bundle["claims"] = _in_scope

`Context.claims` is a read-only property deriving from `bundle["claims"]`, so
the first line raises `AttributeError` and kills the run. It never fired
because the old rule let every brand-wide claim through, which made the
`_aside` count zero on every account it was tested against — the guard could
only fail on the day it first had something to do. Writing the bundle is both
necessary and sufficient.

The pattern to distrust: a branch whose condition is false in every test
fixture is not covered by those tests passing, however many of them there are.

### 2.79 An email nobody could see, withheld for its own good — 2026-08-22

Owner, on a live run reading *"composed, sendable, hero image, NOT DRAFTED IN
ESP"*: **"Why would it not be drafted in ESP? It should always show in the ESP
because how else will I see it and send it?"**

Correct, and the gate was wrong in three separate ways.

**(a) The gate collapsed two different states.** Drafting required
`item.ok and not missing and native_ok and not hard`, and produced NOTHING when
any of them failed. But a draft cannot send — launching is
`send_campaign(confirm=True)`, which the substrate never calls. Withholding it
therefore bought no safety at all; it only removed the owner's single view of
the work. "This must not be sent" and "you may not look at this" had become the
same outcome.

**(b) The composer could never ship.** `_legacy_blocks` built the CTA as
`copy.get("cta_url") or "#"` — and `"#"` is exactly what `email_craft.dead_links`
blocks. So the deterministic fallback, the path that exists to always produce
something usable when no model is available, produced an email that was
guaranteed to be refused. Every `basis: composed` send died on a button whose
URL the drafter is never given and could not have supplied. `_legacy_blocks`
now receives `default_cta_url` like every other path.

**(c) The run blamed the symptom.** An empty `_cta_home` has exactly one cause:
`links.destinations` always includes the site root when a domain is on file, so
no destination means **no domain on the account**. Reported as *'the "Shop now"
button points nowhere'*, which reads as a drafting mistake and sends whoever is
fixing it to the wrong place. One field closes it for every future send, and
the run now says so.

**What changed.** The draft is made whenever there is HTML to make it from.
Anything wrong with it rides in the campaign NAME — internal to Omnisend, so
the owner sees `[NEEDS FIX — …]` in their campaign list while the SUBJECT stays
exactly what a customer would receive. The defect costs the approval, not the
draft: nothing defective is launchable through the system. `draft_into_esp` is
gone as a parameter entirely — producing the draft is what this system IS.

**One line the draft does not cross** (`WITHHOLD_FROM_ESP`): `banned_claim`,
`no_ban_list`, `unbacked_urgency`, `unfit_entity_named`. These are not imperfect
emails, they are false or forbidden statements made in the client's name, and a
draft sitting in the sending platform is one careless click from a list. That is
the one case where withholding buys real safety rather than only removing
visibility. Everything else — dead link, incoherent hero, missing address,
neutral merge tags — is drafted and marked. Guard
`withhold_false_or_forbidden`.

**Recorded, and notified.** Defects go on the run via `systems.record_defects`,
and `blocked_reasons` now counts runs that shipped defective as well as runs
that were blocked — otherwise fixing the symptom (ship it anyway) would have
silently emptied the very list that says to fix the cause. The digest gained a
`DRAFTED BUT NEEDS FIXING` section, because a defective draft carries no
pending approval and was therefore invisible in the one place the owner reads.
The same cause twice is called out as an account problem rather than an unlucky
send.

### 2.80 Approving a photograph did nothing, on a page that looked fine — 2026-08-23

Owner: **"Photo approvals are not working."** They were not. The picture queue
rendered an anchor `<div class="anchor" id="pics">` and, nine lines later,
`<form id="pics" …>`. Every checkbox, the hidden tenant field and all three
buttons carried `form="pics"` — and HTML resolves that to the FIRST element
with the id, which was the div. A `form=` attribute pointing at a non-form
element associates with nothing, so every control on the queue was orphaned:
the page looked completely normal, the buttons submitted an empty request, and
approving a photograph silently did nothing.

Nothing that reads a page for WORDS could have caught it. So it is checked
structurally, on every tab rather than the one that broke, in
`scripts/test_admin_forms.py`: no duplicate ids on any page, and every
`form="x"` resolves to a real `<form id="x">`. Guard
`picture_queue_form_wiring`.

Two things worth keeping from writing that test, both of which made it pass
for the wrong reason first:

* **`_TABS` keys are not the labels.** The tabs are `content` (shown as
  "Review"), `kb` ("Knowledge"), `schema` ("Data layer"). Requesting
  `?tab=review` renders the DEFAULT tab, so the first version of this suite
  checked the same page eight times and reported eight passes.
* **The admin key is `APPROVAL_SECRET`,** not `ADMIN_KEY`. With the wrong one
  the console returns the public landing page — HTTP 200, 2.7KB, and every
  "no duplicate ids" assertion trivially true.

Both were caught only by the deliberate check that the queue had rendered at
all. An assertion about absence, run against a page that was never generated,
is the empty-table false pass again.

### 2.81 A parts contract that counted its own words twice — 2026-08-23

Introduced and caught the same hour, while wiring `catalog_seo_rewrite` to the
coherence contract. A meta description is entirely headline, so the natural
call is `coherence.parts(text=t, prominent=t)` — and `review` built its search
text as `prominent + "\n" + text`, so every phrase in it appeared twice and
`proof_repeated` blocked a correct rewrite over the word "Milan".

The caller was fixed to pass it once, as `prominent`. More importantly the
contract was hardened: `whole` no longer concatenates when `prominent` is
already contained in `text`, because the next caller with a short artifact
would have written exactly the same line.

### 2.83 The brief went out as the subject line — 2026-08-23

Owner: **"we have incorrectly wired the Angle/Concept field in the email
campaign prompt into the subject line which is not the point."** Exactly that.
`_compose_campaign` read:

    line = (goal or seg.get("angle") or "A quick note").split(".")[0]

and put `line` into BOTH `subject` and `headline`. So the planner's internal
brief — *"A reason to come back now, while the habit is recoverable and before
a win-back discount is needed"* — arrived in a customer's inbox as the subject
line. And because an account with no model always takes the composer path, and
this owner's runs were all coming back `basis: composed`, **every send they had
seen was like that**.

Three changes, because the field was wrong in three ways:

* **The composer no longer uses it.** It cannot invent a line, so it uses what
  it actually has: the featured product's name, then the proof's first
  sentence, then the segment. Direction is never copy.
* **The prompt names it as direction.** Handed over under a bare heading, an
  angle reads as copy, and a drafter short of a subject reaches for the
  nearest sentence it was given. It now arrives as "THE ANGLE — the idea this
  email is built around … a brief written FOR you, not copy: never quote it,
  never use it as the subject line."
* **It is optional, and blank is a job.** `required=True` forced a person to
  invent a concept before anything could run — when proposing one from the
  segment, the products and the approved proof is the thing a model is
  genuinely good at. Left blank the drafter chooses, returns it as `angle`,
  and the run says *"no angle was set, so the drafter chose one: …"* so the
  owner can read back what it decided and set it themselves next time.

Guard `angle_is_not_the_subject`.

### 2.84 A test suite nobody would run — 2026-08-23

Owner, watching me run all 81 suites after every edit: **"The full suite run
every single time is wasteful isn't it?"** It was — five minutes on a quiet
machine, over ten under load.

Every suite sets its own `DATABASE_URL` to a fresh temp file at import, so
there was never a shared resource to serialise around. It had simply never been
parallelised. `scripts/test_all.sh` runs them at `-P 8`: **5m+ → 1m28s**, and
takes a substring filter for targeted runs while iterating.

Worth stating as a rule: a check slow enough to skip is a check that will be
skipped, and then it is protecting nothing. The cost of a slow suite is not the
minutes — it is the runs that stop happening.

### 2.85 Draft products were catalogued as products — 2026-08-23

Owner: **"In the example with Eien Health, we have draft products polluting our
entities and therefore all of our systems."** Correct, and the mechanism is one
missing line.

`catalog_sync.sync_shopify` had exactly ONE skip in its whole loop:

    key = (p.get("handle") or str(p.get("id") or "")).strip().lower()
    if not key:
        continue

No `status=active` on the request, no filter in the loop. So a Shopify **draft**
became a `KbEntity` with `review=APPROVED`, its title, price, description and
photograph imported, and only `availability="draft"` to mark it.

Labelling was the right first move — §2.68 is exactly that fix, and it is what
stopped a draft being RECOMMENDED. It was not enough, **because a label only
protects the readers that check it.** `fitness.screen` checks it. The catalogue
counts, the completeness score, the claim editor's entity picker and the
coherence proof scopes do not — they ask `kb.entities()` and get a product.

Drafts and archived products are now skipped, and a product that has BECOME a
draft since the last sync is retired rather than left behind — a fix that only
protects new accounts leaves every existing one polluted for ever, which is the
half that actually bit this owner. Both are counted and named on the sync's
return (`drafts_skipped`, `retired_now_draft`), separately from `out_of_stock`,
because an out-of-stock product is real and coming back and a draft was never a
product. Guard `drafts_are_not_catalogued`.

Not fixed, worth knowing: `published_scope` is read nowhere in the codebase, so
a product published to POS only still reads as available.

### 2.86 Nothing could be taken out of the knowledge base — 2026-08-23

Same message: *"Lets add the ability to remove entities from our knowledgebase
… This is true for approved photos, claims, objections, etc. We should be able
to remove / edit as needed."*

There was no removal path for an entity, an audience or an objection at all,
and the two that existed were reachable only from the REVIEW queue — which an
approved row has already left. An approved photograph could not be
un-approved; a claim that turned out to be wrong could not be retired without
re-finding it in a queue it was no longer in.

`kb.remove(tenant, kind, id)` is one door for all six tables. It is SOFT by
design: every read accessor already filters `review == APPROVED` and
`kb.entities` filters `status == "active"` unconditionally, so rejecting IS
removal from the pipeline — and it is reversible via `kb.restore`, which is
what makes it safe to offer. Hard deletion stays where it was, in the bulk
machine-origin purges.

**The part that is not obvious: removing an entity strands what was scoped to
it.** A claim whose `entity_key` names a row that is no longer active cannot
even be EDITED — `claim_update` validates the key against `entities()` and
refuses with "has nothing in its catalogue keyed …" — so it becomes
unreachable rather than merely unused. So anything scoped ONLY to the entity
comes out with it and the return value names how many. Brand-wide rows are
untouched. `restore` deliberately does NOT undo the cascade: putting a
collection of rows back in bulk resurrects the thing you meant to remove.
Guard `removing_an_entity_takes_its_claims`.

**Two bugs found while wiring it:**

* `situations()` tested `(r.review or "") != prov.PROPOSED`. That test was
  chosen so pre-review legacy rows would not vanish — and a row somebody had
  explicitly REJECTED passed it too, so a removed situation tag went on
  validating new claims for ever. Guard `a_removed_tag_is_not_vocabulary`.
* `embed.forget` was called from exactly one place, the claim-reject branch —
  "leaving the vector behind is the index-drift this design exists to avoid".
  Every other removal left its vector, so a rejected objection stayed findable
  by similarity. `remove()` calls it for every kind.

### 2.87 A theory of taste built out of one range — 2026-08-23

Owner, on a Baci Milano send that was otherwise the best the system had
produced:

> "That's the quiet trick of a well-considered table. It doesn't announce
> itself."
>
> "…even though this positioning is true of the Joke collection, as a brand
> Baci Milano has many maximalist designs so we dont want to sell the idea of a
> good evening as one where the table doesn't take too much attention because
> the next email might say the opposite."

Nothing in that email was false, and nothing in it was incoherent by §2.77's
test: one subject, one product, proof in scope, hero of the right thing. It
argued a **theory of taste** generalised from one range — and the range next
door argues the opposite, so the brand ends up on both sides of its own
aesthetic. This is coherence ACROSS artifacts, which the within-artifact
contract cannot see.

**The root cause is one column.** `positioning` exists on `KbBrand` and nowhere
else — one brand, one position. There was no way to record that Joke is minimal
and Baroque & Rock is maximal. A drafter handed a single brand positioning and a
minimalist product generalised from it, reasonably, because nothing told it the
catalogue disagrees with itself.

Three layers, weakest last:

1. **Positioning is a proof kind.** `PROOF_USAGE["positioning"]` — scoped,
   reviewed, and arriving with what its scope permits, on the same rails every
   other claim rides: *"True of what it is scoped to, and ONLY that … never as
   a claim about the brand, about taste, or about what a good example of the
   category is."* Not `VERBATIM_ONLY`: a position may be rewritten, it may not
   be widened.
2. **The bundle carries the disagreement.** `kb.contested_positioning()` →
   `bundle["contested_positioning"]`, on EVERY bundle rather than fetched by
   whichever generator remembers — a copywriter, a script and an ad go wrong
   here identically. The prompt names which ranges hold which positions,
   because a drafter told abstractly to "avoid generalising" has advice, and
   one told *"joke — minimal; baroque — maximalist"* has a fact.
3. **A lint catches the shape.** `email_craft.generalisations()` flags generic
   normative constructions ("the trick of a", "a well-", "the best ",
   "doesn't announce") in sentences that do NOT name what is being sold —
   naming the subject makes it a description, and describing what you sell is
   the whole job. Advisory on purpose: code cannot know whether the brand
   holds the position, only that the sentence claims it of a category.

Guard `positioning_is_scoped` — which reported MISSED first time, because the
fixture had no brand-wide positioning row and relaxing the scope filter
therefore changed nothing. The row was added and the check bit.

Worth stating as the general rule: **the within-artifact contract stops one
email contradicting itself; only the data layer can stop two emails
contradicting each other.** An aesthetic that lives in one text field cannot be
scoped, and anything that cannot be scoped will eventually be generalised.
