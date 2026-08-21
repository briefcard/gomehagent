# System workflows — one work ledger, per-system vocabulary

**Status: phases 1 (the substrate) and 2 (the surface) ARE BUILT — see "What
is built" at the end. The planners (phase 3+) are not.** Written
2026-08-21 from the owner's directive in the workflow thread: *"really each
system is going to have its own workflow to track the agent's work. So this is
not unique to just the email"* — and, same day: *"making sure you have
incorporated the mechanism for saving changes to the brief and for each system
having a proper complete brief in advance of execution."* Both mechanisms are
specified below and built.

Read `BUILD-STATE.md` first. This document designs; that file records.

## The problem, stated from the console

Today a system's work is visible only **after** execution, and only in two
places: the run log fold on its Systems-tab card (last 8 rows of stage names)
and the global Review queue. Three consequences the owner has now hit:

1. **"Turn on" reads as a mystery.** For a system with no wired generator
   (`campaign_email` today), going live produces one daily `not_built` ledger
   row and nothing else. The switch is an arming switch, not an ignition, and
   nothing on the card says what would happen or when.
2. **There is no plan object.** What the system *intends* to do — which
   segment, what angle, what subject line, when — does not exist as data
   anywhere. It is decided inside a run and visible only once something has
   already been composed and drafted into a live platform.
3. **Nothing is adjustable before production.** Guidance (prose) and hard
   rules (validator) shape *how* it writes; nothing lets the owner see and
   edit *what it is about to do*.

## The reference implementation already exists

The mail path closed the full loop in August and it is the pattern to
generalise, not replace:

    run → approval carries the Gmail DRAFT ID → approving sends the draft
    itself → an edit made in Gmail travels with the send → edits.py writes
    SystemRun.edit_diff → edit_lessons feeds the next draft's prompt

The load-bearing rule inside it: **the editable body lives in the destination
platform, not in our console.** The approval points at the artifact; shipping
ships the artifact itself; the delta is measured between what was generated
and what actually went out. Whatever goes out is what was approved, and
nothing is left behind. (See BUILD-STATE, "Drafts and approvals are one thing
now".)

Everything below extends that shape to systems that do not answer mail.

## The generic workflow

One work ledger — `SystemRun` — with a per-system vocabulary declared in
`systems.CATALOG`. No new tables in v1.

### One new stage: `planned`

A run may now be opened **ahead of production** by a planner, in stage
`planned`, carrying the plan in `SystemRun.brief` (the JSON column; today it
has exactly one writer, which writes a string — fix in passing). `ref` carries
a stable item key (e.g. `campaign:eien:subscribers:2026-09-04`) so a planner
is idempotent: it never double-files an item whose key already has an open
`planned` row. (The `record_scan` double-file bug is the lesson; a sabotage
entry re-introduces double-filing and the suite must catch it.)

When the item comes due, **the planned row becomes the execution row**:
`skill.run` accepts an existing `run_id` and advances the same row through the
existing stages (`brief → draft → validated → … → sent`), so one row is one
item, attempts and repairs stay on the record as they already do, and a failed
run keeps its plan intact for retry (a retry opens a fresh row with the same
`ref`; dedup applies only among rows still in `planned`).

`stats()` and Diagnostics treat `planned` as **queue, not activity**: a
planned row is excluded from run counts and problem counts until it leaves
`planned`. A queue is not work done, and counting it would flatter every
system that plans a lot and ships nothing.

### The workflow contract, declared per system

`CATALOG[key]` grows a declaration, same style as `kb_needs` — data, never a
fork:

| field | what it declares |
|---|---|
| `unit` | what ONE work item is, plainly named ("a campaign email to one segment") |
| `plan_fields` | the plan's schema — what a planner proposes and the owner may edit |
| `planner` | the proposer, or absent — inbound-driven systems have no planner and skip `planned` entirely |
| `artifact` | where the produced thing lives + its ref shape (`gmail_draft`, `esp_campaign`, `cms_article`, `canva_design`, `proposal_rows`) |
| `ship` | what approving does (send the draft / mark launch-ready / publish / apply the rewrite) |
| `measure` | the edit-delta source and the outcome fields |

The console renders every system's workflow from this declaration with ONE
renderer. A system with no planner says so on its surface ("inbound-driven —
work appears when mail arrives"), never an empty pipeline.

### Saving changes to the plan — the owner's edit mechanism

`systems.save_plan(run_id, edits, planned_for=)` is **the only writer of plan
fields after proposal**, and it holds four rules:

1. **Validated against the declaration.** Every key is checked against the
   system's `plan_fields`; an unknown key is refused BY NAME (the
   `esp.personalize` unknown-token pattern). The same check guards
   `open_plan`, so a planner cannot file a field the owner could not edit.
2. **Blank is not an edit.** The form posts every field; absence of typing
   must not clear a value (the `brand_theme.approve` rule).
3. **Every accepted edit is tracked** in `brief["edited"]`, and a resave is a
   re-attestation. The tracked set is what makes carry-forward mechanical:
   `open_plan` re-proposals update ONLY fields not in `edited` — a planner
   tops up around the owner's edits, never over them (sabotage
   `plan_edit_carry_forward`).
