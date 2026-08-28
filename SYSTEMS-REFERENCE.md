# Systems Reference

Derived from the code at `b67533b` (2026-08-27) — `systems.CATALOG`,
`skill.REGISTRY`, `planner.PLANNERS`, a schema walk, and a route dump — not
from memory or older documents. Every claim carries a file anchor so its own
staleness is checkable. Written for whoever designs surfaces over this
platform: the variables listed per system are the ones a UI must expose,
because they are the ones the code actually reads.

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

## 2. The ten systems

### blog — the content spine's producer
- **Requires nothing to run** (`systems.py`): writing needs no store;
  publishing degrades with the reason and the copy is kept whole. KB:
  tone, banned_claims, audience, claim — `banned_claims` is *constitutive*
  for the skill (no ban list → no draft, no model call).
- **Skill** `blog_article` — params `keyword, role, cluster, angle,
  entity_key, utterance`. Angle auto-rotates through `ARTICLE_ANGLES`
  (7 moves; intent narrows, cluster history picks — eight supports under one
  pillar get eight different articles, `skill_pack.py`); an angle named on
  the plan wins. A direct-run keyword joins the map first (`source=
  "direct_run"`), so the board always lists it.
- **Planner** `blog_rollout` — pillar files AHEAD of its support, never
  instead of it. Cadence knobs: `horizon_days` 45 (cap 90),
  `articles_monthly` 4 (cap 30) — `planner.py`.
- **Plan fields (the plan UI):** `keyword*`, role (pillar|support), cluster,
  angle, entity_key.
- **Keyword-map variables** (`db.KeywordTarget`): tier/intent/volume/
  difficulty (computed, never typed; difficulty nullable — unknown ≠ 0),
  cluster_key+role, status candidate→planned→published→won (settled from
  readings BOTH directions, `WON_POSITION=3.0`), priority+priority_parts
  (arguable arithmetic), **`owner_priority` ∈ '', pinned, muted** — a
  separate sort key, never a score bonus; muted = not proposed at all.
- **Loops:** readings nightly 20:05 (`sync_all` → settle → re-score); map
  top-up Mondays 20:25 (`harvest_all`, skips accounts fresher than 7 days,
  never auto-harvests an empty map); progress on demand (tracked vs
  CONTROL, 14-day attribution embargo, goal never invented). Five harvest
  sources (gsc/own/gap/related/questions) — exclude_terms bind ALL five.
- **Surfaces:** Plan tab (readiness chips → board: writing-next with `why`
  arithmetic, moved, opportunities by tier, in-flight with draft/live links,
  muted fold with lessons + accept buttons) · `/admin/article/{output_id}`
  (review, edit — ban-gated saves — approve/deny or record-live-URL) ·
  `/health/blog` (probe=1 asks Search Console for real).
- **Write-back:** approval executor and manual mark-published both call
  `keywords.mark_published` → target_url, published_at, status,
  `ledger.publish`, draft-vs-published delta onto the run (`edits.delta`).

### campaign_email
- Requires `esp`. KB: tone, banned_claims, entity, claim.
- Skill `campaign_email` — params segment*, goal, subject, intent
  (story|education|proof|offer), deadline (the SOURCE of any urgency — blank
  forbids urgency in copy), entity_key, draft_visual. Anti-repeat by FORM:
  the drafter is shown the last sends' shapes/subjects/openings
  (`_craft_brief`).
- Planner `campaign_rollout` — calendar for high-value segments + live
  pressure (moments) for common ones, one `campaign:` ref space. Knobs:
  horizon 21 (cap 90), per_segment_monthly 1 (cap 8), segment_rest_days 6
  (cap 60).
- Artifact `esp_campaign`; launching stays human in the ESP.

### moment_email — a watcher, deliberately skill-less
- Watches carts/enquiries; **proposes nothing and sends nothing** — it
  informs `campaign_rollout`'s pressure path. No plan fields, no queue of
  its own. Any moments UI is read-only + "which cohort it argues for".

### service_desk & lead_responder — mail-owned
- Require `inbox`. Driven by `triage.py` off inbound mail, NOT the tick
  (`externally_driven`); `inbound_reply` exists in the registry but real
  mail bypasses it — a known wiring decision, not an accident. Measure:
  `edits.py` delta at Gmail send; sent-as-is rate feeds promotion.

### catalog_compliance & content_compliance
- catalog: requires `commerce`; skills `catalog_compliance` (tier 1 report,
  weekly Monday 04:30 sweep) and `catalog_seo_rewrite` (tier 2 proposals).
  content: requires nothing (the site is public); crawls every source
  `tenants.content_sources` returns — `Tenant.domain` plus the
  facts-only landing pages — and each finding names the site it is on.
  Both constitutive on `banned_claims` — an empty ban list refuses rather
  than reporting CLEAN. Findings live on **Assurance**.

### ad_creative
- Requires ads OR commerce. Skill `ad_copy` (entity_key*, audience_key*,
  variants 1–5) — copy only, every variant flagged needs_art_direction;
  degrades to a composed placeholder with `basis` saying so. Reachable via
  skill_run/agent only (no planner, tick declares it but plans are filed by
  hand). Natural next input: keyword intent/volume (join exists, unconsumed).

### reorder_engine & reports
- Declared, no generator yet (runs file `not_built` honestly). reorder:
  commerce+esp, cohort replenishment. reports: any of
  analytics/ads/commerce; the weekly client number, `business_model`
  decides its vocabulary (`metrics.OUTCOMES`).

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
| shopify | commerce, cms | cms gated on `write_content` scope actually granted; env stores may use `{domain, client_id, client_secret}` (client_credentials grant) — a registry, not a secret |
| wordpress | cms | app-password; inline JSON-LD |
| omnisend / klaviyo / constant_contact | esp | |
| meta_ads | ads | | 
| canva | design | agency token currently revoked — reconnect |
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
   than reading one silence as a verdict.

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

## 7. Solidify log (recent, newest first)

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
