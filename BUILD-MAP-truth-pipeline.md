# BUILD MAP — the truth pipeline (harvest → facts → QA → truth → change)

For the engineer building it. Read §0 and §1 before writing any code; they are
the process this whole build exists to serve, and every later section is
judged against them. Companion design: `INITIATIVE-claims-reconciliation.md`
(the why, the evidence per brand, the decisions). Repo rules in `CLAUDE.md`
apply to every line here (tenant scoping, `scripts/ship.sh`, a sabotage guard
per fix, `REGISTER.md` regenerated).

## STATUS (2026-11-06) — LIVE

Production `main` = **`c09c71b`** (/health is the authority). Everything in
this map — M0–M9, the kept crawl with its history, and four fixes found by
the first real run (Transak) — is deployed. §13 is the as-built record and
every departure from the plan; **§14 is the lessons, written as rules for
EVERY company, with the onboarding checklist and what is still shaped by the
first clients.** Read §14 before onboarding anyone.

| Account | Pages stored | Trust | Open questions | Answers set | State |
|---|---|---|---|---|---|
| transak | 879 (legal 7, coverage 389, support 146, marketing 112, blog 225) | amber | 13 subjects disagree (1 P1, 9 P2, 3 P3) | 0 | 500+ figures not understood; 53 pages need a browser; no known answers, no audits |
| baci, eien, coverings, ironside, agency | 0 | red — never harvested into the pipeline | — | — | first run: `recrawl=1` |

Live counts: MCP `get_trust`, `get_truth`, `get_statements`, `get_pages`
per account (read 2026-11-06).

**§17 (claim record + per-entity workbook + evidence) is built on branch
`claude/sleepy-mendel-lpoz4j`, not deployed.** **Next, in order:** (0) deploy
§16–§17 on the owner's word; (1) Transak: owner adds known answers and draws 3 audits;
label or dismiss the figures not understood, then "Re-read stored pages";
answer the 13 questions, the P1 first. (2) Close the §14.3 gaps that matter
before the next company. (3) Harvest Baci (most verified conflicts, writable
store), then the rest.

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
M6 `1f1f54d` · M7 `c897356` · M8 `eb525fc` · M9 `7eb6788` · kept crawl
`7f398fa` · retention `bfabbc8` · and four fixes from the first real run
(another session, on Transak, 2026-11-05/06): `de9f1ab` (a sentence
punctuated two ways is one figure, not a crash) · `53337d6` (menus and footers
are not censuses; state tables and licence sections are counted; the
`availability` reader; generated page families read one page per place) ·
`4b45a19` (a NUL byte no longer ends a run; a page remembered without a kept
copy is unread) · `c09c71b` (a clause or step number is not a figure).

| Area | Map said | Built | Why / what is left |
|---|---|---|---|
| Snapshots (M1) | one row per content hash | ONE row per URL (latest) + `page_versions`: the last 5 DISTINCT earlier copies, cleaned nightly | see "The crawl is a kept source" below |
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
- **Retention (owner, 2026-11-04): the last 5 distinct earlier copies per
  page, cleaned passively.** The crawl only APPENDS the previous copy when a
  page changes — no comparison on the crawl path. The nightly
  `crawl_retention` (worker, 03:50; also the `crawl_retention` job kind,
  `pipeline.retention.clean`) drops any copy identical (by text hash) to a
  newer copy or to the current page, then keeps the newest
  `KEEP_VERSIONS = 5`. The current page is never touched.
- Not yet: a page-diff view in the console, and SEO-role tools reading
  `get_pages` directly — the MCP tool is the first consumer.

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

## 14. Global lessons — every company, not one

Owner, 2026-11-06: *"I want this to work for any new company I onboard so the
lessons learned need to be global."* Every lesson below was learned on one
client and is enforced in code that runs the same for every client — no
lesson lives in a client's settings, a prompt, or this document alone. Each
names the case that taught it, where it is enforced, and the guard that fails
if someone removes it. Adding a company adds DATA (a tenant, its sources,
answers QA sets); it never adds a code path.

### 14.1 The rules

