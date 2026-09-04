# The system walkthrough — the prompt to open each thread with

The owner walks the platform one system at a time, finds issues by USING it,
and fixes them one at a time. This file is the prompt that opens each of those
threads, and the protocol they follow. Paste §1 verbatim; it names the system.

The order is in §3. Ask for "the next system" and the thread reads §3, marks
the one it just finished, and tells you which is next.

---

## 1. Paste this (replace `<SYSTEM>` with the one being walked)

> You are continuing the gomehagent build at `/Users/gomehsaias/Documents/gomehagent-build`
> (deployed at https://assistant-web-zm2d.onrender.com).
>
> **We are walking ONE system at a time. This thread is about `<SYSTEM>` and
> nothing else.** I will use it, find issues, and give them to you one at a
> time. Do not go looking for work in other systems; if you notice something
> elsewhere, write it down and tell me at the end.
>
> **Before I give you the first issue, get deeply familiar with this system —
> from the CODE, not from documentation and not from memory.** Read
> `WALKTHROUGH-PROMPT.md` §2 for exactly what "familiar" means here, do it, and
> then give me the briefing it asks for. Documentation is a hint about where to
> look; every fact you tell me must come from a file you actually opened, with
> the `path:line` to prove it.
>
> Then stop and wait for me.

---

## 2. What "familiar" means before the first issue

Do all of it, then produce the briefing at the end. Keep it under ~500 words:
the point is to prove you looked, not to write an essay.

1. **The declaration.** `systems.CATALOG[<system>]` — its `requires`, its
   `workflow.skill`, its `kb_needs`, its cadence. And `skill.REGISTRY` for the
   skill it names: parameters, `constitutive` needs, what it emits.
2. **The path a run takes**, named as functions, end to end: planner (if any)
   → `systems.take_plan` → `skill.run` → the bundle it resolves → the drafter
   → `Context.emit` → the three gates (`validator.check`, `coherence.review`,
   `artifact_check.check`) → `ledger.record` + `ArtifactBody` → approval →
   executor → write-back. Say which steps this system actually HAS; several
   systems are missing several, and that is often where the issue is.
3. **The data layer it reads.** Which of claims / objections / audiences /
   situations / entities / keywords / assets reach this system, WHICH
   generator receives each one, and WHICH gate enforces it. **A rule that
   reaches no validator is a rule that does not exist** — if you find one, say
   so before I ask.
4. **Its surfaces.** Every place in `admin_ui.py` this system is rendered or
   controlled, and every route in `web.py` that acts on it. For each surface:
   what it SAYS and what it lets you DO there. A fact reported with no control
   beside it is a defect in this codebase (see SYSTEMS-REFERENCE §6).
5. **What it is waiting on.** `systems.awaiting(tenant, key)` for a real
   account, and `kb.needs_met` — the distinction between "nobody has told us
   yet" and "it is written and waiting on you" matters and they have different
   fixes.
6. **Its guards.** `grep` the system's modules in `scripts/sabotage.py` and
   name which suites cover it. If a load-bearing behaviour has no guard, say
   which.
7. **Run it once** if it can be run offline, and show me what came out.

**The briefing:** the run path with the missing steps called out · what the
data layer contributes and where it is enforced · the surfaces and what each
lets me do · what it is waiting on · anything that is declared and read by
nobody. End with the two or three things you EXPECT me to hit, and why.

---

## 3. The order, and where we are

Ten systems (`systems.CATALOG`), then the machinery that is not a system but
that every system rides. Mark each as it is finished — this file is the
running record, so update it in the thread that finishes one.

| # | system | skill | status |
|---|---|---|---|
| 1 | `blog` | `blog_article` | **walked** 2026-09-02 (keyword lane: attention/refresh/rivals) |
| 2 | `campaign_email` | `campaign_email` | **walked** 2026-08-31 — see §5 |
| 3 | `ad_creative` | `ad_copy` | rehearsed 2026-09-04; ban list now constitutive; not walked one-issue-at-a-time |
| 4 | `content_compliance` | — (complete by design: sweep files a report) | rehearsed 2026-09-04 |
| 5 | `catalog_compliance` | `catalog_compliance`, `catalog_seo_rewrite` | rehearsed; own-site + named-refusal fixes 2026-09-04 |
| 6 | `service_desk` | `inbound_reply` | rehearsed; learning axis reads its edits 2026-09-03 |
| 7 | `lead_responder` | `lead_reply` (**built** 2026-09-03) | drafts under its own system since 2026-09-04 |
| 8 | `moment_email` | — (a watcher, by design) | rehearsed |
| 9 | `reorder_engine` | `reorder_prompt` (**built** 2026-09-03) | rehearsed |
| 10 | `reports` | `weekly_report` (**built** 2026-09-03) + `report_rollout` planner | rehearsed |
| 11 | `gbp_post` | — (declared 2026-09-03; Google API access not applied for) | blocked on the owner |
| 12 | `gbp_listing` | — (declared 2026-09-03; same gate) | blocked on the owner |

**Every system now has a computed check on all four of the owner's axes**
(context → generator, review flow, API shape, learning) — `systems.effectiveness()`
renders it as SYSTEMS-REFERENCE §2c. **Every system, every seeded account, is
rehearsed in the gate** by `scripts/test_rehearse.py` (2026-09-04): it runs
each skill, planner, executor, scheduled job and console surface offline and
fails on a crash, a bare exception in a note, or an internal identifier in
client-facing text. Run it first in any new thread; it is the state.

Then the cross-cutting machinery, same protocol, same briefing shape:

| # | area | where it lives |
|---|---|---|
| 11 | the creative seam | `creative.py`, `compose.py`, `media.py`, `hosting.py` |
| 12 | the knowledge base | `kb.py`, the Knowledge tab, intake |
| 13 | the gates | `validator.py`, `coherence.py`, `artifact_check.py`, `assurance.py` |
| 14 | approvals & the ladder | `approvals.py`, `systems.py` GATES, the digest |
| 15 | connections & credentials | `credentials.py`, `oauth.py`, Connections |
| 16 | the plan | `keywords.py`, `planner.py`, the Plan tab, `results.py` |

**Suggested start: `blog`.** It is the most complete pipeline — planner,
skill, gates, approval, executor, write-back, and a closed measurement loop —
so it is where "what a finished system looks like" is defined, and every later
walk can be measured against it. `ad_creative` is worth doing third rather
than first: it changed most recently and the newest code is the least worn in.

---

## 4. How a fix lands (unchanged, and not negotiable)

- **Reproduce it first.** A fix for a defect nobody reproduced is a guess.
- **Ship through the ritual:** `./scripts/ship.sh "<subject>" <body-file>` —
  it gates on byte-compile → web import → the full suite, then commits and
  pushes (which deploys). **Never edit the working tree while it runs.** Put
  the subject on the FIRST LINE of the body file: with a body file, ship.sh
  uses the file as the whole message and ignores the subject argument.
- **Every fix ships with its sabotage guard**, and the guard must report
  `[ caught ]` — `python3 scripts/sabotage.py <name>`. `MISSED` means the test
  around it is decoration; the usual cause is that the test called a helper
  directly instead of the surface, or asserted on a label instead of the
  thing.
- **Every console fact ships with its control.** If you tell the owner
  something is missing, the button that fixes it belongs on the same surface.
- **Turn the claim into a check.** A claim about EVERY instance is computed
  from the source (an AST walk, a schema walk), never surveyed by eye.
- **Verify the deploy on `/health`**, which reports the commit. Never infer
  what is running.

---

## 5. What each walked system established

One section per walked system. **Standing rules and traps go here; code facts
go in `scripts/test_open_defects.py`,** which fails the moment a fact stops
being true. Do not restate a code fact in prose — that is how
`SYSTEMS-REFERENCE.md` went stale.

### `campaign_email` — walked 2026-08-31 (commits `bef67d7`..`987b6d4`)

**The one root cause behind every defect found.** An input read by one place
and supplied by another, with nothing declaring the obligation. Every issue in
this walk was an instance: `audiences` (read by every drafter, written by
nobody), `offer` (read, undeclared), `audience_key` (declared, unread),
`revision_notes` (declared supplier was fiction, three private hops),
objections (returned `[]` for generative systems, so the run *denied* what was
on file), `blog_article`'s commitment never reaching `emit` (zero coherence
rules ever ran on an article), claim selection falling back to insertion order
(the six oldest claims won forever).

