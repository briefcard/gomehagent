# Systems Reference

**§2 is GENERATED** by `scripts/gen_systems_reference.py` from
`systems.CATALOG`, `skill.REGISTRY`, `planner.PLANNERS` and `dossier.SCOPES`,
and `test_catalog_vocabulary.py` byte-compares it — so it cannot drift from
the code without the suite going red in the commit that moved it. It used to
say "derived from the code at `ea420b7`", by hand, and by 2026-08-31 it named
four of `campaign_email`'s seven `kb_needs` tokens. A document that describes
the code is a build artifact; hand-maintaining one is hand-maintaining a
compiled binary.

Everything OUTSIDE the generated markers is judgement no walk produces — the
design rules §6 paid for in defects, the integration notes, the cross-system
joins — and stays hand-written, here, on purpose.

---

## 1. The machinery every system rides

A **system** is one pipeline installed per account (`db.System`), a **skill**
is its one unit of work (`skill.REGISTRY`), and everything a skill produces
leaves through `Context.emit` (`skill.py`) — the only exit — where three
deterministic gates run: `validator.check` (may this be said: ban list,
citation), `coherence.review` (is it about the thing it committed to), and
`artifact_check.check` (is it intact: mangled words, unlinked subjects,
placeholder leaks). None is a model reading its own work.

**Universal per-system settings — every system's UI must expose these**
(columns on `db.System`, `db.py`):

| field | values | notes |
|---|---|---|
| `status` | designed · live · paused · retired | the switch; plans file and runs consume only when `live` (`systems.is_on`) |
| `autonomy` | shadow → approve_all → approve_exceptions → auto | promotion is EARNED: `GATES` = 20 runs/90%/10-clean for approve_exceptions, 50/95%/20 for auto (`systems.py`); demotion is free (Down-a-rung control) |
| contract | job_replaced, owner, baseline, primary_metric, counterfactual, kill_criteria, failure_mode, weekly_artifact | advisory, not gating (owner 2026-08-20); gates only promotion |
| `config.cadence` | per-system dict | see each system |
| `config.goal` | organic_clicks, top3, top10, horizon_days | blog only today; **no defaults, ever** — a target nobody chose is a bar nobody can fail (`systems.GOAL_FIELDS`) |

**How work flows:** a planner files plans (`systems.open_plan`, idempotent
per `ref`, owner edits carry forward) → the 07:00 tick or a Run-now consumes
them through `systems.take_plan` (switch, completeness, rung — structural,
uncircumventable) → `skill.run` resolves one grounded bundle → draft → gates
→ `ledger.record` (the decision) + `ArtifactBody` (the artifact, whole, with
`draft_body` preserved for the edit delta) → approval where the rung demands
one → executor ships and **writes back** (`keywords.mark_published`).

**Entry points to `skill.run`** (audited 2026-08-26): the tick (only systems
declaring `workflow.skill`), the weekly compliance sweep, `/admin/plan_run`,
`POST /admin/skill_run` (any skill), and the admin agent's `run_skill` tool.
The mail path bypasses skills entirely (`triage.py` drafts in its own loop).

---

<!-- BEGIN GENERATED: the ten systems — scripts/gen_systems_reference.py -->

## 2. The 10 systems

**Generated — do not edit between the markers.** Every line below is read out of `systems.CATALOG`, `skill.REGISTRY`, `planner.PLANNERS` and `dossier.SCOPES` by `scripts/gen_systems_reference.py`. The prose sections around it are judgement and stay hand-written.

### `ad_creative` — Ad creative

Drafts grounded ad copy from approved claims against an audience and an entity. Copy only — imagery waits on the media layer.

- **Connections:** at least one of `ads`, `commerce`
- **Knowledge (`kb_needs`):** `tone`, `banned_claims`, `audience`, `claim`, `entity`
- **Skill** `ad_copy` — produces `draft`, tier 3, writes=False
  - parameters: `entity_key`, `audience_key`, `variants`, `utterance`, `revision_notes`, `into_batch`, `offer`, `deadline`, `funnel_stage`, `positioning`
  - constitutive (no draft without it): none
- **Planner:** none — plans are filed by hand or by another system
- **Plan fields** (the plan UI; `*` required): `entity_key`*, `audience_key`* (audience), `variants`
- **Unit:** one ad batch for one audience × entity
- **Artifact:** proposal_rows
- **Ship:** approving marks the batch ready, then the copy is carried to the platform by hand and the join finds it again
- **Measure:** asset outcomes per channel, joined by `meta_ads.match` on the copy itself
- **Brand-document scope:** identity, rules, claims, context, catalogue, gaps

### `blog` — Blog / content