| # | Rule (applies to every company) | Taught by | Enforced in | Guard (`scripts/sabotage.py`) |
|---|---|---|---|---|
| 1 | **Completeness is measured, never assumed.** Every stage reports what it did not read: pages left, pages partly read, figures not understood, pages needing a browser, documents not read, template pages left out. Coverage is stated BEFORE any finding. | Transak's seven country counts were missed by a 40-page read with silent cuts | harvest report, `checks.trust`, run card (`jobs.py`) | `a_long_page_is_cut_at_sixty_blocks_again`, `an_unaccounted_figure_is_not_listed`, `an_unrendered_page_reads_as_empty` |
| 2 | **A census is code, not a model.** Figures are swept from the whole page — body, header, footer, stat tiles, embedded page data — by deterministic readers; the model only proposes claims. | "162+ Countries" tiles and footers never reached the claim reader | `pipeline/extractors/*`, `statements.find` | `a_stat_tile_is_dropped_as_noise`, `the_fact_sweep_records_nothing`, `a_javascript_page_reads_as_empty` |
| 3 | **Legal pages are read first, in full, and bind** — compliance, licensing and regulatory pages included — **but a clause or step number on them is not a figure.** | "19 state licences" (compliance page); "11.2 Payment Methods" read as 11.2 payment methods | `compliance.LEGAL_PATHS`, `policy.TIERS["legal"]` (no ceiling), `statements.find` | `legal_pages_are_skipped_by_the_harvest`, `a_licensing_page_is_not_legal`, `a_legal_page_is_cut_like_a_blog_post` |
| 4 | **A table or list under a heading that names a subject is a count; a menu or footer is not.** | the licence table that never writes "19"; nav menus counted as censuses | `extractors/enumerations` | `only_the_number_reader_runs`, `a_table_is_flattened_again` |
| 5 | **Unread is never empty.** A page needing a browser, a page that failed, a page remembered without a kept copy, a scanned PDF — each is listed as unread and lowers trust. | JS pages read as "dead"; `pages_remaining` said 0 while pages were missing | `render.needed`, harvest `_kept_pages`, `checks.trust` | `a_page_with_no_copy_counts_as_read`, `trust_ignores_pages_it_could_not_draw` |
| 6 | **One bad page never ends a run.** A NUL byte, a duplicate sentence, a timeout: contained to that page, recorded, the run goes on. | a 5m49s Transak pass ended on one NUL byte | `parse` strips NUL; per-page error handling in harvest | `a_nul_in_a_page_ends_the_harvest`, `a_nul_in_a_pdf_ends_the_harvest` |
| 7 | **Runs walk the site, they do not restart it**, legal → coverage → the rest, and generated families of 500+ pages are read one page per place — with the skipped count on the run card. | 5,651 `/buy/<coin>/<place>` pages = 22 h for 63 answers | `policy.thin_families`, `policy.rank`, `_tried` | `the_budget_goes_to_marketing_pages_first`, `an_unreadable_page_holds_the_front_of_the_queue` |
| 8 | **Machines propose; a person sets the truth, with a reason.** Per subject × scope (product, market); the most specific scope wins; a source page can be followed. | Baci's shipping policy vs terms; product-level availability | `truth.py`, `findings.decide` | `a_decision_needs_no_reason`, `the_brand_truth_overrides_a_product_truth` |
| 9 | **Everything that can send or publish is held to the truth, failing closed** — including figures the site still disputes. | the inbox and the SEO agent could state any figure | `validator.check` → `truth.check_text` (drafts, triage, `seo_guard`, MCP `check`) | `a_wrong_figure_ships`, `a_disputed_figure_ships`, `a_reply_with_a_wrong_figure_auto_sends` |
| 10 | **A change is done when the page, read again, agrees** — not when the edit was sent. Store edits go through an approval and replace exact, unique wording only. | "fixed" pages that still said the old figure | `change.verify`, `shopify_seo.replace_text` | `a_change_task_closes_before_the_page_agrees`, `a_store_fix_writes_without_approval`, `an_ambiguous_store_edit_guesses` |
| 11 | **The crawl is a source of its own**, kept with history (last 5 distinct copies, cleaned nightly), outside the knowledge reset, readable by MCP `get_pages`. | owner: SEO/AEO and snapshots need it | `fetch.store`, `retention.clean`, `reset.CRAWL` | `a_changed_page_loses_its_old_copy`, `a_knowledge_reset_deletes_the_crawl`, `retention_keeps_duplicate_copies` |
| 12 | **Every table, read and tool is per company.** | the platform rule (`CLAUDE.md` "MANDATORY") | `db.tenant_filter`, `test_tenant_isolation.py` | one `*_reads_every_account` guard per new table |