**Where it now lives.** `app/bundle.py` is the declared package: `PARTS` with
tier, supplier, and absent-semantics; `verify()` at runtime; `audit()` static.
`scripts/test_skill_conformance.py` computes the obligations from the registry
by AST walk — declared↔read in both directions — so a new skill inherits the
contract or fails the suite. That file is the answer to "how do I not miss an
input again"; read it before adding a system.

**The owner's standing rules** (stated in this walk; they bind every system):

- **Claims are human-approved knowledge about entities, brands, policies, or
  positioning.** Generators propose; they never populate. Do not turn model
  output into claims — it defeats the approval process.
- **Overwhelming is not conflicting.** Prefer a data layer full of quality,
  well-associated context over a sparse one. World knowledge that does not
  contradict an approved claim is not a problem to be gated.
- **Audience is singular, and required for anything generated.** One audience
  at a time, always — no piece of content is written without knowing who it
  speaks to. *Audiences* plural applies only to segments in one-to-many
  marketing (email campaigns, ads), never to individual correspondence.
- **Segment ≠ audience.** Segment is who RECEIVES (the ESP cohort). Audience is
  who it is WRITTEN FOR (the persona with pains, vocabulary, buying trigger).
- **Entities, not products.** A product is one kind of entity; venues and
  digital offerings are others. Never write product-shaped code or copy.