Writes grounded articles against the keyword map, and publishes them where there is somewhere to publish to.

- **Connections:** —
- **Knowledge (`kb_needs`):** `tone`, `banned_claims`, `audience`, `claim`
- **Skill** `blog_article` — produces `draft`, tier 3, writes=True
  - parameters: `keyword`, `role`, `cluster`, `angle`, `entity_key`, `entity_keys`, `utterance`, `audience_key`, `revision_notes`
  - constitutive (no draft without it): `banned_claims`
- **Planner:** `blog_rollout`
- **Cadence knobs:** `articles_monthly`=4, `horizon_days`=45
- **Plan fields** (the plan UI; `*` required): `keyword`*, `role` (choice, pillar|support), `cluster`, `angle`, `entity_key` (entity), `entity_keys` (entity_list)
- **Unit:** one article against one keyword
- **Artifact:** cms_article
- **Ship:** publishes the draft article, behind seo_guard
- **Measure:** draft-vs-published delta; position change in `keywords.progress`, against a control
- **Brand-document scope:** identity, rules, claims, context, gaps

### `campaign_email` — Campaign email

Builds and schedules campaign sends from the catalogue and calendar.

- **Connections:** `esp`
- **Knowledge (`kb_needs`):** `tone`, `banned_claims`, `entity`, `claim`, `objection`, `audience`, `asset`
- **Skill** `campaign_email` — produces `draft`, tier 3, writes=True
  - parameters: `revision_notes`, `segment`, `goal`, `subject`, `intent`, `deadline`, `entity_key`, `audience_key`, `offer`, `utterance`, `draft_visual`
  - constitutive (no draft without it): none
- **Planner:** `campaign_rollout`
- **Cadence knobs:** `horizon_days`=21, `per_segment_monthly`=1, `segment_rest_days`=6
- **Plan fields** (the plan UI; `*` required): `segment`* (segment), `audience_key`* (audience), `goal`, `subject`, `intent` (choice, story|education|proof|offer), `entity_key` (entity), `deadline`, `offer`, `draft_visual` (flag)
- **Unit:** a campaign email to one segment
- **Artifact:** esp_campaign
- **Ship:** marks it launch-ready — launching stays human, in the ESP
- **Measure:** our first draft vs what you approved
- **Brand-document scope:** identity, rules, objections, claims, context, catalogue, gaps

### `catalog_compliance` — Catalogue compliance

Checks product copy and SEO metadata in the store against the brand's own banned claims, and proposes compliant replacements.

- **Connections:** `commerce`
- **Knowledge (`kb_needs`):** `banned_claims`
- **Skill** `catalog_compliance` — produces `report`, tier 1, writes=False
  - parameters: `site`, `limit`
  - constitutive (no draft without it): `banned_claims`
- **Planner:** none — plans are filed by hand or by another system
- **Brand-document scope:** identity, rules, context, gaps

### `content_compliance` — Website content compliance

Checks the live site against the brand's own banned claims and reports the pages that break them.

- **Connections:** —
- **Knowledge (`kb_needs`):** `banned_claims`
- **Skill:** none — nothing generates for this system
- **Planner:** none — plans are filed by hand or by another system
- **Brand-document scope:** identity, rules, context, gaps

### `lead_responder` — Lead responder

Answers an inbound enquiry with a grounded, approved draft.

- **Connections:** `inbox`
- **Knowledge (`kb_needs`):** `tone`, `banned_claims`, `audience`, `objection`, `claim`, `next_steps`
- **Skill:** none — nothing generates for this system
- **Planner:** none — plans are filed by hand or by another system
- **Unit:** one thread's reply
- **Artifact:** gmail_draft
- **Ship:** approving sends the draft itself
- **Measure:** edits.py delta; sent-as-is rate
- **Brand-document scope:** identity, rules, situations, objections, claims, context, lookups, gaps

### `moment_email` — Moments (windows worth writing into)

Watches for windows opening — a cart gone cold, an enquiry gone quiet — and lets what it finds decide which cohort the campaign planner writes to next, and when.

- **Connections:** at least one of `commerce`, `inbox`
- **Knowledge (`kb_needs`):** —  ·  `needs_kb=False`, so readiness falls back to `kb.completeness`
- **Skill:** none — nothing generates for this system
- **Planner:** none — plans are filed by hand or by another system
- **Unit:** a window noticed, and the cohort it argues for
- **Artifact:** none — it proposes nothing and sends nothing
- **Ship:** informs the campaign planner; the campaign system does the sending, under its own switch and its own rung
- **Measure:** moments consumed into a plan vs moments that expired unserved
- **Brand-document scope:** identity, rules, context, gaps

