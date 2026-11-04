# BUILD MAP — the truth pipeline (harvest → facts → QA → truth → change)

For the engineer building it. Read §0 and §1 before writing any code; they are
the process this whole build exists to serve, and every later section is
judged against them. Companion design: `INITIATIVE-claims-reconciliation.md`
(the why, the evidence per brand, the decisions). Repo rules in `CLAUDE.md`
apply to every line here (tenant scoping, `scripts/ship.sh`, a sabotage guard
per fix, `REGISTER.md` regenerated).

Status (2026-11-04, end of day): **M0–M9 are all built** on branch
`claude/sleepy-mendel-lpoz4j` — one commit per milestone, each with its
offline checks in `scripts/test_pipeline.py` and its sabotage guards — and
NONE is deployed: production is still `19a68f7` and waits on the owner's
"deploy". §13 lists every place the build departs from this map, and why.

---

## 0. The process you must not lose sight of

```
 1 READ       every page of every source a brand publishes, completely, and say how completely
 2 CAPTURE    every fact those pages state, as data (subject · value · scope · where · authority)
 3 SHOW       a non-technical QA reviewer what the brand says, where it disagrees with itself, by risk
 4 DECIDE     QA sets the truth per subject × scope, from a source they name — never a machine
 5 ENFORCE    every draft, reply and site edit is checked against that truth before it can go out
 6 CHANGE     a changed truth lists every place that states the old value, proposes the edits,
              and closes only when the live pages agree
 7 PROVE      known-answer checks, audits and a trust score say how far the capture can be trusted
```

The owner's words this answers (2026-11-04):
- *"pages making different claims about coverage, licensing … declare a
  specific page / document as the source of truth or reconcile once and have
  the change update across all pages … otherwise identify exactly where the
  changes need to be made manually"*
- *"some products may be available in all markets while others are not"* →
  scope is a first-class dimension.
- *"Transak's own pages give seven different country counts (26, 60+, 64+, 75,
  90, 145, 162). The compliance page shows 19 state licences; the coverage page
  shows 45 states served"* → the capture missed them; completeness must be
  measured, not assumed.
- *"a Quality Assurance team member to control content quality / compliance
  and flag inconsistencies"*, *"organize content to be reviewed cleanly by a
  non-technical compliance reviewer"*.
- *"not one bulky process … modular and lean"*.

## 1. Invariants (any PR that breaks one is wrong, whatever it adds)

1. **No silent loss.** Every stage reports what it did NOT do: pages not
   read, blocks not read, numbers not accounted for, sources not monitored.
   A ceiling is allowed only if it is reported (DEFECTS.md §1).
2. **Generators propose, humans decide.** Machines write statements and
   findings; only QA sets truth; only the owner approves a publish
   (`WALKTHROUGH-PROMPT.md:170`, `provenance.py:25-40` "approved is final").
3. **Code compares, people judge.** Comparison (`truth.compare`) is
   deterministic. Models extract; they never decide what is true.
4. **One fetch, many readers.** A page is fetched once per change and every
   reader (facts, claims, ban-list scan, voice, links) reads the stored copy.
5. **Everything is tenant-scoped** (`CLAUDE.md` "MANDATORY"): `tenant` column,
   per-tenant uniques, `db.tenant_filter`, enforced by
   `scripts/test_tenant_isolation.py`.
6. **Idempotent stages.** Each stage is keyed by (input fingerprint, stage
   version); re-running is free; a rehearsal (`apply=False`) writes nothing.
7. **Fail closed** on every gate that lets content out (`validator.check`,
   `triage._apply_guards`, `seo_guard`).
8. **Legal / compliance pages are binding** (`compliance.LEGAL_PATHS`) and are
   read first and in full.

## 2. Where things are today (anchors)

