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
preview can fire them. `/admin/claim_edit` and `/connect/<token>` are POST and
are the model to follow.

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

**Spreadsheet upload** (Coverings' 26-column spec data, Ironside's rate card)
— the third source. Now unblocked and shaped: parse to rows, call the existing
`kb.add_*` with `origin="upload"` and `source="<file>#<row>"`, and it inherits
dedupe, the review queue and conflict-on-disagreement for free. What it still
needs is its own work: column mapping per client, and a preview before write.

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
python3 scripts/test_brief.py --demo
python3 scripts/seed_kb.py --report      # what each account still needs
python3 scripts/tenant_scope.py --report # what is still unattributed
```

All fifteen suites pass as of 2026-08-12. None of them touch the network.

Re-run all five after any change to `kb.py` — §2.15 is what happens when the
claim in this section is trusted instead of re-checked.