### `reorder_engine` — Reorder engine

Triggers replenishment prompts off purchase cadence.

- **Connections:** `commerce`, `esp`
- **Knowledge (`kb_needs`):** `entity`
- **Skill:** none — nothing generates for this system
- **Planner:** none — plans are filed by hand or by another system
- **Unit:** one replenishment prompt per cohort
- **Artifact:** esp_campaign
- **Ship:** marks it launch-ready — launching stays human
- **Measure:** provider stats, once `reports` exists
- **Brand-document scope:** identity, rules, context, catalogue, gaps

### `reports` — Reports

The weekly number, assembled from whatever is connected.

- **Connections:** at least one of `analytics`, `ads`, `commerce`
- **Knowledge (`kb_needs`):** —  ·  `needs_kb=False`, so readiness falls back to `kb.completeness`
- **Skill:** none — nothing generates for this system
- **Planner:** none — plans are filed by hand or by another system
- **Unit:** the weekly number, one report
- **Artifact:** report_document
- **Ship:** sends it to the client, on approval
- **Measure:** none — the report IS the measurement
- **Brand-document scope:** identity, rules, context, gaps

### `service_desk` — Service desk

Handles routine inbound support with a drafted, checked reply.

- **Connections:** `inbox`
- **Knowledge (`kb_needs`):** `tone`, `banned_claims`, `objection`, `entity`
- **Skill** `inbound_reply` — produces `draft`, tier 3, writes=False
  - parameters: `utterance`, `contact_id`, `entity_key`, `facts`, `draft_with_model`, `thread_id`
  - constitutive (no draft without it): none
- **Planner:** none — plans are filed by hand or by another system
- **Unit:** one thread's reply
- **Artifact:** gmail_draft
- **Ship:** approving sends the draft itself
- **Measure:** edits.py delta; sent-as-is rate
- **Brand-document scope:** identity, rules, situations, objections, context, lookups, catalogue, gaps
<!-- END GENERATED -->

## 2a. What the declarations do not carry

Everything above §2's markers is read out of `systems.CATALOG` and is true by
construction. These are the per-system facts that live in the BODY of a module
rather than in its declaration, so no walk produces them — kept here, by hand,
because they were the half of the old §2 worth keeping and they are what the
generated block cannot say.

**blog** — Angle auto-rotates through `ARTICLE_ANGLES` (7 moves; intent
narrows, cluster history picks — eight supports under one pillar get eight
different articles, `skill_pack.py`); an angle named on the plan wins. A
direct-run keyword joins the map first (`source="direct_run"`), so the board
always lists it. The planner files a pillar AHEAD of its support, never
instead of it. Requiring nothing is deliberate (owner, 2026-08-26): publishing
degrades with the reason and the copy is kept whole at
`/admin/artifact/<output_id>?raw=1`, which IS the workflow on a platform with
no write API.

- **Keyword-map variables** (`db.KeywordTarget`): tier/intent/volume/
  difficulty (computed, never typed; difficulty nullable — unknown is not 0),
  cluster_key+role, status candidate→planned→published→won (settled from
  readings BOTH directions, `WON_POSITION=3.0`), priority+priority_parts
  (arguable arithmetic), **`owner_priority` in '', pinned, muted** — a separate
  sort key, never a score bonus; muted = not proposed at all.
- **Loops:** readings nightly 20:05 (`sync_all` → settle → re-score); map
  top-up Mondays 20:25 (`harvest_all`, skips accounts fresher than 7 days,
  never auto-harvests an empty map); progress on demand (tracked vs CONTROL,
  14-day attribution embargo, goal never invented). Five harvest sources
  (gsc/own/gap/related/questions) — exclude_terms bind ALL five.
- **Surfaces:** Plan tab (readiness chips → board: writing-next with `why`
  arithmetic, moved, opportunities by tier, in-flight with draft/live links,
  muted fold with lessons + accept buttons) · `/admin/article/{output_id}`
  (review, edit — ban-gated saves — approve/deny or record-live-URL) ·
  `/health/blog` (probe=1 asks Search Console for real).
- **Write-back:** approval executor and manual mark-published both call
  `keywords.mark_published` → target_url, published_at, status,
  `ledger.publish`, draft-vs-published delta onto the run (`edits.delta`).

**campaign_email** — Anti-repeat by FORM: the drafter is shown the last sends'
shapes, subjects and openings (`_craft_brief`). The planner writes a calendar
for high-value segments and reads live pressure (moments) for common ones, in
one `campaign:` ref space. `draft_into_esp` is deliberately NOT a plan field:
producing the draft in the client's ESP is what this system IS, and the real
choice sits one level up on the autonomy ladder.

