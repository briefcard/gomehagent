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
| 1 | `blog` | `blog_article` | **walked** 2026-09-02 (keyword lane); mix/reset/refresh + a blog destination that never blocks 2026-09-04 |
| 2 | `campaign_email` | `campaign_email` | **walked** 2026-08-31 — see §5 |
| 3 | `ad_creative` | `ad_copy` | **rebuilt** 2026-09-04 on the owner's four asks — panel before the variants, Instagram caption, a claim reading per variant, frames + winning look |
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

**2026-09-04/05, the §6 thread (`c1b607e`..`48ea9d7`, ten ships).** Streams 2
and 3 are DONE; stream 1 (UX polish) needs the owner at the console.

*The Plan* now has the three controls it lacked. `planner.MIX` declares shares
the way `KNOBS` declares cadence and `blog_rollout` applies them as a BUDGET
WALK over the order the pillar rules produced — seeded with the OPEN QUEUE, so
a daily top-up of one article holds the mix over the queue rather than over
itself. Tier is the spine; branded and buying bend first when the map cannot
supply them. `keywords.mix_recommendation` computes the default from the map
and every number carries its sentence. `reset_schedule` re-dates open plans and
keeps the owner's dates; the CALENDAR planners refuse by name because their week
IS the item. `refresh` installs and tops up every declared planner's system.

*Ad Creative* is rebuilt on all four asks. The Hormozi/Piliero panel sits on the
CONCEPTS before a word is drafted and each variant is written to its own
rewritten brief; the copy is an Instagram caption and is measured as one; the
claim review is one reading per variant; the frames burn no type (it goes to
Canva) and a composite that reads as pasted is dropped after a second plate;
and the brief cites what has actually worked, read from Meta on a button.

**Owner's issue mid-thread, taken alone:** publishing waited for somebody to
choose a blog. `sites.ensure_blog` is the one resolver for the run AND the
publish arm — recorded-if-it-exists, then the store's sole blog, then
`sites.FALLBACK_BLOG_TITLE`, found or created. A store it cannot READ creates
nothing; a store it cannot read with a blog already chosen publishes into it
unconfirmed rather than stranding an account that has been working for months.

