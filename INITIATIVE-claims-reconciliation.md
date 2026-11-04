# INITIATIVE — claims reconciliation: one truth per fact, scoped, owned by QA

Owner, 2026-11-04: *"Is it possible for us to have a claims reconciliation
step? This applies for every brand — in the Transak example we will find pages
making different claims about coverage, licensing, etc. We can either declare a
specific page / document as the source of truth or reconcile once and have the
change update across all pages (if available to Claude, otherwise identify
exactly where the changes need to be made manually). My issue is when there are
seemingly contradicting facts on the brand vs entity level, i.e. some products
may be available in all markets while others are not … Before we build this
out please understand the problem thoroughly and identify examples across all
of our different brands. Then come up with the architecture that would allow a
Quality Assurance team member to control content quality / compliance and flag
inconsistencies."*

STATUS: design only. Nothing below is built. §1 is the problem, §2 the
evidence (each item says how it was verified), §3 what already exists, §4 the
architecture, §5 the phases, §6 open decisions.

**Engineer's build map: `BUILD-MAP-truth-pipeline.md`** — the process
invariants, the modular stage architecture (discover → fetch → parse →
extract plug-ins → account → compare → checks → change), every new table with
its tenant-first unique, per-stage specs and guards, and milestones M0–M9 with
acceptance tests on the real Baci and Transak cases. M0 (statements sweep,
no silent cuts, Site facts) is built on the branch.

---

## 1. The problem, precisely

The knowledge base today stores **claims** — a sentence, its evidence, where it
was read, optional situation tags, optional ONE entity it is true of. That
model has four holes that produce every example in §2:

1. **No notion of "the same fact".** Two claims about the same thing
   ("we ship to X") with different values are two unrelated rows. Nothing
   notices they disagree, because nothing knows they are about the same
   subject. Fingerprint dedup only merges identical sentences.
2. **Scope is one axis, and optional.** A claim is brand-wide or about one
   entity (`entity_key`). There is no market / region / jurisdiction / channel
   / customer-type / date-range dimension, so "available in the EU for product
   A but not product B" cannot be written, and a sentence true of one product
   but filed without an entity is silently asserted about all of them.
3. **No source of truth.** Every source (a page, a policy, the catalogue, an
   upload, the owner) is a peer. There is no way to say "the licences page is
   authoritative for licensing; anything else that disagrees is wrong".
4. **No loop back to where the words live.** When a fact is settled, nothing
   lists every page/product/ad/email that still states the old version, and
   nothing proposes the edit.

A ban list is not a substitute. It stops known-bad *phrases*; it cannot catch
a wrong *value* ("Italian porcelain" passes a list that bans "made in Italy";
"ships to Mexico" passes everything).

## 2. Evidence — real examples, every brand

Verified = read from the live system on 2026-11-04 (Shopify Admin API, the
gomehagent MCP `get_package`, Semrush). Expected = the class of conflict the
business model guarantees, not yet observed in data.

### Baci Milano (ecom, ~300 SKUs, signs/collections)
| # | Conflict | Level | Verified where |
|---|---|---|---|
| B1 | **Shipping Policy** says international = "Canada, Mexico, South America"; **Terms of Service §5.3** says "We currently ship to the United States and Canada." Two legal pages, one store. | brand × market | Shopify `shopPolicies` |
| B2 | Zodiac SEO meta descriptions say **"Italian porcelain coffee cup"** on every sign; the cups are produced in Bangladesh/China (customs entries, 16%/27% duty). Passes the ban list (which bans "made in Italy", "from Italy", "Italian-made") because the *value* is wrong, not the phrase. | entity (collection) × origin | Shopify product `seo.description` |
| B3 | Approved claims filed **brand-wide that are only true of one product**: "This is sold as a set of 6 pieces", "Set of 6 acrylic water glasses from the Aqua collection", "this piece is designed in Italy" — no `entity_key`, so selectable for any product. | scope error | MCP `get_package(baci)` |
| B4 | Ad copy "**10% off** with code FirstBaci"; the code gives **15%**. | offer × channel | Meta creatives + Shopify discount |
| B5 | Free shipping: policy says "may be available above a certain amount — details on the Site"; owner says $110 retail; ads say "free shipping on 2 cups". The real value lives in Shopify shipping settings — a *system* source of truth, not a page. | brand × offer | Shopify policy + owner |
| B6 | Availability by sign: Scorpio, Libra, Taurus at 0, Virgo at 2, while ads/collection copy say "every sign". | entity × time | Shopify inventory |
| B7 | Positioning "Italian design house" vs product pages written as Italian-made (the 2026-08 audit: ~110 banned phrases store-wide, 96 from one SEO template). | brand vs entity copy | code comment `compliance.py` |