- **Thin knowledge caveats a promotion, it never vetoes one.** Shadow is the
  **Learning phase**, and manual approval is available inside it.
- **A hero, not a monogamy rule.** One artifact may mention several entities;
  it may not mix their positioning. Ads are exempt — that is what the
  positioning input is for.
- **Don't just do to do — assess the sense.**

**Traps this walk fell into.** Each cost a cycle; do not repeat them:

1. **Shipping a claim about "every instance" that was surveyed by eye.** Two
   AST audits were wrong (a loop-variable subscript `ctx.bundle[_k] = ...` read
   as absent; documented back-compat read as noise). Resolve loop variables,
   and check `git log -S` before calling something accidental.
2. **A guard that reports `MISSED` is decoration.** Two tests asserted on the
   bundle when only the prompt had changed, and one passed against `None`
   because preflight blocked the run. `python3 scripts/sabotage.py <name>` must
   print `[ caught ]` or the fix is unproven.
3. **Believing a commit message over the code.** `c4f72cc` claimed the workroom
   redraft was covered; it was not, and every Request-changes click refused on
   any account with a persona. Fixed in `c49477f`.
4. **Nearly shipping a no-op.** Measure the current behaviour before writing
   the fix — `resolve` already scoped claims by entity, so the "fix" changed
   nothing. Reverted with the measurement written into the commit.

**Open, in the order to take them** (all proven; see `test_open_defects.py`):

1. **Index our replies.** `EmailLog.body_excerpt` stores inbound mail only; our
   reply lives in an Approval payload and is never indexed. So the archive
   answers "what did they ask before" and never "how did we answer". The
   agentic `email_history_search` tool can reach sent mail, but that is a tool
   the model may call — not context the prompt is assembled from.
