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

## §0 Where this stands (updated 2026-08-28)

Production is on the last commit listed below; every one of them deployed and
was verified at `/health` before the next began. Read §4's step entries for
the detail — this is the map.

**Step 4, tab by tab (spec §§4–11).** Data layer · Connections · Review ·
Systems + workflow · Plan are SHIPPED. Remaining: **Brand (§6)** — the
identity editor and multi-domain source list already landed, so what is left
is the voice deriver behind `_run_bg`, hard-rule REMOVAL (the ban list can be
added to and never subtracted from), and theme-error containment — then
**Assurance (§9)** and **Diagnostics (§10)**. Then step 5 (client product),
step 6 (does Knowledge's Overview fold in), step 7 (completeness audit).

| commit | what |
|---|---|
| `ca6556e` | Multi-domain brand sources — one website, N facts-only landing pages |
| `c55795b` | The send is the approval; drafted replies leave Review |
| `0634bda` | The briefing: ranked by client, bounded, clearable |
| `1d5c563` | Systems board compact + workflow rail |
| `7d9fe94` | `.grp`, and the coverage blind spot that hid it |
| `3b4afa3` | Plan as strategy (Strategy · Schedule rooms) |
| `abf5ec9` | The Schedule runs both ways — planned vs what happened |
| `b7cd6b4` | The artifact is self-describing; `test_sabotage_anchors` |
| `190a581` | Answered mail stops asking; drafts get real names |
| `a3ad78d` | A live draft is not an unanswered thread |
| `99a8ddd` | The queues name the thing; `reconcile_mail` on demand |
| `cec1ad1` | Documentation catches up with the session |
| _next_ | The writer I missed — campaign artifacts carry identity too |

**THE OWNER'S WALKTHROUGH (2026-08-28) is the newest and most valuable input
in this file** — five defects found by using the app, all fixed, all in the
OUT OF BAND entries at the end of §4. One of them corrected a diagnosis of
mine that was wrong (see A LIVE DRAFT IS NOT AN UNANSWERED ONE); the owner
pushing back on it is what found the real bug.

**THE PATTERN THE OWNER NAMED (2026-08-28), recorded in
SYSTEMS-REFERENCE §6b:** three times in this session something was DECLARED
done and was not — "drafts are named in all systems" (two of three
`ArtifactBody` writers), "the guards are green" (one had gone stale in a
shipped commit), "those emails are draftless" (they were not). Each time the
durable fix was the same shape: **turn the claim into a check.** A claim
about EVERY instance has to be computed from the code — `ast` over the
writers, the anchor sweep over the guards — because the instance you did not
think of is precisely the one that is broken. Two suites in this file's
history exist for that reason alone, and both caught something within hours
of being written.

**Standing debts, none of them silent:**
- Three sabotage entries are STALE and carried in `test_sabotage_anchors`'s
  dated `KNOWN_STALE` set: `drafted_is_not_published`,
  `withhold_false_or_forbidden`, `data_layer_says_what_to_fix`. That list may
  shrink and must never grow.
- The briefing's ack links are mutating GETs (Undo is the mitigation);
  POST-ification belongs with the CSRF work in §6.
- Everything still executes in the browser request — the owner has named this
  and parked it behind the UI work, alongside a general optimisation of how
  systems execute. `ArtifactBody.meta` was deliberately done FIRST because a
  worker reading a self-contained artifact is a change of caller, not of data
  model.
- No console surface reviews or reverses digest acks in bulk.
- `_pending_for_system` and the digest once disagreed with the queue about
  the word "waiting"; both now read `decided_in_console`.

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

## §2 Facts (captured at `ed54385`, 2026-08-27 — MUCH OF THIS IS NOW HISTORY)

**Read this section as the STARTING STATE, not the current one.** Most of the
defects catalogued below have been fixed by the steps in §4 and the line
numbers have all moved; `test_sabotage_anchors` is what keeps the guards
honest about where code actually is. Re-verify before relying on any anchor.

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
**4·Data layer AMENDED same day — THE FOUR-TAB CONTRACT (owner,
2026-08-27, reviewing the tab): "the relationship between Knowledge, Data
Layer & Review are not clear enough."** The contract, verbatim intent:
**KNOWLEDGE manages** the approved knowledge by type (add, edit, delete,
scrape new); **the DATA LAYER explains** — how everything connects, how
complete it is, its structure, how systems leverage it, and how effective
it has been "compared to just using a skill without this context /
coherence / compliance layer"; **REVIEW decides** (action items across the
organization — knowledge is approved/denied there); **PLAN is the
strategy** (see the step-4 Plan slot below). Shipped as the amendment:
the six domain management views RE-HOMED to Knowledge (`KB_SUBS` strip:
Overview = the by-type page it has always been, byte-stable — test_kb_ui's
356 checks pass unedited — plus one paged/searchable/editable view per
kind; `_schema_domain` is tab-bound and serves either host; every
back-field and pager URL binds to the hosting tab; the Data layer's
week-old domain addresses 303 to Knowledge with filter/search/page
intact). The Data layer's strip becomes the understanding set — **Queue &
Insights · The map · Leverage · Advanced**. NEW **The map**: a four-column
flow derived live (where a fact enters → the knowledge by kind, with
Knowledge's own counts and "read by N system(s)" → the four gates → the
installed systems, each naming its declared `kb_needs` via `_NEED_KIND` —
a system's reads and the visual cannot disagree by construction); every
node links to the tab that owns it. NEW **Leverage**: the honest
effectiveness answer — there is no ungrounded control arm and the page
says so; what is counted is the counterfactual the assurance ledger keeps
("every one of these is a phrase the model wrote and the layer stopped"):
outputs/grounded/caught/repaired/refused meters, "What would have shipped
without the layer" ranked by rule, per-system reads (green = on file,
amber = missing) with checks/catches. Guards (caught):
`domains_live_on_knowledge`, `map_counts_from_the_kb`,
`leverage_counts_are_real`. Smoke walks Knowledge's six domain sub-views
too. Queue & Insights STAYS on the Data layer: completion-with-inline-fix
is the "completion of the data" surface and rule 1 (act where you report)
keeps the answer box beside the gap it names.
**4·Connections BUILT + SHIPPED 2026-08-27 (spec §11).** Three views on
the `ACCOUNTS_SUBS` strip. **Status** (the default): account card,
capability chips, missing line, connection rows sorted FAILED FIRST
(strip badge = the failed count, same query), and Test connections
converted from a raw-JSON dead-end to a BACKGROUND verify (`_run_bg` —
five live probes must not hang a page) whose per-provider result is
stored (`Setting verify_result:<tenant>`) and rendered ON the card
("Last live test … — hover a chip for the detail"); "Never live-tested"
is the honest first state. **People & links**: portal people
(Revoke CONFIRMS, naming that unused sign-in links die with it; the
Sign-in link button flashes the minted URL on-page as `plink=` instead
of dumping a credential as JSON), the connect-link mint form, and the
intake-links card — all three link flashes now label their copy
affordance. **Advanced**: business-model select, raw wiring with `ui=1`
on every `_field` save (the page's own "Saving reloads to a JSON
response — hit back" copy is GONE, both instances), Add-account and
Grant-access converted to flashes (refusals ride `err=` too; bare JSON
forms survive for hand calls), the bot-access fold reframed as a
neutral **parked by choice** chip with its switch-on condition inside
(it rendered as a working form under a permanent error-styled warning —
a parked decision styled as a defect), and the routes panel as-is.
Connection Disconnect and intake-link Revoke also confirm. Guards (all
caught): `verify_lands_on_the_card`, `signin_link_flashes_back`,
`destructive_asks_first` (which caught its own suite's first, looser
assertion — the pin now binds `onsubmit=`, not the substring),
`parked_reads_as_parked`; `intake_links_have_a_surface` retargeted to
the People view. New suite `test_connections_tab.py`; smoke walks both
new sub-views with class coverage; pins in test_connect_ui, test_oauth,
test_metrics and test_kb retargeted at the views their content moved to,
each with a dated comment. PARKED, named: the purge dry-run (spec
counted it among this page's dead-ends; it actually lives on Review's
catalogue card and converts with Review's own restructure).
**4·Review BUILT + SHIPPED 2026-08-27 (spec §4).** The primary control
decides IN CONSOLE: ship rows POST to NEW `/admin/ship_decide` — the SAME
executor as the signed links (`approvals.apply_decision`), whose own
sentence becomes the flash — with the approve button STATING ITS
CONSEQUENCE per kind ("Approve — pushes the draft to omnisend" /
"Approve & publish" / "Approve — sends it" / "…marks it reviewed,
ready"); the signed /decide links remain the EMAIL mechanism only. Each
row previews THE THING (`_ship_preview`: kept ArtifactBody in a
sandboxed iframe; ad batches list their variants via the board-membership
resolve; text fallback unchanged). EVERY QUEUE PAGES: ship 15, pictures
60-per-page past the old cap, everything-else 15 (+ ONE `pents` datalist
instead of one per card), conflicts 15, plans 15 — a shared `page_req`
threads the requested page past the claims clamp that silently pinned
every other queue to page 1 (a live defect this rebuild exposed). NEW
`_sources_block` at the top: the feeders (Harvest / Mine sent mail /
Store sync / Scan) with last-ran state from `bg_status`, failures loud,
each action beside its state — and the sync action PARKS without a store,
both here and on the renamed **Store sync** section (was "Catalogue" —
it is a sync-and-flags panel; the catalogue lives on Knowledge; key stays
`catalogue` so URLs never break). Pictures: the queue card renders EMPTY
("Nothing waiting — the crawler files what it finds here" + Run
harvest), the add-form folds, entity gets the `ents` datalist. Claims:
the per-card explainer prose reads ONCE in a "How to read these cards"
legend fold (it rendered 15× per page). Plans: approvable rows get
Approve/Skip IN PLACE (`plan_approve`/`plan_skip` grew `back=content`);
complete-it still jumps to the plan's own form. Bulk results render AS
THE FLASH (they were muted .when grey); the purge dry-run flashes its
counts (`ui=1`) — closing the item parked from §11. Guards (all caught,
one MISSED-then-fixed: `sources_lead_the_page`'s find had a
double-escaped newline): `ship_decides_in_console`, `every_queue_pages`,
`sources_lead_the_page`, `store_sync_parks_without_a_store`,
`bulk_reports_are_flashes`. New suite `test_review_tab.py` (24 checks);
retargets with dated comments in test_ship_section (decide buttons →
POST forms), test_workflow_ui (in-place plan buttons), test_kb_ui
(legend + parked sync). PARKED, named: j/k card navigation (spec's
ranked move 6) — a keyboard affordance is worth adding once the owner's
walkthrough confirms the mouse flow; smallest-value move, no structural
cost to defer.
**4·Review AMENDED (owner walkthrough, 2026-08-27) — CARD DECLUTTER +
FILTERS.** Three finds, all shipped in one push: (a) *"the claim cards are
too busy — the metadata should be at the bottom on toggle only"*: the card
now leads with the decision (claim, evidence, scope, duplicates,
situations, buttons) and folds `proof_type · source · origin`, the
found-next-to context, the `proves` field and the usage rule under one
**Details — where it was found, what it proves** toggle BELOW the buttons.
(b) *"the issue of the infinite scroll if I have a lot of claims"* +
*"filter / prioritize"*: the claims queue gains priority CHIPS (all /
came due / brand-level / product-scoped), an origin select built from the
account's real origins, and free-text search over claim+evidence+source+
scope+tags — filter runs BEFORE paging, the pager reports the filtered
depth, the bar names the unfiltered total ("showing 4 of 17"), and the
sub-tab strip count stays the queue's REAL depth so the badge never lies.
No date sort is offered and the reason is recorded: `KbClaim` carries no
`created_at`, so ordering by it would be a sort by accident. (c) *"look
for opportunities to do this on the other approval cards"*: the SHIP
queue gains kind chips (campaigns / articles / replies / ads, derived
from the payload the same way the consequence-button is) + summary
search; **Everything else** gains kind chips + search. FILTERS SURVIVE
THE DECISION — `_back_to_content` grew a `keep=` dict threaded by NAME
(never an echoed URL) through `ship_decide`, `claims_decide` and all five
`claim_edit` exits, so deciding one row keeps the narrowed view the way
`cpage` already kept the page. Guards (all caught): `card_meta_folds`,
`claims_filter_filters`, `filters_survive_the_decision`. Suite
`test_review_tab.py` grew sections 4b/4c (card order, each chip narrowing,
search matching folded metadata, both decide paths preserving filters).

**4·MULTI-DOMAIN BRAND SOURCES — BUILT + SHIPPED 2026-08-27.**
*"Some brands have several domains including landing pages etc that store
their information so we can add that to the brand tab to add all the
sources."* Owner's clarification, which is the whole design constraint:
**one domain is THE WEBSITE; the rest are LANDING PAGES. Branding /
positioning / tone come from the WEBSITE only.** So this is NOT a flat
list of equal domains — it is one primary + N secondaries with different
read permissions, and the code must not blur them:
- `Tenant.domain` STAYS the website and stays the single source for
  identity (`brand_theme` deriver, voice derive, positioning, tone) —
  nothing that reads `t.domain` today changes meaning.
- Secondary sources go in a NEW list (`Tenant.analytics["landing_pages"]`
  or a small table — pick one and say why in the commit), each with its
  own label, and are read for FACTS ONLY: `harvest` (claims/objections/
  images) and `compliance.scan` (a banned phrase on a landing page is
  live too, and today the scan cannot see it).
- Both consumers are single-domain today and each is a one-line seam:
  `harvest.py:432` and `compliance.py:459` both call
  `compliance.discover_pages(t.domain, …)` — the change is to loop the
  source list and CARRY WHICH SOURCE each finding came from, so the
  claim card's Details fold (above) says which site a claim was read off.
- Brand tab gets the editor (spec §6's Identity section): the website
  field labeled as the identity source, plus add/remove landing pages
  with a note stating plainly that voice is never derived from them.
- Guard candidates: `voice_reads_the_website_only` (a landing page must
  never feed the deriver), `harvest_reads_every_source`,
  `scan_covers_landing_pages`.
**Built exactly to that constraint.** STORAGE: a new `Tenant.sources` JSON
column, `[{"url", "label"}]`, landing pages only — NOT `analytics[...]`,
because that dict is the analytics wiring (`ga4_property`/`gsc_site`/
`semrush_db`) that `declared_capabilities` reads for the analytics chip, and
a content-source list hidden behind an unrelated capability means every
reader of `t.analytics` has to know it is two things; NOT a table, because
there is no per-source state to keep — the crawl memory is `HarvestedPage`,
already keyed by page URL, which spans domains as it stands. `db.
_add_missing_columns` makes it a zero-touch migration. ONE READER, one
vocabulary: `tenants.content_sources(key)` returns the website FIRST with
`role="website"`, then the landing pages with `role="landing_page"`, so a
caller reading `[0]` gets identity rather than whichever row was added last;
`source_label(key, url)` names the site a finding came from; `set_website` /
`set_sources` are the canonical writers, and a landing page on the website's
own host is REFUSED WITH A REASON (silently dropping it reads as a broken
form) and dropped again at read time, because `/admin/tenant_set` can still
move the domain by hand after the fact. `_norm` delegates to
`connections.norm_domain` rather than growing a second same-site vocabulary.
THE TWO SEAMS, as designed: `harvest.py` and `compliance.scan` loop
`content_sources`; each carries WHICH SOURCE onto every page it reads
(`source_label` / `site`), each returns a per-source `sources` report, and
"could not enumerate" only fails the RUN when every source failed — naming
each. `domain` and `page_source` still mean the website in both return
dicts, so no existing reader changes meaning. The one thing the design did
not name and the build needed: harvest's page order is now **round-robin
across sources within each of the unread/read bands** — concatenating them
handed the whole budget to the biggest site, so a 500-page website in front
of a 3-page landing site would have read the landing site NEVER, which is
the same defect as not looping at all wearing a fix; the suite pins it with
a budget smaller than the website alone. IDENTITY UNTOUCHED, which is the
point: `voice.gather` and `brand_theme._from_site` still read `t.domain`,
and the suite asserts the deriver fetches ZERO landing-page URLs. CONSOLE:
Brand gains "Where their words are read from" (§6 Identity) — the website
field labelled the identity source, landing pages editable with a per-row
remove, an add row, and the sentence in the page's own words ("Voice is
never derived from a landing page: a page written for one campaign is the
loudest month of the year, not how the brand speaks"); NEW POST
`/admin/brand_sources`, submitted values REPLACE (the identity editor's
contract), refusals ride `err=` as a flash. The claim card's Details fold
now says "read off <site>" — derived from the URL already in `source`, not
stored beside it (rule 8; a stored copy goes stale the moment a page is
relabelled) — and ONLY when the account has more than one source, because
"read off Website" on every card of a single-domain account is a fact stated
once too often. Guards (all three caught): `voice_reads_the_website_only`,
`harvest_reads_every_source`, `scan_covers_landing_pages`. New suite
`test_brand_sources.py` (32 checks); `seed_demo` gives baci a landing page
AND a pending claim read off it, so both the editor and the "read off" line
are clickable, and the single-source accounts still show the quiet case.
Verified on the demo: the card in dark AND light, no horizontal overflow at
desktop or phone width (label/URL share a row and stack when narrow), the
add/remove round-trip, and the website-collision refusal arriving as a
flash. FOUND IN PASSING, not fixed here (one step per push): three sabotage
entries are STALE AT HEAD — `drafted_is_not_published` and
`withhold_false_or_forbidden` (app/skill_pack.py) and
`data_layer_says_what_to_fix` (app/admin_ui.py) patch code that no longer
exists, so those guards test nothing and nothing says so. Worth a sweep that
asserts every `find` appears exactly once, run with the ordinary suite.
**4·Review AMENDED AGAIN (owner, 2026-08-27) — THE SEND IS THE APPROVAL.**
*"Remove 'reply' drafts from the review page. All emails will be considered
approved when they are sent, and the difference between the draft and the
sent email will be the learning difference for the agent to learn from."*
A drafted reply is not a decision this console collects: the draft is in the
client's own mailbox, answering the customer from there IS the approval.
Shipped as three things, because removing the rows alone would have thrown
away the very signal the owner named. (1) **The rows leave**, through ONE
shared predicate `approvals.decided_in_console` — read by the ship queue,
by `pending_count` (the frame's "N waiting" pill, which links straight AT
that queue, so an over-count is a lie you catch in one click — rule 8) and
by `/admin/pending` (whose signed approve link would otherwise mail a
second copy of a letter already sent). Only replies WITH a `draft_id`
leave: a `send_email` with none — an RFQ, an invoice reminder, a shipment
follow-up — exists nowhere but that queue, and dropping those would strand
them silently; the chip is renamed `replies` → `emails` to match the
population that is left, with `flt=reply` kept as an accepted alias.
(2) **The lesson is finally recorded.** `reconcile_drafts` already closed
these rows, and its own docstring promised the delta — `edits` was imported
for it and never called, so the normal path threw the lesson away every
time. It now reads what was actually sent on the thread (NEW
`gmail_client.sent_in_thread`) and calls `edits.record`, which writes
`Approval.payload["edit"]` and `SystemRun.edit_diff` and marks the run
`approved` when it went as-is, `edited` when it did not. (3) **SENT and
DELETED stop being the same event.** To `read_draft` both are one absence;
filing a discarded draft as a send would measure an "edit" against a letter
nobody wrote AND leave the thread owned so no other system could ever
answer it. A deleted draft now closes as `draft_discarded`, records no
delta, and frees the thread in `replies.owner`. An UNREADABLE thread
decides nothing and waits for the next tick — concluding from a network
error would lose a real reply's lesson permanently, since only PENDING rows
are ever revisited. Also fixed in passing, same defect family:
`command_agent`'s WhatsApp-drafted mail created a Gmail draft and then
queued an approval WITHOUT its `draft_id`, so approving composed a SECOND
message on the same thread while the draft sat there — the exact shape
`send_draft` exists to prevent. Guards (all three caught):
`the_send_is_the_approval` (pinned on the shared predicate, so one sabotage
proves the queue, the pill and the fallback at once), `a_sent_draft_teaches`,
`a_deleted_draft_is_not_a_send`. `test_draft_sync.py` grew four sections;
its two `sent_outside` pins were retargeted with a dated comment because the
scenario always MEANT "already sent from Gmail" and the fixture now says so.
NOT changed, named: `_pending_for_system` (Systems tab) and the digest still
count a drafted reply as waiting — it genuinely IS waiting on a person, just
not in the console, and redefining "waiting" app-wide belongs with the
Systems restructure that is the next push, not smuggled into this one.
ALSO in this push: the previous step's `_read_off` reloaded the tenant row
twice per claim card (~30 lookups to render one line); it now takes the
already-loaded source list.

**4·Systems + workflow BUILT + SHIPPED 2026-08-27 (spec §8).** THE BOARD IS
THE SCAN, THE WORKFLOW VIEW IS THE WORK. The card was fifteen kinds of thing
on every row — identity, toggle, workflow link, description, work strip, the
full gate, the autonomy ladder, run stats, promote/demote, an 8-field
contract form, the guidance thread, a hard-rule form and a run log — so a
board of five accounts could not be read, and drawing ONE row loaded that
system's entire run history three times (`stats`, `_shipped_runs`,
`_measured`). Compact now: name · key · rung · **gate chip** (NEW
`_gate_chip`, three states with the FIRST reason — Ready / Blocked — … /
Running thin) · one toggle · one-line description · work strip · Workflow →
(kept PRIMARY: `test_systems_check` pins it as "the place you work" and that
assertion was right — the code was reverted, not the pin). NEW
`_board_counts`: TWO queries for the whole page instead of five per system,
every number still computed from the rows the workflow view lists (rule 8).
The board PAGES (`SYSTEMS_PAGE`, paged before grouping so all-accounts
headings describe what is on the page); the sub-tab count stays the real
depth. Installer entries link at the system they name (they said "installed ·
designed · shadow" and pointed nowhere). **8b, the workflow view** gains the
inner rail every restructured tab has — `WORKFLOW_SUBS`: Plan queue · Drafts
· Waiting on you · Shipped · Measured · Segments (ESP-only, via
`_workflow_subs`) · Settings · Runs — with the four old anchor ids (planned/
waiting/shipped/measured) doubling as sub keys so every existing link lands
right (rule 3); `_sysview_url` emits `&wf=` AND the anchor. NEW
`_settings_section` (full gate with per-blocker fix links, ladder, promote/
demote, contract, thread) and `_runs_section` (the five-number stat, once,
beside the runs it counts). **Waiting decides in place** — it was still
rendering ✅/❌ as bare links into the unstyled `/decide` with no way back,
the very defect Review's queue was rebuilt to end; same `apply_decision`,
consequence-stating button, and `ship_decide` grew `back_system=` so the
redirect returns to THIS tab (rule 3). **One toggle everywhere**: extracted
`_system_toggle`, used by board and workflow view — the latter had a Switch
on / Pause pair, a second labelling for one operation one click away; the
`toggle_says_why_it_cannot_move` anchor line survives byte-identically.
Measured leads with the sent-as-is rate and lists the actual deltas instead
of repeating the board's stat. Creating segments in the ESP — a live write to
the CLIENT'S account — now confirms, naming account and count.
`_pending_for_system` reads `decided_in_console`, closing the follow-up named
in the reply-drafts push. Guards (all caught): `the_board_asks_once`,
`the_board_row_stays_scannable`, `waiting_decides_where_you_are`. New suite
`test_systems_board.py`; `test_workflow_ui` pins retargeted at the rail with
dated comments. TWO OF MY OWN ERRORS, both caught and recorded: the Workflow
button was demoted to secondary against a documented decision (reverted), and
the paging assertion passed for the wrong reason — `_pager` renders NOTHING
on a single page and the check was satisfiable by the word "systems"
appearing anywhere, so it now lowers the cap and asserts a real second page.

**4·Plan STARTED 2026-08-27 — the last undefined class, and the blind spot
that hid it.** Spec §7's P0 named six classes rendering this tab broken;
step 1's token sheet had already styled five, so only `.grp` — the tier /
pillar heading row the architecture and opportunity tables emit — was left.
Defining it is one line. THE FINDING IS WHY NOBODY SAW IT: `.grp` renders
only on a row that exists when the account HAS keywords, and every account
in `test_render_smoke` had none — so the class-coverage check (the one
written precisely because the Plan tab shipped visually broken) walked an
empty Plan tab and reported full coverage of markup it had never rendered.
That is the same shape as the defect it exists to catch, one level up: an
assertion passing because the thing it describes was ABSENT rather than
correct — the `test_console_frame` lesson, again. So the suite now seeds a
real keyword map, `seed_demo` seeds one too (the demo could not show this
tab's tables at all), and NEW guard `data_only_classes_are_covered` fails
only WHILE that seed exists: drop it and the guard goes quiet and says so.
ALSO IN THAT PUSH — **one window control** (spec §7's "two windows, one
control"): `_board_section` was called with a LITERAL 7 while the 7/28/90
control governed only the Progress section below it, so "Moved in the last 7
days" sat directly above a control that silently did not affect it. Both
tables read `days` now, and NEW `_plan_window` renders the control ONCE in
the page header, where it can be seen to govern them.

**4·Plan BUILT + SHIPPED 2026-08-27 (spec §7 + the owner's EXPANDED
INTENT).** `PLAN_SUBS` rail: **Strategy · Schedule · Board · Architecture ·
Progress · Goal &amp; cadence**. Readiness chips and the window control stay
ABOVE the rail because both govern every room. NEW **Strategy** — the
cross-system half the owner asked for ("the plan page should help make sense
of what we want to do and how each system fits into that plan") — surfaces
`strategy.read`, which has existed since the moments work, is deterministic
(no model call), and which NOTHING had ever shown the owner: only
`planner.campaign_rollout` read it. Findings NAMED, NOT SCORED (what is
true / why it matters / what would change it — the `systems.ready()` shape),
the give:ask headline with the honest-zero convention, and beneath it "what
each system is doing about it" from the SAME `_board_counts` the Systems
board renders, so the two pages cannot disagree. Deliberately NOT an
invented finding→system mapping: the findings carry their own fix. NEW
**Schedule** — every system's planned work on one timeline; each system's
Plan queue answered this for itself and nothing answered it for the account.
**Goal &amp; cadence** split out of Progress (`goal_only=`): set once a
quarter, its form was rendering unfolded under a section read weekly, and is
now folded in its own room. `.tblwrap` on the wide tables. TWO FINDS DURING
THE BUILD: (a) my own Schedule classified "no date" by TRUTHINESS while
`plan_complete` requires a VALID one — so a plan carrying an unparseable
date would have been listed under a heading saying it will come due, when
the gate will never pass it; it uses `systems._valid_date` now. (b)
`test_blog_readiness` and `test_console_controls` failed asserting the
publish/measure readiness on the default landing, AND THEY WERE RIGHT: that
block says whether this tab's work can LAND, which governs every room, so
`downstream_html` moved ABOVE the rail rather than the pins being
retargeted. The pins that genuinely moved (the map, the Exclude control, the
goal form) were retargeted at their rooms with dated comments — the Exclude
one at first pointed at Architecture and belongs to Board, caught by
checking where the control actually lives. Guards (all caught):
`one_window_governs_the_page`, `strategy_reaches_the_owner`,
`a_dateless_plan_is_not_scheduled`. New suite `test_plan_tab.py`;
`seed_demo` seeds a keyword map AND planned work across systems so both new
rooms show something real. **AMENDED same day — THE SCHEDULE RUNS BOTH WAYS (owner, 2026-08-27):**
*"if something is changed / added to the plan it should be seen at a high
level on the planning side so we can see what actually happened and what was
planned."* The wiring was already real end to end — `keywords.score` →
`planner.blog_rollout` (pillar before support, cadence, monthly cap) →
`systems.open_plan` → the tick's `systems.plans(due_by=today)` →
`skill.run(run_id=plan.id)`, where **the plan row IS the run row**
(`take_plan` advances the same row: "one row is one item") → artifact →
approval → `keywords.mark_published` writes back. What was missing was that
EVERY Plan-side view filtered `stage == PLANNED`, so a plan VANISHED the
moment the tick consumed it: the tab could show what was coming and never
what became of it. `_schedule_section` now reads the items carrying a
`brief.plan` at ANY stage — one query, not a second "actuals" surface, since
splitting one record across two pages would invent a distinction the data
does not have. NEW `_plan_outcome` names the state and ranks it: **overdue —
held** (with `systems.consumable`'s own reason: system off / incomplete
instruction / the rung wants you — the worker already refuses these every
tick and increments a counter nobody saw), due-and-waiting-for-the-tick,
shipped with its output, skipped with the reason, blocked with `blocked_on`,
no-date. Stuck rows LEAD, with a count. Two things surfaced that the data
already held and nothing showed: `brief["edited"]` (the fields the owner
changed, recorded so the planner cannot overwrite them) now renders as "you
changed: …", and a DIRECT run is deliberately excluded with the reason
stated — it carries no plan, so it is not a departure from one. Guards (both
caught): `the_plan_shows_what_happened`, `a_stuck_plan_says_why`.
`test_plan_tab` grew section 4b. `seed_demo` seeds every state AND every
demo seeder is now idempotent — `open_plan` is idempotent per ref only while
a plan is OPEN, so a consumed one was re-created on each server start and the
demo timeline grew on every restart. PARKED, named: the 9-column
Writing-next trim to 6 with a row-expand (the table is `.tblwrap`-scrolled now, so it no longer
overflows the page — the trim is a readability improvement, not a defect,
and belongs with the owner's walkthrough of what those columns are worth).

**OUT OF BAND — THE ARTIFACT IS SELF-DESCRIBING (owner walkthrough,
2026-08-28).** *"The blog system generates a draft correctly and puts a
preview correctly, but the title, SEO title, and meta description in the edit
area are not available in the review process."* CORRECTED FIRST: the fields
ARE generated (`skill_pack:3505`) and the push IS right — the executor sends
`payload["fields"]`, which carries them; WordPress/Shopify were never the
problem. The bug was that `_article_bundle` finds the approval by scanning
**pending** approvals only, and the workroom read `fields` from it — so a
drafted-but-unqueued or already-decided article rendered a perfect body
preview above three empty boxes. UNDERNEATH IT, SILENT LOSS the owner had not
yet seen: `article_save` wrote the body to `ArtifactBody` but title/SEO/meta
into the approval payload under `if ap is not None`, so typing all three with
no approval pending and pressing a button that says *"the push uses exactly
this"* discarded them without a word. ROOT CAUSE, and the answer to the
owner's larger question about data "hopping around": the artifact was a
complete object only while a decision was pending on it. FIXED by moving
identity to where the thing lives — NEW `ArtifactBody.meta` carries title /
seo_title / seo_description from birth (`ctx.emit`'s `meta` now reaches
`ledger.record`, which was already taking the kwarg and dropping it on the
floor for artifacts); the workroom reads the artifact FIRST with the payload
as fallback for pre-column rows; the save writes it unconditionally; and NEW
`approvals._fields_from_artifact` overlays the artifact's body and identity
onto the payload's machine-set half (handle, structured_data, published) at
publish time — so the edit screen's promise is true by construction rather
than by two copies kept in step by hand. Guards: `the_artifact_is_self_
describing`, `the_push_uses_what_was_reviewed` — the second MISSED on its
first run because the suite called the helper directly, so sabotaging the
real call site changed nothing; it now makes the artifact and the payload
DIVERGE and asserts which one the write read.
**ALSO — A GUARD I BROKE AND SHIPPED.** The bidirectional Schedule rewrite
(`abf5ec9`) replaced the section `a_dateless_plan_is_not_scheduled` was
pinned to, so that guard has been covering NOTHING since it went live. The
full suite was green; the anchor sweep is a separate command and I did not
run it. Repointed at `_plan_outcome`, and NEW SUITE
`test_sabotage_anchors.py` closes the hole: it patches nothing and runs no
sub-suites, only asserting that each of the 163 anchors appears EXACTLY ONCE
in the file it names (once, not at-least-once — an anchor matching twice
patches whichever copy comes first). The three long-standing stale entries
are carried in a dated `KNOWN_STALE` set that MAY SHRINK AND MUST NEVER GROW
(the smoke suite's `ALLOWED_BARE` contract), so they are visible on every run
instead of only when somebody remembers to sweep. Verified by breaking an
anchor, confirming the suite named the right guard, and restoring the file
byte-identically.

**THE OWNER'S WALKTHROUGH, 2026-08-28 — five defects found by USING the
app.** In the order they were found: the blog review page's empty identity
fields (→ THE ARTIFACT IS SELF-DESCRIBING); mail already handled still
sitting in the queue (→ ANSWERED MAIL STOPS ASKING, then corrected by A LIVE
DRAFT IS NOT AN UNANSWERED ONE, which is the one that actually mattered); the
attention card that never cleared (→ ATTENTION CLEARS WHEN IT IS READ);
drafts named `format · timestamp` (→ DRAFTS GET REAL NAMES, extended to the
queues by THE QUEUES NAME THE THING). The entries follow, newest first.

**OUT OF BAND — THE WRITER I MISSED (owner, 2026-08-28).** Owner, with a
screenshot of three rows reading `campaign email · 2026-08-28`: *"Why am I
still seeing that these drafts are not named correctly? This is in the
campaign email system but I asked you to take care of this in all systems."*
Correct. There are THREE places an `ArtifactBody` is constructed —
`ledger.record` (the general path), the ad-batch writer, and the CAMPAIGN
writer, which keeps its own row because the HTML is only final after render,
personalization and rehosting. I wired `meta` through `ctx.emit` →
`ledger.record`, fixed the ad-batch writer, and called it "all systems"
without auditing the third. Fixed on both its branches (create and update,
merging rather than overwriting). Existing campaigns need NO backfill: the
`push` recipe already on the row holds `subject` and `segment_key`, so
`artifact_label` reads it as the fallback — derived, not copied (rule 8).
NEW SUITE `test_artifact_identity.py` makes "all systems" a CHECK instead of
a claim: it parses `app/*.py` with `ast` and fails if ANY `ArtifactBody(...)`
construction omits `meta`. Reading the source rather than exercising the
skills is deliberate — the failure mode is a writer nobody thought about,
and a test that walks the writers it knows about would have missed this one
exactly the way I did. Guard (caught): `every_writer_names_its_artifact`.
`test_sabotage_anchors` caught `a_draft_has_a_real_name` going stale from
the same edit, in the same run — twice in one day it has paid for itself.

**OUT OF BAND — THE QUEUES NAME THE THING, AND A MANUAL RECONCILE (owner,
2026-08-28).** *"Make sure you've changed the naming mechanisms for the
drafts both in the Review tab and inside the workflow drafts tab."* The
Drafts index and the In-progress strip already used `artifact_label`; the
QUEUE ROWS did not — they render `Approval.summary`, and a `skill_output`
summary is `"{skill} for {tenant}: {body[:80]}"`, which for a campaign is
the head of its HTML. So the page whose entire job is choosing between
things titled several of them almost identically. NEW `approval_title`
names a row by its artifact when there is one, keeping the approval's own
summary for everything with none (an RFQ, a theme asset, an SEO update —
those are already written for a person), fed by NEW `_artifacts_for`: ONE
query per page, not one per row. Used by Review's ship queue and the
workflow view's Waiting queue. Guard (caught): `the_queue_names_the_thing`.
ALSO: `reconcile_mail` registered in `ops_jobs.JOBS`, so the mailbox check
can be run on demand (`/admin/run/reconcile_mail`) instead of only on the
worker's 20-minute tick — the owner asked whether existing drafts update
themselves (they do, the query is over ALL pending rows, no backfill) or
whether a check can be run (it could not be). Deliberately NOT a console
button: it would be another action executing in the browser request, which
is the thing the owner has already parked for the worker migration. AND
`/admin/run/{job}` stopped claiming "report will be emailed" — true for
some jobs, not for this one; it names `/admin/status`, which holds every
job's result.

**OUT OF BAND — A LIVE DRAFT IS NOT AN UNANSWERED ONE (owner, 2026-08-28,
correcting my diagnosis).** I told the owner the mail they were looking at
was "draftless"; they answered *"but I have been seeing drafts to these
emails inside of gmail. Are the inbox triage and the lead responder
conflicting?"* — and they were right to push. TWO ANSWERS. (1) NO CONFLICT,
structurally: `worker.py:356` checks `replies.may_reply(... "inbox_triage")`
BEFORE drafting, and `lead_responder`/`service_desk` never draft at all —
`_rehome` only re-attributes the run's LEDGER entry to them when they are
installed and on, so a correction teaches that kind of mail specifically.
One drafter, one draft per thread. (2) MY DIAGNOSIS WAS WRONG about which
rows: triage-drafted replies DO carry a `draft_id` (`worker.py:389`), so the
draftless fix — real, and worth having — was about RFQs and invoice
reminders, not about what the owner was seeing. THE ACTUAL DEFECT:
`reconcile_drafts` stopped at `read_draft`, and a draft that still EXISTS is
not the same as a thread nobody has answered. Reply from a phone, or compose
fresh instead of sending the draft, and the draft sits in the mailbox while
the approval asks to be decided for ever — which is exactly "a list of
emails I've already handled", with the drafts piling up in Gmail beside it.
Now: when the draft is still live, the THREAD is checked too, and a message
sent AFTER the approval was raised (`internalDate`, not the Date header a
client writes) closes it as `answered_elsewhere` — a status distinct from
`sent_outside` because the draft did NOT go and is still there. The delta is
recorded against what the owner ACTUALLY wrote, and the run names the drafts
left behind. It DELETES NOTHING: closing an approval is this function's job,
clearing somebody's mailbox is not. `replies.owner` deliberately does not
free an `answered_elsewhere` thread — somebody did write to that customer.
Guard (caught): `a_live_draft_is_not_an_unanswered_one`.

**OUT OF BAND — ANSWERED MAIL STOPS ASKING, AND DRAFTS GET REAL NAMES
(owner walkthrough, 2026-08-28).** *"There was no feedback for communication
with clients that lets a system know that they have already been answered …
I'm looking at a list of emails that I've already handled."* DIAGNOSIS:
`reconcile_drafts` skipped every approval without a `draft_id` — an RFQ, an
invoice reminder, a shipment follow-up, the report-figures ask — so
answering that person yourself left the row pending for ever. Those are now
asked of the MAILBOX like the drafted ones: by thread when the approval is a
reply, and by NEW `gmail_client.sent_to_since` (one bounded Gmail query,
recipient + date) when it starts a conversation. Closing it records the
delta between what was drafted and what actually went — which is the second
half of the ask ("you should also be getting the feedback of how I answered
so you can inform future responses"): it lands on `SystemRun.edit_diff`,
which `systems.edit_lessons` already feeds back into the drafter, guarded by
the existing `lesson_guidance_reaches_prompt`. AND *"drafts should be
labeled by their relevant identifying elements"*: NEW `artifact_label`, one
function used by the Drafts index, Review's In-progress strip and the
claim-usage link — an email by its SUBJECT · who it is for · what it is
trying to do · date; an article by title · keyword · role; an ad board by
what it sells · to whom · how many variants. Every element was already on
the artifact (`meta`, wired to `ArtifactBody` the push before) and nothing
read it, so four campaigns to four different segments rendered as four
identical `esp campaign · 2026-08-27T10:22` rows on the page whose whole job
is choosing between them. Unknown formats fall back to the old name rather
than a blank. Guards (both caught): `answered_mail_stops_asking`,
`a_draft_has_a_real_name`. AND THE NEW ANCHOR SUITE EARNED ITSELF ON DAY
ONE: the draftless branch files an identical `learn.append` to the drafted
one, so `a_sent_draft_teaches` started matching TWICE — an anchor that
matches twice patches whichever copy comes first, which may not be the one
under test. `test_sabotage_anchors` failed on it immediately; the entry is
re-anchored with the two lines above it.

**OUT OF BAND — ATTENTION CLEARS WHEN IT IS READ (owner walkthrough,
2026-08-28).** *"'Something needs attention' should only show up if a new
issue has appeared. Once I click check systems it should disappear until
there's a new issue. Then the notification icon should disappear."* Same
shape as the briefing's ack, and the same rule: seen means "I have seen
THESE", never "stop telling me". NEW `systems.attention_fingerprint` hashes
the DISTINCT REASONS and deliberately not their counts — the same gap
failing three more runs overnight is one problem continuing, and a card
reappearing because a number moved is the noise this replaces; the trade is
stated in the docstring rather than hidden (a known problem getting worse
stays quiet, and the check is one click away with the full counts). NEW
`mark_attention_seen` is called when the systems check RENDERS, not behind
the one link that points at it, so arriving another way counts too. NEW
`attention_unseen` is read by BOTH the card and the tab badge — one
predicate, because a badge counting what the page does not show is the
lesson the waiting pill already paid for. Guards (both caught):
`attention_clears_when_read`, `attention_returns_for_a_new_reason`.
`test_systems_check`'s pin — which required the card to stand for ever — was
retargeted at the new contract with a dated comment, and now asserts the
whole cycle: raised, read, quiet, a NEW reason raises it again, and MORE of
the same reason does not.

**OUT OF BAND — THE DAILY BRIEFING (owner, 2026-08-27).** Not a console
tab, but the surface the owner actually reads every day, and it had rotted:
*"ever growing daily digest emails that I have no way of clearing or
updating so it's practically useless to me."* Two of its sections had no
bound at all (every pending approval, every past-due deadline, for ever), it
grouped by TYPE across all five clients, and no line carried a control of
any kind. Rebuilt around one item shape — kind · ref · tenant · rank ·
bucket · fingerprint — so ranking, grouping, suppression and the links are
written once instead of per section, and the text and HTML renders read the
SAME structure (they pulled their own rows before, so they could disagree).
**Ranked, by client**: each account leads with its worst thing and the
account with the worst thing leads the email; upcoming, still-open-over-a-
week, and housekeeping sit below as capped lists with real counts. Overdue
money is exempt from the staleness demotion — a bill that falls off the list
is exactly the failure that section would otherwise cause. **Clearable from
the email**: handled · irrelevant · updated, signed links on the same
mechanism approval mail uses (rule 1, act where you report — the owner reads
this on a phone with no session). `updated` is the owner's own reading —
*"the thread context should be updated … it should not reflect outdated
information"* — so it re-reads the source and lets a changed version come
back. **An ack covers the item AS IT WAS**: `db.DigestAck` stores a
fingerprint of what the line said, so a blocked draft that breaks again for
a new reason, or a bill whose amount changed, is a NEW fact and returns
(owner's call over "stay gone"). `irrelevant` is the one that suppresses
regardless — it says the flag was wrong, not the world. A handled deadline
also moves in its OWN status column, carrying `was:` so **Undo** (offered on
the page you land on, since a phone mis-tap on `irrelevant` was otherwise
permanent) restores rather than guesses. The digest was also the last
surface still listing drafted replies as "awaiting your approval" — it now
reads the same `decided_in_console` predicate as the queue and the pill.
Two bugs the build found in itself, both fixed: three signed URLs per line
made the plain-text briefing unreadable (text now carries ONE link per item
opening a three-button page; HTML keeps the three inline), and the `was:`
note was written after the ack row was built, so undo could only guess.
Guards: `a_cleared_item_stays_cleared`, `a_changed_item_comes_back`,
`the_briefing_leads_with_the_client` — the last one MISSED on its first run
because the test account with the worst item was also alphabetically first,
so the assertion passed under either ordering; the fixture now makes them
disagree. New suite `test_digest.py` (39 checks) — the digest had none.
NAMED, not fixed: these ack links are mutating GETs, like `/decide` before
them, so a link-prefetching mail scanner could clear a briefing; Undo is the
mitigation, and POST-ification belongs with the parked CSRF work in §6.
There is no console surface for reviewing or reversing acks in bulk.

Order: **Data layer** (§5 — Queue & Insights + Active Learning + domain
views with pagination/search/editors; Advanced folds the schema reference;
COUNT queries replace full-table loads) → **Connections** (§11 — status-first
rows, JSON dead-ends → `ui=1` flashes, confirm-on-Disconnect/Revoke, parked
states as parked) → **Review** (§4 — rail, in-console approve/deny with
preview on ship, all queues paginated, Sources block, legend-fold, In
progress strip) → **Systems + workflow** (§8 — compact board rows, single
toggle, workflow rail incl. Drafts, Measured dedup, Create-in-ESP confirm) →
**Plan** (§7 — one window control, `.tblwrap`, goal folds, board columns
trimmed; EXPANDED INTENT, owner 2026-08-27: Plan is where the MARKETING
STRATEGY is managed — "keywords are a big part of it but as we run
different systems in parallel and add new systems into it, the plan page
should help make sense of what we want to do and how each system fits
into that plan" — so the restructure adds a cross-system strategy layer
over the keyword plan, drawing on the per-system plans/moments machinery)
→ **Brand** (§6 — voice derive via `_run_bg`, hard-rule remove,
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

### Step 6 — ~~The IA merge (spec §2.3)~~ SUPERSEDED by the four-tab
contract (owner, 2026-08-27): Knowledge and the Data layer stay SEPARATE
on purpose — Knowledge manages, the Data layer explains, Review decides,
Plan is the strategy. The spec's §2.3 merge (retire `tab=kb` into the
Data layer) is dead; nav stays at 9 items. What remains of step 6 is the
small opposite move: once the domain views have carried a week of real
decisions, decide whether Knowledge's Overview one-pager folds into the
per-kind views or stays as the landing. Spec artifact update rides step
7's audit.
- **Gate:** a week of real decisions on the domain views (now on
  Knowledge); smoke + pointers.
- **Checkpoint:** owner confirms nothing they reach weekly got farther
  away.

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