### 14.2 Onboarding a new company — the checklist

1. **Account and sources.** Create the tenant with its domain; add every
   place it publishes (landing sites, help centre, docs host) as content
   sources. Subdomains count.
2. **First read.** `/admin/harvest?tenant=<key>&apply=1&limit=100&recrawl=1`,
   then without `recrawl` until `pages_remaining` is 0. Read the run card
   before anything else: tiers, partly read, template pages left out, pages
   needing a browser, documents read, figures not understood.
3. **Teach the vocabulary.** Review › Site facts › "Figures we could not
   read": say what each kind of figure counts, or "Not a fact"; then
   "Re-read stored pages". This is where a new industry's words enter
   (see 14.3 — today they are learned per company).
4. **Test the capture.** Review › Checks & trust: write 3–5 known answers
   (one per legal/coverage page that matters), draw 3 audits. Trust must not
   be red before anyone relies on a figure.
5. **Data feeds.** If the company publishes an API listing what it supports,
   add it as a data feed and consider making it the source of truth.
6. **Answer the questions** (Review › Questions for QA), P1 first, each with a
   reason; legal review where needed.
7. **Changes.** Review › Changes: approve store fixes, fix the rest by hand;
   they close when the next read agrees.
8. **Only then** let drafts for that company rely on figures — `get_package`
   carries the approved figures and lists the disputed ones.

### 14.3 Still shaped by the first clients — close before calling it general

Found by reading the code on 2026-11-06. Each is a place where a new company
in a different industry would be read worse than Transak or Baci.

1. **The built-in vocabulary is coverage, legal and scale words with a fintech
   lean** (`statements.SUBJECTS`: countries, states, crypto assets, blockchains,
   fiat, payment methods, licences, users, partners). Commerce and service
   facts have no subject: free-shipping thresholds, return windows,
   warranties, discounts, delivery times, capacity, years in business, ratings.
   Currency-prefixed and percentage figures are treated as non-facts by
   `account.NON_FACTS["price"]` and so never become statements — exactly the
   figures an e-commerce brand is held to (Baci: ads say 10% off, code says 15%).
   **CLOSED for money, percent and duration by §15.6 step 1**; the vocabulary
   itself is still code, not the global table (step 3).
2. **What a reviewer teaches stays with one company.** `kb_statement_terms` is
   per tenant, so a word taught for Transak ("corridors") has to be taught
   again for the next fintech. Needed: a GLOBAL vocabulary the owner promotes
   a term into, applied to every company, with the per-company list kept for
   words that mean something different there.
3. **The subject templates of §6 are not built.** A new company starts with the
   same fixed subjects whatever its business model. Needed: templates
   (e-commerce, B2B spec, venue, agency, regulated finance) chosen at
   onboarding, seeding subjects, questions and known-answer prompts.
4. **Coverage-tier keywords lean fintech** (`policy._COVERAGE`: kyc, tokens,
   networks, currencies). A retailer's shipping, returns and stockist pages
   are read at the marketing tier, with a ceiling. The tier list should come
   from the same templates.
5. **Questions and severity exist only for the built-in subjects**
   (`truth.QUESTIONS`, `truth.CRITICALITY` by area). A taught subject gets a
   generic question and P3 unless its area is legal or coverage.
6. **Store auto-fixes are Shopify-only**; WordPress, Squarespace, SEO meta,
   ads and email schedules are manual tasks.
7. **Browser rendering is off** until the owner decides where Chromium runs.

Items 1–5 are one build ("industry templates + a global vocabulary"): data,
not code paths, so every later company benefits from what the previous one
taught.

## 15. Signal vs noise — which figures matter (design, 2026-11-06, NOT BUILT)