4. **A consumed plan is closed to editing** — "this plan was already
   consumed; changes now belong on the next item" — because the brief on a
   finished run is the record of what ran, and editing a record is how a
   ledger stops being one.

Editing a paused system's plans is allowed (fixing plans while stopped is
legitimate work); consuming one is not.

### A complete brief in advance of execution — the completeness bar

The owner's requirement, enforced structurally rather than remembered:

* Each `plan_fields` entry declares `required`; a **planned date is
  generically required** — a dateless plan can never come due, which reads
  as "queued" while meaning "lost".
* `systems.plan_complete(row)` names what is missing, in the field's own
  label ("Segment", "planned date") — never a bare false.
* `systems.consumable()` — one function, every caller — refuses an
  incomplete plan BY NAME, and the row **stays `planned`**: an
  under-specified instruction is never executed and never fails; it waits,
  visibly, on the Planned surface. (Sabotage `plan_complete_gate`.)
* This is deliberately NOT the knowledge gate. Thin knowledge still produces
  (enrich, don't gatekeep); an incomplete INSTRUCTION never runs. Plan gaps
  are the owner's work on the Planned list, so they are never filed through
  `record_unknowns` onto the client-knowledge queue.
* The planner's own bar mirrors it: a planner proposes only what it can
  read from data; a field it cannot fill stays absent and is named — a
  planner that invents a value produces a plan nobody wrote.
* `approve_plan` refuses an incomplete plan too: approving an
  under-specified instruction would move the refusal one step later and
  make it look like consent.

Consumption is `systems.take_plan`, called inside `skill.run(run_id=…)` so
the gates are structural for every caller — the tick cannot reach execution
around them. Every refusal happens **before** the row flips, so a held plan
is never half-consumed. Two further refusals at that last gate: a plan
carrying a field the skill no longer accepts ("the declaration drifted") and
a caller trying to override a plan field at the call ("the plan is the
reviewed instruction"). The suite also pins declaration-vs-skill agreement
statically, so growing a plan (subject line, planned hero) and teaching the
skill to honour it must land in the same change.

### Rules carried over — each one already paid for

* **The switch is the dictator.** A paused system's planner stops
  (`open_plan` refuses a system that is not live) and its planned rows are
  un-consumable (sabotage `plan_switch_gate`). Only `live` plans, only
  `live` produces. Editing a paused system's plans stays allowed.
* **Plans ride the autonomy ladder — no second ladder.** `shadow` and
  `approve_all`: every plan needs an explicit `approve_plan` before it may
  be consumed — because EXECUTION itself has side effects
  (`campaign_email` drafts into the live ESP whenever the copy validates,
  on any rung — `item["ok"]` is the validator's verdict, not the rung's —
  and a run spends model budget). `approve_exceptions` and `auto`: due
  plans consume without the extra tap. And no rung, ever, launches a
  blast: `send_campaign(confirm=True)` stays uncalled by the substrate.
* **Owner edits win and carry forward.** An edited plan field survives
  re-proposal, exactly as owner-edited theme fields survive re-derives
  (rule 3). A planner may top up around the owner's edits, never over them.
* **Absence survives to the output.** No planner → said on the surface. No
  approved hero → the plan says `imageless` and why. An empty stage renders
  its reason and the control that would widen it, never a blank.
* **Enrich, don't gatekeep.** A thin plan produces, labelled. Only an absent
  connection (or a constitutive gap like an empty ban list on a compliance
  sweep) blocks.
* **Nothing generated in a run ships in that run** when it needs human
  finishing — the Canva-hero pattern (a drafted design cannot be a hero;
  the export enters the review queue; the NEXT run uses it).
* **Structural exits stay structural.** Production still leaves through
  `Context.emit` (validator, repairs, approval queueing); ship paths still
  pass their own guards (`seo_guard` on anything that writes to a live site).

## Per-system workflows

The table the whole design exists for. "Today" is honest state, not ambition.

| system | unit of work | planner | artifact | ship (what approving does) | measure | today |
|---|---|---|---|---|---|---|
| `inbox_triage` / `lead_responder` / `service_desk` | one thread's reply | none — inbound-driven | Gmail draft | approving **sends the draft itself** | `edits.py` delta; sent-as-is rate | **loop fully built**; needs only the surface |
| `campaign_email` | one campaign to one segment | rollout proposer: segments (catalog + live ESP audiences) × angle (positioning/claims) × subject proposal × hero readout (`creative.hero_for_campaign` basis) × planned date | ESP draft campaign (id + edit link) | marks **launch-ready**; launch stays human, in the ESP | generated HTML vs ESP draft at launch; ESP stats later (needs `reports`) | skill proven offline, deployed dormant; planner + wiring = the build |
| `ad_creative` | one ad batch (audience × entity) | proposer from proven claims + audiences | copy variants (`basis`, `needs_art_direction`); later: composed images in 1:1 / 4:5 / 9:16 + Canva handoff | marks ready — **no Meta write is wired**, and the surface says so; later: create paused ads | `record_asset_outcome` per channel (the output→ad-id join is unbuilt; fed by hand) | copy-only skill exists; no imagery path wired |
| `blog` | one article against one keyword | keyword-map proposer | CMS **draft** article (`create_article` drafts by default — built) | publish via `update_article`, behind `seo_guard` | draft-vs-published delta; GSC later | publish path built both CMSes; no planner; Ironside blocked on the Squarespace decision |
| `content_compliance` / `catalog_compliance` | one sweep; each proposed rewrite is a child item | the schedule itself (Mon 04:30, `SCHEDULED_ELSEWHERE`) | findings + proposed rewrites | apply the rewrite, through `seo_guard` | violations trend per sweep, `by_phrase` | sweeps scheduled and live; findings reach the digest; no accept-rewrite surface |
| `reorder_engine` | one replenishment prompt per cohort | purchase-cadence proposer (unbuilt) | ESP draft | launch-ready, human launch | provider stats later | declared only |
| `reports` | the weekly number, one report | the calendar | the report document | send to client (approval) | n/a — it IS the measurement | declared; still the largest empty thing (provider figures) |

## The console surface

Per the owner's standing UI rules (`ui-surfaces-not-hyperlinks` memory): real
sections, state first, each fact once, queues paginate, empty states carry
their reason and their control.

1. **The Systems-tab card grows one work strip** — state, not prose:
   `3 planned · 1 waiting on you · 4 shipped this week · 7 of 9 sent as-is`.
   Each figure links into the system's own view. The strip replaces nothing;
   the gate/rung/stats stay.
2. **Each system gets its own workflow view** — a real section inside
   `_shell`, account-scoped, at `tab=systems&system=<key>` (no new top-level
   tabs; nav stays eight items). Sections in work order:
   * **Planned** — plan cards, PREFILLED and editable in place (rule 13),
     paginated ~15, planner button leads ("Propose the next N"), each card:
     approve / edit / skip. For `campaign_email` this IS the email schedule
     the owner asked for: segment, angle, subject, hero status, date.
   * **Waiting on you** — this system's approvals, each with its artifact
     link (open the Gmail draft / the ESP draft / the Canva design).
   * **Shipped** — artifact refs, dates, who launched.
   * **Measured** — sent-as-is ("7 of 9", never a percentage of three),
     edit-delta trend, outcomes per channel; every unmeasurable figure named
     with its reason (`not_yet_measured` pattern).
3. **The Review tab gains ONE new card kind:** "Plans awaiting review", across
   systems, one kind of thing per card. The sidebar Review badge counts plans
   beside approvals — zero clicks to "is there work".
4. The per-system view renders for EVERY installed system from day one — the
   inbox family's is complete immediately because its ledgers already exist.

## Scheduler

`systems_tick`'s "the generator lands here" slot becomes real. For each live
system **with a planner**: (a) top up `planned` rows to the system's horizon —
propose only, never consume; (b) consume due plans whose rung allows it, via
`skill.run` against the planned row. Daily granularity stays — the tick's
question is still "what should happen today". `not_built` keeps its meaning
for systems whose contract declares no planner and no generator.

Cadence and horizon live in `System.config` (JSON, exists), with per-system
defaults in `CATALOG` — e.g. `campaign_email`: horizon 30 days, at most N per
segment per month. Numbers are the owner's to set; the defaults must be
conservative.

## Measurement

`SystemRun.edit_diff` generalises exactly as the build plan recorded ("capture
sent-vs-draft where editing actually happens"): per artifact kind, compare the
generated body against the artifact at ship time — Gmail draft at send
(built), ESP draft HTML at launch, article body at publish. The Measured
section is where the owner's four standing goals become visible per system:
drafts improving (delta trend), context used (grounding rate is already on
Assurance), hard rules respected (catches), and the sent-as-is rate he named.

## What v1 deliberately does NOT do

Parked by choice, not blocked:

* **No new tables.** The plan lives in `SystemRun.brief` (JSON). A column is
  promoted only when a query needs it — "declared and never written is this
  codebase's signature defect", and so is the reverse.
* **No provider metrics.** Opens/clicks/revenue stay with the unbuilt
  `reports` system, already recorded as the largest empty declaration.
* **No Meta ad writes, no auto-launch anywhere, no client-portal exposure**
  of workflows yet.
* **No per-system UI forks.** One renderer, driven by the declaration.

## Build order

1. **~~The contract + the `planned` stage.~~ DONE — see "What is built".**
2. **~~The surface.~~ DONE — see "What is built".**
3. **`campaign_email` end to end.** The rollout planner (calls `open_plan`
   per segment × date, proposes only what it reads from data); first live
   Omnisend draft round-trip. This ABSORBS BUILD-STATE's recorded next-step
   3 (wire campaign_email to a route + agent tool) — the route becomes the
   workflow surface. Owner steps 1–2 recorded there (segments dry-run/apply,
   deriver on Eien) still come first. Growing the plan with `subject` /
   planned-hero fields lands HERE, together with the skill honouring them —
   the drift pin in `test_plans.py` forces the pairing.
4. **Compliance into the surface.** Findings + accept-rewrite (through
   `seo_guard`) as the sweep's child items.
5. **`ad_creative` planner** (copy-only, absence of imagery named), **`blog`
   planner** (keyword map), then `reorder_engine`/`reports` as their
   generators land.

## What is built (2026-08-21, phase 1 — the substrate)

* `systems.CATALOG[*].workflow` — every catalogue system declares
  `unit / skill / plan_fields / artifact / ship / measure`;
  `campaign_email` and `ad_creative` are plan-capable today (their fields
  are exactly what their skills accept — the drift pin enforces it), the
  rest declare their unit and ship semantics for the surface.
* `systems.py`: `workflow()`, `plan_capable()`, `plan_complete()`,
  `open_plan()` (idempotent per `ref`, carry-forward around
  `brief["edited"]`, live-only), `save_plan()` (the only writer;
  validated; blank≠edit; tracked), `approve_plan()` (refuses incomplete),
  `skip_plan()` (terminal `skipped`, decision `denied`, reason kept),
  `plans()` (dateless is never due), `consumable()` (switch + bar + rung,
  one place), `take_plan()` (every refusal before the flip; drift and
  caller-override refused). `stats()` and `can_promote()`'s clean tail
  exclude `planned` — queue is not activity, and plans must not dilute
  the promotion gate.
* `skill.py`: `run(run_id=…)` consumes a plan — the plan's fields become
  the params, the SAME row advances (one row is one item), the brief
  survives execution (and the old string-into-JSON `brief` write is now a
  dict). A blocked preflight on a consume files nothing and leaves the
  plan `planned` — no daily blocked row per stuck plan.
* `worker.systems_tick`: consumes due consumable plans per live
  plan-capable system; a day where plans ran files NO evaluation row (the
  consumed runs are the record); a quiet day files ONE `skipped` row
  saying how many are queued and how many are held and why — never
  `not_built`, because these systems' generator exists.
* `diagnostics`: `planned` split out as `queued` before anything is
  counted — an old open plan is not a stale run, and the log shows
  "queued — planned for <date>".
* `scripts/test_plans.py` (52 checks) + four sabotage guards
  (`plan_edit_carry_forward`, `planner_double_file`, `plan_complete_gate`,
  `plan_switch_gate`), all caught. Note the guard set differs from this
  spec's first draft: `planned_ship_gate` became `plan_complete_gate` —
  completeness IS the pre-execution bar, and "nothing ships from planned"
  is structural (a consumed row goes through the normal `skill.run` path
  and `Context.emit`; there is no other door to patch out).

## What is built (2026-08-21, phase 2 — the surface)

* **The per-system workflow view** — `admin_ui._system_view` at
  `tab=systems&system=<key>`, a real section inside the frame,
  account-scoped. Sections in work order: Planned (plan cards prefilled and
  editable in place, paginated at 15 with the pager on the page; approve /
  save / skip per card; a "Plan one by hand" form derived from the
  declaration — open on the empty state, folded once plans exist, replaced
  by the plain state when the system is off), Waiting on you (pending
  approvals matched by system_id OR run_id), Shipped, Measured (sent-as-is
  from captured deltas; un-captured sends named, never a flattering zero),
  the runs fold, a folded how-to-read. The header carries the GATE when the
  system cannot produce — a queue that can never drain says so where the
  queue is.
* **The work strip** on every Systems-tab card — planned · waiting on you ·
  shipped this week · sent as-is — each figure linking into its section,
  plus a "Workflow →" button.
* **The Review tab's "Plans awaiting you" card** + the sidebar badge now
  counting held plans (`systems.plans_needing_action`): an incomplete plan
  says what to complete, a complete one on shadow/approve_all says
  "approve it", and each row lands on the exact card.
* **Routes** `/admin/plan_new` (mints `manual:<id>` refs — idempotency-by-
  ref is for planners, not people), `/admin/plan_save`, `/admin/plan_approve`,
  `/admin/plan_skip`; every redirect returns the reader to the exact card on
  the exact page.
* **Two fixes found by looking at the rendered page:** the tick no longer
  counts a `skill.run` refusal as a consumption (a blocked system's due
  plans now fall through to the honest blocked evaluation row — pinned in
  the suite), and `skill_pack._flag` parses yes/no strings for the two
  toggle fields, because plans carry text and `bool("no")` is True.
* `scripts/test_workflow_ui.py` (40 checks, TestClient over the real
  routes) beside `test_plans.py` (71).

**Dormant in production still:** no planner exists and `campaign_email` is
live for no account. The surface renders every installed system's view today
— the inbox family's is complete because its ledgers already exist — and the
plan machinery holds data only where somebody files a plan by hand.

## Open decisions for the owner

1. **Cadence numbers** per system (`campaign_email` horizon and per-segment
   monthly cap first) — needed for phase 3's planner, stored in
   `System.config`.
2. Built as recommended, overrule at will: the UI word is **"Plans"**, the
   per-system view lives **under Systems**, and the rung mapping puts the
   explicit plan tap on shadow / approve_all.