**The panel had to be made BINDING, not advisory** (owner, 2026-09-05: *"it
leaves us with a need to apply the edits provided and summarized"*). Two
defects, both reproduced. `ad_prompt` put the rewritten brief BEFORE the
ruleset's `## Angle`, and the two contradict by design — the panel's job is to
say what a concept should stop doing, and the commonest thing it says is to
drop the angle's own mechanic. A brief reading "drop the identity-quiz angle"
sat 190 characters above a heading ordering "which one are you", so the generic
instruction was last, under a heading, and won. The angle is now demoted to
where the concept STARTED and the brief comes last saying it overrides. Second:
nothing verified the brief landed. `ad_craft.review` measures the SHAPE and a
draft passes all of it while keeping the mechanic it was told to drop, because
that is not a character count. `skill_pack.panel_check` asks the same two
reviewers, ONCE for the batch, whether each draft did what its brief said;
anything named as ignored is written again with the objection in front of it.
Nothing emits inside the drafting loop any more — drafts are held, checked,
corrected, then filed. A rewrite that obeys the brief and breaks the craft
rules is REFUSED and the first draft stands, said out loud.

**Then the whole ad system turned out to ship nothing.** Ads are carried to Meta
by hand BY DESIGN, so `/admin/ad_export` is the declared ship for `ad_creative`
— and it read `headline`, `primary_text`, `description` and `cta` off each
variant. A variant row carries `n`, `output_id`, `angle`, `basis`, `claim_ids`,
`claim`, `text` and `dropped`. `primary_text` matched ONE line in the whole
repository: the reader. Every export anyone has ever run was variant headers,
blank lines and the closing instruction — the copy was drafted, craft-checked,
panel-checked, redrafted and approved, then not exported. The suite passed
because it asserted `"variant 1" in txt` and counted marker lines: it checked
the header and never the copy. `text` is now the single writer of the body,
`headline` is written when the drafter produced one, and a variant carrying no
copy at all SAYS so and is counted in the summary line rather than exporting as
a silent blank.

**2026-09-07 — a production break I shipped, reported by the owner.**
`fb00ed1` made `web.ad_frames` send `situation=` into `creative.batch(**args)`
and taught `batch` to take `output_id` in the same commit — not `situation`.
Every Make-frames click from 2026-09-05 17:03 raised
`TypeError: batch() got an unexpected keyword argument 'situation'` inside
`_run_bg`, which catches and RECORDS, so the button still returned 303. Two
days. Nothing caught it: the suite replaced `_run_bg` with a spy and never ran
the receiver; no suite calls `ad_frames` through to the real `batch`;
`/health` reports the commit, not the button. `ec6d023` fixed the seam at
three layers (batch accepts AND forwards; `pick`'s photo-selection brief takes
it too; the suite runs `_run_bg` synchronously into the real `batch`).
`ae6594e` made it a class: every kwargs spread in `web.py` is diffed against
its callee's signature — nine sites. The first run of that check reported
seven clean sites and had silently skipped `ad_frames`→`batch`, because a
ROUTE FUNCTION named `creative` shadows the module in `web`'s namespace; the
suite's own coverage assertion caught it.

**2026-09-07 — the zodiac batch (`588a953`): the app's own promise, "inject
the right thing at the right time", failed at RIGHT THING.** An ad for the
Libra Zodiac Vibe cup — porcelain — came back "18 pieces … shatterproof". The
entity was correct. The claim handed to the writer was a harvested support
reply about acrylic glassware, filed with no entity by `email_harvest` and
approved brand-wide by `review_claim`, which never consulted
`scope_unconfirmed` — the rule written for exactly that sentence, wired to the
objection reviewer only. Then `claims()`'s rotation key re-sorted the whole
list by last-used and threw the specificity order away, so the cup's own claim,
used once, sat behind a never-used acrylic answer. Then the claim's evidence
carried the wrong product into the panel. Fixed at entry (the harvester scopes
by `entity_for`, unique winner or nothing; approval refuses an unscoped
machine claim unless a person ticks brand-wide — route and toolbar box), in
selection (rotation rotates WITHIN a specificity tier), and in the ad (the
entity's own claims lead; an item with none is said on the board). The seam
suite gained the inverse check: parameters a path NEEDS must be PASSED.

**The standing rules this stretch added:**
- **A seam is only tested when both sides execute.** When a caller gains a
  kwarg, the test must invoke the callee — stub the expensive thing BELOW the
  seam, never the seam itself. A spy on one side is a test of the spy.
- **A structural check that can skip a site must assert its own coverage.**
  "None found" is only an answer when the known-bad case is demonstrably
  inside the population that was searched.
- **After gating or narrowing an existing writer, ask what else it was the
  only writer of.** (`6d52cf6` gated `mark_published` and lost the only
  writer of `cms_article_id`; `d35b6c8`/`9a1886d` repaired it.)
- **Scoping is a decision, not a default.** A machine-filed claim with no
  entity is asked about at approval — never believed of everything. A person
  ticking brand-wide IS the decision.
- **Rotation rotates within a specificity tier, never across one.** Where
  there is a subject, its own claims rotate among themselves first.
- **Correctness before craft.** Exemplars would not have fixed writing about
  the wrong product. (And: when a gate is added to a path, check the surface
  that feeds the path can say yes — both refusals of that ship were the UI's
  and the suites' old silent contract, not the code.)
- **A critique that is shown and not applied is a task list, not a system.**
  The panel is evidence behind an ad that already follows it; the board leads
  with what was applied and folds the reviewers' words behind that.
- **The specific instruction must be the LAST word.** Where a generic rule and
  a brief written about this particular subject disagree, ordering decides
  which one the model obeys, and a heading beats a paragraph.
- **A knob the generator ignores is not a knob** — the mix is refused at the
  writer when the shares do not sum, checked against what would be STORED, so
  a partial write cannot leave a mix the planner silently discards.
- **Key a control on the FACT, never on the fault.** The blog picker was shown
  when publishing was `ok is not True`; the moment a missing blog stopped being
  a failure the control vanished. It hangs off `publish["choose"]` now.
- **Assert on the PAYLOAD, never on the frame around it.** The export suite
  checked headers and marker counts, both of which survive an empty body; the
  new assertion blanks a stored batch and demands the export say so.
- **One field, one writer.** My first export fix wrote the body twice (`text`
  and a new `primary_text`); the second copy goes stale the moment an owner
  edits a variant. The assertion that caught it is now the rule.
- **A gate is allowed where only one thing can fail it.** `integration` gates
  composited frames and is not even ASKED of a generated scene — gating those
  would be the false refusal `assess` was written to avoid.
- **An automatic destination is never a silent one.** A blog chosen for the
  owner, a mix applied, a panel that could not sit, a frame dropped as pasted:
  each says so on the run and on the surface.

**Traps this stretch fell into.** Appending guards with `repr()` writes
SINGLE-quoted keys while the file's own entries use `"key": '...'` — an anchor
in the wrong style matches nothing, so assert the count PER ENTRY before
writing. A guard whose target you edit later goes STALE in the same session:
re-run every guard after any further edit to the same function, not only when
it is first written. Four pre-existing guards went stale or ambiguous because
their line moved — `the_review_shows_what_is_unbacked` matched TWICE after the
grounding card grew a second return, which patches whichever comes first.
`apply_decision(ap_id, decision)` takes no `by=`. `keywords.readiness` gates on
`credentials.wired_capabilities`, so a fixture writing only `Tenant.cms` reads
"no CMS connected" — the probe, not the code. A stub whose signature lags the
real function hides the parameter nobody forwards (`_plates(for_product=…)`
was accepted and dropped one call deep).

**Left deliberately unchanged:** `campaign_email` is not in `AUTO_SHIPS` (a
send cannot be recalled); ads are carried to Meta by hand; the reports planner
leaves `to` for the owner (no planner can read it from data); the winning-look
read is on a button and on no schedule.

### The visual boards — 2026-09-07 (one ship; hash in the memory note `gomehagent-creative-substrate`)

**The defect, reproduced in numbers.** Two photographs of the product on
file; four generation calls; none carried an image. Every request was a JSON
body, and the only thing the model was ever told about the product was "do
not invent one". The frame the owner saw — *"a nameless white mug"* — was a
person-led cell that could not carry the product by construction: framing
"incidental or absent", a moment "without the product anywhere", and the
invent-nothing rule. Three ways one grid kept the product out.

**What the owner asked for, in their words, and what each became:**
- *"a visual board similar to a pinterest board from which the AI should
  mimic styling and positioning"* → the brand's own pictures go INTO the
  request as `image[]` inputs on `/images/edits` with `input_fidelity=high`
  (`imagegen.with_references`); the prompt says which inputs are the product
  ("reproduced EXACTLY") and which the look ("not the contents").
- *"different looks per brand - studio vs lifestyle vs specific collections
  … create these references and optionally select which to pull from for
  each run"* → boards are NAMED (`kb.add_board`, stored in
  `KbBrand.visual["boards"]` — the art-direction column, first reader); a
  pin is `board:<slug>:<role>` on the asset; `batch(boards=)`,
  `generate(boards=)`, `pick(boards=)` and the two forms carry the choice;
  none chosen means all; a name that is not a board is refused where it can
  be read and named in the result, never widened to everything.
- *"accessible by the other systems as well not just ads"* →
  `creative.board_inputs` is THE seam: the ad set and the article hero draw
  through it; `pick` gains `pinned_product` (above the newest photograph)
  and `pinned_look` (above brand-wide), both below `proven`;
  `hero_for_campaign` prefers pins within each rung.

**Standing rules it adds:**
- **The boards are the switch.** Nothing pinned → yesterday's route,
  unchanged. The day a route ships must not be the day every account's
  pictures quietly change (`the_board_is_the_switch`).
- **A reference pin is words, never pixels.** Kept out by `may_publish` at
  the one place bytes are fetched — the gate a composite already uses — and
  NAMED in `excluded` and in the set's note. Kept out and said, not kept out
  and silent. A reference may be pinned as the look; never as the product.
- **With the product in the request, no cell excludes it.** `DRAWN_MOMENTS`
  drops `before`; `FRAMINGS_DRAWN` puts the product in the person's hands.
  The old vocabulary is right when a generated product can only be the
  wrong one, and wrong the moment the model has been handed the right one.
- **What a picture was drawn from is on the picture.** `derived_from` holds
  the pin ids, so the set can say "drawn from N of the brand's own pictures"
  from the frames themselves, and an outcome can one day reach the pins.
- **The pinned product shot IS a photograph of the product.** `batch` treats
  `pinned_product` like `photograph`; `pinned_look` is not one.

**Traps this stretch fell into.** The suite's fake image bytes were keyed on
`len(sent)` — after `sent.clear()` the second set duplicated the first and
content-addressing filed zero frames; the counter must be run-wide. Twice the
suite encoded MY expectation rather than the design: "front first" when the
collector promises pick's choice first, and "look-only means no product"
when the design says the board being on means the product's photographs are
used without pinning each one. Read the docstring you wrote before asserting
against it. `sabotage.py` entries are mixed-quoted (`"name": '…'` beside
`'find': '…'`): rewrite a `find`/`replace` by matching the line on its own,
never by its neighbour. Editing `batch`'s loop and signature moved FIVE
existing guards; the anchors test caught them and one matched twice once
`with_references` appended the same rule as `plate`.

**Left for the next ship, in order:** derive-and-confirm a direction row
from a board's pins (the words a reference pin contributes; the
`KbBoard.note` is its seed); an image-embedding distance judge that RANKS a
set against its board and never vetoes; `generate` still fetches its product
source by "newest publishable row + httpx" rather than `pick`; the Pictures
page's "select all" script ticks every `asset_ids` box on the page,
including the boards' and the sets'.

### The ad is about the thing you chose — 2026-09-07 (one ship; hash in the memory note)

**The defect, in the owner's words:** *"I choose a Sagrada familia head
product. Why is joke being referenced? Why is baroque & rock? Your wiring is
all messed up."* Reproduced: for a Sagrada ad the panel and the drafter were
handed `['sagrada-head', 'baroque-rock-tumbler', 'joke-melamine-18']`.
`resolve`'s catalogue branch opened on the named entity and, with no buyer
requirements to rank on, `kb.match_entities` returned the catalogue's first
rows; the 2026-08 fix that made the named entity LEAD that window kept the
strangers behind it. The zodiac cup's "18-piece gift" came the same way. And
the refusal the owner pasted was filed as copy: `ad_craft.parse` is forgiving
by design and nothing asked whether an ad had arrived at all.

**Standing rules it adds:**
- **A named entity is the instruction, and every row says what it is.**
  `resolve` supplies the named entities first (hero, then "also features",
  by key, in order) and marks each row's ROLE — `named`, `matched` (fits
  stated requirements) or `companion` (the ranker's shelf, which with no
  requirements is the catalogue in sort order). The contract is
  per-consumer: an EMAIL may show several and argue one, so it keeps the
  shelf (`test_campaign_variety` holds that line); an AD shows one thing,
  so `_run_ad_copy` drops companions by role before the panel or the
  drafter see the bundle (`a_named_entity_brings_no_strangers`). The first
  cut of this ship made the named list exact for everyone and the campaign
  suite refused it at the gate — the shelf is a feature there.