Owner: *"How would we differentiate between important numbers / figures and
noise? … research thoroughly how top-tier scrapers do this."*

### 15.1 What the live data says (Transak, 2,402 statements, 2026-11-06)

| Share | What it is | Treat as |
|---|---|---|
| 38% | stated in dated blog / news / press posts | HISTORY: true on its date, not a current claim |
| 45% | no subject named in the sentence (a bare "in 25+ countries", a stat tile) | the brand's IF it sits in the brand's own furniture or hero; unknown otherwise |
| ~7% | worked examples ("Scenario 3: … 50 countries"), other companies (Visa, Stripe, Deel, MiCA) | NOT the brand's claim |
| 1 sentence on 236 pages | "in 25+ countries" — one template block | ONE claim with 236 placements: one decision, one fix |

And the 500+ figures not understood are mostly non-facts with recognisable
shapes: step numbers, HTTP codes in API docs, CSS colour values, star
ratings and review text, "Last 30 days" UI labels, licence/ID numbers.

### 15.2 What the best extractors do (research)

- **Score every fact, keep a threshold, keep the provenance.** Diffbot gives
  each fact a confidence in [0,1] from source trust and cross-source
  agreement and drops facts below 0.5; Google's Knowledge Vault attaches a
  confidence and provenance to every triple. → every statement gets a
  `weight` with its reasons; below the line is HIDDEN, never deleted.
- **Agreement is counted per independent source, not per page.** Truth-
  discovery work (Dong, Berti-Équille, Srivastava) shows copied values
  inflate a false answer; detect copying and count it once. → a sentence
  repeated across 236 pages is ONE claim with 236 placements.
- **Source trust is learned from how often a source is right.**
  Knowledge-Based Trust scores a source by the share of its facts that check
  out. → each page TYPE (legal, product, blog, partner announcement) earns a
  trust from QA's own decisions over time.
- **Three classes, not two.** ClaimBuster sorts sentences into check-worthy
  factual, unimportant factual and non-factual; CheckThat! 2025 added a task
  for numerical claims specifically. → material / immaterial / not a figure.
- **Typed quantities, normalised units.** Recognizers-Text, Quantulum and
  CQE extract value + unit + kind (money, percent, duration, count); CQE
  finds unit normalisation is where most tools fail. → every figure gets a
  KIND, and money keeps its currency.
- **Templates are found across pages, content within a page.** Boilerpipe and
  Trafilatura judge one page (text and link density); site-level template
  detection compares many pages of one site. → we already have both
  (furniture field, cross-page repetition); for COMPLIANCE a site-wide
  figure is the most important, not the least — it reaches every visitor.
- **Typed extraction by page type; models only for the custom part.** Zyte
  runs deterministic trained models for standard page types and an LLM only
  for custom fields. → industry templates choose what is expected per page
  type; Claude (via MCP) proposes only what the rules cannot decide.
- **Noise rules learned from "mark as noise" feedback** (Visualping,
  PageCrawl, Distill): ignore by region or pattern, refined from each
  dismissal. → a reviewer's "Not a fact" becomes a reusable RULE, global
  when the owner promotes it.

### 15.3 The design — five facts about every figure, then one weight

Computed by code at read time (no model in the app), stored on the
statement, re-computable from the kept crawl with `reprocess`:

| Axis | Values | How it is decided |
|---|---|---|
| **kind** | count · money (with currency) · percent · duration · rating · identifier · code · step · date · technical | the figure's own shape and DOM context (`<code>`, `<style>`, ordered-list markers, API-doc pages) — identifier/code/step/technical are NOT figures |
| **about** | brand · product (entity) · customer quote · third party · example | brand name / aliases / "we, our" in the sentence; review blocks and JSON-LD Review; a named other organisation without the brand; "e.g., scenario, imagine, for companies…" |
| **as_of** | the date the statement speaks for | the page's own date (JSON-LD `datePublished`/`dateModified`, a date in the URL, the post date), an in-text "as of Q1 2026"; undated evergreen pages = now |
| **placement** | where and how often: hero / header / footer / body / legal / table + number of pages carrying the same sentence | the Document's field and section, and the text fingerprint across the crawl (copy detection) |
| **materiality** | P1 commitment · P2 customer-facing fact · P3 vanity | the SUBJECT's industry template: price, shipping threshold, return window, licences, coverage = commitments; users, partners = vanity |