2. **The input register** — as the JOIN computed from the declaration
   surfaces, **not a fourteenth place to state things.** The three surfaces
   that reported success wrongly are closed (`9826a7d`..HEAD, 2026-08-31)
   and the vocabulary can now be trusted, which was the precondition:
   `scripts/test_catalog_vocabulary.py` joins every list derived from
   `systems.CATALOG` back to the declaration — the `kb_needs` vocabulary must
   reach an answer in `kb.KB_SUPPLIERS`, `dossier.SCOPES` is computed over
   CATALOG rather than written beside it, and `SYSTEMS-REFERENCE.md` §2 is
   written by `scripts/gen_systems_reference.py` and byte-compared. Start
   there: that suite is the register's first three columns already.

**Open question the owner has not answered:** should `blog_article` require a
reader? It is one-to-many, but its reader is defined by search intent.

### The effectiveness program — 2026-09-02..04 (commits `eec8707`..`5024d51`, 20 ships on the last day)

**What it was.** The owner's standard for every system, stated 2026-09-03:
the right context funnels in, the review flow is right, the shape pushed into
the tool is right, and it learns with every iteration — "that's how we
measure effectiveness." Then: complete the unfinished systems to that
standard, run operations in parallel on workers, and "continue until you have
verified the functionalities and the quality … if something obviously needs
to be fixed or can improve the process, implement it."

**The one root cause, again.** Two halves of a contract written in different
places, each correct alone: `measure` was a sentence read by no code while
`edits.record` wrote deltas no generator read; `ship_by` was empty for two
systems; a Skill bound one `system_key` while `ROUTES` sent mail to two; 25
crons and no lease; a catalogue finder that read the PRIMARY site whenever the
caller named none. Every fix was a join plus a computed check that the join
holds.

**The owner's standing rules from this stretch:**
- **"Just based on the words we're prioritizing. We don't want an expensive
  solution that we don't actually need or use regularly."** Scope per-phrase
  API spend to `attention()` + `next_to_write()`, capped, TTL'd, never on render.
- **The learning axis converges only as rules.** Deltas are evidence; rules are
  what the drafter reads; the owner is the gate. Recurrence (>=3 distinct
  sends) is decided in code; the model writes one sentence; approving is the
  only way in; a rule that does not shrink the delta is retired.
- **GBP is two systems, not one** — the post, and the listing it lands on.
- **Ads publish to Meta by hand** (the export sheet) — by design, not a gap.
- **Unattended recurring spend on a client's quota is the owner's call** —
  `numInstances`, weekly rival reads, auto-send: declared, never defaulted on.
