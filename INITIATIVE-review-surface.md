# INITIATIVE — the review surface: see what the AI did, decide one thing at a time

Owner, 2026-11-07: *"the current interface and workflow for people to review
claims isn't clear — it is a lot of redundant fields and doesn't allow a
reviewer to easily review. As it stands we are actually increasing the barrier
for me to provide value to Transak. We need to be able to clearly understand
what AI is crawling and determining, what users are finding, what gaps need
filling."*

This document is the audit (§1, every number measured on 2026-11-07 against
production or the code), the research (§2), and the architecture (§3–§5).
Nothing here is built. Read §1 before touching `admin_ui.py`'s Review tab.

---

## 1. The audit — what is wrong, measured

### 1.1 The claim card asks for everything at once
One proposed claim on Review › Claims renders **22 editable fields, 9 buttons
and 6 separate forms** (rendered and counted, `admin_ui._card` +
`_record_block`). Inside one card:

| Duplicated | The two copies |
|---|---|
| What it is true of | "True of — blank means the whole brand" (`entity_key`) **and** "True of — pick one or several" (claim record) |
| Evidence | "Evidence — the number or the proof" (free text on the claim) **and** the evidence list + form (link / team statement) |
| The sentence | "Claim" (editable verbatim text) **and** "Statement — one sentence that stands alone" |
| What it means | "What it proves — written by the model" (a gloss the 2026-11-06 audit found overstates in 268 claims) |

Plus five situation-tag checkboxes, "Not proof — file as background", and three
bulk-destructive buttons ("Clear all proposals", "Show me what it would
delete", "Clear and re-harvest") rendered in the same area as the per-claim
buttons. Each block saves separately: **"Save record" does not save the claim
edits above it, and "Save & approve" does not save the record** — editing both
and pressing one silently drops the other.

### 1.2 One claim, seven places
Review has **14 sub-tabs** (`admin_ui.REVIEW_SUBS`). The same underlying claim
or figure surfaces in: Claims (the queue), Claims by entity (workbook +
counts), Inconsistent wording (groups), Site facts (figures by subject),
Questions for QA (findings), Conflicts, Changes. There is no single place that
shows one claim's whole state — found where, what the AI decided, what a person
decided, what is missing, what it changed on the site.

### 1.3 The queue has no order and no reason
Transak's queue is **1,871 proposed claims**, paged in id order. A licence
claim on a legal page and a sentence about ANZ Bank's stablecoin sit side by
side with the same weight. No card says *why* it is in the queue or *what the
reviewer is being asked*.

### 1.4 What the AI did is invisible
- The crawl's own account — pages discovered, read, skipped, partly read, what
  the model extracted per page, what the guards dropped, what it cost — exists
  only in a job's result blob. The console shows "last run" and a count.
- Derived values carry their origin (`scope_origin`: page / url / rule /
  vocabulary / claude / reviewer) but it renders as a small chip, and a
  code-made attachment looks like a reviewer's.
- Accuracy is measured for **one** automated step (claim grouping,
  `claim_groups.accuracy`). Subject, entity, kind and date derivation are not
  measured at all. The one hand-measurement made (2026-11-07, 100 labelled
  claims): today's entity attachment is **73% precise, 34% recall** — and
  nothing in the console says so.

### 1.5 What reviewers find is not collected
Known answers: **0**. Audits: **0** (3 needed for a recall figure). A
reviewer's correction (changing an entity, rewriting a statement, rejecting
with a reason) is stored on the row and nowhere else: it does not feed any
accuracy figure, any list of "what people found", or the next harvest.

### 1.6 The gaps are scattered
Transak today (MCP, 2026-11-07):

| Gap | Count | Where it shows now |
|---|---|---|
| Claims whose subject is undecided | 935 of 1,872 | nowhere as a list |
| Claims with no standalone statement | 1,872 | per card only |
| Claims with no entity | 1,225 | Claims by entity (count) |
| Claims kept as dated history | 174 | nowhere |
| Figures no reader understood | 3,510 | Checks & trust |
| Pages that need a browser | 53 | Checks & trust |
| Open findings (1 P1: licence count) | 21 | Questions for QA |
| Claims with no proof | ~all | per card only |

No one list says: here is what is missing, how much, who owns it, and the one
action that closes it.

### 1.7 Roles are fused
One card asks one person to decide truth, scope, wording, evidence, tags and
background status. The owner has already split one role off: *"note proof but
not require it … add proof after the approval process as a separate role"*
(2026-11-07).

### 1.8 Two workflows that disagree
The workbook (`claim_sheet`) and the console card ask different questions with
different fields; a reviewer who learns one does not know the other.

---

## 2. Research — how review tools that work are built