**weight = materiality × attribution × currency × trust, with reach as the
tie-breaker** — stored with its reasons ("about a third party", "in a 2022
post", "on 236 pages, footer"). Three bands, like ClaimBuster:
- **material** → findings, the fact gate, change tasks;
- **immaterial** (about others, dated history, examples, vanity) → kept and
  visible under "not counted", never a finding, never blocks a draft;
- **not a figure** → hidden by rule, the count reported.

Every band is shown with its count; a reviewer can move a figure between
bands, and that ruling becomes a RULE (pattern + scope) that applies to every
later read — globally once the owner promotes it.

### 15.4 What changes in what is stored

- `kb_statements` gains `kind`, `currency`, `about`, `as_of`, `placement`,
  `claim_fp` (the sentence fingerprint across pages), `reach`, `weight`,
  `band`, `reasons`. `statements.summary` and `findings.compute` read only the
  material band, grouped by claim (one claim, N placements), largest reach
  first — "in 25+ countries ×236" heads the countries question.
- `kb_figure_rules` (new, global or per tenant): noise and attribution rules
  ("hsl(…)" = technical; "Step N" = step; reviews block = customer quote),
  each with who promoted it and what it matched — the "mark as noise" loop.
- `kb_vocabulary` (new, global or per tenant): unit word → subject → kind →
  materiality. The current built-in list moves here as global rows; a
  reviewer's term is per tenant until the owner promotes it (§14.3 item 2).
- `kb_templates` (new, data): per industry — e-commerce, B2B spec, venue,
  agency, regulated finance — the subjects, their materiality, the page types
  that are coverage-tier, the question per subject, and known-answer prompts
  for onboarding (§14.3 items 3–5).
- Source trust per page type, computed from QA decisions (`findings` decided
  "this page is wrong" vs "correct") — a column on the tier policy, reported
  on the trust panel.

### 15.5 What it is not

No model judges inside the app (owner direction, 2026-10-22). The axes are
rules; what the rules cannot decide stays `unknown` and is shown as such.
Claude, through MCP, may PROPOSE labels for the unknowns in bulk — they land
as proposals a reviewer accepts, exactly like harvested claims.

### 15.6 Build order (each with its guard, per §9)

1. **BUILT (2026-11-06)** — `kind` + the non-figure rules (identifiers, codes, steps, CSS, ratings) and
   money / percent as REAL figures — fixes the Baci 10%-vs-15% blind spot.
   `app/quantities.py` (one rule set for the site reader AND the draft gate):
   money with currency, percent, duration, rating, each given a subject only
   by the words around it (`RULES` — offer / pricing / policy / shipping /
   service / reputation subjects; a bare price stays the catalogue's). New
   `quantities` reader; `kind` + `currency` on every statement; $ never agrees
   with €. `account.NON_FACTS` gained named rules — identifier, code,
   technical, label, step, ui — counted per rule on the run card
   (`not_figures_by_rule`). Offer, pricing and policy subjects are P1.
   Guards: `a_discount_is_not_a_figure`, `the_gate_ignores_money_and_percentages`,
   `dollars_agree_with_euros`, `an_identifier_is_a_figure_to_explain`,
   `style_values_are_figures`. After deploy: "Re-read stored pages" applies it
   to every stored page with no crawl.
2. `about` + `as_of` + `claim_fp`/`reach`; findings and summary read the
   material band grouped by claim.
3. `kb_vocabulary` + `kb_figure_rules`, global with per-tenant overrides,
   with "promote to all companies" on the console.
4. `kb_templates` per industry, chosen at onboarding; tier keywords and
   questions come from it.
5. Source trust per page type from QA decisions.

Sources: Diffbot (data provenance, knowledge fusion) · Google Knowledge Vault
(KDD 2014) and Knowledge-Based Trust (VLDB 2015) · Dong, Berti-Équille,
Srivastava, "Integrating Conflicting Data: The Role of Source Dependence"
(PVLDB 2009); "Truth Discovery Algorithms: An Experimental Evaluation"
(arXiv 1409.6428) · ClaimBuster; CLEF CheckThat! 2018–2025 · CQE (EMNLP
2023); Quantulum; Microsoft Recognizers-Text · Boilerpipe; Trafilatura;
Web2Text (ECIR 2018) · Zyte AI extraction · Visualping, PageCrawl, Distill
noise-filtering docs.

## 16. One claim, every place it appears — claim groups (design, 2026-11-06, NOT BUILT)

Owner: *"Shouldn't we be aggregating claims and use the pages as references?
If they are duplicates then they just get added to a list of places the claim
was found … any repeating claims only show up once even if they are phrased
differently."* Then: *"research it thoroughly first."*

### 16.1 What Transak's 1,823 proposed claims actually are (measured)

| Kind of sameness | Count | What it needs |
|---|---|---|
| Same words on many pages | already ONE row each (fingerprint + "also seen on") | nothing new |
| Same meaning, different words | small: word-overlap grouping merges ~40–80; meaning-based matching will find more | merge as VARIANTS, every wording and page kept |
| Same pattern, different value ("Transak supports USDC on {Sui, Apechain, …}") | 104 claims in 17 families | ONE family item listing every value — never merged as duplicates (each value is its own fact) |
| Similar words, different number or scope ("25+ countries" vs "over 160 countries") | the coverage and licence disagreements | NEVER merged: a finding for Questions for QA |
| By source: blog/news/press 1,245 (68%), product & marketing 303, docs 128, help centre 75, legal 48, newsletter 24; only 782 name Transak at all | — | ORDER the queue by materiality and reach (§15 axes), dated and third-party material out of the default view |

Grouping alone takes the queue from ~1,823 to ~1,650–1,740 items; grouping
plus ordering puts ~550 in front of a reviewer first.

### 16.2 What the research says (and the decision each one drives)

- **Fixed similarity bands with a human middle.** Deployed claim-matching
  (Meedan's tipline work) auto-groups above cosine 0.95 and sends 0.88–0.95
  to people; 0.88 measured ~95% precise on a labelled sample (FACTors).
  Record linkage (Fellegi–Sunter, Splink) uses the same three-way split:
  link / possible link (clerical review) / no link. → **Three bands:**
  auto-merge, "same claim?" proposal for a reviewer, separate.
- **Embeddings do not see numbers or negation.** A sentence and its negation
  score as near-identical; cosine measures topical overlap, not truth
  conditions (HEROS; negation-benchmark work). Numeric mismatch is its own
  contradiction class in NLI typologies. → **Hard blocking rules before any
  similarity:** same numbers (normalised by the figure readers), same
  negation, same product and market scope — otherwise never the same claim.
  Same subject with a different number is routed to findings, not merged.
- **Connected components over-merge by chaining.** Single linkage joins two
  groups through one close pair; transitive closure of pairwise matches
  stitches unrelated claims together (clustering and entity-resolution
  literature). → **Join a group only if similar to its canonical claim
  (centroid), not to any one member.**
- **Keep every source record; the golden record is separate.** Entity
  resolution practice: group records, keep all of them, and build the
  canonical one by explicit SURVIVORSHIP rules with lineage back to each
  source. → **Canonical wording = the variant on the most authoritative page
  (legal > product > docs > help > blog), newest first; every variant and
  page kept** (a change must reach every wording).
- **Templates are database rows rendered into prose.** Wrapper-induction and
  template-detection work treats repeated page/sentence structures as
  generated from a structured source, and extracts the slot values. →
  **Pattern families are detected by masking the one slot that varies; the
  slot values become structured statements** (the coverage list), reviewed
  once as a family.
- **Queues are ordered by value, not arrival.** Moderation queues rank by
  predicted severity × reach (views) × review time; LinkedIn reports ~60%
  faster time-to-action from dynamic ordering. Measure queue depth,
  time-to-first-review of the most severe items, and the no-action rate — a
  high rate of rejections means thresholds are wrong, not reviewers slow.
  → **Order by materiality × reach (pages, later GSC impressions) ×
  authority; report those three queue metrics.**
- **Check the automatic merges by sampling.** Clerical review as stratified
  sampling by score decile reviewed ~7% of pairs instead of ~23% for the same
  confidence (IJPDS 2026). → **Audit a sample of auto-merges per score band
  each month; the measured precision moves the bands.**

### 16.3 The design

- `kb_claim_groups` (tenant-scoped): canonical claim id, kind (`variants` |
  `family`), slot pattern for families, member count, page count, max
  authority, materiality, created/updated, decided_by.
- `kb_claim_members`: group id, claim id, wording, page(s), similarity to the
  canonical, band (auto | proposed | confirmed | split), decided_by.
- Grouping runs after every harvest and re-read: block by numbers, negation
  and scope → embedding similarity to each group's canonical (one matrix
  product, `embed._matches`) → bands → families by slot masking.
- The claims queue shows GROUPS: one card per group, canonical wording, "found
  on N pages in M wordings", the values of a family; one decision applies to
  every member (approve, reject, demote to background), and any member can be
  split off. Ordered by materiality × reach × authority; blog history,
  third-party and dated claims behind a filter, counted.
- A change to an approved claim lists every member's page (M8 change tasks
  already work per page).
- Never deletes a claim; a split is recorded; every decision carries who and
  why (§7).

### 16.4 Build order (each with its guard)

1. Blocking rules + variant groups with the three bands; the queue shows
   groups. Guard: two claims with different numbers are never one group.
2. Pattern families with slot values → structured statements. Guard: "USDC
   on Sui" and "USDC on Apechain" are never merged as one claim.
3. Queue order by materiality × reach × authority, with the dated /
   third-party filter (uses §15 step 2's `about` and `as_of`, built together).
4. Monthly sample audit of auto-merges per band; queue metrics on the trust
   panel.

Sources: Claim2Vec (arXiv 2604.09812) · FACTors (arXiv 2505.09414) · Claim
Matching Beyond English (arXiv 2106.00853) · claim-detection survey (arXiv
2401.11969) · RETSim (arXiv 2311.17264) · Manku et al., near-duplicates for
web crawling (Google) · HEROS (arXiv 2306.05083) · negation-robust
representations (arXiv 2507.12782) · contradiction prototypes (arXiv
2310.14732) · Stanford IR book on complete-link clustering · entity
resolution and golden-record practice (Splink, MDM guides) · IJPDS
threshold and clerical-review sampling papers · LinkedIn engineering on
content-review prioritisation; QUEST queue simulation (arXiv 2103.16816) ·
Joint template detection and wrapper generation (Microsoft Research).

## 17. The claim record — who, what it is true of, as of when, what it rests on (BUILT 2026-11-06, branch only)

**Why.** Owner, 2026-11-06, on the Transak harvest: *"not only do these facts on
their own lack the context to have any significance, but a reviewer would have
no way of verifying, supporting or approving them"* — and the approved claim
feeds prompts. The audit of all 1,823 claims (§17.2) showed the §16 grouping and
the first context rules covered three of nine failure families.

### 17.1 Researched before built
| Need | Source | What we took |
|---|---|---|
| Claim + reference, approved once, retired | Pharma claims library (Veeva PromoMats) | a claim record with linked evidence |
| What evidence a claim needs | CAP Code 3.7; FTC reasonable basis (1984); FCA FG23/3; MiCA Art. 66 | evidence per KIND, held before approval |
| How scope is stored | Wikidata restrictive qualifiers | `scope`: as_of, market, jurisdiction, conditions… — a consumer must keep them |
| A fragment made to stand alone | Choi et al. 2021 (decontextualization) | `statement`, and **infeasible** as an honest outcome |
| Who / is it worth checking | ClaimBuster; Factcheck-GPT | `subject`: self / other / market; only self is approvable |
| Page dates | `htmldate` (fast mode, markup only) | replaces our hand-written date reader; ~0.8 accuracy → shown with its origin, correctable |
| Countries | `pycountry` | markets from country-page URLs and text |

### 17.2 The audit (Transak, 1,823 claims, 2026-11-06)
57% name no subject (740 on blog posts — ANZ, PYUSD, MiCA, Visa); 66% matched no
kind; 195 coverage figures with **17 different country counts** (18+ … 190+:
different products, different things counted, different years); 13% fragments;
268 "proves" glosses that overstate; 55 testimonials used as product fact;
55 dated items the event rule missed; 8 comparatives missed.

### 17.3 As built
* `app/claim_record.py` — vocabulary (self names + the account's **entities**
  with `attributes.match = {urls, words}`; products ARE entities), `derive`
  (code: date, read-at, market, jurisdiction, sandbox, subject when the account
  names itself / speaks as "we" / on its own product or legal page, entity by
  URL/words — never a pick between two), `set_record` (claude < reviewer;
  a reviewer's value is final), evidence (`link` checked to resolve, or the
  team's **statement of how it is counted**, with as-of and who; withdrawn is
  kept), `missing()` + `gate()` (per kind: regulatory→link + jurisdiction;
  comparative/superlative→link AND method; coverage→link or method + entity;
  relationship→confirmation ≤90 days; testimonial→consent; absolute→conditions;
  history and sandbox flagged), `qualifier_line` (what prompts carry).
* `app/claim_sheet.py` — the workbook: one sheet per entity + Brand-wide / Not
  assigned / Not about us + Entities; upload **Check** (writes nothing) /
  **Apply**; a claim on two rows with two entities becomes two claims; decisions
  approve (same gate) / reject / history / replace on site / remove from site
  (→ `change.create_wording`, one task per page — the list of places to edit).
* `claim_context` kinds: + comparative, regulatory, coverage; event catches
  "now live / now supports / gone live"; superlative and relationship tightened
  (no "only once", "first time", "integration paths").
* Gate in `kb.review_claim`, two switches per account (`claim_scope`):
  `record_required` blocks an incomplete RECORD; `evidence_required` also
  blocks missing PROOF. Owner, 2026-11-07: *"note proof but not require it…
  add proof after the approval process as a separate role"* — so proof is
  noted everywhere (card, workbook column, the prompt's `proof: pending | on
  file`) and Transak runs with the record required, proof noted. Both off by
  default; set in Review › Claims by entity.
* `kb.keep_as_history` — approved, status `history`, never selectable.
* Prompts: bundle claims carry `statement` + `true_only`; grounding renders
  "TRUE ONLY: … — never state it without these".
* MCP `propose_claim_record` — Claude proposes subject / entity / qualifiers /
  statement / infeasible; never approves; never overwrites a reviewer.
* Console: Review › **Claims by entity** (download/upload, counts, names,
  evidence switch, recompute on the worker); every queue card carries the
  record, what is missing, and the evidence form. Re-group now runs on the worker.
* Jobs `claim_records`; refresh after every harvest and reprocess.
* Suite `scripts/test_claim_record.py`; 9 sabotage guards, all caught.

### 17.3b Added 2026-11-07
* Entities carry a description and reference pages (Entities sheet columns
  7–8; `attributes.references`); an edited existing entity is updated.
* `entity_of`: one URL match outranks products merely named in the claim.
* Uploads RELINK claims — setting an entity changes that claim; only a
  second row with another entity (a split) makes a copy, and re-uploading
  the same file adds nothing (guard `attaching_a_claim_copies_it`).
* MCP: `get_entities`, `propose_entity` (proposed; same key updates),
  `propose_claim_records` (bulk ≤500, never over a reviewer),
  `recompute_claim_records` (queues on the worker).
* Reset group `scan` + Review › Claims by entity › Start over (keeps what
  people decided).

### 17.4 Not done / next
1. Transak: owner sets names + entities (workbook Entities sheet), turns
   evidence on; a Claude session runs `propose_claim_record` over the ~900
   undecided subjects; reviewers work the workbook.
2. Transak's lookup API (`/api/v2/lookup/countries`, `isAllowed`; fiat
   currencies with countries + payment methods) as the source of record for
   coverage — not yet called live (auth requirement contradicts itself in docs).
3. `proves` still reaches the bundle; it is a model gloss that overstates
   (§17.2) — drop it from prompts once statements exist.
4. Measure the kind rules from reviewer edits, as §16 measures grouping.
