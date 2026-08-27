# INITIATIVE — UI Overhaul

The console reskin + restructure and the client-product build, executed so that
**every push leaves the whole app usable, every feature lands with its proof,
and the experience never spends a day half-migrated.** The design source is the
spec artifact "Saias Ops Overhaul" (rev 2, 2026-08-27,
https://claude.ai/code/artifact/2c73eb04-9c51-4e1c-b619-134157c9c35e) — §
references below point into it. This file is the working plan; update it as
steps land, the way INITIATIVE-solidify is updated.

Working agreement carried over from the 2026-08-23 walkthrough: **one page at a
time, reviewed with the owner before the next starts.** And the standing rules
paid for in defects (SYSTEMS-REFERENCE §6) bind every step: act where you
report · three states not two · redirects keep the reader's place · one writer
one reader one vocabulary · drafted ≠ published · the owner outranks the
arithmetic visibly · refusals are flashes, never raw JSON · every fact once.

---

## §1 The fluidity contract

Six rules that keep the app feeling whole while it changes underneath:

1. **Reskin before restructure.** The token sheet (step 1) changes every page's
   clothes in one push, so there is never a two-skins era. Structure moves
   later, tab by tab.
2. **A tab restructure ships whole** — rail + sections + pagination in one
   push, never a half-converted page.
3. **URLs and params never break.** New names (`sub=`, `page=`) accept the old
   ones (`view=`, `cpage=`, `ppage=`) as aliases; retired pages 303 to their
   successors (`/admin/article/*` → `/admin/work/*`; later `tab=kb` →
   `tab=schema`). `scripts/test_pointers.py` already refuses unregistered
   paths; keep it green on every push.
4. **Every push leaves all nine tabs + the portal rendering** — asserted
   mechanically by the render-smoke suite (step 0), not by hope.
5. **Rollback is the previous commit.** Push = deploy and there is no staging,
   so every step is previewed on the local demo server before `ship.sh`, and
   every commit on main is itself shippable.
6. **The owner sees each page before the next begins** — the checkpoint column
   in §4 is part of the definition of done, not a courtesy.

---

## §2 Facts (as of `ed54385`, 2026-08-27 — re-verify anchors before relying)

- `app/admin_ui.py` (6,163 lines) renders the whole console: `_CSS` at :85,
  `_shell` at :552, `_TABS` at :393. Two `<script>` tags total. No build step.
- `app/portal_ui.py:119` wraps the sign-in form in
  `<form onsubmit='return false'>` — the nested inner form is dropped by the
  HTML parser; **no client can request a sign-in link** (spec §13, P0).
- `app/admin_ui.py:621` puts the console key in the Client-view URL;
  `portal._sig` HMACs with `(APPROVAL_SECRET or "")` — fails open when empty.
- `web.py:275` `/health` and `:346` `/health/connections` have no auth and
  enumerate inboxes/tenants/shop names.
- `render_plan` (admin_ui.py:5952) uses `.cards .lbl .big .grp .card.warn
  .bad` — none defined in `_CSS`; Plan's readiness strip and error state
  render unstyled.
- Intake links: routes `/admin/intake_new|intake_links|intake_revoke`
  (web.py:1930–1977) exist; no console UI references them.
- The artifact store: `ArtifactBody.body` (current, edited, publishes) +
  `draft_body` (frozen at emit). `/admin/article/{output_id}` edits persist to
  `body` but nothing indexes in-progress work; no versions; no feedback
  capture. `edits.delta` writes `SystemRun.edit_diff` (mail + article paths).
- Learning channels, all real, none surfaced at the artifact:
  `systems.note → feedback_block` (guidance injected into prompts),
  `systems.edit_lessons` (observed, 60d), `systems.promote_rule` (→
  `banned_claims` → validator), `keywords.mute_lessons` (+ accept route).
- Gates at emit: `validator.check`, `coherence.review`, `artifact_check.check`;
  email defects currently ride the ESP campaign NAME (`[NEEDS FIX — …]`).
- Ship path: `scripts/ship.sh` (byte-compile → import → `test_all.sh`) is the
  only sanctioned push; pre-push hook refuses ungated main pushes; ~101 suites,
  97 sabotage guards (8 anchored on admin_ui/web source lines — run
  `python3 scripts/sabotage.py <name>` after touching those regions).
- Frame contract pins (test_console_frame): `class="side"`,
  `<div class="main">` split marker, account name within 400 chars after it,
  "All accounts" placement, `--tint` reaching the page, the
  `>(\d+) waiting<` pill with `sub=ship&tenant=` href, one `all_tenants(`
  call, `gomeh_account` cookie semantics.
- `.claude/launch.json` has one entry (`gomehagent`, port 8099) running
  `app.web:app` against the real env. **There is currently no throwaway-DB
  demo entry** — step 0 adds one.
- Live traffic through these pages: eien campaign approvals, daily article
  review, the mail path. First-live-run rule applies: watch the first one.

---

## §3 Verification machinery (built once in step 0, used by every step)

- **`scripts/test_render_smoke.py`** — renders every tab × every tenant ×
  every sub-view (+ the portal tabs, intake, connect) via TestClient
  (`base_url="https://testserver"`, fresh client per auth assertion): asserts
  200, the frame markers, and — the check that would have caught the Plan tab
  — **every `class="…"` used in the output is defined in the served CSS.**
- **The demo ritual** — `gomehagent-demo` launch entry: scratch
  `DATABASE_URL` (throwaway Postgres/sqlite), `scripts/seed_demo.py` seeding
  all five accounts with representative rows (plans, drafts, pending claims,
  pictures, conflicts, a defective run), `APPROVAL_SECRET=demo`. Every step is
  clicked through here — desktop and a phone width — before `ship.sh`.
- **Per-step acceptance checklist** — each step in §4 names its spec section;
  the step is done when every ranked move in that section is shipped or
  parked-with-reason *in this file*.
- **Pin retargeting convention** — when copy a suite pins must change, repoint
  the assertion at a body-specific marker deliberately, with a comment saying
  why (worked examples: test_console_frame:135–141).
- **Counts-from-lists rule as a test** — every badge/chip count is computed
  from the same query that renders its list (SYSTEMS-REFERENCE rule 8); the
  smoke suite spot-checks Review's badge against the rendered queue lengths.

---

## §4 The steps

Format: **ships · new guards · gate · owner checkpoint.** One step = one or a
few pushes; never interleave two steps.

### Step 0 — Safety rails (no visual change)
**BUILT 2026-08-27, unpushed — owner ships via `./scripts/ship.sh` after the
checkpoint.** What landed:
- The five P0s: portal sign-in un-nested (`portal_ui.py` — the card wrapper
  is a `<div>`, never a `<form>`, with the parser-drop explained in place) +
  portal nav carries `tenant` for owner sessions + `/portal/in/<t>?tab=`
  honoured; `/health` answers **liveness + commit + skills only** without the
  key (the deploy checks stay keyless by design; inboxes/oauth need it) and
  `/health/connections` refuses with a 401 naming why; the Client-view link
  is keyless + `portal._sig` returns None on an empty secret (`_sign` raises,
  `read_session` rejects); the six Plan classes defined in `_CSS`
  (`.cards .lbl .big .card.warn .tbl tr.grp .bad`); the **Intake links card**
  on Connections (folded, live-count summary, copyable URLs, mint via
  `intake_new?ui=1` flashing back as `ilink=`, revoke with a flash).
- The §3 machinery: `scripts/test_render_smoke.py` (every tab × sub-view ×
  two accounts + `*` + portal/sign-in; frame marker; **CSS-class coverage**
  with a shrink-only `ALLOWED_BARE`), `scripts/seed_demo.py` (refuses
  non-demo databases), `gomehagent-demo` launch entry (port 8098, sqlite
  `/tmp/gomeh-demo.db`, key `demo`).
- Seven sabotage guards, each verified `caught`: `portal_signin_submits`,
  `health_is_liveness_only`, `connections_probe_needs_key`,
  `client_view_carries_no_key`, `portal_sessions_fail_closed`,
  `intake_links_have_a_surface`, `plan_classes_defined`.
- One deliberate retarget: `test_canva.py` keys its `/health/connections`
  read (comment in place).
- **Gate (met):** all 102 suites + smoke green; unauthenticated `/health` =
  `{ok, commit, skills}` and nothing more; `/health/connections` → 401;
  sabotage 7/7 caught.
- **Checkpoint (owner, before ship):** run the client sign-in loop once —
  `/portal` → request a link → mint from Connections → People → redeem on a
  phone; and click through the demo server (`gomehagent-demo`).

### Step 1 — The token sheet (the one-commit reskin)
**BUILT + OWNER-APPROVED 2026-08-27, committed `279f8d9` (unpushed).**
`_CSS` values → the token system, dark-first, same class names; dead `.tabs`
rules and every un-themed hex retired; visible focus states; `.tblwrap`
staged; fonts system-stack-first (Hanken Grotesk / JetBrains Mono when
present). Owner's one review find, fixed in the same commit: bare `<a>`
elements had no base rule and rendered browser-default blue on the dark
ground — `a{color:var(--acc);underline}` now, which also makes the Plan
board's pin/mute links read as controls. Gate met: smoke class-coverage +
all 102 suites green. Deviation from the original step text: the SVG icon
helpers move to step 2, where the components that consume them land —
"added, not yet used" would have been dead code in this commit.

### Step 2 — Shared components + frame
- **2a BUILT + committed `adb4b6e` (unpushed): the LIGHT palette + toggle**
  (owner addition 2026-08-27). `body[data-theme=light]` second token block,
  pagehead toggle, `gomeh_theme` cookie (180d), dark default, on-accent inks
  tokenized. Smoke holds token PARITY (light must define every dark token,
  type stacks exempt), toggle persistence, and body-tag attribution — that
  check was wrong twice (grepped the page, matched the stylesheet's own
  comments) before reading the real body tag; the lesson is in the suite.
  Guards: `light_defines_every_token`, `theme_survives_the_session`.
  Verified live on the demo in both themes.
- **2b BUILT + committed `9820629` (unpushed).** Badges: `_badges()` one
  pass per render (Review = proposals + held plans + conflicts + approvals;
  Systems = attention; Connections = failed creds; Data layer = readiness
  next_actions + mute-lesson proposals), amber everywhere, per-part
  fail-to-zero, per-account rollups on the `*` switcher (full=False cheap
  path), titles say what each counts. Single h1 (six body h1s + Assurance's
  triple account-naming removed; "Systems check" → h2, pin intact). ✅/❌ →
  Approve/Deny `.btn`/`.btn.danger` on ship queue + workflow waiting +
  Knowledge decide (test_ship_section retargeted with comment). System-card
  duplicate toggle removed. Plan joins the sticky flash. Sign out link +
  /admin/logout → 303 signin. Unknown tab= → 303 Review with err flash
  (was: silent Connections at 200). Aliases: `sub=` primary everywhere
  (view= accepted), `page=` primary (cpage=/ppage= accepted). Guard:
  `badge_counts_match_lists` (caught). Smoke pins: badge==list, one-h1,
  Sign out, unknown-tab redirect, alias reach, logout door.
  DEFERRED, named: shared render-helper extraction + SVG icon set land with
  step 4's first restructured tab — helpers without a consumer are dead
  code, and the rebuilds are their consumer.
- **Original 2b scope (for reference):**
- **Ships:** one helper each for flash (sticky, three semantics, used by
  Plan/Assurance/Diagnostics too), pager (15/page, above+below, one
  vocabulary), buttons (labeled actions — ✅/❌ retire everywhere the console
  renders them), toggle (single convention; the duplicate on `_system_card`
  dies), styled fold, empty-state block. Frame: single h1 (body h1s removed),
  badge system computed in one per-request pass (Review = decisions incl.
  conflicts + pictures; Systems = attention; Connections = failed creds;
  Data layer = next_actions + unknowns + lessons), per-account rollups on
  `*`, Sign out in the foot, unknown `tab=` redirects with a flash, `sub=` /
  `page=` aliases accepted.
- **New guards:** `badge_counts_match_lists`; retarget the pill/frame pins
  deliberately.
- **Gate:** test_console_frame + test_pointers + smoke; badge numbers match
  queue lengths on seeded demo data.
- **Checkpoint:** owner confirms "is there work?" is answerable from the
  sidebar alone, per account and on All accounts.

### Step 3 — The work loop (spec §3; the owner-named core)
**3.1 + 3.2 BUILT + committed `d6970f7` (unpushed).** `/admin/work/{id}`
absorbs `/admin/article` (303, every pin intact — test_article_review rides
the redirect); three earned properties kept verbatim. `ArtifactVersion`
(v1 = the frozen draft, VIRTUAL — no backfill, no way to version-bug the
draft) + `FeedbackItem` tables, tenant-scoped, classified OPERATIONS in the
same change; `ArtifactBody.state` = the Save-for-later hold, released by a
plain save / publish write-back / mark-as-published. Three indexes: Review
In-progress strip, per-system **Drafts** section on the workflow view, the
Plan board's existing links. Feedback rail live: draft-level stays open
(rides the next redraft), system-level → `systems.note` → the prompt,
rule-level → `promote_rule` → the ban list — each at FILING time, with the
Learned-from-you fold on the page. Guards (all caught):
`draft_survives_edit`, `version_appends_never_overwrites`,
`workroom_indexed`, `feedback_reaches_prompt`, `rule_reaches_validator`.
DEVIATION, named: the redraft route moved from 3.1 into 3.3 — its consumer
is the email workroom, and machinery without a consumer is dead code.
**3.3 BUILT + committed `2d5b101` (unpushed): REVIEW-BEFORE-PUSH + the email
workroom.** Owner inverted the flow (2026-08-27): the ESP draft stays, but
preview/feedback/adjustment happen in OUR data layer first. Emit now HOLDS
the campaign (campaign path writes its own ArtifactBody — rendered HTML,
draft_body frozen; `emit` only carries the validated copy); the workroom
renders it (desktop/phone/plain frames, subject/preheader/segment header,
block-drawn feedback parts, plan fold) with an Adjust-before-push form
writing the approval's `esp_push` payload — which `push_campaign_to_esp`
(the ONLY ESP campaign write; idempotent; refuses withdrawn verdicts and
recorded defects; credits the hero at the real draft) reads when the
APPROVAL executes. [NEEDS FIX] retires with its reason. Same day, same
commit: **draft products are not even OFFERED** — the plan's entity picker
filters draft/archived/unpublished (oos stays, labeled); fitness still
screens the drafter's pool. Six suites retargeted with dated comments;
campaign_variety now proves the executor push end-to-end. Guards (caught):
`draft_products_never_offered`, `approving_pushes_the_draft`,
`push_refuses_withdrawn`. **3.3b BUILT + committed `7dfcadc` (SHIPPED — steps 0–3.3 all deployed
2026-08-27; production /health confirms per push):** `skill_pack.
redraft_artifact` — Request-changes on every held artifact: open
draft-level FeedbackItems + typed note + plan-field overrides
(segment/entity/intent/deadline/angle; entity select draft-filtered) →
fresh run through every gate with the notes FIRST in the drafter brief
(rides `craft` for email / the resolve bundle for articles, so stub
signatures survive and can observe); old row SUPERSEDED (status +
destination `superseded:<new>`, approval withdrawn, workroom page keeps a
forward link, keyword row re-pointed, feedback marked applied). Refusals:
pushed→edit in platform; published→revision path; no direction→reroll
refused. Proven end-to-end in campaign_variety + article_review. Guards:
`redraft_supersedes`, `redraft_carries_the_notes` (caught).
**3.4 BUILT + SHIPPED 2026-08-27: the ad variant board.** The batch is an
`ArtifactBody` (`format="ad_batch"`, JSON of 1–5 variants, anchored on the
first variant's ledger row; `draft_body` = the frozen original, virtual v1)
written by `_run_ad_copy` and rendered at `/admin/work/<anchor>`: one card
per variant with angle chip, amber `needs_art_direction` chip, honest
`composed fallback — not ad copy` chip, the claim it stands on, inline copy
edit (ban-gated like every owner edit, every change appends a version),
inline draft-feedback (`part="variant N"`, the existing rail), and
drop/restore (a judgement, not a delete — greyed card, named consequences).
Any VARIANT's id 303s to its board (ship-queue rows now link "review on its
board"; campaigns gained the same "review in the workroom" link — same
family, same fix). Regenerate rides `redraft_artifact` (same digest — the
`redraft_carries_the_notes` guard binds it) with `ad_copy` gaining
`revision_notes` (notes FIRST in the brief) + `into_batch` (the refill run
writes no second board), but IN PLACE, its own tail: kept variants survive
verbatim (owner edits included), dropped ones are replaced 1:1 through
every gate, replaced rows close as `superseded` with destination
`replaced-in-batch:<successor>` — deliberately NOT `superseded:`, so the
board never renders as a superseded PAGE — and their approvals withdraw
per-variant. Nothing dropped = the whole batch redrafts (the button says
so). Batch decide is one gesture: kept approved first, dropped DENIED;
every state of the bar says **no ad-platform write is wired** (the system's
declared ship). Guards (all caught): `ad_batch_is_kept`,
`ad_regenerate_keeps_kept`, `ad_variant_edit_is_ban_gated`,
`batch_approve_denies_dropped`, `variant_reaches_its_board`. New suite
`test_ad_board.py` proves the loop offline end to end; smoke walks the
board (CSS class coverage + the variant redirect); `seed_demo.py` seeds a
real batch through `skill.run` (ANTHROPIC key stripped first — the demo
must never spend; composed basis is the honest offline face). Verified on
the demo desktop + phone width, dark + light. DEVIATIONS, named: (1) cards
render the copy whole — `_AD_SYSTEM`'s contract is "two or three short
lines, no headline label", so a headline/body/CTA split would misrepresent
the artifact; it waits on a drafter contract that produces structure.
(2) spec §3c's "renderings beside copy" (compose/imagegen previews) parks
with the media layer (build map 05/06) — ad_copy is copy-only by its own
note. (3) per-variant approvals stay (the batch bar resolves them all);
grouping their ship-queue rows belongs to step 4's Review restructure.
(4) no variants-count override on regenerate — replacements are 1:1 with
drops; growing a batch is a new run. On the credential-less demo,
regenerate refuses with its reason (rule 7 — the refusal was made to name
`blocked_on` instead of a bare "blocked"). STANDING WATCH: the first real
batch through board → regenerate → approve, per the first-live-run rule.
Sub-steps land separately, each shippable:
- **3.1 Backend:** `ArtifactVersion` (v1 backfilled from `draft_body`) +
  `FeedbackItem` tables (auto-migrate + backfill in the same change, per the
  migration rule); `/admin/work/{output_id}` route absorbing
  `/admin/article/*` (301/303, pins retargeted); redraft route: re-run the
  skill against the same plan with a run-scoped note, new version appended,
  ESP draft replaced.
- **3.2 Blog workroom** (upgrade in place): Save-for-later state, versions +
  diff, feedback rail (fix-this-draft / teach-this-system / make-it-a-rule),
  Learned-from-you strip, gate findings pinned inline, keyword context
  header, into `_shell`; the three indexes — workflow **Drafts** section,
  Review **In progress** strip, Plan links.
- **3.3 Email workroom:** rendered preview (desktop / 360px / plain-text
  iframe — Brand's mechanic), subject/preheader inline edit re-validated,
  block list with per-block feedback, Request-changes redraft, format +
  intent overrides recorded on the plan, defects render on the page instead
  of only the ESP campaign name. Edit-in-Omnisend stays the post-draft path
  (locked architecture), `edit_diff` at launch unchanged.
- **3.4 Ad variant board:** batch stored as `ArtifactBody` JSON; variant
  cards, per-variant edit/feedback/drop, regenerate-with-feedback,
  `needs_art_direction` chips, approve = batch ready (honest: no ad-platform
  write). May land after step 4 starts if no batch exists to judge.
- **New guards:** `review_is_what_publishes` (kept across the move),
  `draft_survives_edit` (v1 immutable), `redraft_appends_never_overwrites`,
  `feedback_reaches_prompt` (teach-level lands in `feedback_block`),
  `rule_reaches_validator` (promote path), `workroom_indexed` (no
  redirect-only artifacts).
- **Gate:** full loop on demo per kind: plan → draft → feedback → redraft →
  edit → approve → publish/launch-ready → delta visible. Then **watch the
  first live one** on eien (email) and the next real article (blog).
- **Checkpoint:** owner reviews one real article and one real campaign
  through the new loop and files at least one teach-level and one rule-level
  feedback; both visibly land (prompt block / ban list).

### Step 4 — Tab-by-tab restructure (spec §§4–11; one tab per push)
**4·Data layer BUILT + SHIPPED 2026-08-27.** `tab=schema` restructured
whole (fluidity rule 2): a `SCHEMA_SUBS` strip — Queue & Insights (the
landing) · six domain views · Advanced — with counts from the same queries
that render each list. **Queue & Insights**, three lanes: (1) "What to fix,
in order" — readiness blockers with TYPED controls (a missing situation
gets an inline answer box → new POST `/admin/objection_add`, canonical
writer, origin=human so it lands approved and readiness moves the moment
it files; brand/approve blockers keep their labeled link-buttons — one
writer per control), the unknowns inline-save moved here, the intake
question folded, blocked_reasons folded ("what cost an output, 30d");
(2) **Active Learning** — `systems.edit_lesson_rows()` (NEW: the
structured reader `edit_lessons` now formats from, one query for the lane
AND the prompt) with Keep-as-guidance (→ `systems.note`, then leaves the
lane — it lives in the guidance), Make-it-a-rule (typed phrase →
`promote_rule` → ban list), Dismiss (NEW `dismiss_edit_lesson`, a Setting
marker read by the SHARED rows query — a dismiss that only hid the card
would keep teaching the model); mute-lesson TERM proposals with one-click
accept (`exclude_term` grew back-threading), source/cluster patterns
informational with a Plan link (no one-click accept exists for them —
named, not faked); (3) **Grounded output v1** — top-3 claims by 90d
Output.claim_ids usage, the carrying sentence extracted + bolded from the
kept ArtifactBody (ad variants resolve to their BATCH and quote the
variant's own copy, never the JSON), workroom link, per-claim editor link,
uses fold; honest empty/not-kept states. **Domain views** (claims/
objections/audiences/catalogue/situations/photos): paged 15 (`_pager` —
the 2b-deferred shared helper extraction landed here, with `_claim_row`/
`_claim_editor_form`/`_objection_row`/`_situation_overlap_card` pulled
from render_kb's closures byte-identically — test_kb_ui's 356 checks pin
it), search-as-filter, pending-count chips linking at Review, structured
add forms (NEW POST `/admin/kb_row_add` — named fields, same canonical
writers; the pipe textareas survive only on Knowledge until step 6).
Claims: state chips incl. **Removed with per-row Restore** (closes
"restore is still an API call"); audiences: **the editor the kind never
had** (NEW `kb.update_audience` + POST `/admin/audience_update`);
catalogue: per-row add-to-group + this-page bulk fold (the 200-checkbox
wall dies) + Sync from store; situations: folded add + the overlap merge
card moved here; photos: pager past 60 + "N waiting · decide on Review"
chip. **Advanced** = the old page (every pin kept: identifiers,
relationships, no-foreign-keys, APPROVED-only counts) with fill bars from
ONE aggregate query per table (CAST AS TEXT for JSON emptiness — valid on
sqlite AND Postgres where VARCHAR is not) + GROUP BY breakdowns; the
suite asserts against the SQL actually executed that the fill-bar tables
are never full-loaded. **Badge** = `_schema_needs_you()["n"]`, the SAME
computation the queue renders (fixing a live defect: the old badge read a
mute_lessons "proposals" key that never existed, so half the promised
count was permanently zero). Rule-3 back-threading throughout: every
form/link carries back=schema parts by NAME (`_back_parts`/`_back_to_kb`
extended; kb_add, kb_unknown, kb_remove, kb_restore, situation_add,
claim_review, claim_update, objection_edit, merge_situation,
entity_group, exclude_term all honor them; Knowledge's forms unchanged).
Guards (all caught): `queue_answers_land_approved`,
`lesson_guidance_reaches_prompt`, `lesson_dismiss_is_real`,
`claim_restore_has_a_surface`, `schema_badge_matches_queue`. New suite
`test_schema_tab.py` (35 checks); smoke walks all 8 sub-views with CSS
class coverage; test_data_layer + test_kb_ui shape pins retargeted at
`sub=advanced` with dated comments; seed_demo seeds 17 claims (1
removed), an unanswered situation, a gap, and two observed lessons.
Verified on the demo: queue/claims/removed/advanced, desktop + phone,
dark + light. PARKED, named: craft-proposals lane (spec names it; no
carrier exists in code — joins when one does); Grounded-output v2 (live
re-render) stays in §6; the at-a-glance card still counts via
`kb.completeness` (loads 4 kinds once — small; the spec's offender was
the per-table fill loop, which is fixed). Knowledge stays whole until
step 6's gate (a week of real decisions on the new domain views); the
temporary duplication is that gate's design.
Order: **Data layer** (§5 — Queue & Insights + Active Learning + domain
views with pagination/search/editors; Advanced folds the schema reference;
COUNT queries replace full-table loads) → **Connections** (§11 — status-first
rows, JSON dead-ends → `ui=1` flashes, confirm-on-Disconnect/Revoke, parked
states as parked) → **Review** (§4 — rail, in-console approve/deny with
preview on ship, all queues paginated, Sources block, legend-fold, In
progress strip) → **Systems + workflow** (§8 — compact board rows, single
toggle, workflow rail incl. Drafts, Measured dedup, Create-in-ESP confirm) →
**Plan** (§7 — one window control, `.tblwrap`, goal folds, board columns
trimmed) → **Brand** (§6 — voice derive via `_run_bg`, hard-rule remove,
error containment) → **Assurance** (§9 — folds fold, drill filter leads,
catches paginate, per-account scan links on `*`) → **Diagnostics** (§10 —
rail, limit control, orphan adopt/archive, cost off the default view).
- **New guards:** per tab as touched (the 8 existing anchored guards run
  after every admin_ui edit regardless).
- **Gate per tab:** suites + affected sabotage guards + test_pointers +
  smoke + demo click-through of every sub-view and empty state.
- **Checkpoint per tab:** owner walkthrough, same protocol as 2026-08-23;
  next tab does not start until this one passes.

### Step 5 — The client product (spec §§13–16)
- **Ships:** portal five tabs (Overview / **Work** — deliverables via the
  workrooms' client-safe renderers / Results / Your tools with Fix-it connect
  links / We need with period + confirmation), period picker, brand lockup +
  Help contact, mobile keeps identity; the client vocabulary map (display
  names, plain-English states, no repr/slugs/roadmap leaks) **as a pinned
  test**; intake → POST + per-system questions from `kb_needs`/`waiting_on` +
  end-of-flow review screen + branded error pages; client proposals for
  audiences/objections/entities routed through the same pending lane as
  claims; connect completion state + shared error pages; `/decide` framed
  (outcome + back + next-waiting).
- **New guards:** `portal_speaks_client` (vocabulary test),
  `intake_submits_by_post`, `client_rows_land_pending`.
- **Gate:** owner plays a client on a phone start to finish: request link →
  sign in → read Work → fix a "needs re-connecting" tool → answer an intake
  → submit a figure and see the confirmation.
- **Checkpoint:** send one real client the portal only after this gate.

### Step 6 — The IA merge (spec §2.3), one week after step 4's Data layer
- **Ships:** Knowledge's domains fully absorbed; `tab=kb` 303s with the flash
  naming the move; nav drops to 8 items; `test_kb_ui` pins retargeted.
- **Gate:** a week of real decisions on the new domain views first; smoke +
  pointers.
- **Checkpoint:** owner confirms nothing they reach weekly got farther away.

### Step 7 — Completeness audit (the spec's own medicine)
- Walk every ranked list in the spec (§1–§16) and §17's table: each item
  **shipped** (name the commit) or **parked** (name the reason, here).
  No silent caps. Update the artifact to rev 3 with the outcome; write the
  memory.

---

## §5 Effort shape (pushes, not promises)

0: 2–3 · 1: 1 · 2: 2 · 3: 4–6 · 4: 8 (one per tab) · 5: 3–4 · 6: 1 · 7: 0–1.
Steps 0–2 are days, not weeks; step 3 is the largest genuinely new build;
step 4 is steady cadence work gated by owner walkthroughs.

## §6 Parked / out of scope (named, not forgotten)

- **Creative generation goes behind ONE provider-agnostic seam when the
  media layer lands** (owner decision 2026-08-27, while reviewing 3.4).
  Today three disconnected pieces exist: `creative.py` (email hero,
  library→Canva-draft, the only skill-wired path), `compose.py`/
  `imagegen.py` (product compositing + OpenAI scenes, reachable only via
  the manual `/admin/creative` curl route), and nothing for ads or blogs.
  The §3c "renderings beside copy" build must NOT add a fourth per-channel
  generator: one purpose-aware front door (ad | email_hero | …, purpose
  sets the format contract — Meta 1:1/4:5/9:16 vs 1200×600 hero) over
  duck-typed provider adapters, the `esp.py` shape exactly ("adding a
  provider is a profile row plus an adapter module — never a branch inside
  the generator"), because the owner expects to plug in an ad-specific
  image API later. Invariants stay OUTSIDE the providers so no future API
  bypasses them: rights gate (approved+owned only), product fidelity (the
  product is drawn/composited, never model-painted — the Canva
  invented-pitchers and repainted-handle lessons), `basis` on every
  candidate, human approval before anything customer-facing. The board UX
  binds to the seam, so swapping providers never changes how review works.
  REFINED 2026-08-27 (owner): centralized PER BRAND/CLIENT (one library,
  one brand identity per tenant) with a PURPOSE REGISTRY shaping the
  output — ad_creative / blog_header / email_hero / thumbnail / … each
  declare their own format contract (sizes, aspect ratios), composition
  contract (text overlay or none, logo placement, safe areas), selection
  rules, and destination handling. A purpose is data the front door reads,
  never an if-chain inside a generator — adding "thumbnail" must be a
  registry entry, the way adding an ESP is a profile row.

- CSRF + POST-ification of the ~37 mutating GETs — after the restructure so
  URLs move once (spec §17 P2).
- Grounded-output preview v2 (live re-render); v1 (citation search) rides
  step 4's Data layer if cheap, else parks here.
- Client approve/comment lane in the portal Work tab — a later autonomy rung.
- ~~Light-theme console~~ — UNPARKED 2026-08-27 (owner: "Can we also have a
  light mode equivalent and have a toggle in the top header?"). Now ships in
  step 2; dark remains the default.