**moment_email** — Watches carts and enquiries; **proposes nothing and sends
nothing**. It informs `campaign_rollout`'s pressure path. Filing one plan per
PERSON was the first cut and was wrong: `esp_id_for` targets a whole segment,
so two cold carts would have been two identical sends to the entire list. Any
moments UI is read-only plus "which cohort it argues for".

**service_desk & lead_responder** — Driven by `triage.py` off inbound mail,
NOT the tick (`externally_driven`); `inbound_reply` exists in the registry but
real mail bypasses it — a known wiring decision, not an accident. Measure:
`edits.py` delta at Gmail send; sent-as-is rate feeds promotion. NOTE
(2026-08-31): `service_desk` does not declare `claim` in its `kb_needs`, which
is why the derived brand-document scope gives it no claims section. A system
that drafts customer replies and never declared it needs approved proof is a
question for its walk.

**catalog_compliance & content_compliance** — catalog runs `catalog_compliance`
(tier 1 report, weekly Monday 04:30 sweep) and `catalog_seo_rewrite` (tier 2
proposals). content crawls every source `tenants.content_sources` returns —
`Tenant.domain` plus the facts-only landing pages — and each finding names the
site it is on; `<head>` is stripped before matching, which is why catalogue SEO
metadata needs its own system. Both constitutive on `banned_claims` — an empty
ban list refuses rather than reporting CLEAN. Findings live on **Assurance**.

**ad_creative** — Degrades to a composed placeholder with `basis` saying so.
Reachable via skill_run/agent only (the tick declares it but plans are filed by
hand). **`needs_art_direction` is CONSUMED** (2026-08-30): the variant board
carries **Make frames** (8/16/24) per variant → `POST /admin/ad_frames` →
`creative.batch` off the request, reading the OUTPUT ROW rather than the board
JSON, so frames are generated against the same positioning, audience and claim
that `results` later attributes performance to. Natural next input: keyword
intent/volume (join exists, unconsumed).

**reorder_engine & reports** — Declared, no generator yet; runs file
`not_built` honestly. reports: `business_model` decides its vocabulary
(`metrics.OUTCOMES`).

---


---

## 2b. The creative seam — one ladder, one carousel, three stages

Added 2026-08-29/30. Every system that needs a picture goes through the same
two calls, and a picture's whole life is three named stages.

**Choosing one: `creative.pick`** (`creative.py`). ONE ladder, three systems —
the email hero, the article image and the ad frame were each about to grow
their own selection rule. It never generates (generation is minutes and lands
`proposed`); it selects, or hands back the brief and says make one elsewhere.

| the piece is about | the ladder |
|---|---|
| a product (`entity`, or an explicit `entity_key`) | proven for that product → a photograph of it → brand-wide |
| a topic (`situation`, `topic`, an audience) | proven about the subject → a picture about the subject → **NOTHING** |

That last rung is an EXCLUSION, not a ranking. An article about knee pain with
a photograph of a bottle is not a slightly worse article, and ordering would
have let it through exactly when it matters — when nothing better exists.

**Making many: `creative.batch`** — the ad carousel. Owner, 2026-08-30: *"each
ad will need a carousel of images - potentially up to 20-30 variations."*

- **A grid, not a loop.** angle × lever × moment × framing. `ANGLES` and
  `VALUE_LEVERS` are `ad_craft`'s own (borrowed, never re-declared);
  `MOMENTS` (before/during/after) and `FRAMINGS` (person_led / product_led /
  detail / context) are properties of a photograph and live in `creative.py`.
- **The walk carries** (mixed radix). `i % len` on every axis reads as
  diagonal and is not: 4×4×3×4 has period TWELVE, so the "24 frames" button
  would have produced twelve approaches twice with `identity` welded to
  `dream_outcome` for ever. See DEFECTS §2.88.
- **The framing decides the ROUTE.** `imagegen.plate` appends "scenery only,
  nothing that could be the wrong product", because a generated pitcher is not
  this client's pitcher. So `product_led`/`detail` generate the SCENE and
  composite the client's real photograph via `compose.product_on_scene` —
  which had been able to do this since it was written and had never had a
  caller. With no photograph those framings are **dropped and said** in
  `held_back`, never swapped for a generated stand-in.
- **Cost:** N prompts × `PER_PROMPT` (2) images. `plates=12` → 24 frames in 12
  calls, about a dollar. Thirty separate generations would be $1.50, a quarter
  of an hour, and thirty photographs of the same table.
- **A repeat is not a variation.** `media.put` is content-addressed and
  `add_asset` dedupes on URL, so identical frames would fold into one row
  answering to two cells. Counted as `repeats` and said in the note.