| Concern | Today | File |
|---|---|---|
| Page discovery | sitemap → WP API → homepage crawl; legal kept on request; 10k/source | `compliance.discover_pages` :432, `harvest.DISCOVERY_CAP` |
| Fetch + parse | inline in the harvest loop; `text_blocks` keeps `<main>` minus furniture | `harvest.harvest` :417, `compliance.text_blocks` :138 |
| Crawl memory | url → content hash, claims found, partly-read flag | `db.HarvestedPage` |
| Claim extraction (AI) | verbatim spans, merged fragments, chunked, input coverage | `extract.extract` :394, `merge_short`, `chunks` |
| Fact capture | regex sweep over the full page incl. furniture + page data | `statements.sweep` :167, `db.KbStatement` |
| Fact view | Review › Site facts, by subject, conflicts first | `admin_ui._facts_card`, `REVIEW_SUBS` :6280 |
| Claims | proposed → approved/rejected; legal derived from source URL | `kb.add_claim` :2088, `kb.is_legal_claim` |
| Conflicts | per row × field, Keep ours / Take theirs | `provenance.record_conflict` :206, `db.KbConflict`, Review › Conflicts |
| Ban-list scan | fetches the site AGAIN, phrases only | `compliance.scan` :638, `check_page` :550 |
| Gates | ban list, citation present, entity available | `validator.check`, `seo_guard.check`, `triage._apply_guards` |
| Write-back | Shopify/WordPress body + SEO meta via approvals | `approvals._execute` :903 (`seo_update` …) |
| Jobs | queue with kinds, payload → `fn(tenant, **payload)` | `jobs.KINDS` :70, `jobs.enqueue` :253 |
| Registry pattern | sources as data | `sources.py` |
| Claude access | MCP: get_claims, get_statements (+CSV), get_package (BINDING block) | `mcp_server.py` |

The monolith to dissolve: `harvest.harvest` (~500 lines: fetch, parse, sweep,
extract, filter, file, report in one loop) and `compliance.scan` (a second
fetch of the same site).

## 3. Target architecture

```
 DISCOVER ─► FETCH ─► PARSE ─► EXTRACT ──► ACCOUNT ─► COMPARE ─► FINDINGS ─► QA DECIDES ─► TRUTH
 page list   snapshot  document  statements  coverage   (pure fn)  queue        (sources,      │
 + risk tier (stored   (blocks,  (plug-ins,   unaccounted                        scope, value)  │
             once)     tables,   same record) numbers                                           ▼
                       data)          │                                         CHANGE ◄────────┘
                                      └──► CHECKS (ban list, known answers,     locations → edit
                                           audit samples, trust score)          proposals / tasks
                                                                                → verified on fetch
 Readers of truth: get_package · validator/seo_guard/reply guards (contradicts_fact) · MCP get_truth
```

Each box is a module with one job, a stored output and a job kind. The harvest
becomes a thin coordinator that enqueues stages.

### 3.1 Module layout

```
app/pipeline/
  __init__.py         stage registry: name → (fn, input kind, output kind, version)
  policy.py           RISK_TIERS and the tier × plug-in × ceiling table (data, not branches)
  discover.py         sources → PageRef rows with risk tier
  fetch.py            PageRef → Snapshot (content-addressed); optional browser render
  parse.py            Snapshot → Document (sections, blocks, tables, faq, data, links)
  extractors/
    __init__.py       EXTRACTORS registry + Extractor protocol + version
    numbers.py        today's statements.sweep, moved
    tables.py         header × row × cell → statements
    structured.py     JSON-LD / microdata / page data → statements
    ai_facts.py       model → subject/value/scope triples, verbatim-verified
    ai_claims.py      today's extract.extract, moved
    legal.py          clause-level statements off binding pages
  account.py          Document + Statements → unaccounted numbers, read coverage
  checks/
    __init__.py       CHECKS registry + Checker protocol
    banned.py         today's compliance.check_page, reading Documents (no refetch)
    known_answers.py  golden facts vs statements
    audit.py          random page samples for human audit
    trust.py          per-brand trust score
app/truth.py          Fact, FactValue, Source authority; resolve(); compare()
app/findings.py       Finding lifecycle (generalises KbConflict)
app/change.py         ChangeRequest → Locations → Tasks → verification
app/review/           plain-language QA surfaces (cards, decisions, audit export)
```

### 3.2 Data contracts (new tables; every one tenant-scoped)

New-table checklist for EACH (the suites enforce it — `test_tenant_isolation`,
`test_reset`, `test_shopify_compliance`, `test_data_layer`):
`tenant` column + index · `UniqueConstraint("tenant", …)` · reads via
`db.tenant_filter` · classified in `reset.KNOWLEDGE` (or another set) ·
described in `admin_ui._KB_DESCRIBED` · `REGISTER.md` regenerated.