- **The product's own catalogue facts are the confirmed details.** A
  store-synced row is approved data; its description and attributes reach
  the panel and the drafter as "facts you may state as they are". A drafter
  told to invent nothing and handed "set: 6" alone will decline — and did.
- **A reply that speaks to the operator is a decline, not a draft.** No
  `HEADLINE:`/`LEVERS:`/`---` plus a phrase like "I need to stop here" or
  "can you confirm" → `ad_craft.declined()` returns the ask; the variant is
  not filed, the run and the summary say it, the board record carries it,
  and the board shows the chip and the ask. A real ad is never read as one:
  any marker makes it an ad; a caption asking its READER a question is not
  a decline.

**Left deliberately unchanged:** a decline is not retried — the model said
what it needs and the honest answer is to show that; the fix is upstream
(the claim, the entity), not a louder prompt.

### Canva: a revoked connection is not a connection — 2026-09-07 (one ship; hash in the memory note)

**The defect, in the owner's words:** *"Canva would not renew the token for
baci: Sign-in was rejected: Token lineage has been revoked — reconnect it on
the Accounts tab."* and *"We agreed that when a specific client is not
connected it will resolve to organize by folders in Canva."* Reproduced:
`canva._token` resolved Baci's own credential, renewal was rejected, and the
error came back one line above the text promising the agency's connection
serves every account. Baci's row stayed ACTIVE — the Accounts tab said
"connected — by client" over a dead connection — and the remembered folder
had been made in Baci's Canva, so the agency's token could not have filed
into it anyway.