**Reviewing them: one card, every frame** (`admin_ui._batch_cards`, Review ·
Pictures). Owner: *"I'd like to see everyone and then we can reject the ones
we dont like or the whole batch."* Each frame shows the angle/framing it was
generated along and `creative.assess`'s own read — **advice, never a filter**
(the same conclusion `imagegen.similarity` reached: a measurement that can
veto will veto good work). Per-frame keep, **Reject the set** (which reads the
set, not whatever boxes are ticked), and the set's frames LEAVE the flat
crawler queue so one decision never has two buttons.

**Where a picture lives: `hosting.py`** — three stages, DERIVED from the row
by `hosting.stage()`, never stored twice.

| stage | meaning |
|---|---|
| `ours` | our `media` blob store holds the bytes; unreviewed ones expire after 14 days |
| `editable` | a Canva design exists (`KbAsset.canva_design_id`), so type and layout can be changed |
| `hosted` | the client's own CMS serves it; `KbAsset.url` is THEIR url and `hosted` records where |

- **Canva is on demand, per frame** (`hosting.to_canva` → the long-existing
  `canva.editable_from_image`; the finished design returns via
  `canva.harvest`). Thirty designs up front is twenty-eight canvases nobody
  opens and a client folder unusable within a week.
- **Approval hands it over** (`hosting.publish`, background label `hosting`).
  Refuses anything unapproved — a draft in a client's media library is a draft
  their staff will find and use. The crops travel with the frame **or nothing
  moves**. Then our bytes go: `media.py` calls itself "a handoff, not a CDN",
  and approved pictures were the one case where that was not true.