### Eien Health (ecom supplements)
| # | Conflict | Level | Status |
|---|---|---|---|
| E1 | Regulated wording: ban list covers cure/treat/FDA approved, but a structure/function claim is legal only with the DSHEA disclaimer, per product. Ban lists cannot express "allowed IF disclaimer present". | entity × regulation | Expected (ban list verified) |
| E2 | Per-product benefit claims (GLP-1 Support vs Triple Power® Joint Support) must not cross products — same scope hole as B3. | entity | Verified claims are brand-level in `get_package(eien)` |
| E3 | Subscription terms / price on site vs Amazon vs emails. | channel | Expected |

### Coverings Etc (B2B surfaces)
| # | Conflict | Level | Status |
|---|---|---|---|
| C1 | Positioning says materials come "from our Italian manufacturing warehouse" — brand-wide origin, while the range spans products whose origin/certification differs (recycled content %, slip rating, frost/exterior suitability are per SKU). | brand vs entity spec | Verified positioning; specs expected |
| C2 | No ban list, 0 claims → the account is BLOCKED for drafting today. | — | Verified `get_package(coverings)` |
| C3 | Spec values repeated in PDFs, Shopify, Salesforce and quotes. | entity × source | Expected |

### Miami Ironside (local venue / district)
| # | Conflict | Level | Status |
|---|---|---|---|
| I1 | Facts about **tenants** (a designer's biography; the Bizzotto family story) filed as brand-wide Ironside claims — they are true of an entity, not the district. 7 of 35 claims brand-wide and untagged. | scope error | Verified `get_package(ironside)` |
| I2 | Third-party statistics (Ellen MacArthur 40% / 30%, COP30) need source + date and go stale. | external, time | Verified claims |
| I3 | Capacity, hours, rates differ per space; rates are banned in copy but still vary per space and date. | entity × time | Expected |

### MarketingThatWorks (agency)
| # | Conflict | Level | Status |
|---|---|---|---|
| A1 | Case-study numbers ("$6M → $20M in 18 months") restated on site, LinkedIn, decks — any edit must propagate. | brand × channel | Expected |
| A2 | Confidential client names must never appear (banned) — a *negative* truth. | brand | Verified ban list |

### Transak (crypto on/off-ramp — the owner's case)
| # | Conflict | Level | Status |
|---|---|---|---|
| T1 | The same facts are published across **transak.com, support.transak.com, docs.transak.com, global.transak.com and the blog**: "countries-and-crypto-supported", "payment-methods-fees-and-limits", "payment-methods-processing-time", "how-to-submit-kyc", "trust-notice", remittance, virtual-account payments. | brand × source | Verified page list (Semrush) |
| T2 | Coverage is a **matrix**, not a sentence: country × product (on-ramp / off-ramp / remittance / virtual account / NFT checkout) × payment method × asset × customer type (retail / partner). A product live in the US may not be in the UK. | entity × market | Expected (the business model guarantees it) |
| T3 | Licensing is **per jurisdiction and per legal entity** (registration numbers, regulator, effective date); legal pages are binding. | market × legal | Expected |
| T4 | Fees and limits change over time and differ by method and KYC tier. | entity × time | Expected |
| T5 | 0 ban list, 1 claim → BLOCKED for drafting. | — | Verified |

**What the examples have in common:** every conflict is a *subject* (shipping
destinations, origin, set size, discount %, availability, licence) with a
*value* that depends on a *scope* (which product, which market, which channel,
which date). The fix is a model of subjects and scoped values, not more rules
about sentences.

## 3. What already exists (anchors) — and what it cannot do

**Reuse, do not rebuild:**
- **Provenance + per-field conflicts** — `provenance.may_write` / `apply_fields`
  (`provenance.py:169-203`, `:308-340`): "approved is final"; a machine
  source that disagrees records a `KbConflict` (`db.py:2314`) per row × field,
  shown as **Review › Conflicts / "Sources disagree"** (`admin_ui.py:6283`,
  `:8417-8455`), resolved Keep ours / Take theirs (`web.py:9096`).
  Precedence is by origin KIND only; `store_sync` owns price + availability.
- **Scope hierarchy** — `KbEntity.parent_keys` groups + `kb.ancestors()`
  (`kb.py:2684`); `claims()` ranks exact > group > brand (`scope_depth`,
  `kb.py:2708`). `kb.scope_conflicts()` (`kb.py:2800`) already pairs claims at
  different depths sharing a tag — computed, JSON-only
  (`/admin/scope_conflicts`), no UI. `kb.scope_unconfirmed()` (`:4460`) flags
  machine rows whose scope was never decided.
- **The one live-vs-approved comparison** — `catalog_sync.py:305-330`: a
  Shopify product's name/price/description against the approved entity,
  disagreements become `KbConflict`. The pattern §4 generalises.
- **Legal = binding** — `kb.is_legal_claim` / `legal_claims`, injected into
  `get_package` (built 2026-11-04). Advisory in the prompt, not enforced.
- **Write-back executors** — `seo_update` (`approvals.py:980` → Shopify
  `body_html` + SEO meta, WordPress `content` + excerpt), `seo_article_revision`,
  `gbp_listing_fix`; guarded by `seo_guard` (ban list) before any live write.
- **Near-duplicates** — `provenance.near_duplicates` (0.65 Jaccard) shows
  "1200 vs 1250 orders" side by side, proposals only.

**The gaps the examples fall into:**
- No market / region / jurisdiction / channel / date on any KB row;
  `KbEntity.availability` and `price` are single global values.
- `KbConflict` is one row × one field — it cannot hold "page A vs page B" or
  rank sources; claims bypass `apply_fields`, so claim-vs-claim disagreement is
  never recorded. `status="conflicted"` exists and nothing sets it.
- Nothing compares a live page or a draft against approved facts for a
  different VALUE: `compliance.scan` = banned phrases; `validator.check` =
  citation present + bans + entity available; `claim_trace` = support, not
  contradiction.
- No per-URL authority (`HarvestedPage` = url, hash, count).
- No index from a fact to the pages/fields that state it, so nothing can turn a
  resolution into `seo_update` approvals.
- **No QA identity**: `User.role` is owner|client|freelancer; the console has
  ONE credential (`APPROVAL_SECRET`), `approved_by` is mostly blank and
  `KbConflict` has no `resolved_by`. An auditable QA role needs per-user
  console logins first.

Docs that already set the rules this must keep: BUILD-STATE.md:2855
("Conflicts are flagged, never resolved" by code), DEFECTS.md:2593 (brand vs
product scope, the GLP-1 non-sequitur), DEFECTS.md:815 (blank `entity_key`
ambiguous), WALKTHROUGH-PROMPT.md:170 ("Generators propose; they never
populate"), RUNBOOK.md:318.

## 4. Architecture

### 4.1 The model — subjects, scoped values, sources with authority

Three new concepts, layered on the existing claims (claims stay; they become
*statements of* a fact rather than the fact itself).

**Fact** (`kb_facts`) — one subject the brand can be right or wrong about.
`tenant`, `subject` (a stable key: `shipping.destinations`,
`product.origin`, `offer.first_order_discount`, `coverage.onramp`,
`licence.registration`), `kind` (`enum` | `number` | `boolean` | `text` |
`list`), `unit`, `criticality` (`legal` | `regulated` | `commercial` |
`descriptive`), `owner` (who signs it off). Subjects come from a per-business-
model template (§4.6) plus whatever QA adds.

**Fact value** (`kb_fact_values`) — the truth, per scope.
`fact_id`, `value`, and a **scope** — a small set of named dimensions, each
optional (blank = "all"):
- `entity` — product / collection / venue / service (existing `KbEntity`
  keys, and their groups, so "all Zodiac cups" is one scope)
- `market` — country / region / jurisdiction (ISO codes + named groups:
  `EU`, `LATAM`)
- `channel` — website, Amazon, wholesale, email, ads
- `audience` — retail / partner / trade
- `valid_from` / `valid_to` — so a fee change or a seasonal offer is a dated
  value, not an overwrite
plus `status` (`proposed` | `approved` | `retired`), `approved_by`,
`authority_source_id`, `evidence`.

**Resolution rule (the brand-vs-entity answer):** the most specific matching
scope wins — exactly like CSS specificity. `shipping.destinations` = {US, CA}
at brand scope; `coverage.offramp` = {not available} for market `GB`, product
`offramp` overrides the brand-wide "available in 150+ countries". A
contradiction is only a contradiction when two approved values claim the
**same** scope. Different scopes saying different things is the design, not
a conflict — which is what "some products are available in all markets while
others are not" needs.

**Source** (extends today's harvested pages + content sources) — every place a
statement can live: a URL, a policy, a PDF/upload, a system (Shopify shipping
settings, the discount table, inventory), the owner. Each source carries an
**authority** per subject:
- `canonical` — the source of truth for these subjects (the licences page for
  `licence.*`; Shopify inventory for `availability`; the shipping settings for
  `shipping.free_threshold`). A canonical source *sets* the value.
- `binding` — legal pages (already marked by `kb.is_legal_claim`): may not be
  contradicted; disagreement with canonical is a P1 flag, never auto-resolved.
- `derived` — marketing pages, product copy, ads, emails, blog: must *agree*;
  they never set truth.

### 4.2 The pipeline

```
harvest/sync ──► statements (claims, as today, + subject & scope extracted)
                      │
                      ▼
               MATCH to a fact subject  (model proposes; QA confirms new subjects)
                      │
                      ▼
               COMPARE with the fact's approved value at the most specific scope
                      │
     ┌────────────────┼──────────────────────────────┐
     ▼                ▼                              ▼
  agrees          no value yet                  disagrees
  (corroborate)   (propose value; canonical     (FINDING: subject, scope,
                   source → auto-propose)        source A vs value, severity)
                                                     │
                                                     ▼
                                     QA RECONCILIATION QUEUE (§4.4)
                                                     │
                       decide: which value, at which scope, from which source
                                                     │
                                                     ▼
                         PROPAGATION: every source that states the old value
                         → an edit proposal (if writable) or a manual task
```

Matching and scope extraction are model work (they need reading), but every
**decision** is deterministic or human: comparing values is code; choosing the
truth is QA; writing to a site goes through the existing approval queue.

### 4.3 Findings — what QA is shown

Each finding = subject, scope, the conflicting statements with their sources
and authority, the current approved value (if any), severity, and a proposed
resolution. Severity is computed, not guessed:
- **P1** — involves a `binding` or `canonical` source, or `criticality` legal /
  regulated (B1, T3, E1).
- **P2** — commercial value wrong in a live channel (B4 discount, B5 shipping,
  B6 availability, T4 fees).
- **P3** — descriptive/scope hygiene (B3, I1 mis-scoped claims).

Kinds of finding: `contradiction` (same scope, different values),
`scope_error` (a statement asserted brand-wide that is only true of an entity —
B3, I1), `stale` (past `valid_to`, or the canonical system changed — B6),
`unsupported` (a live page asserts a subject with no approved value),
`banned_value` (value contradicts a binding/regulated fact even though no
banned phrase appears — B2).

### 4.4 The QA workspace

A **Reconcile** tab per account (and an all-accounts inbox), owned by a `qa`
role (new value of `User.role`; can approve facts and findings, cannot
publish):
1. **Truth sheet** — every subject × scope with its approved value, source,
   approver, date. The thing QA maintains. Exportable/importable as CSV so it
   can be edited in a spreadsheet or by a Claude session (via MCP, below).
2. **Findings queue** — sorted by severity; each with *Keep A* / *Keep B* /
   *Both, at different scopes* (the brand-vs-entity resolution: split the
   value and set each scope) / *Neither — set value* / *Not the same subject*.
3. **Source authority** — declare a page/document/system canonical for a set
   of subjects ("support article 7846056 is canonical for `coverage.*`").
4. **Propagation board** — after a decision: every place still stating the old
   value, with status (proposed edit → approved → published, or manual task →
   done → re-verified on the next harvest).

Every QA decision is logged (who, when, before/after) — the audit trail a
compliance review needs.

### 4.5 Propagation — "update across all pages"

For each source stating a superseded value:
- **Writable through an existing executor** (Shopify product description /
  SEO fields, Shopify pages, WordPress posts) → generate the minimal edit
  (sentence-level replace), file it as an approval of the existing kinds;
  nothing publishes without the owner/QA tap.
- **Not writable** (Intercom/Zendesk help centres, docs sites, PDFs, Amazon,
  a partner's page) → a manual task with the exact URL, the exact sentence,
  and the replacement text.
- **Our own outputs** (drafts in the queue, live ads, scheduled emails) →
  re-run `check`; a draft contradicting an approved fact is blocked.
The next harvest re-reads those pages; the finding closes only when the live
page agrees (closed loop, not "marked done").

### 4.6 Subject templates per business model

Seeded so QA starts with structure, not a blank page:
- **ecom_inventory / ecom_dtc** (Baci, Eien): origin, materials, dimensions,
  set size, care, shipping destinations, shipping times, free-shipping
  threshold, returns window, discount terms, availability, regulated claims
  (Eien: structure/function + disclaimer).
- **b2b_spec** (Coverings, Transak): spec values per SKU, certifications,
  lead times, MOQ, regions served; Transak: coverage matrix, licences per
  jurisdiction, fees/limits per method and tier, KYC requirements, supported
  assets.
- **local_venue** (Ironside): capacity per space, hours, amenities, tenant
  facts (as entities), accessibility.
- **digital_products / agency**: case-study figures, client confidentiality,
  service scope.

### 4.7 Where it plugs into what exists

- **Scope** reuses `KbEntity` + `parent_keys` groups and `ancestors()` for the
  entity dimension; market / channel / audience / dates are the new
  dimensions. Specificity = the existing `scope_depth` extended.
- **Findings** generalise `KbConflict`: add `kind`, `subject`, `scope`,
  `severity`, the competing statements (source + authority) and `resolved_by`;
  the existing Review › Conflicts cards become the findings queue rather than a
  second queue. `scope_conflicts()` output becomes `scope_error` findings.
- **Systems as sources** follow `catalog_sync`'s pattern (compare, never
  overwrite approved, record the disagreement).
- **Propagation** files `seo_update` / `seo_article_revision` /
  `gbp_listing_fix` approvals — no new executor; `seo_guard` still runs.
- **QA identity** needs per-user console logins (Phase 0 below) so every
  decision has a `resolved_by`.

- Drafting: `get_package` serves the resolved truth for the scope being
  written about (product + market + channel), plus every `binding` value —
  instead of a flat claim list. `check` gains a deterministic
  `contradicts_fact` gate for numbers, lists and enums.
- MCP (Claude UI): `get_truth(tenant, subject?, scope?)`,
  `get_findings(tenant, severity?)` and CSV export of both; writes stay in the
  console (QA decisions are human acts, like approvals today).
- Harvest: unchanged reading; adds subject+scope extraction on each
  statement; legal pages already read first and marked binding.
- Systems as sources: Shopify inventory, shipping settings, discounts and
  Meta creatives are read as statements too, so B4/B5/B6 are caught without
  waiting for a page to repeat them.

### 4.8 Every existing path, in this shape

Owner, 2026-11-04: *"make sure that the harvest / compliance check etc match
this shape."* Today each path has its own idea of a fact and its own judge. In
the new shape there are exactly **three shared parts**, and every path either
PRODUCES statements or CHECKS content through them:

1. **`Statement`** — the one record every reader emits:
   `tenant, text, subject?, value?, scope{entity, market, channel, audience,
   valid_from, valid_to}, source{kind: page|document|system|mail|human|agent,
   ref (url / file / system key), field (body, seo_description, policy…),
   authority: canonical|binding|derived}, origin, observed_at, content_hash`.
   A claim becomes a Statement that a person approved; a sentence on a live
   page is a Statement nobody has to approve to be checked.
2. **`truth.resolve(tenant, subject, scope)`** — the approved value at the
   most specific matching scope (entity → its groups → brand, × market ×
   channel × date), with the source that set it. The ONLY place truth is read.
3. **`truth.compare(statement) → Finding | None`** — deterministic: same
   subject and scope, different value = `contradiction`; asserted wider than
   the truth's scope = `scope_error`; no approved value = `unsupported`;
   past `valid_to` = `stale`; value forbidden by a binding/regulated fact =
   `banned_value`. The ONLY judge. Every check below calls it, so a harvest, a
   draft and a customer reply can never disagree about what is true.

Plus one index, **`statement_locations`** (fact/statement ↔ url, field,
sentence, observed_at, hash): where each value is stated. This is what makes
propagation (§4.5) and the closed loop possible, and it is written by the
readers below as a side effect of reading.

**Producers — must emit Statements with subject + scope + authority:**

| Path (today) | Today it… | In the new shape it… |
|---|---|---|
| `harvest.harvest` (website + landing pages + subdomains) | proposes claims; legal pages read first, marked by URL | emits Statements per sentence with **scope from the page** (product URL → entity, locale path `/en-gb/` or `?country=` → market, help-centre/docs → channel), **authority from the source** (legal → binding; a source QA declared canonical → canonical; else derived); writes `statement_locations`; calls `compare` on every Statement so the crawl itself raises findings; re-reads pages with OPEN findings first so a fix is verified on the next run |
| `catalog_sync.sync_shopify` | name/price/description vs approved entity → `KbConflict`; availability overwritten | is a **canonical system source** for price, availability, variants — per Shopify Market where the store has markets (so availability gets its market dimension from the system, not from prose); disagreements become findings in the same queue |
| *new* system readers (shipping settings, discount codes, inventory, Meta live creatives) | — (B4, B5, B6 were found by hand) | canonical Statements for `shipping.*`, `offer.*`, `availability`; ad text read as derived Statements (channel = ads) |
| `email_harvest` (sent mail) | proposes claims from what the brand wrote | Statements with channel = email, authority = derived — what was PROMISED to customers is checked, never treated as truth |
| `propose.py` (agent) / `kb_seed` / console add-claim (`web.py:4810`, `:5136`) / bulk import (`kb.py:3823`, `:4967`) | add claims, scope optional | must state subject + scope (or explicitly "brand-wide"); the console form gains scope pickers (entity/group, market, channel, dates); seeded subjects come from the §4.6 templates |
| uploads (PDF spec sheets, licences, policies) | via `inbox_attachment` / KB upload | a document source; QA can declare it **canonical** for subjects ("this licence PDF is canonical for `licence.*` in GB") |

**Checks — must call `truth.compare`, then their own rules:**

| Check (today) | Today it verifies… | In the new shape it… |
|---|---|---|
| `compliance.scan` (live site, scheduled) | banned PHRASES only; legal pages skipped | becomes the **live-site truth scan**: every page's Statements through `compare` (findings with severity), THEN the ban list. Legal pages are INCLUDED in the truth scan (they are where binding values live — B1 is two legal pages disagreeing) and still excluded from the ban-phrase scan only |
| `validator.check` / MCP `check` (drafts) | ban list, a citation exists, entity available | adds the **`contradicts_fact` gate**: each draft sentence that states a subject is compared at the draft's scope (product + market + channel); a contradiction or `banned_value` blocks, `unsupported` warns |
| `triage._apply_guards` / `responder` / MCP `inbox_draft` (customer replies) | ban list, guards | same gate on replies — a reply promising a 30-day return when the binding policy says 7 is blocked before it is drafted |
| `seo_guard.check` (before any live-site write) | ban list on prose fields | same gate on the NEW text, so a propagation edit or an SEO edit can never write a value that contradicts truth |
| `claim_trace.annotate` (grounding reading) | marks sentences supported by approved claims | also marks sentences that **contradict** — the reading shows red, not just "unsupported" |
| `kb.scope_conflicts` / `label_conflicts` (JSON only) | pairs at different depths / tags | feed `scope_error` findings into the queue (no separate JSON-only surface) |
| `provenance.apply_fields` / `KbConflict` | per-row field disagreements | the findings table generalises it; existing conflicts migrate in |

**Readers of truth — must read through `resolve`:**
- `get_package` serves resolved values for the scope being written (plus every
  binding value), not a flat claim list.
- `get_claims` stays the statement register; a new `get_truth` (+ CSV) is the
  truth sheet; `get_findings` (+ CSV) the queue — all through MCP for Claude.
- `voice` keeps reading the website only and never legal pages (unchanged —
  voice is not a fact).

**What this changes in the code built today (2026-11-04):** the harvest's
`is_legal_url` marking becomes the `binding` authority on the page's source;
`kb.is_legal_claim` / `legal_claims` become `resolve(..., authority=binding)`;
`get_claims`' `legal` column becomes `authority`. No rework of the crawl
memory, legal-first ordering or CSV export — they carry over as they are.

## 5. Phases (each ends with a QA/owner check; nothing publishes without a tap)

0. **QA identity** — per-user console logins and a `qa` role (today one shared
   `APPROVAL_SECRET`); `approved_by` / `resolved_by` filled from the session.
1. **Truth model** — `kb_facts`, `kb_fact_values` with scope + specificity
   resolution, source authority; subject templates per business model;
   tenant-scoped like every table (`tenant` column, per-tenant uniques,
   `db.tenant_filter`). Truth-sheet CSV export/import. *Done when* Baci B1,
   B5 and Transak T2 can be written down correctly, including "product X not
   in market Y" overriding a brand-wide value.
2. **Statements → subjects** — extend the harvest and the catalogue/system
   syncs to tag each statement with a subject and scope (model proposes,
   unknown subjects queued for QA). Backfill existing claims. *Done when*
   B3 and I1 surface as `scope_error` from data already on file.
3. **Findings** — deterministic comparison + severity; the Reconcile tab
   queue; `qa` role. *Done when* B1 (two legal pages disagree) shows as P1
   and B2 ("Italian porcelain") as `banned_value` without a ban-list edit.
4. **Decisions + audit** — keep / split by scope / set value / not-same-
   subject; every decision logged.
5. **Propagation** — edits through existing Shopify/WordPress approval kinds,
   manual tasks for everything else, closed on re-harvest.
6. **Drafting uses truth** — `get_package` serves resolved values for the
   scope; `check` blocks a draft that contradicts an approved fact.
7. **Claude UI** — MCP `get_truth`, `get_findings`, CSV for both.

Suggested first account: **Baci** (most verified conflicts, writable
Shopify), then **Transak** (the matrix case), then the rest.

## 6. Decisions

Owner, 2026-11-04: *"I like your suggestions"* — taken as the defaults below.
1 and 4 had no single suggestion, so the conservative reading is recorded;
change them here if that is wrong.

| # | Decision | Taken as |
|---|---|---|
| 1 | Who is QA | The owner for now; Phase 0 still builds per-user logins + a `qa` role so a QA hire slots in with an audit trail |
| 2 | Default authority when nothing is canonical | legal page (binding) > system (Shopify settings, inventory, discounts) > owner-approved claim > marketing page / ad / email |
| 3 | Markets | ISO country codes + named groups (EU, LATAM, "all supported") |
| 4 | Live-site edits | Every live-site edit still needs the owner's tap; QA approves the *truth*, the owner approves the *publish* |
| 5 | Pages we cannot write (Transak help centre/docs) | Manual task lists with exact URL, sentence and replacement; connect their CMS later |

### The questions as originally asked

1. **Who is QA?** A separate login with a `qa` role, or the owner for now?
2. **Default authority when nothing is declared canonical:** legal page >
   system (Shopify settings/inventory) > owner-approved claim > marketing page?
3. **Markets vocabulary:** ISO country codes plus named groups (EU, LATAM,
   "all supported") — agreed?
4. **Auto-propagation:** may QA approve an edit to a live product page
   directly, or does every live-site edit still need the owner's tap?
5. **Help centres we cannot write to** (Transak support/docs): manual task
   lists only, or should we connect their CMS (Intercom/GitBook) later?