**Standing rules it adds:**
- **A definitive rejection is recorded, then routed around.** Revoked,
  invalid grant, expired → `credentials.record_failure` (the one writer),
  which `resolve` reads at once; a shared provider falls through to the
  agency's. A transient error changes nothing — switching a client's designs
  into the agency's Canva on a timeout is how "why is our design in their
  Canva" starts (`a_transient_canva_error_does_not_switch_accounts`).
- **A folder belongs to the account that made it.** Remembered per account
  (`design.canva_folders[source]`), the legacy id read as the account that
  made it, the agency's root the legacy setting; a folder that is gone is
  forgotten and recreated once, never failed on for ever.
- **Whose Canva is said where the edit happens.** `canva.which_account` is
  the one sentence; `to_canva`'s note, the set card and the Accounts tab
  all read it.
- **Look before editing.** Every frame has a viewer — fit, then a click to
  its own pixels — with the edit control inside it.

**Traps this stretch fell into.** A regex block replacement that ends at
"the next triple newline" swallowed the whole next function
(`upload_asset`); `test_canva` caught it. Compare `def` lists against HEAD
after any block rewrite. A per-account memory key beside a legacy one means
every reset in every suite must clear both (see `test_canva`'s reset). A
public helper for that with no caller — `forget_folders`, first cut — was
refused by `test_register` as an empty connection, rightly: recreate-once
already covers an owner who reorganised by hand. The `/folders` counter in a fake counts the ROOT first: "the first
client folder" is the second id.

### A rotating refresh token is spent once — 2026-09-07 (one ship; hash in the memory note)

**The defect, in the owner's words, minutes after reconnecting Canva:**
*"Sign-in was rejected: Refresh token used twice. All access tokens granted
from this flow are now revoked."* — the second lineage in a day, and the
root of the first. Canva's refresh tokens are SINGLE-USE; `oauth.access_token`
hands the successor back (its own comment predicted this failure to the
word) and no caller kept it. `canva._token` minted from the stored token on
EVERY API call, so one edit (upload, poll, design, folder) spent the same
token twice by its second call. Reproduced with a single-use fake endpoint:
the second `_token()` call returns the owner's exact message. Constant
Contact minted the same way; Google survived only because its tokens do not
rotate. The agency fallback shipped earlier that day would have burned the
agency's lineage identically.

**Standing rules it adds:**
- **One door mints.** `credentials.bearer(tenant, provider)` is where an
  access token comes from — Canva, Constant Contact, Google. A caller that
  mints anywhere else spends a single-use token the row does not know about
  (`canva_mints_through_the_one_door`, `constant_contact_mints_through_the_one_door`).
- **The rotation is stored before the token it bought is used.** A crash
  between the two cannot leave a spent token on file
  (`a_refresh_rotation_is_stored_before_the_token_is_used`).
- **One refresh per lifetime, cached ON THE ROW.** Ciphertext in `meta`
  with its expiry, so every worker shares it; a revoked or failed row is
  never read by the resolver, so Disconnect still takes effect — the reason
  `oauth` cached nothing, kept (`an_access_token_is_reused_for_its_lifetime`,
  `the_access_token_is_cached_on_the_row_not_in_the_process`).
- **A caller that waited for the lock re-reads the row.** The secret it
  read before waiting may have rotated
  (`a_caller_that_waited_for_the_lock_rereads_the_row`).

**Traps this stretch fell into.** A fake token endpoint that names every
successor `r<n>` regardless of the seed made a correct rotation read as a
failure — derive the successor from the seed. "Nothing cached" is a rule
about WHERE, not WHETHER: the cache belongs on the row the status gates,
never in a process.

### Every Canva call is the documented one — 2026-09-07 (one ship; hash in the memory note)

**The defect, in the owner's words:** *"Canva: 400: 'name' must be one of the
following: doc, email, presentation, whiteboard, but was instagram-post."*
and the directive: *"make sure you're referencing the api docs when you fix
issues associated with a specific tool."* Read against the published
contracts: there is no social preset — a frame is a CUSTOM design in pixels;
filing is `POST /v1/folders/move` with `to_folder_id` + `item_id`, not the
`/folders/{id}/items` path this code invented (so every design's filing had
been failing as the `filed_error` nobody read, and the recreate-once logic
from earlier that day would have minted duplicate folders on that 404); an
upload name is 50 characters unencoded, not 120.

**Standing rules it adds:**
- **A provider fix starts at the provider's published contract, and the
  contract becomes a suite.** `test_canva_calls_are_the_documented_ones.py`
  carries the URLs it was read from in its docstring, so the next reader
  checks the docs, not the code's memory of them. Every Canva call's shape
  is now a check with a guard (`a_frame_becomes_a_custom_design_at_its_own_size`,
  `only_a_documented_preset_is_sent`, `a_design_is_filed_with_the_documented_move_call`,
  `an_upload_name_fits_canvas_limit`).
- **A refusal names the contract.** `design_type_for` refuses an undocumented
  preset or an out-of-range size with the four presets, the limits and the
  URL — before the call is made.
- **A name this code made up is a bug waiting for its first live call.**
  "instagram-post" and `/folders/{id}/items` survived because no Canva call
  had ever been made for real; the docstrings said "VERIFY on first live
  call" and nobody did. The verify is now the suite.

**Traps this stretch fell into.** A 404 from an endpoint that does not exist
is indistinguishable, to a "folder gone" check, from a folder that does not
exist — a recreate-on-404 must sit behind a call known to be right.

### The product is judged against its own photographs — 2026-09-07 (one ship; hash in the memory note)

**The owner's question:** *"the photos are better but they are still not
recreating the product photos exactly. How can we improve this?"* — and
*"Lets follow your advice."* Reproduced: a drawn frame was filed as it came,
two candidates both kept, neither compared to the photographs it was drawn
from; the prompt said "reproduce exactly" and named nothing; four look pins
rode beside the product; a cutout went up mostly margin.

**Standing rules it adds:**
- **The judge ranks; it never vetoes.** Four candidates per drawn cell,
  every one compared to the product's photographs with the differences
  NAMED, the closest filed with its match; a set with no faithful candidate
  still files its closest and says so
  (`every_candidate_is_judged_against_the_photographs`,
  `the_closest_candidate_is_the_one_kept`).
- **What is wrong is corrected once, by name.** Below `FIDELITY_KEEP` with
  differences named, one redraft with "CORRECT exactly these", kept only if
  closer (`a_wrong_product_is_redrawn_once_with_its_differences_named`).
- **The same checklist on both sides.** Derived once per product from its
  photographs (cached by their fingerprint), it is what the prompt is told
  to keep and what the judge holds as its rubric
  (`the_checklist_reaches_the_prompt`, `the_checklist_is_derived_once_and_cached`,
  `the_judge_holds_the_same_checklist_as_the_prompt`).
- **The look yields to the product; a product input is trimmed.** Two look
  pins when the product is in the request; a cutout cropped to its alpha
  (`the_look_yields_to_the_product`, `a_product_input_is_trimmed_to_the_product`).
- **Fidelity is said on the frame** — "product match 72 · the glyph is a
  star, not the Cancer crab · best of 4" — where the frame is kept or
  rejected (`fidelity_is_said_on_the_frame`).
- **A rendering is not the photograph.** Where exactness is non-negotiable —
  a catalogue-accurate hero — the composite route stays the rule. And
  exact reproduction of a specific object is a provider capability:
  `scripts/bakeoff.py` runs the same product through several models as
  numbered sets for the owner's blind ranking
  (`a_bakeoff_model_reaches_the_request`).

**Traps this stretch fell into.** A trim check on "product-1" passed for
the wrong reason: `pick`'s choice leads the product inputs, and which
photograph that is depends on creation order — find the input by its
property (transparency), never by position. `id(blob)` keys a per-blob
record safely only within one loop iteration; the dict is rebuilt per cell.

---

## 6. Next thread — paste this (UX polish, then whatever the owner brings)

> You are continuing the gomehagent build at `/Users/gomehsaias/Documents/gomehagent-build`
> (deployed at https://assistant-web-zm2d.onrender.com). Read the memory notes
> `gomehagent-systems-effectiveness` (its LAST section first) and
> `gomehagent-walkthrough-handoff`, then `WALKTHROUGH-PROMPT.md` §4 (the protocol,
> unchanged) and §5 (the owner's standing rules and the traps) BEFORE touching
> anything.
>
> **First move:** `python3 scripts/test_rehearse.py` — read its artifacts, not the
> pass line.
>
> Under §4 unchanged: reproduce first; every fix ships a sabotage guard that
> prints `[ caught ]` (run it — and re-run it after any LATER edit to the same
> function, because a guard whose target moved goes stale in the same session);
> ship via `./scripts/ship.sh "<subject>" <body-file>` with the subject on the
> body's first line; never edit the tree while it runs; `python3
> scripts/register.py --write` before shipping whenever a guard or a caller moved;
> verify on `/health`; write the memory note before the thread ends.
>
> **1. THE CREATIVE QUALITY GAP — the owner's live thread, and it outranks the
> rest.** 2026-09-05: *"we still have not defined how we will improve the output
> of the actual generated content. Is it a model difference? Is it an approach?
> an input? A tool that must be used?"* Answered and published; the analysis is
> in the memory note `gomehagent-creative-substrate` and the artifact it names.
> **Read that note before touching any generator** — it carries 70 verified
> findings and, more importantly, four traps that will bite whoever starts:
>
> - `_PLATE_RULE` must be split into THREE constants. Moving the whole string
>   behind `for_product` re-introduces invented products for 100% of Ironside
>   and Coverings frames — the failure this architecture was built after.
> - Phase 3 REOPENS the owner's 2026-09-04 "type belongs in Canva" decision.
>   Do not reverse it unilaterally; re-put it as *type we control, in your
>   font, positioned by measurement, with Canva kept as an override.*
> - No deterministic gate can fail the ad the owner calls horrible. Get ~40
>   labelled frames from them FIRST; ship only the measures that separate.
> - Week 0 is two owner tasks, not code: two direction rows, and a blind
>   ranking of three providers. The "mostly approach" weighting is
>   introspection, and three weeks of renderer rests on it.
>
> **SHIPPED 2026-09-05 on the owner's go-ahead** (`fb00ed1`, `5a95333`,
> `a054632`, `6b93601`, `493b7ac` — 18 guards, rehearsal clean across five
> accounts): the ad's own words and situation reach the picture brief and its
> frames ride back on the export tagged `output:<id>`; a review that did not
> run is no longer counted as a pass and an ad's result reaches the pictures
> that ran in it; "Photographic and real" is off the ad path and the treatment
> lives on the FORMAT with the craft question following it; `_PLATE_RULE` is
> split three ways; every criterion is positive-polarity with the pass-line
> stated; and a WordPress article carries its featured image.
>
> **SHIPPED 2026-09-07: THE VISUAL BOARDS** (one ship, 19 new guards, 5
> re-anchored — §5 has the record). Per brand, named boards of the brand's own
> pictures; the product's photographs and the owned look pins go into the
> request as image inputs; a run selects its boards; the article hero, `pick`
> and the campaign hero reach the same boards through `creative.board_inputs`.
> The owner's next move is not code: create Baci's boards (Studio, Lifestyle,
> the zodiac collection) and pin — the switch is theirs. Then: derive a
> direction row from a board's pins and confirm it; the distance judge that
> ranks and never vetoes; `generate`'s source via `pick`.
>
> **SHIPPED 2026-09-07, SECOND: THE AD IS ABOUT THE THING YOU CHOSE** (7
> guards, §5 has the record). A named entity is exactly the brief's entity
> list; the product's own catalogue facts reach the panel and the drafter; a
> reply that speaks to the operator is a decline the board shows, never copy.
>
> **SHIPPED 2026-09-07, THIRD: CANVA FALLS BACK TO THE AGENCY + THE FRAME
> VIEWER** (9 guards, §5 has the record). A revoked client connection is
> recorded and routed around; folders are per account; the set says whose
> Canva; every frame can be looked at, full size, before it is edited.
>
> **AND THE COPY QUESTION, answered 2026-09-07 — the owner asked what is
> missing for exceptional ad copy.** The answer, in order of leverage: a
> COPY BOARD (the brand's best copy + a swipe file as exemplars — the move
> that fixed the pictures), then the model and prompt diet (drafter and
> panel run Sonnet 4.6 at 400 tokens under a rule stack), then an insight
> step before concepts, then a review harvest for verbatims, then results
> feeding hooks. The owner's move first: 5 exceptional ads + 5 they would
> never run. Memory note `gomehagent-creative-substrate` carries it.
>
> **SHIPPED 2026-09-07, FOURTH: A ROTATING REFRESH TOKEN IS SPENT ONCE**
> (6 guards, §5 has the record). `credentials.bearer` is the one door: the
> access token cached on the row for its lifetime, one refresh under a lock,
> the rotation stored first. Canva, Constant Contact and Google mint through
> it. The owner reconnects Canva once more and the lineage holds.
>
> **SHIPPED 2026-09-07, FIFTH: EVERY CANVA CALL IS THE DOCUMENTED ONE**
> (4 guards, §5 has the record and the owner's standing rule: a provider
> fix starts at its published contract, encoded as a suite with the URLs).
> Frames are custom designs at their own size; filing uses /folders/move;
> upload names fit 50 characters.
>
> **SHIPPED 2026-09-07, SIXTH: THE PRODUCT IS JUDGED AGAINST ITS OWN
> PHOTOGRAPHS** (10 guards, §5 has the record). Best of four per drawn cell,
> the differences named and corrected once, the product's checklist on both
> sides, the look yielding to the product, trimmed inputs, fidelity on the
> frame. `scripts/bakeoff.py --tenant baci --entity <key> --models a,b` for
> the owner's blind ranking; `--reveal` afterwards.
>
> **WHAT IS LEFT NEEDS THE OWNER. Do not proceed past this without them.**
> Two direction rows (Baci, Ironside) — hand them a filled draft to strike
> through. ~40 frames they label horrible/fine, without which any gate you
> build stops broken files and calls itself a quality bar. A ~$20 blind
> ranking of three providers, because the "mostly approach" weighting is
> introspection and the renderer rests on it.
>
> **AND THE ONE THAT IS A DECISION, NOT A TASK.** Ironside and Coverings need
> `compose.photo_with_headline` — the no-generation path, their own photograph
> cropped and typed, already written with zero callers. It SETS TYPE INTO A
> FRAME, which reverses the owner's 2026-09-04 call and collides with the
> guard `no_type_is_burned_into_a_frame`. DO NOT SHIP IT UNILATERALLY. Re-put
> it as *type we control, in your font, positioned by measurement, with Canva
> kept as an override* — a different proposal from the baked DejaVu at a fixed
> position they rejected.
>
> **Before anything: `python3 scripts/test_the_route_sends_what_the_callee_takes.py`
> and `test_ad_arrives_whole.py`.** Make-frames was broken in production for two
> days by a kwarg the route sent and `batch` did not take (`fb00ed1` → fixed
> `ec6d023`). The first is the class-wide check; if you add a kwarg to any
> route→function spread, it is the one that will tell you the receiver was
> not taught. Stub below the seam, never the seam. Then
> `python3 scripts/test_a_claim_knows_what_it_is_about.py` — the zodiac batch,
> reproduced end to end; it is the test that any change to claims, scoping,
> rotation or the ad run must keep green.
>
> **The next three correctness ships, read to the line, before any craft work:**
> coherence's `subject_absent` (coherence.py ~312) NUDGES below
> SUBJECT_MATCH_MIN_WORDS, so a two-sentence ad committed to an entity that
> never names it passes — it needs a matcher reliable enough on short copy to
> block; `claim_trace` files every sentence that is not `about_us`/`off_catalogue`
> as "world" (431/451), so "18 pieces" about a single cup needed no approval —
> it needs an `about_entity` category checked against `KbEntity.attributes`;
> and `panel_prompt` (ad_craft.py:532) still injects a brand-scope claim's
> evidence, mostly closed for new claims and open for already-approved rows.
> Then the swipe file.
>
> **2. UX polish — the other open stream, and it needs the owner.** They walk the
> console and give you the surface; take each as given, one ship each, act where
> you report. There is no list to work from: asking them to open the console and
> name what is wrong IS the first move of this stream.
>
> **3. If the owner gives you an issue instead, do that and only that.**
>
> **What is already done, so you do not rebuild it** (2026-09-04, `c1b607e`..`b20e6f2`):
> the Plan's mix / recommendation / reset / refresh; Ad Creative's Hormozi–Piliero
> panel before the variants, the Instagram caption format, one claim reading per
> variant, frames with no burned type and an integration gate, and the winning
> look read from Meta on a button; and publishing that never waits for a blog to
> be chosen. §5 carries the standing rules each of those added.
>
> **The nearest unfinished edges, if the owner has nothing:**
> - `EFFECTIVENESS["ad_creative"]` still declares the gap "ad_copy is shown no
>   winners or losers when it drafts the next batch". The PICTURES read the
>   winning look now; the COPY does not — `meta_ads.match` joins outcomes onto
>   `Output` rows and no drafter reads them back.
> - `creative.assess`'s other criteria are still notes. `integration` gates
>   because only a composite can fail it; whether any other should is a decision,
>   not an omission.
> - The mix knobs bind the BLOG planner only. Whether a campaign or a post
>   queue wants shares of its own is unasked.
>
> **Still the owner's:** Google's Business Profile API approval (quota 0 until
> then — `gbp.probe` names it), one real Klaviyo push, the first Semrush click,
> `/health/workers` after a day at two instances, and `OPENAI_API_KEY` present so
> the frames actually generate.