| Finding | Source | What we take |
|---|---|---|
| Reduce each annotation to one decision (accept / reject / ignore); the model proposes, the person judges; smaller decisions give a tighter loop | Prodigy docs (vendor claim, not a study) | **One question per card**, the AI's proposal pre-filled |
| Judging a proposed label *and* the text at once adds load; split it | Prodigy forum (anecdotal) | The proposal is shown separately from the evidence, and decided in one press |
| Show only what is relevant to the current step; "one thing per page" (GOV.UK); never hide required or legal information | NN/g, *4 principles to reduce cognitive load* | Fields open only when the reviewer chooses **Fix**; legal and risk facts are always visible |
| Route by confidence: auto-pass high, review borderline, escalate low; thresholds per field, revisited | HITL practice write-ups (vendor/practitioner) | Route by **measured** method precision and by claim risk |
| Every human decision is a first-class event: who, what, when — the audit trail compliance needs and how you tell whether model or reviewer was wrong | same | A **decision log**; accuracy per method is computed from it |
| Match review mode to consequence: approve-before for high stakes, review-after for moderate, exception-only for mature high-volume | same | Regulatory/coverage/superlative claims: approve-before; the rest can batch |
| A claims library links each approved claim to its references; a readiness check runs **before** routing to reviewers; review is tiered | Veeva PromoMats (vendor material) | Pre-review checks fill the record before a person sees it; separate tiers (truth → proof → site change) |
| Unassigned queues rot; give every queue an owner and age | HITL practice | Each gap has an owner and an age |

Caveats: the Prodigy, Veeva and HITL sources are vendor or practitioner
material, not controlled studies. NN/g is the only research-grade source here.
The measurement in §1.4 is ours and its labels are Claude's until the owner
checks them (`transak-entity-sample-100.xlsx`).

---

## 3. The architecture

Four layers. The bottom two make the AI legible; the top two give people one
place and one question at a time. **No new truth tables** — every layer reads
the tables that exist (`kb_claims`, `kb_statements`, `findings`,
`kb_claim_groups`, `kb_conflicts`, `unaccounted_numbers`, `page_snapshots`,
`harvested_pages`, `usage`).

```
 ┌──────────────────────────────────────────────────────────────────────┐
 │ D  SURFACES   Overview · Review queue · Library · Changes            │
 │               (console, workbook and MCP show the SAME items)        │
 ├──────────────────────────────────────────────────────────────────────┤
 │ C  DECISION LOG   every accept / fix / reject as an event            │
 │                   → precision per AI method → what may auto-pass     │
 ├──────────────────────────────────────────────────────────────────────┤
 │ B  REVIEW ITEMS   one derived queue of "a decision someone must      │
 │                   make", each with ONE question, the AI's proposal,  │
 │                   its reason, its risk, its evidence                 │
 ├──────────────────────────────────────────────────────────────────────┤
 │ A  STAGE REPORTS  crawl → read → record → group → propose → review → │
 │                   change; each run says what went in, what came out, │
 │                   what was dropped and why, and what it cost         │
 └──────────────────────────────────────────────────────────────────────┘
```

### 3.A Stage reports — "what the AI is crawling and determining"
Each pipeline stage writes one report per run (one new table,
`stage_reports`: tenant, stage, run_id, started/finished, `in`, `out`,
`dropped` {reason: n}, `cost_usd`, `method_version`):

| Stage | In → out | Dropped, by reason |
|---|---|---|
| crawl | discovered → fetched → stored | dead, duplicate, needs browser, blocked |
| read (model) | pages → claims proposed | banned phrase, not verbatim, partly read |
| read (figures) | pages → figures | not understood |
| record | claims → subject / entity / market / date derived | ambiguous (left for a person) |
| group | claims → groups | below threshold |
| propose (Claude, MCP) | claims → proposals | infeasible |
| review | items → decided | — |
| change | decisions → page tasks → verified | — |

The Overview renders these as one funnel per account, with cost from `usage`.

### 3.B Review items — one queue, one question each
A pure function `review.items(tenant)` derives, never stores, every decision
outstanding. Item types and the single question each asks:

| Item | The question | One-press answers |
|---|---|---|
| claim · scope | "Is this Transak's claim, about **On-ramp**?" (the AI's proposal) | Yes · Fix · Not Transak's · Not a claim |
| claim · truth | "Approve: *As of Mar 2026, Transak's off-ramp covers 18+ countries.*" | Approve · Fix wording · History · Reject |
| group · inconsistency | "The site says 18+ and 25+ for off-ramp countries. Which is right?" | pick one · both (different scope) · remove |
| figure · not understood | "What is '5.7M' on these 12 pages?" | label · noise |
| finding · question | "How many licences do we say we hold?" (P1) | set answer |
| page · unread | "53 pages need a browser" | render · ignore |
| proof (separate role) | "What supports this approved claim?" | link · team statement |

Each item carries: the **evidence** (the sentence highlighted in its paragraph,
page title, date, link), the **AI's proposal with its reason** ("on /off-ramp;
names 'countries'"), the **method and its measured precision** ("entity by page
address — 73% on the sample"), and a **risk** score (kind: regulatory /
coverage / superlative / comparative rank highest; legal page; reach = pages it
appears on; P-level of any finding it touches).

Ordering: risk × reach, then age. Batching: items in one claim group, or one
template family, are decided together.