| Table | Key fields | Unique | Notes |
|---|---|---|---|
| `page_refs` | tenant, source_label, url, risk_tier, discovered_at, last_fetched_at, status (due/ok/dead/unreadable), unmonitored_reason | tenant+url | replaces the discovery list built per run |
| `page_snapshots` | tenant, url, fetched_at, http_status, content_hash, html_blob_ref, rendered (bool), bytes | tenant+url+content_hash | bytes in the blob store (`media.py` pattern), not the row |
| `page_documents` | tenant, snapshot_id, parser_version, sections (JSON), blocks, tables, faq, page_data, links, hidden_present (bool), size_blocks, numbers_total | tenant+snapshot_id+parser_version | deterministic |
| `kb_statements` (exists, extend) | + document_id, extractor, extractor_version, section_path, scope_entity, scope_market, scope_channel, scope_audience, valid_from, valid_to, locator (css/section/table cell) | tenant+url+fingerprint (exists) | one record for every extractor |
| `extract_runs` | tenant, document_id, extractor, version, input_hash, status, statements, cost_tokens, cut (bool), error | tenant+document_id+extractor+version | idempotency + cost ledger |
| `unaccounted_numbers` | tenant, document_id, number_text, context, status (open/ignored/labelled), label_subject | tenant+document_id+number_text+context_hash | QA labels grow the vocabulary |
| `kb_facts` | tenant, subject, kind, unit, criticality (legal/regulated/commercial/descriptive), owner | tenant+subject | the subject register (templates §6) |
| `kb_fact_values` | tenant, fact_id, value, number, qualifier, scope_* (entity, market, channel, audience), valid_from/to, status (proposed/approved/retired), mode (follows_source/pinned), source_id, decided_by, decided_at, reason | tenant+fact_id+scope hash+valid_from | the truth |
| `kb_sources` | tenant, kind (page/document/system/api/owner), ref, label, authority (canonical/binding/derived), governs (subjects × scope) | tenant+kind+ref | "make this the source of truth" |
| `findings` | tenant, kind (contradiction/scope_error/unsupported/stale/banned_value/missing_known/unaccounted), severity (P1/P2/P3), subject, scope, statement_ids, fact_value_id, status (open/decided/closed), assignee, due, decided_by, decision, reason | tenant+kind+subject+scope+statement-set hash | generalises `KbConflict`; existing rows migrated |
| `known_answers` | tenant, subject, scope, expected, tolerance, where_expected (url/source), set_by | tenant+subject+scope+where | QA-authored |
| `check_results` | tenant, check, run_at, passed, details | — | trust score input |
| `change_requests` | tenant, fact_id, scope, old_value, new_value, effective_at, reason, requested_by, status | — | QA-created |
| `change_tasks` | tenant, change_id, location (url/field/sentence or output/system ref), kind (auto_edit/manual/unmonitored), approval_id, status (open/proposed/approved/published/verified), verified_at | — | closes only on re-fetch agreement |

`users` gains roles `qa` and per-user console sessions (M5 prerequisite);
`decided_by`/`requested_by` reference them.

### 3.3 Interfaces (the only seams between modules)

```python
# extractors/__init__.py
class Extractor(Protocol):
    name: str
    version: int                     # bump → re-runs over stored documents only
    tiers: set[str]                  # which risk tiers it runs on (from policy)
    uses_model: bool
    def run(self, doc: Document, ctx: TenantCtx) -> ExtractResult: ...
# ExtractResult = statements: list[Statement], cut: bool, read_blocks: int,
#                 total_blocks: int, cost_tokens: int, notes: list[str]

# checks/__init__.py
class Checker(Protocol):
    name: str
    version: int
    def run(self, tenant: str, docs: list[Document], stmts: list[Statement]) -> CheckResult: ...

# truth.py — pure, no I/O beyond reads
def resolve(tenant, subject, scope) -> FactValue | None        # most specific scope wins
def compare(stmt: Statement, truth=resolve) -> Finding | None  # the ONLY judge
```

Every gate and checker calls `compare`; nothing else decides agreement.

## 4. Stage specs

For each: responsibility · input → output · idempotency key · job kind ·
reported losses · tests · guard.

