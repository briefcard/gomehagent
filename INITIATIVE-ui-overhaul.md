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
- **Ships:** `_CSS` values replaced by the compiled token system (spec §1) —
  dark committed, same class names, dead `.tabs` rules removed, every class
  the smoke suite found now defined, visible focus states, `.tblwrap` +
  component classes available. Inline SVG icon helpers added (not yet used).
  Fonts: system-stack first; self-hosted WOFF2 subsets only if the demo
  click-through misses them.
- **New guards:** none beyond smoke; retarget style-adjacent pins with
  comments.
- **Gate:** smoke class-coverage green; all nine tabs + portal + intake +
  connect clicked through on demo at desktop + 375px.
- **Checkpoint:** owner approves the look on Review + Systems on the demo
  server **before** the push (this is the aesthetic go/no-go for everything
  after).

### Step 2 — Shared components + frame
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

- CSRF + POST-ification of the ~37 mutating GETs — after the restructure so
  URLs move once (spec §17 P2).
- Grounded-output preview v2 (live re-render); v1 (citation search) rides
  step 4's Data layer if cheap, else parks here.
- Client approve/comment lane in the portal Work tab — a later autonomy rung.
- Light-theme console — the console committed to dark; revisit only if a
  second operator asks.