### 3.C Decision log — what people find, and how good the AI is
One new table, `review_events`: tenant, item type, item id, field, AI value,
AI method, human value, decision, reason, who, when. Written by every decision
path (console, workbook, MCP proposals marked as proposals). It yields:

- **What reviewers found**: corrections, rejections and their reasons, by
  entity and by kind, on the Overview.
- **Precision per method** (Wilson 95% lower bound, as `claim_groups`
  already does): a method's proposals may pre-fill; it may auto-pass only
  above 99%.
- The audit trail compliance asks for.

### 3.D Surfaces — four, replacing the claim-related sub-tabs
1. **Overview** — the account at a glance: the stage funnel (3.A); AI vs
   person share of decisions; accuracy per method; the **gaps list** (§1.6
   table, live) with an owner and one button each; what reviewers found this
   week; cost.
2. **Review** — the queue (3.B). The card: evidence on the left, the AI's
   proposal and reason on the right, 3–4 buttons. **Fix** opens only the
   field being fixed. Keyboard: accept / fix / reject / next. Filters: item
   type, entity, risk. One save per decision, always.
3. **Library** — what prompts receive: approved claims by entity, each as its
   statement + qualifiers + proof state; the proof queue for the proof role;
   the workbook export (same items, same columns as the card).
4. **Changes** — site edits and their verification (exists; kept).

Retired as separate places (their content becomes item types or Overview
panels): Claims, Claims by entity, Inconsistent wording, Site facts, Questions
for QA, Conflicts, Checks & trust. Removed from the review card: the duplicate
entity selector, the free-text evidence field, the editable verbatim claim
(the site's words are evidence, not an input), "what it proves", situation
tags (derived; editable in Library), the bulk-destructive buttons (moved to
Overview › account actions, behind a confirmation).

### 3.E Roles
| Role | Decides | Surface |
|---|---|---|
| Reviewer | scope and truth of claims; groups; findings | Review |
| Proof | evidence for approved claims | Library › proof |
| Site editor | page changes | Changes |
| Account owner | names, entities, switches, rescans | Overview › settings |

### 3.F MCP (the data layer, unchanged in spirit)
`get_overview` (stage funnel, gaps, accuracy) and `get_review_items` (the same
items, read-only) so a Claude session can analyse and propose; Claude never
decides an item.

---

## 4. Phases — each one shippable, each one removes something

| Phase | Builds | Removes | Done when |
|---|---|---|---|
| 0 | Freeze: no new field on the claim card | — | — |
| 1 | Stage reports for crawl + read + record; **Overview** with funnel, gaps list, cost | "last run" counters scattered on 4 tabs | the owner can say, for Transak, what was read, found, dropped and missing, from one page |
| 2 | `review_events`; every decision path writes it; precision per method on Overview | — | each automated step shows a measured precision |
| 3 | `review.items` + the new **Review** card (scope and truth items) | duplicate fields; Claims + Claims by entity sub-tabs | a claim is decided in one press; a test proves no edit can be lost between saves |
| 4 | Groups, figures, findings, unread pages as item types | Inconsistent wording, Site facts, Questions for QA, Conflicts, Checks & trust sub-tabs | Review has one queue |
| 5 | Claude proposal pass over MCP feeding items with reasons; routing by measured precision | — | proposals show their reason and their method's precision |
| 6 | **Library** + proof role queue; workbook = item columns | divergent workbook columns | prompts read only Library |

Every phase ships with its tests, its sabotage guards and REGISTER.md, per
CLAUDE.md. Tenant scoping applies to both new tables.

---

## 5. Decisions only the owner can make
1. **Who reviews Transak** — you alone, Transak's team, or both (tiers)? This
   sets whether roles need separate logins now or later.
2. **Risk order** — is regulatory > coverage > superlative > comparative the
   right priority for Transak's compliance?
3. **What auto-passes** — even at a measured 99%, should any Transak decision
   skip a person (e.g. "not Transak's claim" for market statistics)?
4. **Labels** — correct `transak-entity-sample-100.xlsx`; it becomes the fixed
   test every method is scored against.

## Sources
- Prodigy, Web application & text classification docs: https://prodi.gy/docs/web-app · https://prodi.gy/docs/text-classification · forum: https://support.prodi.gy/t/efficient-binary-annotation-using-textcat-teach/2343
- NN/g, 4 principles to reduce cognitive load: https://nngroup.com/articles/4-principles-reduce-cognitive-load
- Veeva PromoMats MLR review: https://www.veeva.com/eu/products/veeva-promomats/mlr-review/ · Next-gen MLR review: https://www.veeva.com/eu/wp-content/uploads/2025/05/Veeva-PromoMats-Next-gen-MLR-Review.pdf · 2025 innovation guide: https://www.veeva.com/resources/veeva-promomats-2025-innovation-guide/
- HITL practice: https://blackline.com/blog/human-in-the-loop-at-scale/ · https://velt.dev/blog/designing-human-in-the-loop-workflows-ai-products · https://www.docsumo.com/blog/human-in-the-loop-review · https://www.antoinebuteau.com/automation-series-5-human-in-the-loop-is-a-design-pattern-not-a-failure/