- **A refusal keeps the picture.** No CMS, an upload the platform rejects —
  the bytes stay and the row is not rewritten. `media.sweep` now separates
  "kept because approved" from `unhosted` ("kept because nothing would take
  it"); they shared one number, so a broken connection read as normal.
- **Placements** (4:5, 9:16) are cut by `creative.placements` **on approval**,
  and recorded ON the frame rather than filed as assets — a 9:16 crop as its
  own row would be selectable by `pick` as an email hero.

**Backends:** `sites.backend(profile).put_image(profile, blob, filename=, alt=)`.
`wordpress_seo` needs nothing new (the app password already authenticates).
`shopify_seo` needs **`write_files`** — see §4.

---

## 3. The data layer under all of it

47 tenant-scoped tables; `test_tenant_isolation` walks the schema. **One
writer per table that matters:**

| table | writer | holds |
|---|---|---|
| kb_* | kb.py | claims/audiences/objections/entities/situations — proposals need approval; `attributed_to` settable in the claim editor |
| keyword_targets / keyword_readings | keywords.py | the plan to rank / the observations (two sources, disagreement kept) |
| outputs | ledger.py | the DECISION (claim, angle, entity) — body[:2000] only |
| artifact_bodies | ledger.py | the artifact whole; `draft_body` frozen at emit for the delta |
| system_runs / systems | systems.py | every run incl. blocked; the ladder's evidence |
| approvals | approvals.py | what waits on a person; kind travels into every digest card |
| digest_acks | digest.py | what the owner has already dealt with in the briefing — fingerprinted, so a changed item comes back |
| tool_calls | toolcalls.py | every provider round trip per account — Semrush included (one shared key, attributed) |
| media_blobs | media.py | bytes we are holding, content-addressed; a HANDOFF, not a CDN — approved pictures leave for the client's CMS, unreviewed ones expire in 14 days |

Reset groups: knowledge / operations / access (`reset.py`); every new table
classifies in the change that adds it — `test_reset` fails the build otherwise.

**Two columns carry identity, added 2026-08-27/28 and worth knowing:**

- `Tenant.sources` — the FACTS-only landing pages. `Tenant.domain` stays the
  WEBSITE and is still the single identity source (`brand_theme`, `voice.
  gather`); `tenants.content_sources()` returns website-first and is read by
  `harvest` and `compliance.scan` ONLY. Nothing that derives identity calls it.
- `ArtifactBody.meta` — what the artifact IS (title, seo_title,
  seo_description, subject, segment, intent…). It used to live only in the
  approval payload, so an artifact was a complete object only while a decision
  was pending on it. The executor overlays `meta` + `body` onto the payload's
  machine-set fields at publish, so what was reviewed is what is pushed.

**Approval statuses beyond pending/approved/denied:** `sent_outside` (the
draft went, from the mailbox), `answered_elsewhere` (the thread was answered
another way and OUR draft is still sitting there), `draft_discarded` (deleted
unsent — frees the thread in `replies.owner`; the other two do not).

---

## 4. Integrations

| provider | grants | notes |
|---|---|---|
| google | inbox, analytics | **per-account** (owner, 2026-08-26): each tenant its own consent; alias falls back to `t.key`, never the agency. GSC needs `webmasters.readonly` — live 403 until re-consent. Env-group Google grants inbox ONLY |
| shopify | commerce, cms | cms gated on `write_content` actually granted. **Hosting an approved image needs `write_files`** (Files has no REST route; the GraphQL one is outside the nine scopes every store granted before 2026-08-30) — asked for now, and Connections says "not granted: write_files" until the store re-connects once. `write_products` would work and is refused on purpose: it would put an advertisement on the storefront product page. Env stores may use `{domain, client_id, client_secret}` (client_credentials grant) — a registry, not a secret |
| wordpress | cms | app-password; inline JSON-LD |
| omnisend / klaviyo / constant_contact | esp | |
| meta_ads | ads | | 
| canva | design | the EDITABLE stage of a picture's life (`hosting.to_canva`). **`app/canva.py` has never met the live API** — every path says so in its own docstring. `scripts/verify_canva.py <tenant> [--design]` is the live check (which credential resolved, per-client folder created/reused/written back); it needs the live `DATABASE_URL` and is not a suite. Agency token was revoked — reconnect |
| semrush | (global) | ONE key, all accounts, read-only — cannot pollute the Semrush account; per-account attribution via tool_calls; market per account (`analytics.semrush_db`, default us, advisory when unset) |

Onboarding is product-only: `/admin/tenant_add` → `/connect/<token>` →
`/intake/<token>` → install. `needed_for` includes cms when blog is
installed. `Tenant.domain` alone enables scraping/compliance (no platform); it is
the WEBSITE and the only identity source — landing pages
(`Tenant.sources`) are read for facts, never for voice or theme.

---

## 5. Cross-system joins (what feeds what)

- moments → campaign_rollout's pressure path (never sends itself)
- keyword map → blog_rollout → blog_article → publish write-back →
  readings → score → next plan (closed 2026-08-26)
- mute lessons → exclude_terms (accept button) → ALL five harvest sources
- performance.sync → ledger.confirm_sent (campaigns) → strategy
- correlate (nightly 20:10, after readings at 20:05) narrates rows already
  written; sweep approvals are decisions only — "executed" is claimed only
  for kinds with an executor arm
- ad_copy's `needs_art_direction` → `creative.batch` → the pictures queue →
  approval → `creative.placements` + `hosting.publish` (closed 2026-08-30)
- Unconsumed joins, ready: article↔keyword recheck pass; intent/volume →
  ad briefs; cluster link obligations

---

## 6. Design rules paid for in defects (for the UI agent)

1. **Act where you report.** A named gap carries its control on the same
   surface (blog picker, market form, Turn-it-on, exclude accept, situation
   add). A fix instruction containing a URL or command is a defect.
2. **Three states, not two.** ok / not-ok / **not checked** — an unprobed
   capability renders `?`, never a tick (`readiness.measure`).
3. **Redirects keep the reader's place.** Section travels with the anchor
   (`_back_to_content` derives it); tenant+system+page travel on systems
   redirects; a decision never costs the place.
4. **One writer, one reader, one vocabulary** for every label a page reads
   back (`BG_LABELS`, flash keys) — `test_pointers.py` enforces routes,
   tabs (console AND portal vocabularies), and bg-label parity mechanically.
5. **Drafted ≠ published**, and the summary leads with which; a run that
   makes one reviewable thing LANDS on it.
6. **The owner outranks the arithmetic, visibly** — pin/mute beside the
   score, computed priority still shown, so disagreement is on record.
7. **Refusals are flashes with reasons where the button was** — never raw
   JSON, never a dead 401 (chat links redirect to sign-in).
8. **Every fact stated once**; counts come from the lists actually rendered.
   Stronger form paid for in 2026-08-27/28: a count and the list it counts
   read ONE predicate (`approvals.decided_in_console`, `systems.
   attention_unseen`, `_board_counts`), because a badge counting what the
   page does not show is a number nobody can act on.
9. **One fact, one home; every surface is a view over it.** An artifact's
   identity lived only in its pending approval, so it was a complete object
   only while a decision was open on it — the review page went blank and an
   edit made there was discarded in silence. Where a thing IS decides where
   it is stored; the approval, the run and the queue all read it.
10. **An acknowledgement covers the item AS IT WAS.** "Handled", "seen",
   "cleared" are fingerprinted against what the line actually said, so a
   changed item returns and an unchanged one stays quiet (`digest_acks`,
   `systems.attention_fingerprint`). Seen never means "stop telling me" —
   permanently silencing a live problem is how a real one is missed.
11. **A check run against emptiness checks nothing.** `.grp` was undefined
   for weeks while the class-coverage suite walked a Plan tab with no
   keywords in it, and `test_console_frame` once passed against a database
   with no systems. A suite must seed the state whose markup it claims to
   cover — `data_only_classes_are_covered` fails while that seed is absent.
12. **Absence is not an answer.** A Gmail draft that still exists is not a
   thread nobody answered; a missing draft is not necessarily a send. Ask
   the source the second question (`sent_in_thread`, `sent_to_since`) rather
   than reading one silence as a verdict. Stronger form paid for 2026-08-28:
   a run over SEVERAL sources reported one set of totals, so a landing page
   that read nothing hid behind a website that read plenty — the per-source
   report existed and no surface rendered it. A total is not a per-source
   answer, and a source that contributed zero has to say so where the run is
   reported (`_summarise`'s `READ NOTHING`, the Brand source card).
13. **A feature is not the storing of it.** `test_brand_sources` had 32
   checks — every one about STORING and NAMING a content source, not one
   about READING one — so multi-domain sources passed for a day while a
   landing page on a path scraped nothing at all. The seed made it worse by
   demonstrating a bare subdomain, the shape that happened to work, with a
   hand-filed claim. When a feature's point is that something HAPPENS, the
   suite has to make it happen and inspect what came back; and the fixture
   has to be the shape people actually have (for landing pages that is
   `theirdomain.com/pages/x`, not a subdomain).

---

## 6b. TURN THE CLAIM INTO A CHECK (the day's most expensive lesson)

Named by the owner, 2026-08-28, after it happened three times in one session.
Each time the agent DECLARED something done and it was not, and each time the
durable fix was the same shape: stop asserting the property, start testing it.

| the claim | how it was false | the check that replaced it |
|---|---|---|
| "drafts are named in all systems" | two of THREE `ArtifactBody` writers were fixed; the campaign writer keeps its own row and was never audited | `test_artifact_identity` parses `app/*.py` with `ast` and fails if any construction omits `meta` |
| "the guards are green" | a Schedule rewrite left `a_dateless_plan_is_not_scheduled` pinned to code that no longer existed — in a SHIPPED commit | `test_sabotage_anchors` fails when any anchor stops matching EXACTLY once |
| "those emails are draftless" | they were not; triage-drafted replies carry a `draft_id`, and the real bug was elsewhere entirely | the owner pushed back — the only check that caught this one |

**The rules that fall out of it:**

1. **A claim about EVERY instance must be computed, not surveyed.** "All the
   writers", "every tab", "each system" — if the set is not derived from the
   code, the one you did not think of is the one that is broken. Read the
   source (`ast`) or the schema, never your memory of it.
2. **Verification that only runs when someone remembers is not verification.**
   The sabotage harness reported STALE loudly and nobody ran it for a week.
   The cheap half — is the anchor still there — belongs in the suite that runs
   every time.
3. **A test that passes against emptiness proves nothing** (rule 11), and a
   test that exercises only the paths you already know about proves only those.
   Prefer a check over the POPULATION to a check over your examples.
4. **When the owner contradicts a diagnosis, investigate before defending.**
   The one defect here that no automated check would ever have found was found
   by the owner saying "but I have been seeing drafts in Gmail". Re-read the
   code with their observation as the premise.

---

14. **A route that exists is not a route that works.** `test_pointers` refuses
   a control pointing nowhere and passed the whole time a landing page
   scraped nothing. Two further questions have to be computed, not surveyed,
   and `test_control_piping.py` computes both with shrink-only allowlists:
   does any suite PRESS this control, and does any surface RENDER the
   warnings this producer computes? The second is where the expensive
   defects live — a fact about something going wrong that no human can reach
   is the same defect as a KB rule that never reaches a validator.
15. **A check that reads its own bookkeeping is an empty check.** The piping
   suite's first version grepped every suite including itself, and its own
   allowlist named the thirteen unpressed controls — so it reported zero.
   Exclude self, then SABOTAGE THE CHECK: plant the defect it claims to
   catch and watch it fail before trusting it green.

---

## 7. Solidify log (recent, newest first)

- 2026-08-28 — the hidden-warning backlog worked: 38 → 6. Eleven were the
  CHECK crying wolf (keys consumed upstream, keys rendered by the producer's
  own module, `web.py` missing from the surface set) — a noisy check gets
  skimmed, so the filter was fixed first. Seventeen were ONE defect:
  `_summarise` reported a run's gains and dropped its losses, so a harvest
  that refused to write five claims said "proposed 12". `_losses()` now names
  what was refused, skipped and dropped, reason first, with one real instance.
  The six that remain each carry a verified reason, and the suite states what
  the check cannot see: a key rendered by dumping the whole dict.
- 2026-08-28 — "how many UI units did we build without piping?" Answered by
  computation, not survey: 70 console controls, 13 pressed by no suite (all 13
  then hand-pressed and all 13 work); 335 producers, 38 warning-shaped keys no
  surface renders — which is where the landing-page defect actually lived.
  Both are now shrink-only allowlists in `test_control_piping.py`. One fixed
  on the spot: the voice panel offered Adopt without saying the tone came from
  arithmetic rather than a model, or that the sample was one sentence.
- 2026-08-28 — a landing page is a PAGE. The owner asked whether the scraper
  actually pulls facts off one; it did not, and 113 suites said nothing.
  `discover_pages` treated every source as a SITE (sitemap under the path,
  then wp-json under the path, then the links OUT of the page — never the
  page itself), source identity was the HOST so
  `theirdomain.com/pages/spring` could not be added at all, and a source that
  enumerated nothing was invisible behind one that did. Fixed with
  `compliance._one_page`, `tenants._norm_url`, a normalising `set_website`,
  and `READ NOTHING` in `_summarise` plus last-read state and its buttons on
  the Brand source card. Rules 12 (stronger) and 13 are the price.
- 2026-08-28 — Brand, the last tab of step 4: the voice deriver came OFF the
  page request (`voice.derive` behind `_run_bg`, proposal stored on
  `KbBrand.voice_proposed` so it outlives the request that made it — 8ms
  response where a site crawl plus a model call used to block); hard rules
  became liftable, which required computing the writers FIRST — `ast` found a
  second appender inside `systems.promote_rule`, and a second writer to a list
  that can now shrink is a silent contradiction, so it delegates and `kb.py`
  holds exactly one appender and one subtractor (`test_ban_list` computes
  that claim rather than restating it); and the theme half stopped being able
  to take the tab down with it — a stale Shopify credential used to remove the
  identity editor, the hard rules and the source list, which are the controls
  you would use to fix the account. Two defects found by previewing: 124px of
  page overflow at phone width (`.tblwrap`, reused from Plan) and a redirect
  that stranded `key=` in the URL fragment.
- 2026-08-28 — the owner's walkthrough, five defects and their fixes:
  the artifact became self-describing (`ArtifactBody.meta`) after the blog
  review page rendered three empty boxes above a perfect preview AND
  discarded edits made there in silence; `reconcile_drafts` widened twice —
  first to outbound mail with no Gmail draft behind it, then (the one the
  owner actually had) to a thread ANSWERED ANOTHER WAY while our draft sat
  there unsent; the Systems attention card clears when the check is read and
  returns only on a new reason; every draft and every queued decision gained
  a real name (`artifact_label`, `approval_title`) instead of
  `format · timestamp` or the skill name plus eighty bytes of HTML. Also
  `test_sabotage_anchors`, after a Schedule rewrite left a guard covering
  nothing in a SHIPPED commit — it now fails the build the moment an anchor
  stops matching exactly once.
- 2026-08-27 — the daily briefing became a briefing: ranked by client,
  bounded, and clearable from the email (handled / irrelevant / updated,
  signed links; `db.DigestAck` fingerprints what the line said so a changed
  item comes back). Same day: the send is the approval for drafted replies —
  they leave the review queue and `reconcile_drafts` records the draft-vs-sent
  delta that its docstring had promised and never written.

- 2026-08-27 `b67533b` — pointer-integrity sweep: 75 not-ok directions
  fixed at ~8 root causes; `test_pointers.py` + `test_pointer_fixes.py`
  hold it. Sender + attributed_to + down-a-rung controls added; digest
  honest per kind; exclude terms bind all sources; connect offers cms.
- 2026-08-26 `015cb63` — runs land on the article; drafted keywords always
  visible on the board. `640456c`-era: Review gained "May it ship?" (first),
  WhatsApp Edit points at the review page, pre-push hook gates main
  (`scripts/ship.sh` only sanctioned push path).
- 2026-08-26 — article review loop: full-body review page, ban-gated edits,
  publish write-back (`keywords.mark_published`), draft-vs-published delta
  computed at last. Board (4 tables), pin/mute, mute lessons, angle
  rotation, `/health/blog`, per-account Google, ArtifactBody retention.
- Full daily narrative: INITIATIVE-seo-blog.md §2; architecture drawing:
  the Content Spine artifact (2026-08-26).