**DISCOVER** — enumerate pages per source (`tenants.content_sources`), assign
`risk_tier` by policy (URL patterns + page type + legal paths), record
unmonitored sources (PDF links, iframes, external domains, app-store, social)
with reasons. Key: (tenant, source, sitemap hash). Job: `discover`. Reports:
pages per source, method, unmonitored list. Tests: Transak-like fixture with
subdomains, legal pages first, PDF listed as unmonitored. Guard:
`unmonitored_sources_are_not_listed`.

**FETCH** — due pages only (new, changed per sitemap lastmod, stale per tier
schedule, open finding/task needing verification first). Store snapshot by
hash; dead/failed recorded (today's `_tried`). Browser render only for tier
`interactive` (Playwright already in the container; add to the Render image
in M6). Key: (url, content_hash). Job: `fetch`. Reports: fetched, unchanged,
dead, failed, rendered. Guard: `a_dead_page_holds_the_queue` (exists in
spirit).

**PARSE** — Snapshot → Document: sections by heading path, blocks (with
`merge_short`), tables as header×row×cell, FAQ, JSON-LD/microdata, embedded
page data, links, hidden-but-present content flagged (`hidden_present`),
furniture kept as its own section (not discarded). Code only. Key:
(snapshot_id, parser_version). Job: `parse`. Reports: size_blocks,
numbers_total, tables, has_page_data. Guards: `a_table_is_flattened_again`,
`furniture_is_discarded_again`.

**EXTRACT** — run every registered extractor allowed for the page's tier.
Deterministic ones always; model ones only for blocks whose hash is new
(cache by block hash × version). Key: (document_id, extractor, version).
Job: `extract` (fan out per document). Reports per run: statements, cut,
read/total blocks, tokens. Guards: one per extractor
(`a_stat_tile_is_dropped_as_noise` exists, `a_long_page_is_cut…` exists).

**ACCOUNT** — every number token in the Document minus those inside an
extracted statement span = unaccounted. Filters for phone/date/postcode/price
in an example are explicit and listed. Key: (document_id, extractor set hash).
Reports: numbers_total, accounted, unaccounted. Guard:
`an_unaccounted_number_is_not_listed`.

**COMPARE** — pure: statements × truth → findings; dedupe by statement-set
hash; severity by criticality and source authority (legal/regulated → P1;
commercial → P2; descriptive/scope → P3). Re-runs when statements or truth
change. Guard: `a_contradiction_with_a_binding_value_is_not_P1`.

**CHECKS** — `banned` (today's phrase scan, now on Documents, legal excluded
from phrases only), `known_answers` (found / missing / different), `audit`
(N random pages per run → a QA sample card), `trust` (coverage %, high-risk
pages fully read, known answers passed, audit recall, unaccounted open). Job:
`checks`. Guards: `a_failed_known_answer_raises_nothing`,
`the_ban_scan_fetches_the_site_again`.

**CHANGE** — QA creates a ChangeRequest → `locations` = every statement of the
subject with a different value + claims mentioning it + our outputs
(`Output`, scheduled ESP sends, live ad creatives, GBP posts) + system
settings + unmonitored sources (manual checklist) → tasks: `auto_edit` via
existing approval kinds (`seo_update`, `seo_article_revision`,
`gbp_listing_fix`; `seo_guard` + `compare` run on the new text), `manual`
(url + exact sentence + replacement), `unmonitored`. A task is `verified`
only when a later fetch's statements agree. Guard:
`a_change_closes_before_the_page_agrees`.

## 5. Policy (data, in `pipeline/policy.py`)

| Tier | How assigned | Extractors | Ceiling | Fetch cadence |
|---|---|---|---|---|
| `legal` | `LEGAL_PATHS` (privacy, terms, cookie, legal, disclaimer, policies, compliance, licens, regulat) | all + `legal` | none | weekly + on change |
| `coverage` | URL/heading words: coverage, countries, supported, fees, limits, pricing, payment-methods, kyc | all | none | weekly |
| `product` | entity pages (catalogue handles), product URLs | numbers, tables, structured, ai_facts, ai_claims | 8 chunks | on change |
| `support` | help centre / docs hosts | numbers, tables, structured, ai_facts, ai_claims | 8 chunks | monthly |
| `marketing` | everything else | numbers, structured, ai_claims | 4 chunks | monthly |
| `blog` | /blog, /news | numbers, ai_claims | 2 chunks | quarterly |
| `interactive` | flag: thin body + scripts, or known pickers | + browser render | per base tier | per base tier |

A ceiling hit is always reported (`cut`), and any tier can be raised per page
by QA.

## 6. Subject templates (seed `kb_facts` per business model)

- `ecom_*` (Baci, Eien): origin, materials, dimensions, set size, care,
  shipping.destinations, shipping.times, shipping.free_threshold,
  returns.window, offer.*, availability, regulated.claim + disclaimer (Eien).
- `b2b_spec` (Coverings, Transak): spec.* per SKU, certifications, lead
  times, MOQ, regions; Transak: coverage.countries / states / crypto_assets /
  blockchains / fiat_currencies / payment_methods per product, legal.licences
  per jurisdiction × legal entity, fees and limits per method × KYC tier.
- `local_venue` (Ironside): capacity per space, hours, amenities, tenants as
  entities.
- `digital_products` (agency): case-study figures, confidentiality.

Extractor vocabularies (numbers.py units, ai_facts prompts) are generated from
these templates, and QA labels on unaccounted numbers add to them.

## 7. QA surfaces (non-technical reviewer)

Language: plain English, no "subject/statement/fingerprint". Grouped by topic
("Where we operate", "Licences & registrations", "Fees & limits",
"Products", "Returns & shipping").

1. **Question cards** — "How many countries do we say we serve?": the
   approved truth + its source; every page's sentence highlighted with link
   (screenshot when rendered); colour by severity; one decision with a
   required one-line reason: *This is correct* · *This page is wrong* ·
   *Both right — different products/markets* (asks which) · *Needs legal
   review* (assigns). Each decision writes a `kb_fact_values` row and closes
   or creates findings.
2. **Sources** — every source of truth, what it governs, follows/pinned;
   "Make this the source of truth" from any card.
3. **Changes** — each ChangeRequest with its task list and progress bar.
4. **Known answers & audit** — add expected facts; audit sample cards ("Did
   we miss anything on this page?").
5. **Trust** — per brand: coverage, high-risk pages fully read, checks
   passed, audit recall, open unaccounted numbers — with dates.
6. **Binding documents library** — policies/licences with versions.
7. **Audit log export** — every decision (who, when, why, before/after) as
   PDF/CSV.
8. **Digest** — weekly: new contradictions, open changes, failed checks.

MCP mirrors for Claude sessions: `get_statements` (exists), `get_findings`,
`get_truth`, `get_changes`, `get_trust` — all JSON + CSV, read-only. QA
decisions stay in the console (human acts).

## 8. Milestones (each shippable; acceptance uses real cases)

| M | Scope | Acceptance (must demonstrate on live data) | Size |
|---|---|---|---|
| **M0** ✅ built | no silent cuts in `extract`, number sweep → `KbStatement`, JS page data, Review › Site facts, `get_statements`, recrawl passes through, legal incl. compliance/licens/regulat | Transak recrawl: country values include the owner's seven (26, 60+, 64+, 75, 90, 145, 162) where present in page code; states 19 (binding) vs 45 flagged | — |
| **M1** | Snapshot + Document store under the current harvest; `parse.py`; fetch once | harvest output unchanged on fixtures; a second reader (ban scan) reads stored docs | M |
| **M2** | Ban-list scan → `checks/banned.py` on Documents | site fetched once per change; scan results identical on fixtures | S |
| **M3** | Extractor registry + versions; move numbers/ai_claims; add `tables`, `structured`; `account.py` + unaccounted numbers; per-block AI cache | bump a version → re-run on stored docs with zero fetches; Transak compliance table → 19 licence statements; unaccounted list non-empty and labelled by QA | L |
| **M4** | Stages as job kinds; harvest = coordinator; `policy.py` tiers + ceilings; coverage report + risk labels | a failed page fails one job; legal/coverage pages never `cut`; report shows tier per page | M |
| **M5** | Per-user console logins + `qa` role; `known_answers`, `audit`, `trust` | QA adds "19 licences on /compliance"; a harvest that captures 10 raises a P1 `missing_known` | M |
| **M6** | `truth.py` (facts, values with scope, sources/authority, resolve, compare); `findings` (migrate `KbConflict`); question cards; Sources | Baci B1 (two policies disagree) = P1; Transak countries resolvable per product; "Both right — different products" splits scope | L |
| **M7** | `contradicts_fact` gate in `validator.check`, reply guards, `seo_guard`; `get_package` serves resolved truth | a draft saying "ships to Mexico" against truth {US, CA} is blocked | M |
| **M8** | `change.py`: ChangeRequest → locations → auto-edit approvals / manual / unmonitored → verified on fetch; Changes surface; audit export | change "free shipping $110" lists every page/ad/email stating otherwise; closes only after re-fetch agreement | L |
| **M9** | Browser render for `interactive`; PDF reading for binding documents; public-API sources (Transak coverage API) | a country picker's options captured; a licence PDF's numbers become binding statements | M |

Rollout per tenant: Baci (most verified conflicts, writable Shopify) →
Transak (the matrix case) → Eien → Coverings → Ironside → agency. Each
milestone behind a per-tenant switch (`Tenant.systems` or a flag) until its
acceptance is shown on that tenant.

## 9. Testing (per repo rules)

- One offline suite per stage contract, fixtures under `scripts/fixtures/`:
  a Transak-like site (stat tiles, footer figures, JS page data, a 19-row
  licence table, a country picker loaded by API, a PDF link) and a Baci-like
  store (two policies that disagree, "Italian porcelain" meta).
- Every fix: reproduce first, then a sabotage guard in `scripts/sabotage.py`
  (named in §4); `scripts/test_sabotage_anchors.py` must stay green.
- Tenant isolation for every new table and MCP tool; reset / data-layer /
  Shopify-compliance classification in the same change.
- Pure functions (`resolve`, `compare`, `policy`) get table-driven tests
  covering scope specificity and severity.
- Ship only via `scripts/ship.sh` gates; production push only on the owner's
  explicit OK, when `/health` reports `jobs_running 0`.

## 10. Operations

- **Cost**: model extractors run on changed blocks only; `extract_runs`
  records tokens; per-tenant monthly budget with a visible stop, never a
  silent one.
- **Observability**: each stage's report is stored (`jobs` result) and the
  trust panel aggregates them; a stage that reads nothing says READ NOTHING
  (`jobs.py` already does for sources).
- **Backfill**: M1 creates snapshots on next fetch; M3 re-runs extractors over
  stored documents; M6 migrates `KbConflict` rows into `findings`; claims are
  linked to subjects by `ai_facts` + QA confirmation, never auto-merged.
- **Kill switches**: per-stage enable flag; a broken extractor is disabled
  without stopping the others.

## 11. Open questions (owner)

1. QA hire timing (M5 logins can come earlier if a reviewer starts sooner).
2. Budget ceiling per tenant per month for model extraction.
3. Render image size on Render for browser rendering (M9) — accept, or run
   rendering as a separate service.
4. Which partner/third-party pages count as "ours" for change tasks
   (e.g. Transak's listings on partner sites).

## 12. Glossary

- **Snapshot** — a page's bytes as fetched, stored once by content hash.
- **Document** — a parsed snapshot: sections, blocks, tables, data.
- **Statement** — one fact a source states: subject, value, scope, where,
  authority. Not approved; a record of what was said.
- **Claim** — a sentence a person approved as proof (existing).
- **Fact / fact value** — the truth for a subject at a scope, set by QA from a
  named source.
- **Finding** — a disagreement or gap `compare` or a check found.
- **Source of truth** — a page/document/system/API QA declared canonical for
  some subjects × scopes; legal pages are binding by default.
- **Change** — a new truth value and the tasks to make every location agree.

## 13. As built — where it departs from this map (read before extending)

Each item is a deliberate decision or a known gap, not an accident. Commits:
M1 `1e8ced3` · M2 `9cce423` · M3 `6249013` · M4 `6845318` · M5 `6563882` ·
M6 `1f1f54d` · M7 `c897356` · M8 `eb525fc` · M9 (this commit).

| Area | Map said | Built | Why / what is left |
|---|---|---|---|
| Snapshots (M1) | one row per content hash | ONE row per URL (latest), `prev_hash` + `changed_at` kept | change verification needs only the latest copy; history per version is not stored |
| Stages as jobs (M4) | a job kind per stage, harvest a coordinator | harvest calls the stages in-process; `reprocess`, `checks`, `findings` are job kinds | a page failure is already contained per page; per-page jobs can come when a site outgrows one run |
| `extract_runs` (M3) | table with tokens per run | `extract_cache` (paid reading per exact chunk) + report counts | per-run token cost is in `usage`, not per extractor |
| `kb_facts` register (M6) | a subject table with criticality and owner | `truth.CRITICALITY` by subject area, `truth.QUESTIONS` per subject | a per-tenant override of severity needs this table |
| Findings (M6) | migrate `KbConflict` | `findings` is new; field-level `KbConflict` stays on Review › Conflicts | they judge different things (an approved field vs a later import); merge when one queue is wanted |
| QA identity (M5) | per-user logins + `qa` role | the reviewer NAMED on each decision is recorded (`by`); `users.role` documents `qa` | owner decision: "QA = owner for now". Logins change only who may sign in, not the data |
| Auto-edit (M8) | Shopify + WordPress | Shopify product / page / collection bodies, exact-once replacement on approval | WordPress pages, SEO meta fields and ad creatives are `manual` tasks |
| Change locations (M8) | pages, outputs, ESP sends, ads, GBP, settings | stored pages, pending approvals, unreadable pages | live ESP schedules, ad creatives and GBP posts are not yet scanned |
| Render (M9) | browser for interactive pages | `pipeline.render` behind `RENDER_JS`; off ⇒ page marked `rendered=2`, reported, trust amber | owner decision §11.3: Chromium on Render, or a render service |
| Documents (M9) | PDF reading for binding docs | PDFs linked from legal/coverage pages, 20 per run, binding when legal | scanned PDFs need OCR (reported as "no text") |
| Surfaces (§7) | digest, binding-documents library, screenshots | not built | Review tabs: Site facts, Checks & trust, Questions for QA, Changes; QA log CSV |

### The crawl is a kept source (owner, 2026-11-04)

*"There is value in the crawl data itself for future operations like SEO/AEO
work, Snapshots, etc so plan to keep it as a reachable source."*

- `page_snapshots` (each page as last fetched, with its parsed Document) and
  `page_versions` (every earlier distinct copy, archived when a page changes)
  form their own reset group, **`crawl`**, outside the default reset. A
  knowledge reset clears what was concluded and KEEPS the pages;
  `pipeline.reprocess` rebuilds the facts from them with no re-crawl.
- MCP **`get_pages`** (read-only): the crawl listed and searchable (tier,
  title, headings, words, links, tables, JSON-LD, last change, earlier
  copies), or one page in full with its history; `version=<hash>` reads an
  earlier copy. This is the seam for SEO/AEO work: titles and headings,
  internal links, structured data, what changed when.
- Not yet: a retention policy (every distinct copy is kept; compressed), a
  page-diff view in the console, and SEO-role tools reading `get_pages`
  directly — the MCP tool is the first consumer.

### Where each piece lives

`app/pipeline/` — `fetch`, `parse`, `extractors/{numbers,enumerations,structured}`,
`account`, `policy`, `checks`, `reprocess`, `render`, `documents`, `apis` ·
`app/truth.py` (answers, sources, scopes, `resolve`, `agrees`, `check_text`) ·
`app/findings.py` (`compute`, `rebuild`, `decide`) · `app/change.py`
(`create`, `locations`, `propose`, `execute_fix`, `verify`, `audit_log`) ·
`shopify_seo.replace_text` · the gate in `validator.check` (and so in triage
and `seo_guard`) · MCP `get_statements`, `get_trust`, `get_truth`.

### After deploy — the first run, in order

1. Deploy (gates, `jobs_running 0`, `SHIP_GATED=1 git push origin HEAD:main`).
2. `/admin/harvest?tenant=transak&apply=1&limit=100&recrawl=1`, then without
   `recrawl` until `pages_remaining` is 0. Read the run card: tiers, partly
   read, figures not understood, pages needing a browser, documents read.
3. Review › Checks & trust: add the known answers you are sure of (e.g. the
   compliance page's licence count), draw 3 audits.
4. Review › Site facts: label or dismiss the figures not understood, then
   "Re-read stored pages".
5. Review › Questions for QA: answer each, P1 first, with a reason.
6. Review › Changes: propose store fixes (each is an approval), fix the rest
   by hand; a task closes when the next read shows the page agrees.