- **Every reference into the knowledge base is picked from its table, never
  typed, and refused on write when it is not there** — segment, audience,
  entity (2026-09-04: "All the Entity selectors should be drop downs … we
  should not have to know the slug. It should sync with the entity table and
  make sure to associate them"). `admin_ui.entity_select` is the one entity
  picker; `scripts/test_entity_selectors.py` walks every console page and
  every plan declaration to prove no text box and no unknown key survives.

**Traps this stretch fell into.** Each cost a run; the harness caught every one
before `main`:
- The capability gate reads the WIRED view (`tenants.capabilities`), not the
  declaration — stub the function, not `shopify_store`.
- The validator fails closed on a bare tenant ("no ban list, nothing can be
  sent safely") — fixtures seed `kb.ensure_brand` + `kb.add_banned` FIRST; the
  constitutive gate fires before any site or store check.
- A skill that SENDS must declare `writes=True` or `emit` queues no approval.
  `apply_decision` takes `"approved"`, not `"approve"`. Emit TEXT; carry html
  in `meta`, or the card shows `<div style=…>`.
- An approval KIND's executor arm lives in `_execute` AND the kind in
  `_HANDLED` — that is what `register.py` scans; an arm in `apply_decision`
  reads as "no executor arm".
- `knobs_for` returns knob SPECS; `cadence_for` (campaign) / `blog_cadence_for`
  / `report_cadence_for` return VALUES — and `knobs_for` branches per planner.
  `open_plan` refuses any plan key the system's `plan_fields` do not declare.
  Plan briefs nest fields under `brief["plan"]`. Intent vocabulary is
  story/education/proof/offer. `SystemRun` has `system_id`, not `system_key`;
  `systems.start_run` returns the id.
- `Setting` had eleven uncoordinated writers and the register refused a
  twelfth — stamp a marker on the row it is about instead (the archived note).
  `Memory.tenant` is EMPTY; filter by `scope == systems.thread_key(t, k)`.
- A sign-off is the LAST line and a greeting the FIRST; a classifier that
  matched anywhere misfiled "Thanks for reaching out" as a changed sign-off.
- A rehearsal against a STUBBED backend produces refusals that name the real
  provider ("omnisend has no campaign reporting"). Confirm against the real
  module with only the transport stubbed before calling anything a gap.
- When a loop body moves into a per-account unit, every guard anchored on it
  goes STALE — re-anchor; never add to KNOWN_STALE. A captured docstring
  carries its own indent. A `ship.sh` log from a previous attempt makes an
  `until grep SHIP_EXIT` return early — wait on the process, or a fresh file.
- In zsh, `path` IS `$PATH`. Naming a shell variable `path` erased every
  command for that call.

**Open, in the order to take them (owner, 2026-09-04 evening — §6 carries the
detail):** 1. UX polish, surface by surface. 2. The Plan's mix (share per tier /
intent / branded), a recommended default computed from the map, a schedule reset,
a refresh that installs new systems' planners. 3. Ad Creative (1)–(3): the
Hormozi/Piliero panel BEFORE variants, claim-review tabs per variant + an Instagram
caption format, and the pictures — no paste, no burned type, a winning-ad look.
4. Owner actions, unchanged: Google API access (both GBP systems), one real
   Klaviyo push, the first Semrush "Read the competition" click,
   `/health/workers` after a day at two instances, `OPENAI_API_KEY` present.

**Taken 2026-09-03 (this thread):** the ledger's "no skill" entry is split —
by-design (`ship_by` resolves; nothing to draft) is printed and never open,
UNBUILT (`ship_by=""`) is the recorded claim `{gbp_listing, gbp_post}` and
goes red when either names a performer. Trap found on the way: the ledger's
own sabotage guard had printed `MISSED` since 2026-09-02 — it mutated the
"cleared" branch entry 3 stopped measuring — so the one suite that must fail
on good news had no guard that could make it. Re-pointed at `gbp_post`'s
empty `ship_by`. A count (2 -> 1) stays truthy; the set is the claim.
Omnisend segment paging is CURSORS — `paging.hasMore` + `cursors.after`,
same path `?after=` — proven live 2026-09-03 on the Baci brand; the adapter
followed a `paging.next` the API never sends, so page two was never read.
Re-anchored the path-keyed paging test to the recorded live body.
The segment COUNT: there is no count field on a list row at all (the probe
returned None because the adapter forwarded only id and name, and the API
sends none) — it is `contactsCount` on `GET /segments/{id}/statistics`,
proven live (65 on Baci's "Repeat buyers"). `omnisend.segment_count` →
`esp.audience_count` (profile `count_fn`) → `reconcile` asks for LINKED
segments only, on the weekly sweep, so the zero-members drift can fire on
the one ESP in use. Two halves again: `esp.audiences` read `count`,
`omnisend.segments` never supplied it, and the comment between them said
"carries no counts" as a guess.
`weekly_report`: the ArtifactBody row DOES carry `format="report_document"`
(the emitted item dict does not, and nothing reads it there); what was wrong
is that `artifact_label` had no branch for it, so every client report in
Review, Drafts and the held list read "report document · <date>" with the
subject, recipient and window sitting unread in its meta. Named now.
With that the open list above holds the owner's actions only. Two things
the rehearsal SHOWS that are not gaps, so the next thread does not chase
them: the catalogue skills read `failed: no Shopify store is connected for
'x'` because the rehearsal calls below `preflight` — in production
`systems.ready` blocks them by name before any store lookup, and the
RuntimeError is the named second line; and `weekly_report` PRODUCES for an
account with no ban list because `client_report` makes no model call, so
there is nothing for a validator to check. Verification method that worked:
the Omnisend connector in-session IS the Baci brand's live API (read-only);
a docs-read shape is confirmed or corrected in one call.
Owner's issue 2026-09-04, entity pickers: five KB forms typed a slug into a
datalist; the ad-creative plan field declared no `kind`, so it was a bare
text box AND `_check_plan_refs` skipped it (keyed on `kind`); `entity_list`
("also about") had no renderer branch at all; `/admin/objection_add` wrote
an unknown key through. One helper now renders every picker; the objection
writer resolves and refuses; multi-select values are joined for `entity_list`.
GBP platform half (owner: "what are all the APIs … implement it correctly"):
`app/gbp.py` read adapter + `probe`; `business.manage` in the Google flow, the
CLI and the privacy page (a suite proves the three agree); `gbp` DECLARED as
`Tenant.gbp.location` and WIRED only when the consent carried the scope
(`CAPABILITY_SCOPES`, compared on the scope's leaf); `/admin/gbp_probe`;
`/health/connections["gbp"]`. The seven APIs are named once
(`gbp.APIS_TO_ENABLE`) and shown on the account card. Still the owner's:
Google's access approval (quota 0 until then), and nothing writes to Google
until the skills exist. Trap: a test fixture that deletes and re-adds a
credential in one session hits the UNIQUE(tenant, provider, site) — update
the row, as `store_oauth` does.
Picker grouping is the account's choice (owner: "one might need to do it by
collection, another by entity type"): `KbBrand.selection.entity_grouping` ∈
`admin_ui.GROUPINGS` (type | collection), written by `/admin/brand_update`
merged into `selection`, the control on the Knowledge tab beside the
selection line; `collection` groups by `parent_keys` (the ranges
`sync_collections(adopt=…)` wrote), ranges first, the rest "Not in a
collection", a member of two ranges under both.
Owner's Ad Creative issues 2026-09-04 (four). (4) "Edit in Canva doesn't
open Canva; it duplicates the image": the route redirected back to Content
with a flash; `create_design` filed a second `kind="design"` row for the
frame; `harvest` skipped the frame as "already an image" and filed the export
as a third. Now: 303 to the editor in a new tab; `record=False` from
`to_canva`; harvest lands the export ON the frame (`source` gains "edited in
Canva"); a named `design_id` re-harvests.
Shipped on the owner's word after the GBP post ship. Issues (1)-(3) — the
Hormozi/Piliero panel before variants, claim-review tabs per variant with an
Instagram caption format, the frames (cut-out paste, burned PIL type, no
winning-ad reference) — are REPRODUCED in the memory note, not started.
GBP posts (owner: "a post generator … convert existing blogs, emails or ads
… or from scratch to address objections or reinforce claims"; "if posts are
part of the Plan it needs to be clear they need to set up a plan"): built
ON the existing Plan infrastructure — `plan_fields` on the CATALOG row,
`planner.PLANNERS["gbp_post"]` (one a week, derived/native alternating, the
local keyword from the SAME keyword map the blog reads), `open_plan` /
`save_plan` / `_check_plan_refs` with three new reference kinds (artifact,
objection, claim — pickers, never typed ids), `knobs_for` (`posts_weekly`),
`plan_complete` gaining `one_of`. The system page carries `workflow.explain`
so it SAYS posts are planned work. `gbp_post` is in the conformance suite's
NO_SEGMENT set: its reader is whoever searched, like an article. The one
write is `approvals.publish_gbp_post` → `gbp.create_post`, on approval only.
GBP audit (owner: "how are they to run and review the results of each audit?
How does it align with the overall Plan and Planned Strategy?"): `gbp_listing`
built in catalog_compliance's shape — `app/gbp_listing.py` rubric (100 points,
every check a measurement of a field Google returned; reads Google refused are
scored unknown and NAMED), report filed `fmt="report"` (the ledger files the
body row; the Reports room reads line 3), fixes as `gbp_listing_fix` approvals
(website from the account's domain; a model-drafted description through the ban
list) → `_execute` → `gbp.patch_location`; runs every Monday (`gbp_audit_sharded`)
and from "Run the check now" (`/admin/system_run_now`, generic for every report
system); ALIGNMENT = the head terms of the keyword map the listing never says +
whether posts are planned; `gbp_listing.trend` is the `measure_fn`; the Plan tab's
Strategy page carries a "Local presence" card from `gbp_listing.latest`. With
that NOTHING in the catalogue is unbuilt: the ledger's RECORDED_UNBUILT is empty
and its guard moved to the last open entry (the correspondence archive).
`gbp_post` now rides `ledger.ARTIFACT_FORMATS` — one writer of body rows.

**Left deliberately unchanged:** `campaign_email` is not in `AUTO_SHIPS` (a
send cannot be recalled); ads are carried to Meta by hand; the reports planner
leaves `to` for the owner (no planner can read it from data).

---

## 6. Next thread — paste this (UX polish; the plan's mix and schedule; Ad Creative rebuilt)

> You are continuing the gomehagent build at `/Users/gomehsaias/Documents/gomehagent-build`
> (deployed at https://assistant-web-zm2d.onrender.com). Read the memory notes
> `gomehagent-systems-effectiveness` (its LAST section first) and
> `gomehagent-walkthrough-handoff`, then `WALKTHROUGH-PROMPT.md` §4 (the protocol,
> unchanged) and §5 (the owner's standing rules and the traps) BEFORE touching anything.
>
> **First move:** `python3 scripts/test_rehearse.py` — read its artifacts, not the
> pass line.
>
> Three streams, in the owner's order, one ship at a time under §4 unchanged:
> reproduce first; every fix ships a sabotage guard that prints `[ caught ]` (run
> it — a guard that passes with the mutation is decoration); ship via
> `./scripts/ship.sh "<subject>" <body-file>` with the subject on the body's first
> line; never edit the tree while it runs; `python3 scripts/register.py --write`
> before shipping whenever a guard or a caller moved (REGISTER.md is byte-compared
> in the gate); verify on `/health`; write the memory note before the thread ends.
>
> **1. UX polish.** The owner walks the console and gives the surface; take each
> as given, one ship each, act where you report.
>
> **2. The Plan: refresh, reset, and a recommended mix.** Owner, 2026-09-04: *"I will
> need to refresh the plan to add new systems and to reset the schedule if the
> initial schedule doesn't make sense. I should be able to adjust the plan based on
> the percent of long tail / branded / short / specific topics etc and the app should
> recommend a base setting default based on the current status of the brand and
> where the best opportunities lie."* Where the facts are: keyword tier
> `head|body|long_tail` and intent `informational|commercial` on `db.KeywordTarget`
> (db.py:1058-1059); branded tokens `keywords.brand_tokens_for` (keywords.py:178);
> the ranking `keywords.score` (keywords.py:466); the blog planner
> `planner.blog_rollout` (pillar before support; `LEAD_DAYS` planner.py:43); the
> cadence knobs `planner.KNOBS` / `knobs_for` (planner.py:122 / 166) written by
> `systems.set_cadence` (systems.py:1679) through `/admin/plan_cadence`
> (web.py:6342); opportunities `funnel.proposals` (funnel.py:382) and
> `strategy.read` (strategy.py:67). What does NOT exist: a MIX knob — the map is
> planned by score, never by a declared share per tier / intent / branded; a
> schedule RESET — `planned_for` is set once by the planner and nothing re-dates
> open plans; a REFRESH that brings a newly declared system's planner into an
> account's Plan (`planner.PLANNERS`, `top_up` planner.py:1147 run per system by the
> tick). Build them on the same Plan infrastructure every system uses (the GBP
> systems were built on it today — keep it so): the mix as declared knobs the planner
> READS (rule 4 — never a knob the planner ignores; `_check_plan_refs`-style refusals
> for a share that does not sum); the recommended default COMPUTED from the map's
> current state (the share of candidates per tier / intent / branded, striking-
> distance positions, what is already published) and shown on the Plan tab as a fact
> WITH its control; reset as a control that re-dates open plans from today under the
> cadence without touching owner edits (`open_plan` carries `brief["edited"]`
> forward); refresh as the control that installs and tops up every declared system's
> planner for the account.
>
> **3. Ad Creative — properly, this time.** Owner, on the latest output: *"what are
> we using to generate them? The current output is still horrible and the copy is
> really bad. I need you to properly implement what I asked for."* The four asks of
> 2026-09-04; (4) Edit in Canva is shipped (`f50083c`); (1)–(3) are reproduced in the
> memory note and NOT built:
> - (1) every ad copy goes through the "Alex Hormozi" and "Sam Piliero" test to
>   self-justify — show what each would say and apply the improvements BEFORE the
>   variants are generated. Today `ad_craft.review` (ad_craft.py:186) runs AFTER each
>   draft, one redraft on a block, and no panel exists. Build it as one model pass over
>   the CONCEPTS (angle × claim × offer × reader) that critiques as Hormozi (the value
>   equation, the offer) and Piliero (the hook, one idea, diversity across the batch),
>   rewrites each variant's brief, is shown on the variant board, and only then
>   `draft_ad` runs — a stubbable seam like `draft_ad` (skill_pack.py:1108), so the
>   suite proves the improved brief reached the drafter before generation.
> - (2) the claim-review section needs TABS per generated variant — `_grounding_card`
>   (admin_ui.py:12037) concatenates every variant into one reading; and the copy
>   format must be optimised for Instagram — `ad_craft.REPLY_FORMAT` (ad_craft.py:345)
>   is a headline plus two or three lines with no caption shape (first line under the
>   125 fold, line breaks, a CTA line, hashtags only if they earn it — measure it in
>   `ad_craft.review`, the way `gbp_post.review` measures a post).
> - (3) the pictures. WHAT GENERATES THEM: OpenAI `gpt-image-1` (`imagegen.MODEL`,
>   imagegen.py:48). `imagegen.plate` (imagegen.py:216) paints an EMPTY scene; then
>   `compose.product_on_scene` (compose.py:282) PASTES the product cut-out at 52% of
>   the width with a drawn contact shadow, and `compose._draw_text` (compose.py:140)
>   burns the headline in DejaVu or Arial (`_FONT_PATHS`, compose.py:46) — that is
>   the "pasted onto another image" and the "embarrassing text". `imagegen.place_product`
>   (imagegen.py:281) is the masked-edit route, measured repainting the product.
>   `creative.batch` (creative.py:743) picks the route per framing
>   (`NEEDS_THE_PRODUCT`, creative.py:740); `creative.assess` (creative.py:369) is a
>   vision review that never gates; NOTHING reads winning ads — `meta_ads.live_ads`
>   (meta_ads.py:105) returns copy and insights, no creative image URLs. THE COPY is
>   Claude (`config.CLAUDE_MODEL`) in `_draft_ad_live` (skill_pack.py:1108) with
>   `_AD_SYSTEM` (skill_pack.py:1047) and `ad_prompt` (skill_pack.py:1150), one call
>   per claim. What follows from the code: type belongs in Canva now that the door
>   works — stop burning it into frames; stop the paste for product-led frames (a
>   reference-image generation with the real product, or a plate lit and framed for
>   the shot, with the assessor's INTEGRATION verdict as a gate rather than a note);
>   read the account's winning ads (add `creative{image_url,thumbnail_url}` to the
>   Meta fields, rank by CTR/ROAS) into a "winning look" the brief cites — on the
>   owner's click, never unattended (§5's spend rule); and hold the copy to the panel
>   in (1). Reproduce each with the rehearsal's artifacts before building.
>
> Still the owner's: Google's Business Profile API approval (quota 0 until then —
> `gbp.probe` names it), one real Klaviyo push, the first Semrush click.
>
> If the owner gives you an issue instead, do that and only that.
